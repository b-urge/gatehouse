"""Enablement agent (plan §2, §4 phase 2): ONE agent, THREE registered actions.

Activated by `vendor-approved` ("Vendor acme-saas-inc approved..."). It recalls
the review's findings from Memory Bank (a ledgered `recall_findings@1` node),
generates a microlearning module CONDITIONED on those findings — the weak-MFA
gap becomes an MFA-setup lesson — then executes exactly three registered
actions through the generic `take_action` tool: provisioning ticket, module
publish, rollout comms draft. Any other action name (`approve_vendor` included)
is refused by the registry and reported as a refusal_node: the same firewall
that guards phase 1, biting live in phase 2.

Run:  cp agents/review_fleet/.env agents/enablement/.env  &&  adk run agents/enablement
Try:  "Vendor acme-saas-inc approved. Run enablement."
"""

from __future__ import annotations

import json
import os
import re

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.tool_context import ToolContext
from pollard import PolicyViolation

import ledger.enablement as enledger

MODEL = "gemini-3.5-flash"
DEFAULT_VENDOR = "acme-saas-inc"
_VENDOR_RE = re.compile(r"vendor\s+([A-Za-z0-9][A-Za-z0-9._-]*?)[.!?,;:]?(?:\s|$)", re.IGNORECASE)


def _vendor_id(ctx: CallbackContext | ToolContext) -> str:
    pinned = ctx.state.get("vendor_id")
    if pinned:
        return pinned
    content = ctx.user_content
    text = " ".join(p.text for p in (content.parts or []) if p.text) if content else ""
    match = _VENDOR_RE.search(text)
    return match.group(1) if match else DEFAULT_VENDOR


def open_enablement(callback_context: CallbackContext) -> None:
    vendor_id = _vendor_id(callback_context)
    er = enledger.open_enablement_run(callback_context.invocation_id, vendor_id)
    callback_context.state["vendor_id"] = vendor_id
    callback_context.state["enablement_run"] = er.root_id
    return None


def close_enablement(callback_context: CallbackContext) -> None:
    try:
        report = enledger.close_enablement_run(
            callback_context.invocation_id,
            enablement_result=callback_context.state.get("enablement_result"),
        )
    except LookupError:
        return None
    callback_context.state["enablement_report"] = report
    db = os.environ.get("GATEHOUSE_ENABLEMENT_DB", enledger.DEFAULT_DB)
    print(
        f"[ledger] {report['label']} spent={report['spent']} avoided={report['avoided']}\n"
        f"[ledger] pollard show {db} {report['root_id']}"
    )
    return None


def recall_review_findings(query: str, tool_context: ToolContext) -> dict:
    """Recall this vendor's review findings from Memory Bank. The recall is
    recorded in the evidence ledger; cite the returned recall_node (and any
    evidence_run mentioned inside the memories) in the module you generate."""
    er = enledger.enablement_run_for(tool_context.invocation_id, _vendor_id(tool_context))
    try:
        node = er.recall(query)
    except PolicyViolation as refused:
        return {"error": str(refused), "refusal_node": refused.refusal_id, "memories": []}
    return {**node.result, "recall_node": node.id}


def take_action(action: str, args_json: str, tool_context: ToolContext) -> dict:
    """Execute one registered enablement action. `action` is the action name;
    `args_json` is its arguments as a JSON object string matching the action's
    schema exactly. Unregistered actions are refused by the registry — report
    the refusal_node instead of retrying."""
    er = enledger.enablement_run_for(tool_context.invocation_id, _vendor_id(tool_context))
    try:
        args = json.loads(args_json)
    except ValueError as e:
        return {"error": f"args_json is not valid JSON: {e}"}
    if not isinstance(args, dict):
        return {"error": "args_json must encode a JSON object"}
    try:
        node = er.act(action, args)
    except PolicyViolation as refused:
        return {"refused": str(refused), "refusal_node": refused.refusal_id, "action": action}
    return {**node.result, "action": action, "action_node": node.id}


_RESULT_SHAPE = json.dumps(
    {
        "vendor_id": "<vendor>",
        "enablement_run": "<enablement_run id from state>",
        "recall_node": "<recall_node from recall_review_findings>",
        "conditioned_on": ["<control ids the module addresses, e.g. CC6.1>"],
        "module_title": "<title>",
        "receipts": {
            "ticket": "<action_node>",
            "module": "<action_node>",
            "comms": "<action_node>",
        },
        "refusals": ["<refusal_node ids, if any action was refused>"],
    }
)


def build_enablement(model: str | BaseLlm = MODEL) -> Agent:
    """The enablement agent. `model` is injectable for scripted tests."""
    return Agent(
        name="enablement_agent",
        model=model,
        description="Gatehouse phase-2 enablement: findings-conditioned onboarding.",
        instruction=(
            "You are the enablement agent. A vendor was just approved; state has "
            "vendor_id={vendor_id?} and enablement_run={enablement_run?}. Steps, in order: "
            "(1) recall_review_findings with a query like 'security gaps and access control "
            "findings'. (2) From the recalled findings, generate a MICROLEARNING MODULE "
            "for staff who will use this vendor, CONDITIONED on the concrete gaps — if a "
            "finding names weak MFA on a legacy tier, the module teaches MFA setup for it. "
            "Structure the module as JSON with exactly: hook (one attention line naming the "
            "real gap), concept (short explanation grounded in the findings), scenario (one "
            "workplace situation with three options and the correct one marked), summary "
            "(one sentence). (3) Execute EXACTLY three actions via take_action, in order: "
            'create_provisioning_ticket {"vendor_id","system":"vendor-portal",'
            '"access_level":"standard","justification":<cite the review>}; '
            'publish_training_module {"vendor_id","title","module":<the module JSON as a '
            'string>,"conditioned_on":[<control ids from findings>],"evidence":<recall_node>}; '
            'send_rollout_comms {"vendor_id","audience":"all-staff","draft":<3-sentence '
            'announcement mentioning the training>,"mode":"draft-only"}. Only these three '
            "action names exist; anything else (approve_vendor especially) will be refused — "
            "if that happens, record the refusal_node and continue. (4) Output ONLY JSON "
            f"shaped exactly like: {_RESULT_SHAPE}"
        ),
        tools=[recall_review_findings, take_action],
        output_key="enablement_result",
        before_agent_callback=open_enablement,
        after_agent_callback=close_enablement,
    )


root_agent = build_enablement()
