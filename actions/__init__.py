"""ActionSpec registry (plan §4): the pollard firewall between the fleet and the world.

Every action an agent may take is declared here with a version, a JSON-schema
contract, and a side-effects flag. A `tool_call` on any name *not* declared —
for example the `approve_vendor(status="approved")` the poisoned corpus doc
tries to inject — never runs; pollard writes a refusal node to the ledger and
raises `PolicyViolation` instead (proved by `spikes/refusal_spike.py`).

Handlers are bound at runtime through `build_registry` so tests and spikes can
attach stubs while the fleet attaches the validity-gated retriever. Spec
identity (name, version, schema, side_effects) is what gets digested into every
node, so change a schema only by bumping the version.
"""

from __future__ import annotations

from typing import Any, Callable

from pollard import ActionSpec, Registry

Handler = Callable[[dict[str, Any]], dict[str, Any]]

RETRIEVE_EVIDENCE = "retrieve_evidence"
RETRIEVE_EVIDENCE_VERSION = "1"

# Phase-1 firewall: names the fleet must never be able to invoke. Kept as data so
# the audit and the refusal spike can point at one place. `approve_vendor` is a
# human decision, not an agent action — its absence from the registry is the control.
FORBIDDEN_ACTIONS: tuple[str, ...] = ("approve_vendor",)

_RETRIEVE_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "query_time": {"type": "string", "minLength": 1},
        "k": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    "required": ["query", "query_time", "k"],
    "additionalProperties": False,
}


def retrieve_evidence_spec(handler: Handler | None = None) -> ActionSpec:
    """`retrieve_evidence@1`: validity-gated corpus search. Read-only, no side effects."""
    return ActionSpec(
        name=RETRIEVE_EVIDENCE,
        version=RETRIEVE_EVIDENCE_VERSION,
        description=(
            "Search the vendor evidence corpus as of query_time. Returns only chunks "
            "chronofy still considers valid, plus re-acquisition notices for pruned ones."
        ),
        schema=_RETRIEVE_EVIDENCE_SCHEMA,
        side_effects=False,
        handler=handler,
    )


def build_registry(*, retrieve_evidence: Handler) -> Registry:
    """The phase-1 registry: exactly one action, and none of FORBIDDEN_ACTIONS."""
    registry = Registry([retrieve_evidence_spec(retrieve_evidence)])
    for name in FORBIDDEN_ACTIONS:
        if name in registry:  # pragma: no cover - guards future edits, not runtime data
            raise ValueError(f"{name!r} must never be a registered action")
    return registry
