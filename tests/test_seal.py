"""Seal and verify, offline (plan §5, the seal-digest beat): a closed review carries a
rolling SHA-256 seal and a custody record; replaying the recording seals to the very
same digest without attesting; and a ledger edited after the fact cannot be sealed."""

import sqlite3

import pytest
from pollard import IntegrityError, MemoryStore, SQLiteStore, seal

import ledger
from ledger.seal import custody_records, seal_review, signer_identity, verify_review
from retrieval.search import ValidityGatedRetriever

NOW = "2026-08-23T12:00:00"
FAKE_HITS = [
    {
        "chunk_id": "acme-soc2-2026#02",
        "doc_id": "acme-soc2-2026",
        "fact_type": "soc2_report",
        "issued": "2026-05-20",
        "content": "CC6.1 exception: MFA not enforced on the legacy tier.",
        "distance": 0.2,
    }
]


def fake_retriever() -> ValidityGatedRetriever:
    return ValidityGatedRetriever(
        embed_fn=lambda text, task: [0.0] * 8, search_fn=lambda vec, k: FAKE_HITS
    )


def exploding_retriever() -> ValidityGatedRetriever:
    def boom(*args):
        raise AssertionError("replay must never reach the retriever")

    return ValidityGatedRetriever(embed_fn=boom, search_fn=boom)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", NOW)
    monkeypatch.setenv("GATEHOUSE_LEDGER_TRACE", "0")
    monkeypatch.setenv("GATEHOUSE_SIGNER", "muntaser@gatehouse-test")
    monkeypatch.delenv("GATEHOUSE_RUN_LABEL", raising=False)
    ledger.reset()
    yield
    ledger.reset()


def review(invocation: str, verdict: str = '{"risk_score": 0.4}') -> dict:
    run = ledger.open_review_run(invocation, "acme-saas-inc")
    run.consult("mfa on the legacy tier")
    return ledger.close_review_run(invocation, review_result=verdict)


def test_closing_a_review_seals_it_and_publishes_custody():
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    first = review("inv-1")
    second = review("inv-2")

    sealed = first["seal"]
    assert sealed["algorithm"] == "sha256:pollard/v1:seal"
    assert len(sealed["digest"]) == 64
    assert sealed["nodes"] == 4  # root, review_opened, search, verdict
    assert sealed["digest"] == seal(ledger.runtime().store, first["root_id"]).digest
    assert sealed["custody"]["sequence"] == 1 and second["seal"]["custody"]["sequence"] == 2
    assert sealed["custody"]["signer"] == "muntaser@gatehouse-test"

    records = custody_records()
    assert [r.root_id for r in records] == [first["root_id"], second["root_id"]]
    assert records[0].digest == sealed["digest"] and records[0].store_id == "memory"
    assert verify_review(first["root_id"]) == {"ok": True, "findings": []}


def test_replay_seals_to_the_same_digest_without_attesting(tmp_path, monkeypatch):
    db = tmp_path / "golden.db"
    monkeypatch.setenv("GATEHOUSE_RUN_LABEL", "review:acme-saas-inc:golden")
    ledger.configure(store=db, mode="record", retriever=fake_retriever())
    recorded = review("live")
    ledger.reset()

    ledger.configure(store=db, mode="replay", retriever=exploding_retriever())
    replayed = review("later")

    assert replayed["seal"]["digest"] == recorded["seal"]["digest"]
    assert "custody" not in replayed["seal"]  # a replay re-derives; it does not attest
    assert len(custody_records()) == 1


def test_an_edited_ledger_cannot_be_sealed(tmp_path):
    db = tmp_path / "runs.db"
    ledger.configure(store=db, retriever=fake_retriever())
    closed = review("inv-1")
    root_id = closed["root_id"]
    search = next(n for n in ledger.runtime().store.walk(root_id) if n.kind == "tool_call")

    # Someone rewrites history: the pruned/valid evidence set of a recorded search.
    forged = search.result_text.replace("MFA not enforced", "MFA enforced")
    assert forged != search.result_text
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE nodes SET result = ? WHERE id = ?", (forged, search.id))

    tampered = SQLiteStore(db, read_only=True)
    with pytest.raises(IntegrityError, match="result digest does not match"):
        seal_review(root_id, store=tampered, publish=False)
    report = verify_review(root_id, store=tampered)
    assert report["ok"] is False
    assert report["findings"][0]["node_id"] == search.id


def test_unwritable_custody_log_is_a_warning_not_a_failure(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setenv("GATEHOUSE_SEAL_DB", str(blocker / "seals.db"))
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    with pytest.warns(RuntimeWarning, match="seal digest computed but not published"):
        closed = review("inv-1")
    assert len(closed["seal"]["digest"]) == 64 and "custody" not in closed["seal"]


def test_signer_identity_prefers_the_explicit_setting(monkeypatch):
    assert signer_identity() == "muntaser@gatehouse-test"
    monkeypatch.delenv("GATEHOUSE_SIGNER")
    monkeypatch.setenv("K_SERVICE", "gatehouse-intake")
    assert signer_identity() == "gatehouse-intake"
    monkeypatch.delenv("K_SERVICE")
    assert "@" in signer_identity()
