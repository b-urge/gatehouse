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
    from .dispatch_logic import (
        approval_decision,
        approved_event,
        decode_push,
        enablement_prompt,
        extract_review_result,
        kickoff_prompt,
    )
except ImportError:  # Cloud Run buildpack context (gunicorn main:app)
    from dispatch_logic import (  # type: ignore[no-redef]
        approval_decision,
        approved_event,
        decode_push,
        enablement_prompt,
        extract_review_result,
        kickoff_prompt,
    )

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "gatehouse-hackathon")
LOCATION = os.environ.get("ENGINE_LOCATION", "us-central1")
ENGINE_ID = os.environ.get("ENGINE_ID", "")
ENABLEMENT_ENGINE_ID = os.environ.get("ENABLEMENT_ENGINE_ID", "")
APPROVED_TOPIC = os.environ.get("APPROVED_TOPIC", "vendor-approved")
APPROVAL_THRESHOLD = float(os.environ.get("APPROVAL_THRESHOLD", "0.7"))

app = Flask(__name__)

_invoke_fn: Callable[[str], dict] | None = None
_enable_invoke_fn: Callable[[str], dict] | None = None
_publish_approved_fn: Callable[[dict], str] | None = None


def _default_invoke_fn(engine_id: str | None = None) -> Callable[[str], dict]:
    """Call an engine via streamQuery, consume to completion, keep all events."""
    import google.auth
    import google.auth.transport.requests
    import requests as http

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])

    def invoke(message: str) -> dict:
        google.auth.transport.requests.Request()
        creds.refresh(google.auth.transport.requests.Request())
        url = (
            f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
            f"/locations/{LOCATION}/reasoningEngines/{engine_id or ENGINE_ID}:streamQuery"
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
        lines: list[str] = []
        for line in resp.iter_lines():
            if line:
                lines.append(line.decode())
        final = lines[-1][:4000] if lines else ""
        return {"events": len(lines), "final": final, "lines": lines[-200:]}

    return invoke


def get_invoke_fn() -> Callable[[str], dict]:
    global _invoke_fn
    if _invoke_fn is None:
        _invoke_fn = _default_invoke_fn()
    return _invoke_fn


def get_enable_invoke_fn() -> Callable[[str], dict]:
    global _enable_invoke_fn
    if _enable_invoke_fn is None:
        _enable_invoke_fn = _default_invoke_fn(ENABLEMENT_ENGINE_ID)
    return _enable_invoke_fn


def _default_publish_approved() -> Callable[[dict], str]:
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT, APPROVED_TOPIC)

    def publish(event: dict) -> str:
        future = publisher.publish(
            topic_path, json.dumps(event).encode(), vendor_id=str(event.get("vendor_id", ""))
        )
        return future.result(timeout=30)

    return publish


def get_publish_approved_fn() -> Callable[[dict], str]:
    global _publish_approved_fn
    if _publish_approved_fn is None:
        _publish_approved_fn = _default_publish_approved()
    return _publish_approved_fn


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

    review = extract_review_result(result.get("lines", []))
    if review is None:
        print("approval: no review_result found in stream (nothing published)")
        return ("", 204)
    approved, reason = approval_decision(review, APPROVAL_THRESHOLD)
    if approved:
        out = approved_event(review, event)
        message_id = get_publish_approved_fn()(out)
        print(f"approval: APPROVED - {reason}; vendor-approved published ({message_id})")
    else:
        print(f"approval: HELD - {reason}")
    return ("", 204)


@app.post("/approved")
def approved():
    body = request.get_json(force=True, silent=True) or {}
    try:
        event = decode_push(body)
    except ValueError as e:
        print(f"drop malformed approved push: {e} :: {json.dumps(body)[:500]}")
        return ("", 204)
    if not ENABLEMENT_ENGINE_ID:
        vendor = event.get("vendor_id")
        print(f"approved event for {vendor} received; no enablement engine configured")
        return ("", 204)
    prompt = enablement_prompt(event)
    print(f"enable: {prompt}")
    result = get_enable_invoke_fn()(prompt)
    print(f"enablement done: events={result['events']} final={result['final'][:300]}")
    return ("", 204)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
