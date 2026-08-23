"""Review fleet (plan §4 phase 1): orchestrator + two «Reviewer»-shaped agents.

Pipeline (SequentialAgent):
  security_reviewer  -> state["security_findings"]
  dpa_legal_reviewer -> state["dpa_findings"]
  review_synthesizer -> final ReviewResult JSON (vendor_id, findings, risk_score)

Both reviewers share one tool, `search_vendor_evidence`, which is the
validity-gated retriever: they can only ground findings in evidence chronofy
still considers valid, and every pruned document arrives as an explicit
re-acquisition notice (the freshness-trap beat). Evidence-node ids come from
the retriever's pollard callback once the orchestrator wires the ledger (D4);
until then they read "unrecorded".

Run:  cp agents/hello/.env agents/review_fleet/.env  &&  adk run agents/review_fleet
Try:  "Review vendor acme-saas-inc."
"""

from __future__ import annotations

import json

from google.adk.agents import Agent, SequentialAgent

from contracts.reviewer import Finding, ReviewResult  # noqa: F401  (contract this fleet honors)
from retrieval.search import ValidityGatedRetriever

_retriever: ValidityGatedRetriever | None = None


def _get_retriever() -> ValidityGatedRetriever:
    global _retriever
    if _retriever is None:
        _retriever = ValidityGatedRetriever()
    return _retriever


def search_vendor_evidence(query: str) -> dict:
    """Search the vendor evidence corpus. Returns only temporally valid chunks,
    plus explicit notices for any evidence pruned as stale (do NOT rely on
    pruned evidence; surface each notice as a re-acquisition finding)."""
    r = _get_retriever().retrieve(query, k=6)
    return {
        "valid_evidence": [
            {
                "chunk_id": h.chunk_id,
                "doc_id": h.doc_id,
                "fact_type": h.fact_type,
                "issued": h.issued,
                "validity": round(h.validity, 3),
                "content": h.content,
            }
            for h in r.valid
        ],
        "pruned_notices": r.reacquisition_notices(),
        "stl_satisfied": r.stl_satisfied,
        "evidence_node": r.evidence_node,
    }


_FINDING_SHAPE = json.dumps(
    {
        "control": "<control or clause id, e.g. CC6.1 or DPA §4.1>",
        "severity": "low | medium | high",
        "rationale": "<one or two sentences grounded in retrieved evidence>",
        "policy_clause": "<the clause/criterion this was scored against>",
        "evidence_node": "<evidence_node id from the search tool result>",
    }
)

security_reviewer = Agent(
    name="security_reviewer",
    model="gemini-3.5-flash",
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
    model="gemini-3.5-flash",
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
    model="gemini-3.5-flash",
    description="Assembles the fleet's findings into one ReviewResult.",
    instruction=(
        "Assemble the final vendor review. Security findings: {security_findings}. "
        "DPA findings: {dpa_findings}. Deduplicate, then compute risk_score in "
        "[0,1]: start 0.1, +0.15 per medium, +0.3 per high, +0.1 per EVIDENCE-STALE, "
        "cap 1.0. Output ONLY JSON: {\"vendor_id\": \"acme-saas-inc\", \"findings\": "
        "[...], \"risk_score\": <float>} - findings keep the exact input shape."
    ),
    output_key="review_result",
)

root_agent = SequentialAgent(
    name="vendor_review_orchestrator",
    description="Gatehouse phase-1 review fleet: security -> DPA -> synthesis.",
    sub_agents=[security_reviewer, dpa_legal_reviewer, review_synthesizer],
)
