"""The fleet end-to-end under ADK's own runner, offline: a scripted model stands in
for Gemini, a fake retriever for Firestore, and the ledger is real. Proves the
orchestrator opens one run per review, every search lands as a TOOL_CALL node the
reviewer then cites, and the verdict is noted under the run.
Skips cleanly in CI (google-adk isn't installed there)."""

import asyncio
import json

import pytest

pytest.importorskip("google.adk")

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402
from pollard import MemoryStore, NodeKind  # noqa: E402

import ledger  # noqa: E402
from agents.review_fleet.agent import build_fleet  # noqa: E402
from retrieval.search import ValidityGatedRetriever  # noqa: E402

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


class ScriptedLlm(BaseLlm):
    """Reviewer turn 1: search. Turn 2: one finding citing the node it was handed.
    Synthesizer: echo the rendered instruction's JSON skeleton so we can check
    the state templating."""

    model: str = "scripted"

    async def generate_content_async(self, llm_request, stream=False):
        last = llm_request.contents[-1] if llm_request.contents else None
        has_tools = bool(llm_request.config and llm_request.config.tools)
        fn_responses = [p.function_response for p in (last.parts or []) if p.function_response]
        if has_tools and not fn_responses:
            part = types.Part.from_function_call(
                name="search_vendor_evidence", args={"query": "MFA and access control"}
            )
        elif has_tools:
            hit = fn_responses[0].response
            finding = {
                "control": "CC6.1",
                "severity": "medium",
                "rationale": hit["valid_evidence"][0]["content"],
                "policy_clause": "SOC 2 CC6.1",
                "evidence_node": hit["evidence_node"],
            }
            stale = [
                {
                    "control": "EVIDENCE-STALE",
                    "severity": "medium",
                    "rationale": notice,
                    "policy_clause": "evidence freshness",
                    "evidence_node": hit["evidence_node"],
                }
                for notice in hit["pruned_notices"]
            ]
            part = types.Part(text=json.dumps([finding, *stale]))
        else:
            instruction = llm_request.config.system_instruction
            skeleton = instruction[instruction.index("Output ONLY JSON:") + 17 :].strip()
            part = types.Part(text=skeleton)
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def run_fleet(prompt: str) -> tuple[dict, list]:
    runner = InMemoryRunner(agent=build_fleet(model=ScriptedLlm()), app_name="gatehouse-test")

    async def go():
        session = await runner.session_service.create_session(
            app_name="gatehouse-test", user_id="muntaser"
        )
        events = [
            e
            async for e in runner.run_async(
                user_id="muntaser",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            )
        ]
        session = await runner.session_service.get_session(
            app_name="gatehouse-test", user_id="muntaser", session_id=session.id
        )
        return dict(session.state), events

    return asyncio.run(go())


@pytest.fixture(autouse=True)
def offline_ledger(monkeypatch):
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", NOW)
    monkeypatch.delenv("GATEHOUSE_RUN_LABEL", raising=False)
    ledger.reset()
    retriever = ValidityGatedRetriever(
        embed_fn=lambda text, task: [0.0] * 8, search_fn=lambda vec, k: FAKE_HITS
    )
    ledger.configure(store=MemoryStore(), retriever=retriever)
    yield
    ledger.reset()


def test_fleet_records_every_search_and_findings_cite_real_nodes():
    state, _ = run_fleet("Review vendor acme-saas-inc.")
    store = ledger.runtime().store

    assert state["vendor_id"] == "acme-saas-inc"
    assert state["query_time"] == NOW
    root = store.get(state["evidence_run"])
    assert root.kind == NodeKind.ROOT
    assert root.payload["run"].startswith("review:acme-saas-inc:")

    security = json.loads(state["security_findings"])
    dpa = json.loads(state["dpa_findings"])
    cited = {f["evidence_node"] for f in security + dpa}
    assert "unrecorded" not in cited
    assert len(cited) == 2  # one search per reviewer, two distinct nodes
    for node_id in cited:
        node = store.get(node_id)
        assert node.kind == NodeKind.TOOL_CALL
        assert node.payload["tool"] == "retrieve_evidence"
        assert node.payload["args"]["query_time"] == NOW
    assert any(f["control"] == "EVIDENCE-STALE" for f in security)  # the freshness trap fired

    assert state["evidence_report"]["spent"]["steps"] == 2.0
    assert ledger.get_review_run(state["evidence_report"]["root_id"]) is None


def test_verdict_is_noted_under_the_run_and_carries_the_run_id():
    state, _ = run_fleet("Review vendor acme-saas-inc.")
    store = ledger.runtime().store
    root_id = state["evidence_run"]

    assert f'"evidence_run": "{root_id}"' in state["review_result"]
    assert '"vendor_id": "acme-saas-inc"' in state["review_result"]

    # Walk the trunk: root -> search -> search -> verdict note.
    trunk, cursor = [], root_id
    while children := store.children(cursor):
        cursor = children[0]
        trunk.append(store.get(cursor))
    kinds = [n.kind for n in trunk]
    assert kinds == [NodeKind.TOOL_CALL, NodeKind.TOOL_CALL, NodeKind.NOTE]
    assert trunk[-1].payload["kind"] == "review_result"
    assert root_id in trunk[-1].payload["review_result"]
