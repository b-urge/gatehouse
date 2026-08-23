"""The retriever's gate, offline: stale pen test pruned, current valid,
policy clauses invariant, prune notices name the doc (the D4 beat in unit form)."""

from datetime import datetime

from retrieval.search import ValidityGatedRetriever

NOW = datetime(2026, 8, 23, 12, 0)

FAKE_HITS = [
    {
        "chunk_id": "acme-pen-test-2026-07#01",
        "doc_id": "acme-pen-test-2026-07",
        "fact_type": "pen_test",
        "issued": "2026-07-15",
        "content": "MED-1: legacy tier single-factor auth.",
        "distance": 0.27,
    },
    {
        "chunk_id": "acme-pen-test-2025-02#01",
        "doc_id": "acme-pen-test-2025-02",
        "fact_type": "pen_test",
        "issued": "2025-02-10",
        "content": "No critical or high findings.",
        "distance": 0.29,
    },
    {
        "chunk_id": "acme-dpa#01",
        "doc_id": "acme-dpa",
        "fact_type": "policy_clause",
        "issued": "2026-01-15",
        "content": "Clause 4.1: US/EU residency only.",
        "distance": 0.41,
    },
]


def make_retriever(record):
    return ValidityGatedRetriever(
        embed_fn=lambda text, task: [0.0] * 8,
        search_fn=lambda vec, k: FAKE_HITS,
        on_consultation=record,
    )


def test_stale_pruned_current_valid_policy_invariant():
    r = make_retriever(lambda payload: "node-123").retrieve("security gaps", query_time=NOW)
    valid_ids = {h.doc_id for h in r.valid}
    pruned_ids = {h.doc_id for h in r.pruned}
    assert "acme-pen-test-2026-07" in valid_ids
    assert "acme-dpa" in valid_ids
    assert pruned_ids == {"acme-pen-test-2025-02"}
    stale = r.pruned[0]
    assert stale.validity < 0.5
    assert r.stl_satisfied


def test_prune_notice_reads_as_reacquisition_finding():
    r = make_retriever(lambda payload: "node-123").retrieve("pen test", query_time=NOW)
    notices = r.reacquisition_notices()
    assert len(notices) == 1
    assert "acme-pen-test-2025-02" in notices[0]
    assert "request updated evidence" in notices[0]


def test_consultation_callback_receives_evidence_payload():
    seen = {}

    def record(payload):
        seen.update(payload)
        return "pollard-node-abc"

    r = make_retriever(record).retrieve("mfa", query_time=NOW)
    assert r.evidence_node == "pollard-node-abc"
    assert seen["valid"] and seen["pruned"]
    assert "stl_robustness" in seen
