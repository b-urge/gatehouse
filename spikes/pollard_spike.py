"""D1 spike: one Gemini call recorded as a content-addressed pollard node.

  python spikes/pollard_spike.py --mock   # offline plumbing check (no GCP)
  python spikes/pollard_spike.py          # live Gemini 3.5 Flash via Vertex AI

Then inspect the ledger:
  pollard runs evidence/runs.db
  pollard show evidence/runs.db <root-id>
"""

from __future__ import annotations

import argparse
import os

from pollard import Budget, Runtime

MODEL = "gemini-3.5-flash"
DB = "evidence/runs.db"


def gemini_fn(payload: dict) -> dict:
    from google import genai

    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
    resp = client.models.generate_content(model=payload["model"], contents=payload["input"])
    usage = getattr(resp, "usage_metadata", None)
    return {
        "text": resp.text,
        "usage": {
            "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
        },
    }


def mock_fn(payload: dict) -> dict:
    return {
        "text": f"[mock] echo: {payload['input']}",
        "usage": {"input_tokens": 12, "output_tokens": 8},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="run offline against a mock model fn")
    args = ap.parse_args()
    fn = mock_fn if args.mock else gemini_fn

    os.makedirs(os.path.dirname(DB), exist_ok=True)
    with Runtime(DB).run("d1-spike", budget=Budget(tokens=20_000)) as run:
        node = run.model_call(
            {"model": MODEL, "input": "Say hello to Gatehouse in one sentence."},
            fn=fn,
        )
        print("root id :", run.root_id)
        print("node id :", node.id)
        print("text    :", node.result["text"])
        print("report  :", run.report())
    print(f"\nInspect: pollard runs {DB} && pollard show {DB} {run.root_id}")


if __name__ == "__main__":
    main()
