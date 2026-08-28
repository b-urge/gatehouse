"""Record the golden review (plan §5, the killer move) and export it for the repo.

One live run of the real fleet — Gemini + Firestore — under a pinned label and
as-of time, recorded into a fresh ledger, then exported as a sealed,
self-contained subtree:

    evidence/golden/acme-saas-inc.pollard   (sealed export; import verifies it)
    evidence/golden/MANIFEST.json           (label, query_time, seal, spend)

Afterwards `pytest tests/test_golden_replay.py` (or `--pollard-mode=replay`)
replays the whole review offline — exploding model, exploding retriever — and
must land on the same ReviewResult and the same seal digest.

  python spikes/record_golden.py               # LIVE: spends Gemini + Firestore
  python spikes/record_golden.py --scripted    # offline pipeline check, no spend

Live prerequisites: agents/review_fleet/.env (gcloud ADC, Vertex on), the
Firestore corpus seeded. Katie: this is your one command for item D.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

GOLDEN_DIR = REPO / "evidence" / "golden"
EXPORT = GOLDEN_DIR / "acme-saas-inc.pollard"
MANIFEST = GOLDEN_DIR / "MANIFEST.json"
RECORDING_DB = REPO / "evidence" / "golden-recording.db"
LABEL = "review:acme-saas-inc:golden"
PROMPT = "Review vendor acme-saas-inc."


def pin_environment(query_time: str) -> None:
    import os

    os.environ["GATEHOUSE_RUN_LABEL"] = LABEL
    os.environ["GATEHOUSE_QUERY_TIME"] = query_time
    os.environ["GATEHOUSE_EVIDENCE_DB"] = str(RECORDING_DB)
    os.environ.setdefault("GATEHOUSE_LEDGER_MODE", "record")


def drive_fleet(model) -> dict:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from agents.review_fleet.agent import build_fleet

    runner = InMemoryRunner(agent=build_fleet(model=model), app_name="gatehouse-golden")

    async def go():
        session = await runner.session_service.create_session(
            app_name="gatehouse-golden", user_id="golden-recorder"
        )
        async for _ in runner.run_async(
            user_id="golden-recorder",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=PROMPT)]),
        ):
            pass
        session = await runner.session_service.get_session(
            app_name="gatehouse-golden", user_id="golden-recorder", session_id=session.id
        )
        return dict(session.state)

    return asyncio.run(go())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--scripted",
        action="store_true",
        help="use the offline scripted model + fake retriever (pipeline check, no spend)",
    )
    args = ap.parse_args()

    if RECORDING_DB.exists():
        sys.exit(f"refusing to overwrite {RECORDING_DB}; delete it to re-record")
    if args.scripted and MANIFEST.exists():
        recorded = json.loads(MANIFEST.read_text()).get("model")
        if recorded != "scripted":
            sys.exit(
                f"refusing: {MANIFEST} holds a REAL golden (model {recorded!r}); "
                "a --scripted run must not overwrite it"
            )
    query_time = datetime.now().replace(microsecond=0).isoformat()
    pin_environment(query_time)

    from dotenv import load_dotenv

    load_dotenv(REPO / "agents" / "review_fleet" / ".env")
    import os

    # The Vertex/AI-Studio switch changes the tool declarations ADK puts in the
    # request, and the declarations are part of each model call's identity. The
    # manifest records it so the replay runs under the same backend flavor.
    request_environment = {
        "GOOGLE_GENAI_USE_VERTEXAI": os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "")
    }

    import ledger
    from agents.review_fleet.agent import MODEL

    ledger.reset()
    if args.scripted:
        sys.path.insert(0, str(REPO / "tests"))
        from test_fleet_ledger import FAKE_HITS, ScriptedLlm

        from retrieval.search import ValidityGatedRetriever

        ledger.configure(
            store=RECORDING_DB,
            retriever=ValidityGatedRetriever(
                embed_fn=lambda text, task: [0.0] * 8, search_fn=lambda vec, k: FAKE_HITS
            ),
        )
        state, model_name = drive_fleet(ScriptedLlm()), "scripted"
    else:
        state, model_name = drive_fleet(MODEL), MODEL

    report = state["evidence_report"]
    root_id, sealed = report["root_id"], report["seal"]
    print(f"recorded  {report['label']}  root {root_id[:12]}…")
    print(f"spent     {report['spent']}")
    print(f"sealed    {sealed['digest']}")

    from pollard import SQLiteStore, export_subtree

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    exported = export_subtree(SQLiteStore(RECORDING_DB, read_only=True), root_id, EXPORT)
    manifest = {
        "label": report["label"],
        "root_id": root_id,
        "vendor_id": state.get("vendor_id", "acme-saas-inc"),
        "query_time": query_time,
        "prompt": PROMPT,
        "model": model_name,
        "environment": request_environment,
        "seal": {"algorithm": sealed["algorithm"], "digest": sealed["digest"]},
        "nodes": sealed["nodes"],
        "spent": report["spent"],
        "recorded_at": datetime.now().replace(microsecond=0).isoformat(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"exported  {EXPORT.relative_to(REPO)}  ({exported.nodes} nodes)")
    print(f"manifest  {MANIFEST.relative_to(REPO)}")
    print("\nNext: pytest tests/test_golden_replay.py -q   (then commit evidence/golden/*)")


if __name__ == "__main__":
    main()
