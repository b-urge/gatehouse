"""Evidence plane, phase 2: the enablement agent's slice of the ledger.

Mirrors `ledger` (phase 1) with its own Runtime built on the enablement
registry: memory recall is the read-only `recall_findings@1` node, and each of
the three side effects is a TOOL_CALL node whose id is the action's receipt.
An unregistered name — `approve_vendor` included — becomes a REFUSAL node via
`EnablementRun.act`, which is the live registry-firewall beat.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pollard import MemoryStore, Node, PolicyViolation, ReplayMode, Runtime, Store
from pollard.meters import DepthMeter, StepMeter, WallClockMeter
from pollard.runtime import Run

from actions.enablement import ACTION_VERSIONS, build_enablement_registry, default_handlers
from ledger import _strip_fences  # same fence-stripping as phase 1 verdict notes

DEFAULT_DB = "evidence/enablement.db"

_lock = threading.Lock()
_runtime: Runtime | None = None
_runs: dict[str, EnablementRun] = {}


@dataclass
class EnablementRun:
    """One vendor enablement's slice of the ledger."""

    run: Run
    vendor_id: str
    invocation_id: str

    @property
    def root_id(self) -> str:
        return self.run.root_id

    def recall(self, query: str, *, top_k: int = 5) -> Node:
        args = {"vendor_id": self.vendor_id, "query": query, "top_k": int(top_k)}
        return self.run.tool_call(
            "recall_findings", args, version=ACTION_VERSIONS["recall_findings"]
        )

    def act(self, name: str, args: dict[str, Any]) -> Node:
        """Registered action or REFUSAL node — PolicyViolation propagates."""
        return self.run.tool_call(name, args, version=ACTION_VERSIONS.get(name, "1"))


def configure_enablement(
    *,
    store: str | Path | Store | None = None,
    handlers: dict[str, Callable] | None = None,
    mode: str | ReplayMode | None = None,
    on_node: Callable[[Node], None] | None = None,
) -> Runtime:
    global _runtime
    mode = ReplayMode(mode or os.environ.get("GATEHOUSE_LEDGER_MODE", ReplayMode.RECORD))
    if store is None:
        store = os.environ.get("GATEHOUSE_ENABLEMENT_DB", DEFAULT_DB)
    registry = build_enablement_registry(handlers=handlers or default_handlers())
    if on_node is None:
        from ledger.tracing import ledger_span_hook

        on_node = ledger_span_hook()

    def build(target: str | Path | Store) -> Runtime:
        return Runtime(
            target,
            registry=registry,
            meters=[StepMeter(), DepthMeter(), WallClockMeter()],
            mode=mode,
            on_node=on_node,
        )

    with _lock:
        try:
            if isinstance(store, (str, Path)) and mode != ReplayMode.REPLAY:
                Path(store).parent.mkdir(parents=True, exist_ok=True)
            _runtime = build(store)
        except (OSError, sqlite3.Error) as exc:
            warnings.warn(
                f"enablement ledger store {store!r} unavailable "
                f"({type(exc).__name__}: {exc}); recording in memory",
                RuntimeWarning,
                stacklevel=2,
            )
            _runtime = build(MemoryStore())
        _runs.clear()
    return _runtime


def runtime_enablement() -> Runtime:
    return _runtime if _runtime is not None else configure_enablement()


def reset_enablement() -> None:
    global _runtime
    with _lock:
        _runtime = None
        _runs.clear()


def enablement_label(vendor_id: str, invocation_id: str) -> str:
    return os.environ.get("GATEHOUSE_RUN_LABEL") or f"enable:{vendor_id}:{invocation_id}"


def open_enablement_run(invocation_id: str, vendor_id: str) -> EnablementRun:
    er = EnablementRun(
        run=runtime_enablement().run(enablement_label(vendor_id, invocation_id)),
        vendor_id=vendor_id,
        invocation_id=invocation_id,
    )
    with _lock:
        _runs[invocation_id] = er
    return er


def get_enablement_run(invocation_id: str) -> EnablementRun | None:
    with _lock:
        return _runs.get(invocation_id)


def enablement_run_for(invocation_id: str, vendor_id: str = "unknown") -> EnablementRun:
    return get_enablement_run(invocation_id) or open_enablement_run(invocation_id, vendor_id)


def close_enablement_run(
    invocation_id: str, *, enablement_result: str | None = None
) -> dict[str, Any]:
    with _lock:
        er = _runs.pop(invocation_id, None)
    if er is None:
        raise LookupError(f"no open enablement run for invocation {invocation_id!r}")
    if enablement_result is not None:
        er.run.note(
            {
                "kind": "enablement_result",
                "vendor_id": er.vendor_id,
                "enablement_result": _strip_fences(enablement_result),
            }
        )
    return {"root_id": er.root_id, "label": er.run.label, **er.run.report()}


__all__ = [
    "EnablementRun",
    "PolicyViolation",
    "close_enablement_run",
    "configure_enablement",
    "enablement_run_for",
    "get_enablement_run",
    "open_enablement_run",
    "reset_enablement",
    "runtime_enablement",
]
