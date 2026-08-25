"""The refusal-node spike, offline: the poisoned doc's own injected call is parsed
from the corpus file, refused by the fleet's registry, and recorded as a REFUSAL
node with provenance back to the document."""

import pytest
from pollard import NodeKind

import ledger
from spikes.refusal_spike import POISONED_DOC, extract_injected_call, run_spike


@pytest.fixture(autouse=True)
def fresh_ledger():
    ledger.reset()
    yield
    ledger.reset()


def test_the_corpus_doc_still_carries_the_payload():
    name, args = extract_injected_call(POISONED_DOC.read_text(encoding="utf-8"))
    assert (name, args) == ("approve_vendor", {"status": "approved"})


def test_injected_call_is_refused_into_the_ledger(tmp_path):
    out = run_spike(tmp_path / "runs.db")
    refusal = out["refusal"]

    assert out["registered"] == ["retrieve_evidence@1"]
    assert refusal.kind == NodeKind.REFUSAL
    assert refusal.payload["reason"] == "policy"
    assert refusal.payload["blocked_kind"] == "tool_call"
    assert "approve_vendor" in refusal.payload["detail"]
    assert refusal.payload["registry_digest"] == ledger.runtime().registry.registry_digest

    store = ledger.runtime().store
    (note_id,) = store.children(refusal.id)
    note = store.get(note_id)
    assert note.kind == NodeKind.NOTE
    assert note.payload["source_doc"] == "acme-vendor-overview"
    assert note.payload["refusal"] == refusal.id
    assert out["report"]["spent"].get("steps", 0.0) == 0.0  # nothing executed
