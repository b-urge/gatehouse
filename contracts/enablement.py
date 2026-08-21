"""«Enablement» contract — phase 2, one agent, three registered actions."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from contracts.reviewer import Finding


@runtime_checkable
class Enablement(Protocol):
    """Activated by the vendor-approved event; conditions its outputs on the
    review findings recalled from Memory Bank."""

    name: str

    def on_vendor_approved(self, vendor_id: str, findings: list[Finding]) -> list[str]:
        """Returns receipts for the three registered actions:
        provision-access, generate-training, draft-rollout."""
        ...
