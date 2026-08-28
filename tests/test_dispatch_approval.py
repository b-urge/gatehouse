"""Approval logic offline: review extraction from streamed events, the
threshold decision (fail-closed), the approved event shape, and the /approved
route invoking enablement. Flask route test skips in CI."""

import json

import pytest

from services.dispatcher.dispatch_logic import (
    approval_decision,
    approved_event,
    enablement_prompt,
    extract_review_result,
    strip_fences,
)

REVIEW = {
    "vendor_id": "acme-saas-inc",
    "evidence_run": "root999",
    "findings": [{"control": "CC6.1"}],
    "risk_score": 0.65,
}


def _event_line(delta: dict) -> str:
    return json.dumps({"actions": {"state_delta": delta}})


def test_extract_review_from_fenced_state_delta():
    lines = [
        _event_line({"security_findings": "[]"}),
        _event_line({"review_result": "```json\n" + json.dumps(REVIEW) + "\n```"}),
        _event_line({"evidence_report": {"root_id": "root999"}}),
        "not-json",
    ]
    assert extract_review_result(lines) == REVIEW
    assert extract_review_result(["not-json", "{}"]) is None


def test_decision_thresholds_and_fail_closed():
    assert approval_decision(REVIEW, 0.7) == (True, "risk_score 0.65 <= threshold 0.7")
    held, reason = approval_decision({**REVIEW, "risk_score": 0.9}, 0.7)
    assert not held and "held" in reason
    held, reason = approval_decision({"vendor_id": "x"}, 0.7)
    assert not held and "no risk_score" in reason


def test_approved_event_and_prompt():
    ev = approved_event(REVIEW, {"vendor_id": "ignored", "doc_id": "d-7"})
    assert ev["vendor_id"] == "acme-saas-inc"
    assert ev["findings_count"] == 1 and ev["source_doc_id"] == "d-7"
    prompt = enablement_prompt(ev)
    assert "acme-saas-inc" in prompt and "root999" in prompt


def test_strip_fences():
    assert strip_fences("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert strip_fences('{"a": 1}') == '{"a": 1}'


def test_push_publishes_approved_and_approved_route_enables(monkeypatch):
    pytest.importorskip("flask")
    import base64

    import services.dispatcher.main as m

    lines = [_event_line({"review_result": json.dumps(REVIEW)})]
    m._invoke_fn = lambda prompt: {"events": len(lines), "final": lines[-1], "lines": lines}
    published = []
    m._publish_approved_fn = lambda event: (published.append(event) or "msg-appr-1")

    client = m.app.test_client()
    envelope = {
        "message": {
            "data": base64.b64encode(
                json.dumps({"vendor_id": "acme-saas-inc", "doc_id": "d-7", "text": "t"}).encode()
            ).decode()
        }
    }
    r = client.post("/push", json=envelope)
    assert r.status_code == 204
    assert published and published[0]["vendor_id"] == "acme-saas-inc"

    enabled = []
    monkeypatch.setattr(m, "ENABLEMENT_ENGINE_ID", "999")
    m._enable_invoke_fn = lambda prompt: (enabled.append(prompt) or {"events": 3, "final": "{}"})
    appr_envelope = {
        "message": {"data": base64.b64encode(json.dumps(published[0]).encode()).decode()}
    }
    r = client.post("/approved", json=appr_envelope)
    assert r.status_code == 204
    assert enabled and "acme-saas-inc" in enabled[0]

    m._invoke_fn = None
    m._enable_invoke_fn = None
    m._publish_approved_fn = None
