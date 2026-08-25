"""Evidence plane (plan §3, §5): the pollard ledger the review fleet writes to.

One `Runtime` per process, one `Run` per review, keyed by the ADK invocation id.
Every retrieval passes through the registered `retrieve_evidence@1` action, so
its inputs and the exact evidence set consulted become a content-addressed
TOOL_CALL node — the id a finding cites. In replay mode pollard serves that node
from the ledger and the retriever (embeddings, Firestore) is never called.

Environment (all optional):
  GATEHOUSE_EVIDENCE_DB   sqlite ledger path        (default evidence/runs.db)
  GATEHOUSE_LEDGER_MODE   record | hybrid | replay  (default record)
  GATEHOUSE_QUERY_TIME    ISO as-of time pinned for every retrieval in a review
                          (golden runs; default: now, pinned once per review)
  GATEHOUSE_RUN_LABEL     fixed run label so a golden run can be replayed by name
  GATEHOUSE_LEDGER_TRACE  0 to silence the content-free OpenTelemetry spans (default on)

Inspect:  pollard runs evidence/runs.db  /  pollard show evidence/runs.db <root-id>
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pollard import Node, ReplayMode, Runtime, Store
from pollard.meters import DepthMeter, StepMeter, WallClockMeter
from pollard.runtime import Run

from actions import RETRIEVE_EVIDENCE, RETRIEVE_EVIDENCE_VERSION, build_registry
from retrieval.search import ValidityGatedRetriever

DEFAULT_DB = "evidence/runs.db"
DEFAULT_K = 6

_lock = threading.Lock()
_runtime: Runtime | None = None
_reviews: dict[str, ReviewRun] = {}


@dataclass
class ReviewRun:
    """One vendor review's slice of the ledger."""

    run: Run
    vendor_id: str
    invocation_id: str
    query_time: str  # ISO; every retrieval in this review is as-of this instant

    @property
    def root_id(self) -> str:
        return self.run.root_id

    def consult(self, query: str, *, k: int = DEFAULT_K) -> Node:
        """Registered retrieval. Raises PolicyViolation if the registry refuses it."""
        args = {"query": query, "query_time": self.query_time, "k": int(k)}
        return self.run.tool_call(RETRIEVE_EVIDENCE, args, version=RETRIEVE_EVIDENCE_VERSION)


def _retrieval_handler(retriever: ValidityGatedRetriever) -> Callable[[dict], dict]:
    def retrieve(args: dict[str, Any]) -> dict[str, Any]:
        result = retriever.retrieve(
            args["query"], k=args["k"], query_time=datetime.fromisoformat(args["query_time"])
        )
        return result.to_dict()

    return retrieve


def configure(
    *,
    store: str | Path | Store | None = None,
    retriever: ValidityGatedRetriever | None = None,
    mode: str | ReplayMode | None = None,
    on_node: Callable[[Node], None] | None = None,
) -> Runtime:
    """Build the process-wide Runtime. Fleet code lets the environment decide;
    tests pass a MemoryStore/tmp path and a fake retriever."""
    global _runtime
    mode = mode or os.environ.get("GATEHOUSE_LEDGER_MODE", ReplayMode.RECORD)
    if store is None:
        store = os.environ.get("GATEHOUSE_EVIDENCE_DB", DEFAULT_DB)
    if isinstance(store, (str, Path)) and ReplayMode(mode) != ReplayMode.REPLAY:
        Path(store).parent.mkdir(parents=True, exist_ok=True)
    registry = build_registry(
        retrieve_evidence=_retrieval_handler(retriever or ValidityGatedRetriever())
    )
    if on_node is None:  # content-free spans to whatever OTel provider is installed
        from ledger.tracing import ledger_span_hook

        on_node = ledger_span_hook()
    with _lock:
        _runtime = Runtime(
            store,
            registry=registry,
            # No TokenMeter until model calls are recorded: tool results carry no usage.
            meters=[StepMeter(), DepthMeter(), WallClockMeter()],
            mode=mode,
            on_node=on_node,
        )
        _reviews.clear()
    return _runtime


def runtime() -> Runtime:
    return _runtime if _runtime is not None else configure()


def reset() -> None:
    """Drop the Runtime and all open reviews (tests)."""
    global _runtime
    with _lock:
        _runtime = None
        _reviews.clear()


def review_label(vendor_id: str, invocation_id: str) -> str:
    return os.environ.get("GATEHOUSE_RUN_LABEL") or f"review:{vendor_id}:{invocation_id}"


def pin_query_time(explicit: datetime | str | None = None) -> str:
    """The review's as-of instant: explicit > $GATEHOUSE_QUERY_TIME > now (second precision)."""
    explicit = explicit or os.environ.get("GATEHOUSE_QUERY_TIME")
    if explicit is None:
        return datetime.now().replace(microsecond=0).isoformat()
    if isinstance(explicit, str):
        explicit = datetime.fromisoformat(explicit)
    return explicit.isoformat()


def open_review_run(
    invocation_id: str, vendor_id: str, *, query_time: datetime | str | None = None
) -> ReviewRun:
    label = review_label(vendor_id, invocation_id)
    review = ReviewRun(
        run=runtime().run(label),
        vendor_id=vendor_id,
        invocation_id=invocation_id,
        query_time=pin_query_time(query_time),
    )
    with _lock:
        _reviews[invocation_id] = review
    return review


def get_review_run(invocation_id: str) -> ReviewRun | None:
    with _lock:
        return _reviews.get(invocation_id)


def review_run_for(invocation_id: str, vendor_id: str = "unknown") -> ReviewRun:
    """The tool's entry point: the open review for this invocation, or a new one."""
    return get_review_run(invocation_id) or open_review_run(invocation_id, vendor_id)


def close_review_run(invocation_id: str, *, review_result: str | None = None) -> dict[str, Any]:
    """Note the fleet's final verdict under the review, drop it, return the report."""
    with _lock:
        review = _reviews.pop(invocation_id, None)
    if review is None:
        raise LookupError(f"no open review for invocation {invocation_id!r}")
    if review_result is not None:
        review.run.note(
            {
                "kind": "review_result",
                "vendor_id": review.vendor_id,
                "review_result": _strip_fences(review_result),
            }
        )
    return {"root_id": review.root_id, "label": review.run.label, **review.run.report()}


def _strip_fences(text: str) -> str:
    """Model output arrives as ```json ... ```; keep the ledger note as bare JSON text."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    try:
        return json.dumps(json.loads(text), sort_keys=True)
    except ValueError:
        return text
