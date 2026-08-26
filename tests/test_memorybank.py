"""Memory bridge offline: findings become recallable facts; run_sync survives a
running event loop; unconfigured bridge is a quiet no-op. No cloud, no ADK."""

import asyncio

import pytest

import memorybank

FINDING = {
    "control": "CC6.1",
    "severity": "medium",
    "rationale": "MFA not enforced on the legacy tier.",
    "policy_clause": "SOC 2 CC6.1",
    "evidence_node": "abc123",
}


class FakeService:
    def __init__(self):
        self.added = []

    async def add_memory(self, *, app_name, user_id, memories):
        self.added.append((app_name, user_id, [m.content.parts[0].text for m in memories]))

    async def search_memory(self, *, app_name, user_id, query):
        class Part:
            text = memorybank.finding_to_fact(user_id, FINDING, "root999")

        class Content:
            parts = [Part()]

        class Memory:
            content = Content()

        class Res:
            memories = [Memory()]

        return Res()


def test_store_and_recall_roundtrip():
    pytest.importorskip("google.adk")  # MemoryEntry lives in ADK
    svc = FakeService()
    n = memorybank.run_sync(
        memorybank.store_findings("acme-saas-inc", [FINDING], "root999", service=svc)
    )
    assert n == 1
    app, user, texts = svc.added[0]
    assert (app, user) == (memorybank.APP_NAME, "acme-saas-inc")
    assert "CC6.1" in texts[0] and "root999" in texts[0] and "abc123" in texts[0]

    got = memorybank.run_sync(
        memorybank.recall_findings("acme-saas-inc", "mfa", service=svc)
    )
    assert got and "MFA" in got[0]


def test_unconfigured_bridge_is_a_noop(monkeypatch):
    monkeypatch.delenv("GATEHOUSE_MEMORY_ENGINE", raising=False)
    assert memorybank.run_sync(memorybank.store_findings("v", [], "r")) == 0
    assert memorybank.run_sync(memorybank.recall_findings("v", "q")) == []


def test_run_sync_inside_a_running_loop():
    async def inner():
        return 41 + 1

    async def outer():
        return memorybank.run_sync(inner())

    assert asyncio.run(outer()) == 42
