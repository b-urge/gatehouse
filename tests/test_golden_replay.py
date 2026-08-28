"""The killer move (plan §5): the committed golden review — recorded against live
Gemini + Firestore — replays offline, byte for byte. The sealed export refuses to
import if tampered; the replay reruns the whole fleet with a model and retriever
that raise if touched; and the replayed run seals to the manifest's exact digest.
Skips until the golden fixture is recorded, and in CI (no google-adk there)."""

import json
from pathlib import Path

import pytest

pytest.importorskip("google.adk")

GOLDEN = Path(__file__).resolve().parents[1] / "evidence" / "golden" / "acme-saas-inc.pollard"
MANIFEST = GOLDEN.with_name("MANIFEST.json")
if not (GOLDEN.exists() and MANIFEST.exists()):
    pytest.skip(
        "golden fixture not recorded yet (spikes/record_golden.py)", allow_module_level=True
    )

from pollard import NodeKind, SQLiteStore, import_subtree  # noqa: E402
from test_model_calls import ExplodingLlm, exploding_retriever, run_with  # noqa: E402

import ledger  # noqa: E402


@pytest.fixture()
def golden(tmp_path, monkeypatch, request):
    mode = request.config.getoption("--pollard-mode", default=None)
    if mode == "record":
        pytest.skip("golden test is replay-only; re-record via spikes/record_golden.py")
    manifest = json.loads(MANIFEST.read_text())
    store = SQLiteStore(tmp_path / "golden.db")
    imported = import_subtree(GOLDEN, store)  # verifies the seal before writing a node
    assert imported.root_id == manifest["root_id"]
    monkeypatch.setenv("GATEHOUSE_RUN_LABEL", manifest["label"])
    monkeypatch.delenv("GATEHOUSE_QUERY_TIME", raising=False)  # the recording carries it
    for key, value in manifest.get("environment", {}).items():
        # Replay under the recorded backend flavor: these vars shape the request
        # (e.g. Vertex adds response_json_schema to tool declarations).
        if value:
            monkeypatch.setenv(key, value)
        else:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GATEHOUSE_LEDGER_TRACE", "0")
    ledger.reset()
    ledger.configure(store=store, mode="replay", retriever=exploding_retriever())
    yield manifest, store
    ledger.reset()


def test_golden_review_replays_offline_to_the_same_seal(golden):
    manifest, store = golden

    state = run_with(ExplodingLlm(model=manifest["model"]), prompt=manifest["prompt"])

    review = json.loads(ledger._strip_fences(state["review_result"]))
    assert review["vendor_id"] == manifest["vendor_id"]
    assert review["evidence_run"] == manifest["root_id"]
    assert 0.0 <= float(review["risk_score"]) <= 1.0
    assert review["findings"], "a golden review with no findings would prove nothing"
    for finding in review["findings"]:
        cited = store.get(finding["evidence_node"])  # every citation resolves in the ledger
        assert cited.kind == NodeKind.TOOL_CALL
        assert cited.payload["tool"] == "retrieve_evidence"

    assert state["query_time"] == manifest["query_time"]  # read back from review_opened
    report = state["evidence_report"]
    assert report["seal"]["digest"] == manifest["seal"]["digest"]
    assert report["avoided"]["steps"] == report["spent"]["steps"] > 0
    if manifest["model"] != "scripted":
        assert report["avoided"]["tokens"] > 0  # real Gemini usage, never re-spent
