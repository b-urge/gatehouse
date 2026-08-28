"""Phase-2 «Enablement» actions (plan §4): the three things Gatehouse does after
a human approves a vendor — declared here, executed nowhere else.

  provision_access@1     side effect. A provisioning ticket for the named systems.
  generate_training@1    pure. Conditioned microlearning outline for the rollout.
  draft_rollout_comms@1  pure. The announcement draft for the named channels.

Handlers default to deterministic simulations (the hackathon writes no real
tickets); production swaps them via `build_enablement_registry(provision=...)`.
Determinism matters: simulated results are functions of their args, so an
enablement run replays and seals like everything else. `approve_vendor` remains
forbidden here exactly as in the review registry — approving is the human's act
that *starts* enablement, never an action inside it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pollard import ActionSpec, Registry
from pollard._canon import canonical_bytes

from actions import FORBIDDEN_ACTIONS, Handler

PROVISION_ACCESS = "provision_access"
GENERATE_TRAINING = "generate_training"
DRAFT_ROLLOUT_COMMS = "draft_rollout_comms"
ENABLEMENT_VERSION = "1"

_NONEMPTY = {"type": "string", "minLength": 1}
_NAMES = {"type": "array", "items": _NONEMPTY, "minItems": 1, "maxItems": 12}

_PROVISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": _NONEMPTY,
        "systems": _NAMES,
        "justification": _NONEMPTY,
    },
    "required": ["vendor_id", "systems", "justification"],
    "additionalProperties": False,
}

_TRAINING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": _NONEMPTY,
        "topics": _NAMES,
        "audience": _NONEMPTY,
    },
    "required": ["vendor_id", "topics", "audience"],
    "additionalProperties": False,
}

_COMMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor_id": _NONEMPTY,
        "summary": _NONEMPTY,
        "channels": _NAMES,
    },
    "required": ["vendor_id", "summary", "channels"],
    "additionalProperties": False,
}


def _digest(args: dict[str, Any], n: int = 8) -> str:
    return hashlib.sha256(canonical_bytes(args)).hexdigest()[:n].upper()


def simulated_provision(args: dict[str, Any]) -> dict[str, Any]:
    """A provisioning ticket the demo can point at; id is content-addressed on the args."""
    return {
        "ticket_id": f"TCK-{_digest(args)}",
        "status": "queued",
        "vendor_id": args["vendor_id"],
        "systems": list(args["systems"]),
    }


def simulated_training(args: dict[str, Any]) -> dict[str, Any]:
    outline = [f"Module {i}: {topic} — what changed and what to check" for i, topic in
               enumerate(args["topics"], start=1)]
    return {"format": "microlearning", "audience": args["audience"], "outline": outline}


def simulated_comms(args: dict[str, Any]) -> dict[str, Any]:
    draft = (
        f"We are onboarding {args['vendor_id']}. {args['summary']} "
        "Access is provisioned per the approved review; questions to #vendor-reviews."
    )
    return {"draft": draft, "channels": list(args["channels"])}


def build_enablement_registry(
    *,
    provision: Handler | None = None,
    training: Handler | None = None,
    comms: Handler | None = None,
) -> Registry:
    """The enablement registry: three actions, one side effect, nothing forbidden."""
    registry = Registry(
        [
            ActionSpec(
                name=PROVISION_ACCESS,
                version=ENABLEMENT_VERSION,
                description="Open a provisioning ticket granting the vendor's named systems.",
                schema=_PROVISION_SCHEMA,
                side_effects=True,
                handler=provision or simulated_provision,
            ),
            ActionSpec(
                name=GENERATE_TRAINING,
                version=ENABLEMENT_VERSION,
                description="Generate a microlearning outline conditioned on the review.",
                schema=_TRAINING_SCHEMA,
                side_effects=False,
                handler=training or simulated_training,
            ),
            ActionSpec(
                name=DRAFT_ROLLOUT_COMMS,
                version=ENABLEMENT_VERSION,
                description="Draft the rollout announcement for the named channels.",
                schema=_COMMS_SCHEMA,
                side_effects=False,
                handler=comms or simulated_comms,
            ),
        ]
    )
    for name in FORBIDDEN_ACTIONS:
        if name in registry:  # pragma: no cover - guards future edits, not runtime data
            raise ValueError(f"{name!r} must never be a registered action")
    return registry
