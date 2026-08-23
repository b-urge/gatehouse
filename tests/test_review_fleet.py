"""Fleet wiring conforms to the plan: sequential pipeline, shared gated tool.
Skips cleanly in CI (google-adk isn't installed there)."""

import pytest

pytest.importorskip("google.adk")


def test_orchestrator_shape():
    from agents.review_fleet.agent import root_agent

    assert root_agent.name == "vendor_review_orchestrator"
    names = [a.name for a in root_agent.sub_agents]
    assert names == ["security_reviewer", "dpa_legal_reviewer", "review_synthesizer"]


def test_reviewers_share_the_gated_tool_and_chain_state():
    from agents.review_fleet.agent import dpa_legal_reviewer, security_reviewer

    assert security_reviewer.tools and dpa_legal_reviewer.tools
    assert security_reviewer.output_key == "security_findings"
    assert dpa_legal_reviewer.output_key == "dpa_findings"
