"""The ADK adapter (plan §5): every Gemini call is a MODEL_CALL node, and a recorded
review replays end to end with the model and the retriever both provably unreached —
the offline half of "judges reproduce the full review with no credentials, no spend".
Skips in CI (google-adk isn't installed there)."""

import asyncio
import json

import pytest

pytest.importorskip("google.adk")

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402
from pollard import MemoryStore, NodeKind  # noqa: E402
from pollard.errors import MissingRecording  # noqa: E402
from test_fleet_ledger import FAKE_HITS, ScriptedLlm  # noqa: E402

import ledger  # noqa: E402
from agents.review_fleet.agent import build_fleet  # noqa: E402
from ledger.adk import identity_safe, response_result  # noqa: E402
from retrieval.search import ValidityGatedRetriever  # noqa: E402

GOLDEN_LABEL = "review:acme-saas-inc:golden"
NOW = "2026-08-23T12:00:00"


class CountingLlm(ScriptedLlm):
    """The scripted model, but it reports token usage like Gemini does."""

    model: str = "gemini-3.5-flash"

    async def generate_content_async(self, llm_request, stream=False):
        async for response in super().generate_content_async(llm_request, stream):
            response.usage_metadata = types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=20
            )
            yield response


class ExplodingLlm(BaseLlm):
    model: str = "gemini-3.5-flash"

    async def generate_content_async(self, llm_request, stream=False):
        raise AssertionError("replay must never reach the model")
        yield  # pragma: no cover - makes this an async generator


def exploding_retriever() -> ValidityGatedRetriever:
    def boom(*args):
        raise AssertionError("replay must never reach the retriever")

    return ValidityGatedRetriever(embed_fn=boom, search_fn=boom)


def fake_retriever() -> ValidityGatedRetriever:
    return ValidityGatedRetriever(
        embed_fn=lambda text, task: [0.0] * 8, search_fn=lambda vec, k: FAKE_HITS
    )


def run_with(model, prompt="Review vendor acme-saas-inc."):
    runner = InMemoryRunner(agent=build_fleet(model=model), app_name="gatehouse-test")

    async def go():
        session = await runner.session_service.create_session(
            app_name="gatehouse-test", user_id="muntaser"
        )
        async for _ in runner.run_async(
            user_id="muntaser",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            pass
        session = await runner.session_service.get_session(
            app_name="gatehouse-test", user_id="muntaser", session_id=session.id
        )
        return dict(session.state)

    return asyncio.run(go())


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setenv("GATEHOUSE_LEDGER_TRACE", "0")
    monkeypatch.delenv("GATEHOUSE_RUN_LABEL", raising=False)
    monkeypatch.delenv("GATEHOUSE_QUERY_TIME", raising=False)
    ledger.reset()
    yield
    ledger.reset()


def test_identity_safe_strips_floats_and_keeps_everything_else():
    value = {"validity": 0.932, "k": 6, "ok": True, "none": None, "hits": [{"d": 0.5}], "s": "x"}
    assert identity_safe(value) == {
        "validity": "0.932", "k": 6, "ok": True, "none": None, "hits": [{"d": "0.5"}], "s": "x"
    }


def test_response_result_carries_the_verbatim_response_and_usage():
    response = LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text="ok")]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=7, candidates_token_count=3
        ),
    )
    result = response_result(response)
    assert LlmResponse.model_validate(result["response"]) == response
    assert result["usage"] == {"input_tokens": 7, "output_tokens": 3}


def test_every_model_call_is_a_node_with_the_request_as_identity(monkeypatch):
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", NOW)
    ledger.configure(store=MemoryStore(), retriever=fake_retriever())
    state = run_with(CountingLlm())
    store = ledger.runtime().store

    calls = [n for n in store.walk(state["evidence_run"]) if n.kind == NodeKind.MODEL_CALL]
    assert len(calls) == 5
    first = calls[0]
    assert first.payload["agent"] == "security_reviewer"
    assert first.payload["model"] == "gemini-3.5-flash"
    assert "search_vendor_evidence" in json.dumps(first.payload["config"]["tools"])
    assert first.payload["contents"][0]["parts"][0]["text"] == "Review vendor acme-saas-inc."
    assert first.result["usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert first.result["response"]["content"]["parts"][0]["function_call"]["name"] == (
        "search_vendor_evidence"
    )
    assert state["evidence_report"]["spent"]["tokens"] == 600.0  # 5 calls x 120


def test_recorded_review_replays_offline_end_to_end(tmp_path, monkeypatch):
    db = tmp_path / "golden.db"
    monkeypatch.setenv("GATEHOUSE_RUN_LABEL", GOLDEN_LABEL)

    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", NOW)
    ledger.configure(store=db, mode="record", retriever=fake_retriever())
    recorded = run_with(CountingLlm())
    ledger.reset()

    # Replay: no as-of time in the environment (the recording carries it), a model and a
    # retriever that explode if touched, and strict replay mode.
    monkeypatch.delenv("GATEHOUSE_QUERY_TIME")
    ledger.configure(store=db, mode="replay", retriever=exploding_retriever())
    replayed = run_with(ExplodingLlm())

    assert replayed["review_result"] == recorded["review_result"]
    assert replayed["security_findings"] == recorded["security_findings"]
    assert replayed["dpa_findings"] == recorded["dpa_findings"]
    assert replayed["query_time"] == NOW  # read back from the review_opened note
    assert replayed["evidence_run"] == recorded["evidence_run"]
    report = replayed["evidence_report"]
    # `spent` is recomputed from the stored tree (the recording's charges); `avoided` is
    # what this process did not pay: every step and every token.
    assert report["spent"]["steps"] == 7.0 and report["spent"]["tokens"] == 600.0
    assert report["avoided"]["steps"] == 7.0 and report["avoided"]["tokens"] == 600.0


def test_strict_replay_refuses_a_conversation_that_diverged(tmp_path, monkeypatch):
    db = tmp_path / "golden.db"
    monkeypatch.setenv("GATEHOUSE_RUN_LABEL", GOLDEN_LABEL)
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", NOW)
    ledger.configure(store=db, mode="record", retriever=fake_retriever())
    run_with(CountingLlm())
    ledger.reset()

    ledger.configure(store=db, mode="replay", retriever=exploding_retriever())
    with pytest.raises(MissingRecording):
        run_with(ExplodingLlm(), prompt="Review vendor acme-saas-inc. Be brief.")


def test_hybrid_serves_what_it_has_and_records_the_rest(tmp_path, monkeypatch):
    db = tmp_path / "golden.db"
    monkeypatch.setenv("GATEHOUSE_RUN_LABEL", GOLDEN_LABEL)
    monkeypatch.setenv("GATEHOUSE_QUERY_TIME", NOW)
    ledger.configure(store=db, mode="record", retriever=fake_retriever())
    run_with(CountingLlm())
    ledger.reset()

    ledger.configure(store=db, mode="hybrid", retriever=exploding_retriever())
    state = run_with(ExplodingLlm())  # a full hit: nothing live is needed
    assert state["evidence_report"]["avoided"]["steps"] == 7.0
    assert state["evidence_report"]["avoided"]["tokens"] == 600.0
