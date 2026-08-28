"""Phase-2 approval flow (plan §4-§5): dry-run intent -> human approval -> gated execution.

Two passes over one run, and the agent only ever holds the first:

  Pass 1  the Enablement agent's runtime is `dry_run=True`. Pure actions execute
          for real (the human previews actual drafts); side-effectful actions
          become intent nodes (`meta.dry_run`) — recorded, never run. The agent
          is structurally incapable of side effects.
  Human   reads `approval_transcript(...)`, approves.
  Pass 2  `approve_and_execute(...)` — human-triggered code, never the agent —
          resumes the same run with `dry_run=False` and the ApprovalGate policy,
          writes the approval note, re-issues each intended call, seals the run.

ApprovalGate denies any side effect whose ancestry lacks an approval note, so an
unapproved side effect is a refusal node even in pass 2. The run opens with an
`enablement_opened` note pointing at the sealed review it enacts.

Environment: shares GATEHOUSE_EVIDENCE_DB / _SEAL_DB / _LEDGER_TRACE with ledger.
GATEHOUSE_ENABLEMENT_LABEL fixes the run label (golden enablement runs).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pollard import (
    MemoryStore,
    Node,
    NodeKind,
    PolicyViolation,
    ReplayMode,
    Runtime,
    Store,
    seal,
)
from pollard.meters import DepthMeter, StepMeter, WallClockMeter
from pollard.policy import Decision, PolicyContext
from pollard.runtime import Run

from actions.enablement import build_enablement_registry
from ledger import DEFAULT_DB, ModelTokenMeter
from ledger.seal import seal_review

_lock = threading.Lock()
_dry_runtime: Runtime | None = None


class ApprovalGate:
    """pollard Policy: a side effect must descend from an approval note."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def decide(self, ctx: PolicyContext) -> Decision:
        if not ctx.spec.side_effects:
            return Decision.ALLOW
        cursor: str | None = ctx.cursor_id
        while cursor is not None:
            node = self._store.get(cursor)
            if node.kind == NodeKind.NOTE and node.payload.get("kind") == "approval":
                return Decision.ALLOW
            cursor = node.parent
        return Decision.DENY


@dataclass
class EnablementRun:
    """One vendor's enablement slice of the ledger (dry pass: intents + drafts)."""

    run: Run
    vendor_id: str
    invocation_id: str

    @property
    def root_id(self) -> str:
        return self.run.root_id

    def take_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """The generic action door: registered pure actions execute, registered side
        effects become intents (dry pass), everything else becomes a refusal node."""
        try:
            node = self.run.tool_call(action, dict(args))
        except PolicyViolation as refused:
            return {"status": "refused", "node": refused.refusal_id, "reason": str(refused)}
        if node.meta.get("dry_run"):
            return {"status": "recorded_intent", "node": node.id, "action": action}
        return {"status": "executed", "node": node.id, "result": node.result}


def enablement_label(vendor_id: str, invocation_id: str) -> str:
    return os.environ.get("GATEHOUSE_ENABLEMENT_LABEL") or f"enablement:{vendor_id}:{invocation_id}"


def _build_runtime(store: str | Path | Store, *, dry_run: bool, policies: list | None) -> Runtime:
    from ledger.tracing import ledger_span_hook

    return Runtime(
        store,
        registry=build_enablement_registry(),
        meters=[StepMeter(), DepthMeter(), WallClockMeter(), ModelTokenMeter()],
        mode=ReplayMode(os.environ.get("GATEHOUSE_LEDGER_MODE", ReplayMode.RECORD)),
        dry_run=dry_run,
        policies=policies or [],
        on_node=None if os.environ.get("GATEHOUSE_LEDGER_TRACE") == "0" else ledger_span_hook(),
    )


def _store_target() -> str | Path | Store:
    return os.environ.get("GATEHOUSE_EVIDENCE_DB", DEFAULT_DB)


def dry_runtime(store: str | Path | Store | None = None) -> Runtime:
    """The agent-facing runtime: dry_run=True, process-wide."""
    global _dry_runtime
    with _lock:
        if _dry_runtime is None or store is not None:
            target = store if store is not None else _store_target()
            try:
                if isinstance(target, (str, Path)):
                    Path(target).parent.mkdir(parents=True, exist_ok=True)
                _dry_runtime = _build_runtime(target, dry_run=True, policies=None)
            except (OSError, sqlite3.Error) as exc:
                warnings.warn(
                    f"enablement store {target!r} unavailable ({type(exc).__name__}: {exc}); "
                    "recording in memory for this process",
                    RuntimeWarning,
                    stacklevel=2,
                )
                _dry_runtime = _build_runtime(MemoryStore(), dry_run=True, policies=None)
    return _dry_runtime


def reset() -> None:
    global _dry_runtime
    with _lock:
        _dry_runtime = None


def open_enablement_run(
    invocation_id: str, vendor_id: str, *, review_root: str | None = None
) -> EnablementRun:
    """Open the dry (agent) pass. The first note chains this run to the sealed
    review it enacts — the seal digest is re-derived, which re-validates the review."""
    runtime = dry_runtime()
    run = runtime.run(enablement_label(vendor_id, invocation_id))
    review_seal = seal(runtime.store, review_root).digest if review_root else ""
    run.note(
        {
            "kind": "enablement_opened",
            "vendor_id": vendor_id,
            "review_run": review_root or "",
            "review_seal": review_seal,
        }
    )
    return EnablementRun(run=run, vendor_id=vendor_id, invocation_id=invocation_id)


def intended_side_effects(root_id: str, *, store: Store | None = None) -> list[Node]:
    store = store or dry_runtime().store
    return [
        node
        for node in store.walk(root_id)
        if node.kind == NodeKind.TOOL_CALL and node.meta.get("dry_run")
    ]


def approval_transcript(root_id: str, *, store: Store | None = None) -> dict[str, Any]:
    """What the human sees before approving: intended side effects + real drafts."""
    store = store or dry_runtime().store
    intended, drafts = [], []
    for node in store.walk(root_id):
        if node.kind != NodeKind.TOOL_CALL:
            continue
        entry = {"node": node.id, "tool": node.payload["tool"], "args": node.payload["args"]}
        if node.meta.get("dry_run"):
            intended.append(entry)
        else:
            drafts.append(entry | {"result": node.result})
    return {"root_id": root_id, "intended": intended, "drafts": drafts}


def approve_and_execute(
    label: str, *, approved_by: str, store: str | Path | Store | None = None
) -> dict[str, Any]:
    """Pass 2, human-triggered: approval note, then each intended call for real,
    then the seal. Raises PolicyViolation (refusal node) for anything the
    ApprovalGate does not see an approval above."""
    target = store if store is not None else _store_target()
    runtime = _build_runtime(target, dry_run=False, policies=None)
    runtime.policies = [ApprovalGate(runtime.store)]
    run = runtime.resume(label)
    intents = intended_side_effects(run.root_id, store=runtime.store)
    run.note(
        {
            "kind": "approval",
            "approved_by": approved_by,
            "approves": [node.id for node in intents],
        }
    )
    executed = [
        {
            "intent": node.id,
            "tool": node.payload["tool"],
            "node": (done := run.tool_call(node.payload["tool"], dict(node.payload["args"]))).id,
            "result": done.result,
        }
        for node in intents
    ]
    return {
        "root_id": run.root_id,
        "approved_by": approved_by,
        "executed": executed,
        "seal": seal_review(run.root_id, store=runtime.store),
    }
