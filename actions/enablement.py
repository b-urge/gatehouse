"""Phase-2 ActionSpecs (plan §2, §4): the enablement agent's entire action surface.

Discipline rule from the plan: ONE enablement agent, THREE registered actions —
`create_provisioning_ticket@1`, `publish_training_module@1`, `send_rollout_comms@1`
(side-effectful: they write real Firestore documents), plus the read-only
`recall_findings@1` so even Memory Bank recall is a ledgered, content-addressed
consultation. `approve_vendor` stays FORBIDDEN here exactly as in phase 1: the
enablement agent routes every act through the registry via a generic
`take_action` tool, so an injected or hallucinated action name becomes a live
REFUSAL node, not an effect. (pollard's `Run.confirm` is the human-gate option
for these specs; the demo runs them autonomous.)

Handlers bind at runtime through `build_enablement_registry` — tests attach
sinks, the live agent attaches the Firestore writers in `default_handlers`.
"""

from __future__ import annotations

from typing import Any, Callable

from pollard import ActionSpec, Registry

from actions import FORBIDDEN_ACTIONS

Handler = Callable[[dict[str, Any]], dict[str, Any]]

RECALL_FINDINGS = "recall_findings"
CREATE_TICKET = "create_provisioning_ticket"
PUBLISH_MODULE = "publish_training_module"
SEND_COMMS = "send_rollout_comms"

ACTION_VERSIONS: dict[str, str] = {
    RECALL_FINDINGS: "1",
    CREATE_TICKET: "1",
    PUBLISH_MODULE: "1",
    SEND_COMMS: "1",
}

_RECALL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": {"type": "string", "minLength": 1},
        "query": {"type": "string", "minLength": 1},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "required": ["vendor_id", "query", "top_k"],
    "additionalProperties": False,
}

_TICKET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": {"type": "string", "minLength": 1},
        "system": {"type": "string", "enum": ["vendor-portal"]},
        "access_level": {"type": "string", "enum": ["standard", "restricted"]},
        "justification": {"type": "string", "minLength": 10},
    },
    "required": ["vendor_id", "system", "access_level", "justification"],
    "additionalProperties": False,
}

_MODULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 3},
        "module": {"type": "string", "minLength": 20},  # JSON text of the microlearning module
        "conditioned_on": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "evidence": {"type": "string", "minLength": 1},  # recall node / evidence_run cited
    },
    "required": ["vendor_id", "title", "module", "conditioned_on", "evidence"],
    "additionalProperties": False,
}

_COMMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": {"type": "string", "minLength": 1},
        "audience": {"type": "string", "enum": ["all-staff"]},
        "draft": {"type": "string", "minLength": 20},
        "mode": {"type": "string", "enum": ["draft-only"]},  # demo never sends
    },
    "required": ["vendor_id", "audience", "draft", "mode"],
    "additionalProperties": False,
}

_SPECS: dict[str, tuple[str, dict[str, Any], bool]] = {
    RECALL_FINDINGS: (
        "Recall this vendor's review findings from Memory Bank. Read-only; the "
        "recall itself becomes a ledger node the module cites as its evidence.",
        _RECALL_SCHEMA,
        False,
    ),
    CREATE_TICKET: (
        "Open a provisioning ticket for vendor-portal access (Firestore write).",
        _TICKET_SCHEMA,
        True,
    ),
    PUBLISH_MODULE: (
        "Publish the generated microlearning module, conditioned on review "
        "findings (Firestore write).",
        _MODULE_SCHEMA,
        True,
    ),
    SEND_COMMS: (
        "File the rollout comms draft for the vendor launch (Firestore write; "
        "draft-only, never sends).",
        _COMMS_SCHEMA,
        True,
    ),
}


def enablement_spec(name: str, handler: Handler | None = None) -> ActionSpec:
    description, schema, side_effects = _SPECS[name]
    return ActionSpec(
        name=name,
        version=ACTION_VERSIONS[name],
        description=description,
        schema=schema,
        side_effects=side_effects,
        handler=handler,
    )


def build_enablement_registry(*, handlers: dict[str, Handler]) -> Registry:
    """The phase-2 registry: exactly these four actions, none of FORBIDDEN_ACTIONS."""
    missing = set(_SPECS) - set(handlers)
    if missing:
        raise ValueError(f"handlers missing for: {sorted(missing)}")
    registry = Registry([enablement_spec(name, handlers[name]) for name in _SPECS])
    for name in FORBIDDEN_ACTIONS:
        if name in registry:  # pragma: no cover - guards future edits
            raise ValueError(f"{name!r} must never be a registered action")
    return registry


def default_handlers() -> dict[str, Handler]:
    """Live handlers: recall via Memory Bank, the three effects as Firestore
    documents. Cloud clients are built lazily inside each handler."""

    def recall(args: dict[str, Any]) -> dict[str, Any]:
        import memorybank

        memories = memorybank.run_sync(
            memorybank.recall_findings(args["vendor_id"], args["query"], top_k=args["top_k"])
        )
        return {"memories": memories, "count": len(memories)}

    def _write(collection: str, doc: dict[str, Any]) -> dict[str, Any]:
        from google.cloud import firestore

        import memorybank

        db = firestore.Client(project=memorybank.project_id())
        ref = db.collection(collection).document()
        ref.set({**doc, "created": firestore.SERVER_TIMESTAMP})
        return {"ok": True, "doc": ref.path}

    def create_ticket(args: dict[str, Any]) -> dict[str, Any]:
        return _write("provisioning_tickets", {**args, "status": "open"})

    def publish_module(args: dict[str, Any]) -> dict[str, Any]:
        return _write("training_modules", args)

    def send_comms(args: dict[str, Any]) -> dict[str, Any]:
        return _write("comms_drafts", {**args, "status": "draft"})

    return {
        RECALL_FINDINGS: recall,
        CREATE_TICKET: create_ticket,
        PUBLISH_MODULE: publish_module,
        SEND_COMMS: send_comms,
    }
