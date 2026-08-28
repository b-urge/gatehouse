"""Phase-2 approval, offline (plan §4-§5): the agent's pass records intent and real
drafts but cannot touch the world; the human's approval is a note in the chain;
execution descends from it; and an unapproved side effect is a refusal node."""

import pytest
from pollard import NodeKind, PolicyViolation

import ledger.enablement as enablement
from actions.enablement import (
    DRAFT_ROLLOUT_COMMS,
    GENERATE_TRAINING,
    PROVISION_ACCESS,
    build_enablement_registry,
)
from ledger.enablement import (
    ApprovalGate,
    approval_transcript,
    approve_and_execute,
    open_enablement_run,
)

VENDOR = "acme-saas-inc"
PROVISION_ARGS = {
    "vendor_id": VENDOR,
    "systems": ["sso", "billing"],
    "justification": "risk 0.55 accepted by CISO",
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("GATEHOUSE_LEDGER_TRACE", "0")
    monkeypatch.setenv("GATEHOUSE_SIGNER", "muntaser@gatehouse-test")
    monkeypatch.delenv("GATEHOUSE_ENABLEMENT_LABEL", raising=False)
    enablement.reset()
    yield
    enablement.reset()


def dry_open(db):
    enablement.dry_runtime(store=db)
    run = open_enablement_run("inv-1", VENDOR)
    run.take_action(
        GENERATE_TRAINING,
        {"vendor_id": VENDOR, "topics": ["MFA gap"], "audience": "it-admins"},
    )
    run.take_action(
        DRAFT_ROLLOUT_COMMS,
        {"vendor_id": VENDOR, "summary": "Approved with conditions.", "channels": ["#general"]},
    )
    return run


def test_registry_shape_and_forbidden():
    registry = build_enablement_registry()
    assert [f"{s.name}@{s.version}" for s in registry] == [
        "provision_access@1", "generate_training@1", "draft_rollout_comms@1"
    ]
    assert [s.name for s in registry if s.side_effects] == [PROVISION_ACCESS]
    assert "approve_vendor" not in registry


def test_dry_pass_records_intent_and_real_drafts(tmp_path):
    run = dry_open(tmp_path / "runs.db")

    training = run.take_action(
        GENERATE_TRAINING,
        {"vendor_id": VENDOR, "topics": ["EVIDENCE-STALE"], "audience": "managers"},
    )
    intent = run.take_action(PROVISION_ACCESS, PROVISION_ARGS)
    refused = run.take_action("approve_vendor", {"status": "approved"})

    assert training["status"] == "executed"
    assert "Module 1: EVIDENCE-STALE" in training["result"]["outline"][0]
    assert intent["status"] == "recorded_intent"
    store = enablement.dry_runtime().store
    node = store.get(intent["node"])
    assert node.meta["dry_run"] is True and node.result is None  # never ran
    assert refused["status"] == "refused" and "approve_vendor" in refused["reason"]

    transcript = approval_transcript(run.root_id)
    assert [entry["tool"] for entry in transcript["intended"]] == [PROVISION_ACCESS]
    assert transcript["intended"][0]["args"]["systems"] == ["sso", "billing"]
    assert len(transcript["drafts"]) == 3  # two comms/training in dry_open + one here


def test_approval_note_then_execution_then_seal(tmp_path):
    db = tmp_path / "runs.db"
    run = dry_open(db)
    run.take_action(PROVISION_ACCESS, PROVISION_ARGS)

    outcome = approve_and_execute(run.run.label, approved_by="katie@gatehouse", store=db)

    (done,) = outcome["executed"]
    assert done["tool"] == PROVISION_ACCESS
    assert done["result"]["ticket_id"].startswith("TCK-")
    assert outcome["seal"]["custody"]["signer"] == "muntaser@gatehouse-test"

    store = enablement.dry_runtime().store
    executed = store.get(done["node"])
    approval = store.get(executed.parent)
    assert approval.kind == NodeKind.NOTE
    assert approval.payload["kind"] == "approval"
    assert approval.payload["approved_by"] == "katie@gatehouse"
    assert approval.payload["approves"] == [done["intent"]]
    intent_node = store.get(done["intent"])
    assert intent_node.meta["dry_run"] is True and executed.meta.get("dry_run") is None
    assert executed.result == done["result"]


def test_unapproved_side_effect_is_refused_by_the_gate(tmp_path):
    db = tmp_path / "runs.db"
    dry_open(db)  # a run with NO provision intent
    runtime = enablement._build_runtime(db, dry_run=False, policies=None)
    runtime.policies = [ApprovalGate(runtime.store)]
    run = runtime.resume(enablement.enablement_label(VENDOR, "inv-1"))

    with pytest.raises(PolicyViolation) as refused:
        run.tool_call(PROVISION_ACCESS, PROVISION_ARGS)
    refusal = runtime.store.get(refused.value.refusal_id)
    assert refusal.kind == NodeKind.REFUSAL
    assert refusal.payload["detail"] == "denied by policy"
    # Pure actions pass the gate without an approval.
    node = run.tool_call(
        GENERATE_TRAINING, {"vendor_id": VENDOR, "topics": ["x"], "audience": "all"}
    )
    assert node.result["format"] == "microlearning"


def test_opening_note_chains_to_the_sealed_review(tmp_path, monkeypatch):
    db = tmp_path / "runs.db"
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", "2026-08-23T12:00:00")
    import ledger
    from retrieval.search import ValidityGatedRetriever

    ledger.reset()
    ledger.configure(store=db, retriever=ValidityGatedRetriever(
        embed_fn=lambda t, k: [0.0] * 8,
        search_fn=lambda v, k: [{"chunk_id": "c#1", "doc_id": "d", "fact_type": "soc2_report",
                                 "issued": "2026-05-20", "content": "ok", "distance": 0.2}]))
    review = ledger.open_review_run("rev-inv", VENDOR)
    review.consult("mfa")
    closed = ledger.close_review_run("rev-inv", review_result="{}")
    ledger.reset()

    enablement.dry_runtime(store=db)
    run = open_enablement_run("inv-1", VENDOR, review_root=closed["root_id"])
    store = enablement.dry_runtime().store
    (opened_id,) = store.children(run.root_id)
    opened = store.get(opened_id)
    assert opened.payload["review_run"] == closed["root_id"]
    assert opened.payload["review_seal"] == closed["seal"]["digest"]
