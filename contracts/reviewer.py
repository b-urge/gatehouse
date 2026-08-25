"""«Reviewer» contract — the L in the architecture diagram.

Any agent honoring this protocol drops into the fleet unchanged; new reviewers
publish to the Agent Registry and the orchestrator is never modified (O).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Finding:
    control: str
    severity: str  # "low" | "medium" | "high"
    rationale: str
    policy_clause: str  # citation: the clause this was scored against
    evidence_node: str  # pollard node id of the retrieval that grounded it


@dataclass
class ReviewResult:
    vendor_id: str
    findings: list[Finding] = field(default_factory=list)
    risk_score: float = 0.0
    evidence_run: str = "unrecorded"  # pollard root id of the run that produced this review


@runtime_checkable
class Reviewer(Protocol):
    """review(pkg) -> Findings."""

    name: str

    def review(self, package_ref: str) -> ReviewResult: ...
