"""Gatehouse intake service (plan §4, Ingress module — the untrusted edge).

POST /intake {vendor_id, doc_id, text}
  -> Model Armor sanitize (template ma-audit, REGIONAL endpoint — D1 finding)
  -> MATCH_FOUND: 403 + verdict (the poisoned-doc beat; nothing enters the system)
  -> clean:       publish `vendor-docs-received` to Pub/Sub -> 202 + message id

Design notes:
- `decide()` is pure: it turns a sanitize verdict into an allow/block decision
  and is unit-tested offline. Cloud clients are built lazily and injected in
  tests, so importing this module never needs credentials (CI installs neither).
- Model Armor filter version: the ma-audit template rides FILTER_VERSION_ALIAS
  STABLE, which is V1 until 2026-09-01 (day after the deadline) — acceptable
  for the hackathon window and recorded in GEAP-AUDIT.md. Pinning happens at
  the template, not per-request.
- Evidence plane: every request is one pollard run (`intake:<vendor>:<doc>`).
  The screening verdict + decision is the `screen_document@1` node, the publish
  is the `publish_intake@1` node; both ids ride the response and the event so
  the review fleet can chain its own run to them. The document text never
  enters the ledger — only a content-committing digest (see evidence.py).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from flask import Flask, jsonify, request
from pollard import Runtime

try:  # package context (tests: services.intake.main)
    from .evidence import (
        build_runtime,
        intake_label,
        record_publish,
        record_screening,
        seal_digest,
    )
except ImportError:  # Cloud Run buildpack context (gunicorn main:app, CWD=services/intake)
    from evidence import build_runtime, intake_label, record_publish, record_screening, seal_digest

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "gatehouse-hackathon")
LOCATION = os.environ.get("MA_LOCATION", "us-central1")
TEMPLATE = os.environ.get("MA_TEMPLATE", "ma-audit")
TOPIC = os.environ.get("INTAKE_TOPIC", "vendor-docs-received")

app = Flask(__name__)

_screen_fn: Callable[[str], dict] | None = None
_publish_fn: Callable[[dict], str] | None = None
_runtime: Runtime | None = None


def _default_screen_fn() -> Callable[[str], dict]:
    """Live Model Armor sanitize on the REGIONAL endpoint (global 403s — D1)."""
    from google.api_core.client_options import ClientOptions
    from google.cloud import modelarmor_v1 as ma

    client = ma.ModelArmorClient(
        client_options=ClientOptions(api_endpoint=f"modelarmor.{LOCATION}.rep.googleapis.com")
    )
    name = f"projects/{PROJECT}/locations/{LOCATION}/templates/{TEMPLATE}"

    def screen(text: str) -> dict:
        resp = client.sanitize_user_prompt(
            request=ma.SanitizeUserPromptRequest(
                name=name, user_prompt_data=ma.DataItem(text=text)
            )
        )
        r = resp.sanitization_result
        return {
            "invocation_result": r.invocation_result.name,
            "filter_match_state": r.filter_match_state.name,
            "filter_results": {
                key: {"match_state": _match_state(val)} for key, val in r.filter_results.items()
            },
        }

    return screen


def _match_state(filter_result: Any) -> str:
    """filter_results values are oneof wrappers; find the inner *_filter_result
    and read its match_state without caring which filter family it is."""
    for field in (
        "pi_and_jailbreak_filter_result",
        "csam_filter_filter_result",
        "rai_filter_result",
        "sdp_filter_result",
        "malicious_uri_filter_result",
    ):
        inner = getattr(filter_result, field, None)
        if inner is not None and getattr(inner, "match_state", None) is not None:
            state = inner.match_state
            name = getattr(state, "name", str(state))
            if name and not name.endswith("_UNSPECIFIED"):
                return name
    return "NO_MATCH_FOUND"


def _default_publish_fn() -> Callable[[dict], str]:
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT, TOPIC)

    def publish(event: dict) -> str:
        future = publisher.publish(
            topic_path,
            json.dumps(event).encode(),
            vendor_id=event["vendor_id"],
            doc_id=event["doc_id"],
        )
        return future.result(timeout=30)

    return publish


def get_screen_fn() -> Callable[[str], dict]:
    global _screen_fn
    if _screen_fn is None:
        _screen_fn = _default_screen_fn()
    return _screen_fn


def get_publish_fn() -> Callable[[dict], str]:
    global _publish_fn
    if _publish_fn is None:
        _publish_fn = _default_publish_fn()
    return _publish_fn


def get_runtime() -> Runtime:
    """The process ledger. Handlers resolve the cloud fns per call, so tests can
    swap `_screen_fn`/`_publish_fn` without rebuilding the runtime."""
    global _runtime
    if _runtime is None:
        _runtime = build_runtime(
            screen=lambda text: get_screen_fn()(text),
            publish=lambda event: get_publish_fn()(event),
        )
    return _runtime


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "template": TEMPLATE, "topic": TOPIC})


@app.post("/intake")
def intake():
    body = request.get_json(force=True, silent=True) or {}
    vendor_id = body.get("vendor_id")
    doc_id = body.get("doc_id")
    text = body.get("text")
    if not (vendor_id and doc_id and text):
        return jsonify({"error": "vendor_id, doc_id, text are required"}), 400

    run = get_runtime().run(intake_label(vendor_id, doc_id))
    screened = record_screening(run, vendor_id=vendor_id, doc_id=doc_id, text=text)
    verdict, decision = screened.result["verdict"], screened.result["decision"]
    ledger_refs = {"screen_node": screened.id, "intake_run": run.root_id}
    if not decision["allowed"]:
        # The poisoned-doc beat: the payload never crosses the gate — but the verdict did
        # enter the ledger, under a digest of the text rather than the text itself.
        return jsonify(
            {"accepted": False, "reason": decision["reason"], "verdict": verdict, "doc_id": doc_id}
            | ledger_refs
            | {"seal": seal_digest(run)}
        ), 403

    published = record_publish(
        run,
        {"vendor_id": vendor_id, "doc_id": doc_id, "text": text, "screen": decision["reason"]}
        | ledger_refs,
    )
    return jsonify(
        {"accepted": True, "doc_id": doc_id, "message_id": published.result["message_id"]}
        | ledger_refs
        | {"seal": seal_digest(run)}
    ), 202


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
