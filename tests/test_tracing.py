"""[otel] -> Cloud Trace, offline (GEAP-AUDIT row 7): every ledger node becomes a
span that carries ids and digests only — never the query, the evidence, or the
blocked payload — and under ADK's runner the span nests beneath ADK's own tool
span, which is the shape Cloud Trace will show after the --otel_to_cloud deploy.
Skips in CI (no opentelemetry-sdk there)."""

import json

import pytest

pytest.importorskip("opentelemetry.sdk")

from pollard import MemoryStore, PolicyViolation  # noqa: E402

import ledger  # noqa: E402
from ledger.tracing import export_run, ledger_span_hook, local_tracing, tracer  # noqa: E402
from retrieval.search import ValidityGatedRetriever  # noqa: E402

NOW = "2026-08-23T12:00:00"
SECRET_QUERY = "MFA coverage on the legacy tier"
FAKE_HITS = [
    {
        "chunk_id": "acme-pen-test-2026-07#01",
        "doc_id": "acme-pen-test-2026-07",
        "fact_type": "pen_test",
        "issued": "2026-07-15",
        "content": "MED-1: legacy tier single-factor auth.",
        "distance": 0.27,
    }
]


@pytest.fixture(scope="module")
def spans():
    return local_tracing("memory")  # one provider per process; exporter cleared per test


@pytest.fixture(autouse=True)
def fresh(monkeypatch, spans):
    spans.clear()
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", NOW)
    monkeypatch.delenv("GATEHOUSE_RUN_LABEL", raising=False)
    monkeypatch.delenv("GATEHOUSE_LEDGER_TRACE", raising=False)
    ledger.reset()
    yield
    ledger.reset()


def fake_retriever():
    return ValidityGatedRetriever(
        embed_fn=lambda text, task: [0.0] * 8, search_fn=lambda vec, k: FAKE_HITS
    )


def attribute_blob(span) -> str:
    return json.dumps(dict(span.attributes), default=str)


def test_live_spans_are_content_free_and_carry_the_ids(spans):
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())  # default hook
    review = ledger.open_review_run("inv-1", "acme-saas-inc")
    node = review.consult(SECRET_QUERY)
    with pytest.raises(PolicyViolation) as refused:
        review.run.tool_call("approve_vendor", {"status": "approved"})
    ledger.close_review_run("inv-1", review_result='{"risk_score": 0.4}')

    by_name = {s.name: s for s in spans.get_finished_spans()}
    assert set(by_name) == {
        "pollard root",
        "execute_tool retrieve_evidence",
        "pollard refusal",
        "pollard note",
    }
    tool = by_name["execute_tool retrieve_evidence"]
    assert tool.attributes["pollard.node.id"] == node.id
    assert tool.attributes["pollard.parent.id"] == node.parent  # the review_opened note
    assert tool.attributes["pollard.result.digest"] == node.result_digest
    assert tool.attributes["pollard.registry.digest"] == ledger.runtime().registry.registry_digest
    assert tool.attributes["pollard.charge.steps"] == 1
    assert by_name["pollard refusal"].attributes["pollard.refusal.reason"] == "policy"
    assert by_name["pollard refusal"].attributes["pollard.node.id"] == refused.value.refusal_id

    everything = " ".join(attribute_blob(s) for s in spans.get_finished_spans())
    for leaked in (SECRET_QUERY, "single-factor", "approved", "risk_score", "acme-saas-inc"):
        assert leaked not in everything


def test_trace_switch_off_means_no_spans(spans, monkeypatch):
    monkeypatch.setenv("GATEHOUSE_LEDGER_TRACE", "0")
    assert ledger_span_hook() is None
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    ledger.open_review_run("inv-1", "acme-saas-inc").consult("mfa")
    assert spans.get_finished_spans() == ()


def test_export_run_rebuilds_a_parented_tree(spans, monkeypatch):
    monkeypatch.setenv("GATEHOUSE_LEDGER_TRACE", "0")  # record silently, export afterwards
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    review = ledger.open_review_run("inv-1", "acme-saas-inc")
    first, second = review.consult("mfa"), review.consult("pen test")

    count = export_run(review.run.store, review.root_id, tracer())

    assert count == 4  # root, review_opened, two searches
    exported = {s.attributes["pollard.node.id"]: s for s in spans.get_finished_spans()}
    root, a, b = exported[review.root_id], exported[first.id], exported[second.id]
    opened = exported[first.parent]
    assert root.parent is None
    assert opened.parent.span_id == root.context.span_id
    assert a.parent.span_id == opened.context.span_id
    assert b.parent.span_id == a.context.span_id
    assert root.context.trace_id == a.context.trace_id == b.context.trace_id


def test_under_adk_the_ledger_span_nests_beneath_the_tool_span(spans):
    pytest.importorskip("google.adk")
    from test_fleet_ledger import run_fleet  # the scripted, offline fleet

    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    state, _ = run_fleet("Review vendor acme-saas-inc.")

    finished = spans.get_finished_spans()
    by_id = {s.context.span_id: s for s in finished}
    ledger_spans = [s for s in finished if s.name == "execute_tool retrieve_evidence"]
    assert len(ledger_spans) == 2  # one per reviewer
    for span in ledger_spans:
        adk_tool_span = by_id[span.parent.span_id]
        assert adk_tool_span.name == "execute_tool search_vendor_evidence"
        assert span.context.trace_id == adk_tool_span.context.trace_id
    model_spans = [s for s in finished if s.name == "chat scripted"]
    assert len(model_spans) == 5  # every Gemini call, each under ADK's call_llm span
    assert {by_id[s.parent.span_id].name for s in model_spans} == {"call_llm"}
    assert all(s.attributes["gen_ai.request.model"] == "scripted" for s in model_spans)
    cited = {json.loads(state["security_findings"])[0]["evidence_node"]}
    assert cited <= {s.attributes["pollard.node.id"] for s in ledger_spans}
