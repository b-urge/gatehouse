"""Dispatcher: Pub/Sub push (`vendor-docs-received`) -> Agent Engine fleet run.

The async half of D4: intake publishes, this service receives the push, and
invokes the deployed review fleet via the Agent Engine streamQuery REST surface
(regional endpoint — reasoningEngines are platform services, us-central1).

Env: GOOGLE_CLOUD_PROJECT, ENGINE_ID (numeric reasoningEngine id),
     ENGINE_LOCATION (default us-central1).

Ack semantics: 204 only after the fleet run streams to completion, so Pub/Sub
redelivers on failure. The subscription's ack deadline is set to 600s to cover
the fleet's multi-agent runtime.
"""

from __future__ import annotations

import json
import os
from typing import Callable

from flask import Flask, jsonify, request

try:  # package context (tests)
    from .dispatch_logic import decode_push, kickoff_prompt
except ImportError:  # Cloud Run buildpack context (gunicorn main:app)
    from dispatch_logic import decode_push, kickoff_prompt

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "gatehouse-hackathon")
LOCATION = os.environ.get("ENGINE_LOCATION", "us-central1")
ENGINE_ID = os.environ.get("ENGINE_ID", "")

app = Flask(__name__)

_invoke_fn: Callable[[str], dict] | None = None


def _default_invoke_fn() -> Callable[[str], dict]:
    """Call the fleet on Agent Engine: streamQuery, consume to completion."""
    import google.auth
    import google.auth.transport.requests
    import requests as http

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])

    def invoke(message: str) -> dict:
        google.auth.transport.requests.Request()
        creds.refresh(google.auth.transport.requests.Request())
        url = (
            f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
            f"/locations/{LOCATION}/reasoningEngines/{ENGINE_ID}:streamQuery"
        )
        body = {
            "class_method": "stream_query",
            "input": {"user_id": "dispatcher", "message": message},
        }
        resp = http.post(
            url,
            headers={"Authorization": f"Bearer {creds.token}"},
            json=body,
            timeout=560,
            stream=True,
        )
        resp.raise_for_status()
        last_line = ""
        events = 0
        for line in resp.iter_lines():
            if line:
                events += 1
                last_line = line.decode()[:4000]
        return {"events": events, "final": last_line}

    return invoke


def get_invoke_fn() -> Callable[[str], dict]:
    global _invoke_fn
    if _invoke_fn is None:
        _invoke_fn = _default_invoke_fn()
    return _invoke_fn


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "engine": ENGINE_ID, "location": LOCATION})


@app.post("/push")
def push():
    body = request.get_json(force=True, silent=True) or {}
    try:
        event = decode_push(body)
    except ValueError as e:
        # Malformed messages should not redeliver forever; log and ack.
        print(f"drop malformed push: {e} :: {json.dumps(body)[:500]}")
        return ("", 204)

    prompt = kickoff_prompt(event)
    print(f"dispatch: {prompt}")
    result = get_invoke_fn()(prompt)
    print(f"fleet done: events={result['events']} final={result['final'][:300]}")
    return ("", 204)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
