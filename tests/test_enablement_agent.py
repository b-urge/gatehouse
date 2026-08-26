"""The enablement agent end-to-end under ADK's runner, offline: a scripted model
stands in for Gemini, fake handlers for Firestore/Memory Bank, the ledger is
real. Proves: recall is a ledgered node, all three registered actions execute
and return citable node ids, a forbidden `approve_vendor` attempt becomes a
live REFUSAL node (the firewall biting in-agent, not just in a spike), and the
result is noted under the run. Skips cleanly in CI (google-adk absent there)."""

import asyncio
import json

import pytest

pytest.importorskip("google.adk")

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402
from pollard import MemoryStore, NodeKind  # noqa: E402

import ledger.enablement as enledger  # noqa: E402
from actions.enablement import (  # noqa: E402
    CREATE_TICKET,
    PUBLISH_MODULE,
    RECALL_FINDINGS,
    SEND_COMMS,
)
from agents.enablement.agent import build_enablement  # noqa: E402

MEMORIES = [
    "Vendor acme-saas-inc review finding [CC6.1|medium]: MFA not enforced on the "
    "legacy tier (policy: SOC 2 CC6.1; evidence_node abc123; evidence_run root999)"
]

MODULE = {
    "hook": "One legacy login still skips MFA - here's how we close it.",
    "concept": "Acme's SOC 2 flagged single-factor auth on the legacy tier (CC6.1).",
    "scenario": {
        "situation": "You're granted legacy-tier access on day one.",
        "options": ["Use password only", "Enable MFA before first login", "Share creds"],
        "correct": 1,
    },
    "summary": "Enable MFA on the legacy tier before first use.",
}


class ScriptedEnablementLlm(BaseLlm):
    """Turn 1: recall. Turn 2: three registered actions + one forbidden attempt
    (parallel calls). Turn 3: final JSON citing every node the tools returned."""

    model: str = "scripted"

    async def generate_content_async(self, llm_request, stream=False):
        last = llm_request.contents[-1] if llm_request.contents else None
        fn_responses = [p.function_response for p in (last.parts or []) if p.function_response]
        if not fn_responses:
            parts = [
                types.Part.from_function_call(
                    name="recall_review_findings",
                    args={"query": "security gaps and access control findings"},
                )
            ]
        elif fn_responses[0].name == "recall_review_findings":
            recall = fn_responses[0].response
            evidence = recall["recall_node"]
            parts = [
                types.Part.from_function_call(
                    name="take_action",
                    args={
                        "action": CREATE_TICKET,
                        "args_json": json.dumps(
                            {
                                "vendor_id": "acme-saas-inc",
                                "system": "vendor-portal",
                                "access_level": "standard",
                                "justification": "Approved after review; see recall "
                                + evidence,
                            }
                        ),
                    },
                ),
                types.Part.from_function_call(
                    name="take_action",
                    args={
                        "action": PUBLISH_MODULE,
                        "args_json": json.dumps(
                            {
                                "vendor_id": "acme-saas-inc",
                                "title": "MFA on the legacy tier",
                                "module": json.dumps(MODULE),
                                "conditioned_on": ["CC6.1"],
                                "evidence": evidence,
                            }
                        ),
                    },
                ),
                types.Part.from_function_call(
                    name="take_action",
                    args={
                        "action": SEND_COMMS,
                        "args_json": json.dumps(
                            {
                                "vendor_id": "acme-saas-inc",
                                "audience": "all-staff",
                                "draft": "Acme goes live next week; complete the MFA "
                                "microlearning before requesting access.",
                                "mode": "draft-only",
                            }
                        ),
                    },
                ),
                types.Part.from_function_call(
                    name="take_action",
                    args={"action": "approve_vendor", "args_json": json.dumps({"status": "ok"})},
                ),
            ]
        else:
            by_action: dict[str, dict] = {}
            for fr in fn_responses:
                resp = fr.response
                by_action[resp.get("action", "?")] = resp
            result = {
                "vendor_id": "acme-saas-inc",
                "enablement_run": "from-state",
                "recall_node": "cited-above",
                "conditioned_on": ["CC6.1"],
                "module_title": "MFA on the legacy tier",
                "receipts": {
                    "ticket": by_action[CREATE_TICKET]["action_node"],
                    "module": by_action[PUBLISH_MODULE]["action_node"],
                    "comms": by_action[SEND_COMMS]["action_node"],
                },
                "refusals": [by_action["approve_vendor"]["refusal_node"]],
            }
            parts = [types.Part(text=json.dumps(result))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


@pytest.fixture()
def sink_and_ledger(monkeypatch):
    monkeypatch.delenv("GATEHOUSE_RUN_LABEL", raising=False)
    enledger.reset_enablement()
    sink: dict[str, list[dict]] = {CREATE_TICKET: [], PUBLISH_MODULE: [], SEND_COMMS: []}

    def writer(name):
        def handle(args):
            sink[name].append(args)
            return {"ok": True, "doc": f"{name}/doc-{len(sink[name])}"}

        return handle

    handlers = {
        RECALL_FINDINGS: lambda args: {"memories": MEMORIES, "count": len(MEMORIES)},
        CREATE_TICKET: writer(CREATE_TICKET),
        PUBLISH_MODULE: writer(PUBLISH_MODULE),
        SEND_COMMS: writer(SEND_COMMS),
    }
    enledger.configure_enablement(store=MemoryStore(), handlers=handlers)
    yield sink
    enledger.reset_enablement()


def run_enablement(prompt: str) -> dict:
    runner = InMemoryRunner(
        agent=build_enablement(model=ScriptedEnablementLlm()), app_name="gatehouse-test"
    )

    async def go():
        session = await runner.session_service.create_session(
            app_name="gatehouse-test", user_id="katie"
        )
        async for _ in runner.run_async(
            user_id="katie",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            pass
        session = await runner.session_service.get_session(
            app_name="gatehouse-test", user_id="katie", session_id=session.id
        )
        return dict(session.state)

    return asyncio.run(go())


def test_enablement_records_recall_three_actions_and_a_live_refusal(sink_and_ledger):
    state = run_enablement("Vendor acme-saas-inc approved. Run enablement.")
    store = enledger.runtime_enablement().store

    assert state["vendor_id"] == "acme-saas-inc"
    root = store.get(state["enablement_run"])
    assert root.kind == NodeKind.ROOT
    assert root.payload["run"].startswith("enable:acme-saas-inc:")

    result = json.loads(state["enablement_result"])
    kinds = {}
    for node_id in [*result["receipts"].values()]:
        node = store.get(node_id)
        assert node.kind == NodeKind.TOOL_CALL
        kinds[node.payload["tool"]] = node
    assert set(kinds) == {CREATE_TICKET, PUBLISH_MODULE, SEND_COMMS}

    refusal = store.get(result["refusals"][0])
    assert refusal.kind == NodeKind.REFUSAL
    assert "approve_vendor" in json.dumps(refusal.payload)

    # The side effects actually reached the handlers, conditioned on the finding.
    assert sink_and_ledger[PUBLISH_MODULE][0]["conditioned_on"] == ["CC6.1"]
    assert "MFA" in sink_and_ledger[PUBLISH_MODULE][0]["module"]
    assert sink_and_ledger[CREATE_TICKET][0]["system"] == "vendor-portal"
    assert sink_and_ledger[SEND_COMMS][0]["mode"] == "draft-only"

    # Verdict noted under the run.
    assert state["enablement_report"]["root_id"] == state["enablement_run"]
