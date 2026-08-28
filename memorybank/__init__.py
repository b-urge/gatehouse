"""Memory bridge (plan §4 phase 2): review findings -> Memory Bank -> enablement.

Session 1 (the review): after synthesis the fleet persists each finding as one
memory fact scoped to the vendor (`user_id = vendor_id`), so recall is
per-vendor by construction. Session 2 (enablement, days later, different
process): `recall_findings` semantically retrieves them — the exact
cross-session mechanism proven in the D1 audit, now carrying real findings.

Environment:
  GATEHOUSE_MEMORY_ENGINE   reasoningEngine id hosting the Memory Bank
                            (unset => persistence/recall quietly disabled)
  GATEHOUSE_PROJECT         project id override (Agent Engine's ambient
                            GOOGLE_CLOUD_PROJECT is the NUMBER — D4 finding)

The ADK memory service is async-only; `run_sync` runs a coroutine on a fresh
loop in a worker thread so sync pollard handlers can call it even while ADK's
own event loop is running.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from typing import Any

APP_NAME = "gatehouse-reviews"
PLATFORM_LOCATION = "us-central1"  # Memory Bank is platform-regional (D1 finding)


def project_id() -> str:
    """Prefer our explicit var; refuse numeric (project-number) ids — D4 finding."""
    p = os.environ.get("GATEHOUSE_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    return p if p and not p.isdigit() else "gatehouse-hackathon"


def memory_engine_id() -> str | None:
    return os.environ.get("GATEHOUSE_MEMORY_ENGINE") or None


def run_sync(coro: Any, timeout: float = 60.0) -> Any:
    """Run a coroutine to completion from sync code, safe under a running loop."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=timeout)


def _service(engine_id: str):
    from google.adk.memory import VertexAiMemoryBankService

    return VertexAiMemoryBankService(
        project=project_id(), location=PLATFORM_LOCATION, agent_engine_id=engine_id
    )


def finding_to_fact(vendor_id: str, finding: dict[str, Any], evidence_run: str) -> str:
    """One finding -> one durable, recallable sentence carrying its provenance."""
    return (
        f"Vendor {vendor_id} review finding [{finding.get('control', '?')}|"
        f"{finding.get('severity', '?')}]: {finding.get('rationale', '')} "
        f"(policy: {finding.get('policy_clause', '?')}; "
        f"evidence_node {finding.get('evidence_node', '?')}; evidence_run {evidence_run})"
    )


async def store_findings(
    vendor_id: str,
    findings: list[dict[str, Any]],
    evidence_run: str,
    *,
    service: Any | None = None,
) -> int:
    """Persist findings as memory facts. Returns the count written (0 if the
    bridge is unconfigured). Never raises into the review path."""
    engine = memory_engine_id()
    if service is None:
        if engine is None:
            return 0
        service = _service(engine)
    from google.adk.memory.memory_entry import MemoryEntry
    from google.genai import types

    entries = [
        MemoryEntry(
            content=types.Content(
                role="user",
                parts=[types.Part(text=finding_to_fact(vendor_id, f, evidence_run))],
            )
        )
        for f in findings
    ]
    if not entries:
        return 0
    await service.add_memory(app_name=APP_NAME, user_id=vendor_id, memories=entries)
    return len(entries)


async def recall_findings(
    vendor_id: str, query: str, *, top_k: int = 5, service: Any | None = None
) -> list[str]:
    """Semantic recall of this vendor's stored findings (texts, best-first)."""
    engine = memory_engine_id()
    if service is None:
        if engine is None:
            return []
        service = _service(engine)
    res = await service.search_memory(app_name=APP_NAME, user_id=vendor_id, query=query)
    texts: list[str] = []
    for m in res.memories[:top_k]:
        for part in m.content.parts or []:
            text = getattr(part, "text", "") or ""
            if text:
                texts.append(text)
    return texts
