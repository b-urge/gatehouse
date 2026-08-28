"""Intake's slice of the evidence plane (plan §3): every screening verdict is a
content-addressed pollard node, and every publish is a recorded side effect.

Self-contained on purpose: Cloud Run builds this service from services/intake
alone (`--source`), so the fleet's `ledger`/`actions` packages are not here.
The same rules apply — declared actions in a registry, no raw payload in the
ledger: the document text is a `sensitive` schema field, so pollard records a
content-committing digest of it and never the text (which, for a poisoned doc,
is the injection itself).

Actions:
  screen_document@1   read-only. Model Armor sanitize -> {verdict, decision}.
                      A client failure becomes a FAILURE verdict: fail closed,
                      and the ledger shows the screen was unavailable.
  publish_intake@1    side effect. Clean docs onto Pub/Sub -> {message_id}.

Every response carries the run's seal digest (`pollard seal` reproduces it).

Store: $GATEHOUSE_EVIDENCE_DB (sqlite) when set, else in-memory — Cloud Run's
filesystem is ephemeral, so durability on the cloud side is the node id in the
response/event plus the content-free Cloud Trace export.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from pollard import ActionSpec, MemoryStore, Node, Registry, Runtime, seal
from pollard.meters import DepthMeter, StepMeter, WallClockMeter
from pollard.runtime import Run

try:  # package context (tests: services.intake.evidence)
    from .screening import decide
except ImportError:  # Cloud Run buildpack context (CWD=services/intake)
    from screening import decide

SCREEN_DOCUMENT = "screen_document"
PUBLISH_INTAKE = "publish_intake"
VERSION = "1"

ScreenFn = Callable[[str], dict]
PublishFn = Callable[[dict], str]

_SCREEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": {"type": "string", "minLength": 1},
        "doc_id": {"type": "string", "minLength": 1},
        "text": {"type": "string", "minLength": 1, "sensitive": True},
    },
    "required": ["vendor_id", "doc_id", "text"],
    "additionalProperties": False,
}

_PUBLISH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": {"type": "string", "minLength": 1},
        "doc_id": {"type": "string", "minLength": 1},
        "text": {"type": "string", "minLength": 1, "sensitive": True},
        "screen": {"type": "string"},
        "screen_node": {"type": "string", "minLength": 64, "maxLength": 64},
        "intake_run": {"type": "string", "minLength": 64, "maxLength": 64},
    },
    "required": ["vendor_id", "doc_id", "text", "screen", "screen_node", "intake_run"],
    "additionalProperties": False,
}


def build_registry(*, screen: ScreenFn, publish: PublishFn) -> Registry:
    def screen_document(args: dict[str, Any]) -> dict[str, Any]:
        try:
            verdict = screen(args["text"])
        except Exception as exc:  # the screen itself failed: fail closed, on the record
            verdict = {"invocation_result": "FAILURE", "error": type(exc).__name__}
        allowed, reason = decide(verdict)
        return {"verdict": verdict, "decision": {"allowed": allowed, "reason": reason}}

    def publish_intake(args: dict[str, Any]) -> dict[str, Any]:
        return {"message_id": publish(dict(args))}

    return Registry(
        [
            ActionSpec(
                name=SCREEN_DOCUMENT,
                version=VERSION,
                description="Model Armor sanitize of one vendor document; returns the verdict "
                "and the allow/block decision taken on it.",
                schema=_SCREEN_SCHEMA,
                side_effects=False,
                handler=screen_document,
            ),
            ActionSpec(
                name=PUBLISH_INTAKE,
                version=VERSION,
                description="Publish a screened-clean document event to the intake topic.",
                schema=_PUBLISH_SCHEMA,
                side_effects=True,
                handler=publish_intake,
            ),
        ]
    )


def build_runtime(
    store: str | Path | MemoryStore | None = None,
    *,
    screen: ScreenFn,
    publish: PublishFn,
    on_node: Callable[[Node], None] | None = None,
) -> Runtime:
    if store is None:
        store = os.environ.get("GATEHOUSE_EVIDENCE_DB") or MemoryStore()
    if isinstance(store, (str, Path)):
        Path(store).parent.mkdir(parents=True, exist_ok=True)
    return Runtime(
        store,
        registry=build_registry(screen=screen, publish=publish),
        meters=[StepMeter(), DepthMeter(), WallClockMeter()],  # no usage payloads here
        on_node=on_node,
    )


def intake_label(vendor_id: str, doc_id: str) -> str:
    """One run per (vendor, doc): resubmitting the same text lands on the same node."""
    return f"intake:{vendor_id}:{doc_id}"


def record_screening(run: Run, *, vendor_id: str, doc_id: str, text: str) -> Node:
    args = {"vendor_id": vendor_id, "doc_id": doc_id, "text": text}
    return run.tool_call(SCREEN_DOCUMENT, args, version=VERSION)


def record_publish(run: Run, event: dict[str, Any]) -> Node:
    return run.tool_call(PUBLISH_INTAKE, event, version=VERSION)


def seal_digest(run: Run) -> str:
    """Rolling SHA-256 over the request's run — re-validates every node on the way."""
    return seal(run.store, run.root_id).digest
