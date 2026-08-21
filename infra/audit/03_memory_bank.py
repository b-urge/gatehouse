"""GEAP audit: Memory Bank — write one fact, retrieve it back.
Usage: python infra/audit/03_memory_bank.py ENGINE_ID
Platform-regional (us-central1) by design; see GEAP-AUDIT.md findings."""

import asyncio
import os
import sys
import time

from dotenv import load_dotenv
from google.adk.memory import VertexAiMemoryBankService
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types

load_dotenv("agents/hello/.env")
PLATFORM_LOCATION = "us-central1"  # NOT global: reasoningEngines/Memory Bank are regional


async def main(engine_id: str) -> None:
    svc = VertexAiMemoryBankService(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=PLATFORM_LOCATION,
        agent_engine_id=engine_id,
    )
    fact = "Vendor Acme's SOC 2 flagged weak MFA on the legacy tier."
    await svc.add_memory(
        app_name="gatehouse-audit",
        user_id="katie",
        memories=[MemoryEntry(content=types.Content(role="user", parts=[types.Part(text=fact)]))],
    )
    print("write   : ok ->", fact)
    time.sleep(8)  # retrieval indexing lag
    res = await svc.search_memory(
        app_name="gatehouse-audit", user_id="katie", query="What did Acme's SOC 2 flag?"
    )
    print("retrieve:", len(res.memories), "memory(ies)")
    for m in res.memories:
        for part in m.content.parts or []:
            print("  ->", getattr(part, "text", ""))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
