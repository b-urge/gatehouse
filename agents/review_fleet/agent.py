"""Review fleet (plan §4 phase 1): orchestrator + two «Reviewer»-shaped agents.

Pipeline (SequentialAgent):
  security_reviewer  -> state["security_findings"]
  dpa_legal_reviewer -> state["dpa_findings"]
  review_synthesizer -> final ReviewResult JSON (vendor_id, findings, risk_score)

Both reviewers share one tool, `search_vendor_evidence`, which is the
validity-gated retriever: they can only ground findings in evidence chronofy
still considers valid, and every pruned document arrives as an explicit
re-acquisition notice (the freshness-trap beat).

Evidence plane (plan §3, §5): the orchestrator opens one pollard run per review
(before_agent_callback); every Gemini call is a MODEL_CALL node (the ledger/adk
callback pair, which also serves recorded responses in replay mode so the whole
review reruns offline); every search is the registered `retrieve_evidence@1`
action recorded as a TOOL_CALL node whose id the reviewer cites as
`evidence_node`; and the final verdict is noted under the run
(after_agent_callback). `pollard show evidence/runs.db <root-id>` renders it.

Run:  cp agents/hello/.env agents/review_fleet/.env  &&  adk run agents/review_fleet
Try:  "Review vendor acme-saas-inc."
"""

from __future__ import annotations

import json
import os
import re

from google.adk.agents import Agent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.tool_context import ToolContext
from pollard import PolicyViolation

import ledger
from contracts.reviewer import Finding, ReviewResult  # noqa: F401  (contract this fleet honors)
from ledger import adk as ledger_adk

MODEL = "gemini-3.5-flash"
DEFAULT_VENDOR = "acme-saas-inc"
_VENDOR_RE = re.compile(r"vendor\s+([A-Za-z0-9][A-Za-z0-9._-]*?)[.!?,;:]?(?:\s|$)", re.IGNORECASE)


def _vendor_id(ctx: CallbackContext | ToolContext) -> str:
    """Vendor under review: pinned in state by the orchestrator, else parsed from
    the request ("Review vendor acme-saas-inc."), else the demo default."""
    pinned = ctx.state.get("vendor_id")
    if pinned:
        return pinned
    content = ctx.user_content
    text = " ".join(p.text for p in (content.parts or []) if p.text) if content else ""
    match = _VENDOR_RE.search(text)
    return match.group(1) if match else DEFAULT_VENDOR


def open_ledger(callback_context: CallbackContext) -> None:
    """Orchestrator start: one pollard run per review, as-of time pinned once."""
    vendor_id = _vendor_id(callback_context)
    review = ledger.open_review_run(callback_context.invocation_id, vendor_id)
    callback_context.state["vendor_id"] = vendor_id
    callback_context.state["evidence_run"] = review.root_id
    callback_context.state["query_time"] = review.query_time
    return None


def close_ledger(callback_context: CallbackContext) -> None:
    """Orchestrator end: note the verdict under the run and print the spend."""
    try:
        report = ledger.close_review_run(
            callback_context.invocation_id,
            review_result=callback_context.state.get("review_result"),
        )
    except LookupError:  # sub-agent run standalone; nothing was opened
        return None
    callback_context.state["evidence_report"] = report
    db = os.environ.get("GATEHOUSE_EVIDENCE_DB", ledger.DEFAULT_DB)
    sealed = report["seal"]
    custody = sealed.get("custody")
    attested = (
        f"custody #{custody['sequence']} by {custody['signer']}" if custody else "unpublished"
    )
    print(
        f"[ledger] {report['label']} spent={report['spent']} avoided={report['avoided']}\n"
        f"[ledger] sealed {sealed['digest']} ({sealed['nodes']} nodes; {attested})\n"
        f"[ledger] pollard show {db} {report['root_id']}"
    )
    return None


def search_vendor_evidence(query: str, tool_context: ToolContext) -> dict:
    """Search the vendor evidence corpus. Returns only temporally valid chunks,
    plus explicit notices for any evidence pruned as stale (do NOT rely on
    pruned evidence; surface each notice as a re-acquisition finding). Every
    search is recorded in the evidence ledger: cite the returned evidence_node
    id in each finding it grounds."""
    review = ledger.review_run_for(tool_context.invocation_id, _vendor_id(tool_context))
    try:
        node = review.consult(query, k=ledger.DEFAULT_K)
    except PolicyViolation as refused:
        return {
            "error": f"search refused by the action registry: {refused}",
            "refusal_node": refused.refusal_id,
            "valid_evidence": [],
            "pruned_notices": [],
        }
    return {**node.result, "evidence_node": node.id}


_FINDING_SHAPE = json.dumps(
    {
        "control": "<control or clause id, e.g. CC6.1 or DPA §4.1>",
        "severity": "low | medium | high",
        "rationale": "<one or two sentences grounded in retrieved evidence>",
        "policy_clause": "<the clause/criterion this was scored against>",
        "evidence_node": "<evidence_node id from the search tool result>",
    }
)


def build_fleet(model: str | BaseLlm = MODEL) -> SequentialAgent:
    """The fleet. `model` is injectable so tests drive it with a scripted LLM."""
    security_reviewer = Agent(
        name="security_reviewer",
        model=model,
        before_model_callback=ledger_adk.before_model,
        after_model_callback=ledger_adk.after_model,
        description="Reviews vendor security posture from SOC 2 / pen test evidence.",
        instruction=(
            "You are the security reviewer in a vendor-risk fleet. Use "
            "search_vendor_evidence (2-3 targeted queries: SOC 2 exceptions, pen test "
            "findings, MFA/access control). Ground every finding ONLY in valid_evidence; "
            "cite chunk doc_id + issued date in the rationale. For every pruned_notice, "
            "emit a separate finding with control='EVIDENCE-STALE', severity='medium', "
            "recommending re-acquisition. Output ONLY a JSON list of findings, each "
            f"shaped exactly like: {_FINDING_SHAPE}"
        ),
        tools=[search_vendor_evidence],
        output_key="security_findings",
    )

    dpa_legal_reviewer = Agent(
        name="dpa_legal_reviewer",
        model=model,
        before_model_callback=ledger_adk.before_model,
        after_model_callback=ledger_adk.after_model,
        description="Reviews the vendor DPA: residency, subprocessors, breach terms.",
        instruction=(
            "You are the DPA/legal reviewer in a vendor-risk fleet. Use "
            "search_vendor_evidence (queries on: data residency, subprocessors, breach "
            "notification). policy_clause fact_type evidence is invariant - treat clause "
            "text as authoritative. Flag any gap between DPA commitments and other "
            "evidence. Ground every finding in valid_evidence with doc_id citations. "
            "Output ONLY a JSON list of findings, each shaped exactly like: "
            f"{_FINDING_SHAPE}"
        ),
        tools=[search_vendor_evidence],
        output_key="dpa_findings",
    )

    review_synthesizer = Agent(
        name="review_synthesizer",
        model=model,
        before_model_callback=ledger_adk.before_model,
        after_model_callback=ledger_adk.after_model,
        description="Assembles the fleet's findings into one ReviewResult.",
        instruction=(
            "Assemble the final vendor review. Security findings: {security_findings}. "
            "DPA findings: {dpa_findings}. Deduplicate, then compute risk_score in "
            "[0,1]: start 0.1, +0.15 per medium, +0.3 per high, +0.1 per EVIDENCE-STALE, "
            "cap 1.0. Output ONLY JSON: {\"vendor_id\": \"{vendor_id?}\", "
            "\"evidence_run\": \"{evidence_run?}\", \"findings\": [...], "
            "\"risk_score\": <float>} - findings keep the exact input shape."
        ),
        output_key="review_result",
    )

    return SequentialAgent(
        name="vendor_review_orchestrator",
        description="Gatehouse phase-1 review fleet: security -> DPA -> synthesis.",
        sub_agents=[security_reviewer, dpa_legal_reviewer, review_synthesizer],
        before_agent_callback=open_ledger,
        after_agent_callback=close_ledger,
    )


root_agent = build_fleet()
security_reviewer, dpa_legal_reviewer, review_synthesizer = root_agent.sub_agents
