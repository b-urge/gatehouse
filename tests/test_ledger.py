"""The evidence plane, offline: a retrieval becomes a content-addressed TOOL_CALL
node, the as-of time is pinned per review, the verdict is noted under the run,
and replay serves the recorded consultation without touching the retriever."""

from datetime import datetime

import pytest
from pollard import MemoryStore, NodeKind

import ledger
from retrieval.search import ValidityGatedRetriever

NOW = "2026-08-23T12:00:00"

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
]


def fake_retriever(calls: list | None = None) -> ValidityGatedRetriever:
    def search(vec, k):
        if calls is not None:
            calls.append(k)
        return FAKE_HITS

    return ValidityGatedRetriever(embed_fn=lambda text, task: [0.0] * 8, search_fn=search)


@pytest.fixture(autouse=True)
def fresh_ledger(monkeypatch):
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", NOW)
    monkeypatch.delenv("GATEHOUSE_RUN_LABEL", raising=False)
    ledger.reset()
    yield
    ledger.reset()


def test_consult_records_the_gated_evidence_set():
    calls = []
    ledger.configure(store=MemoryStore(), retriever=fake_retriever(calls))
    review = ledger.open_review_run("inv-1", "acme-saas-inc")

    node = review.consult("pen test findings", k=4)

    assert calls == [4]
    assert node.kind == NodeKind.TOOL_CALL
    assert node.payload["args"] == {"query": "pen test findings", "query_time": NOW, "k": 4}
    valid = {h["doc_id"] for h in node.result["valid_evidence"]}
    pruned = {h["doc_id"] for h in node.result["pruned_evidence"]}
    assert valid == {"acme-pen-test-2026-07"}
    assert pruned == {"acme-pen-test-2025-02"}
    assert node.result["pruned_evidence"][0]["validity"] < 0.5
    assert "request updated evidence" in node.result["pruned_notices"][0]
    assert node.result["stl_satisfied"] is True


def test_query_time_is_pinned_once_per_review(monkeypatch):
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    review = ledger.open_review_run("inv-1", "acme-saas-inc")
    first = review.consult("mfa")
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", "2030-01-01T00:00:00")  # ignored mid-review
    second = review.consult("subprocessors")
    assert first.payload["args"]["query_time"] == second.payload["args"]["query_time"] == NOW
    assert second.parent == first.id  # the trunk: consultations chain in order

    explicit = ledger.open_review_run("inv-2", "acme-saas-inc", query_time=datetime(2027, 1, 2, 3))
    assert explicit.query_time == "2027-01-02T03:00:00"


def test_review_run_for_reuses_the_open_review():
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    opened = ledger.open_review_run("inv-1", "acme-saas-inc")
    assert ledger.review_run_for("inv-1") is opened
    lazily = ledger.review_run_for("inv-9")
    assert lazily.vendor_id == "unknown" and lazily.root_id != opened.root_id


def test_close_notes_the_verdict_and_reports_spend():
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    review = ledger.open_review_run("inv-1", "acme-saas-inc")
    review.consult("mfa")
    verdict = '```json\n{"vendor_id": "acme-saas-inc", "findings": [], "risk_score": 0.1}\n```'

    report = ledger.close_review_run("inv-1", review_result=verdict)

    assert report["root_id"] == review.root_id
    assert report["label"] == "review:acme-saas-inc:inv-1"
    assert report["spent"]["steps"] == 1.0
    note = review.run.cursor
    assert note.kind == NodeKind.NOTE
    assert note.payload["kind"] == "review_result"
    assert '"risk_score": 0.1' in note.payload["review_result"]
    assert not note.payload["review_result"].startswith("```")
    assert ledger.get_review_run("inv-1") is None
    with pytest.raises(LookupError):
        ledger.close_review_run("inv-1")


def test_replay_serves_the_recorded_consultation_offline(tmp_path, monkeypatch):
    db = tmp_path / "runs.db"
    monkeypatch.setenv("GATEHOUSE_RUN_LABEL", "review:acme-saas-inc:golden")

    ledger.configure(store=db, mode="record", retriever=fake_retriever())
    recorded = ledger.open_review_run("live-inv", "acme-saas-inc").consult("pen test")
    ledger.close_review_run("live-inv", review_result="{}")
    ledger.reset()

    def exploding_search(vec, k):
        raise AssertionError("replay must never reach the retriever")

    offline = ValidityGatedRetriever(
        embed_fn=lambda text, task: [0.0] * 8, search_fn=exploding_search
    )
    ledger.configure(store=db, mode="replay", retriever=offline)
    replayed = ledger.open_review_run("other-inv", "acme-saas-inc").consult("pen test")

    assert replayed.id == recorded.id
    assert replayed.result == recorded.result
    report = ledger.close_review_run("other-inv", review_result="{}")
    assert report["avoided"].get("steps") == 1.0
