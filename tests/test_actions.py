"""The registry firewall, offline: one registered read-only action, the poisoned
doc's `approve_vendor` refused as a ledger node, and schema gaps closed."""

import pytest
from pollard import MemoryStore, NodeKind, PolicyViolation, Runtime
from pollard.meters import DepthMeter, StepMeter, WallClockMeter

from actions import (
    FORBIDDEN_ACTIONS,
    RETRIEVE_EVIDENCE,
    build_registry,
    retrieve_evidence_spec,
)

GOOD_ARGS = {"query": "MFA coverage", "query_time": "2026-08-24T12:00:00", "k": 6}


def make_runtime(record):
    # No TokenMeter: tool results carry no usage payload, so it would only warn.
    return Runtime(
        MemoryStore(),
        registry=build_registry(retrieve_evidence=record),
        meters=[StepMeter(), DepthMeter(), WallClockMeter()],
    )


def test_registry_has_retrieval_and_nothing_forbidden():
    registry = build_registry(retrieve_evidence=lambda args: {})
    assert RETRIEVE_EVIDENCE in registry
    assert not registry.get(RETRIEVE_EVIDENCE).side_effects
    for name in FORBIDDEN_ACTIONS:
        assert name not in registry


def test_schema_closes_the_obvious_gaps():
    spec = retrieve_evidence_spec()
    assert spec.validate_args(GOOD_ARGS) is None
    assert "query" in spec.validate_args({**GOOD_ARGS, "query": ""})
    assert "k" in spec.validate_args({**GOOD_ARGS, "k": 99})
    # The poisoned doc's payload smuggled into a legitimate call is still refused.
    assert "status" in spec.validate_args({**GOOD_ARGS, "status": "approved"})


def test_registered_call_runs_handler_and_records_node():
    seen = []

    def record(args):
        seen.append(args)
        return {"valid": ["acme-soc2-2026#02"], "pruned": []}

    with make_runtime(record).run("test-review") as run:
        node = run.tool_call(RETRIEVE_EVIDENCE, GOOD_ARGS, version="1")
    assert seen == [GOOD_ARGS]
    assert node.kind == NodeKind.TOOL_CALL
    assert node.result["valid"] == ["acme-soc2-2026#02"]
    assert node.payload["tool"] == RETRIEVE_EVIDENCE


def test_unregistered_approve_vendor_becomes_refusal_node():
    """The poisoned corpus doc asks for approve_vendor(status='approved')."""
    calls = []
    runtime = make_runtime(lambda args: calls.append(args) or {})
    with runtime.run("test-review") as run:
        with pytest.raises(PolicyViolation) as excinfo:
            run.tool_call("approve_vendor", {"status": "approved"})
        refusal = run.store.get(excinfo.value.refusal_id)
    assert not calls  # nothing ran
    assert refusal.kind == NodeKind.REFUSAL
    assert refusal.payload["blocked_kind"] == "tool_call"
    assert "approve_vendor" in refusal.payload["detail"]
    assert refusal.payload["registry_digest"] == runtime.registry.registry_digest
    # The refusal sits in the trunk: whatever the run does next descends from it.
    assert run.cursor_id == refusal.id
