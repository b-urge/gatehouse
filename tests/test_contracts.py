"""SOLID inspectability: the contracts on the diagram exist and are honored."""

from contracts.enablement import Enablement
from contracts.reviewer import Finding, Reviewer, ReviewResult


class DummyReviewer:
    name = "dummy-reviewer"

    def review(self, package_ref: str) -> ReviewResult:
        f = Finding(
            control="AC-2",
            severity="low",
            rationale="stub",
            policy_clause="§3.1",
            evidence_node="deadbeef",
        )
        return ReviewResult(vendor_id="acme", findings=[f], risk_score=0.1)


class DummyEnablement:
    name = "dummy-enablement"

    def on_vendor_approved(self, vendor_id, findings):
        return ["provision:ok", "training:ok", "rollout:ok"]


def test_reviewer_contract():
    r = DummyReviewer()
    assert isinstance(r, Reviewer)
    out = r.review("pkg://acme")
    assert out.findings[0].policy_clause == "§3.1"


def test_enablement_contract():
    e = DummyEnablement()
    assert isinstance(e, Enablement)
    assert len(e.on_vendor_approved("acme", [])) == 3
