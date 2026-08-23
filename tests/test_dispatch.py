"""Dispatcher logic offline: envelope decoding, kickoff prompt, and the push
route acking only after the fleet call. Flask route test skips in CI."""

import base64
import json

import pytest

from services.dispatcher.dispatch_logic import decode_push, kickoff_prompt


def _envelope(event: dict) -> dict:
    return {"message": {"data": base64.b64encode(json.dumps(event).encode()).decode()}}


def test_decode_roundtrip_and_prompt():
    event = {"vendor_id": "acme-saas-inc", "doc_id": "d1", "text": "..."}
    decoded = decode_push(_envelope(event))
    assert decoded["vendor_id"] == "acme-saas-inc"
    assert "Review vendor acme-saas-inc" in kickoff_prompt(decoded)
    assert "d1" in kickoff_prompt(decoded)


def test_malformed_envelope_raises():
    with pytest.raises(ValueError):
        decode_push({"message": {"data": "not-base64!!"}})
    with pytest.raises(ValueError):
        decode_push({"nope": True})
    with pytest.raises(ValueError):
        decode_push(_envelope({"doc_id": "x"}))  # no vendor_id


def test_push_route_invokes_fleet_then_acks():
    pytest.importorskip("flask")  # CI lacks flask; runs locally
    import services.dispatcher.main as m

    calls = []
    m._invoke_fn = lambda prompt: (calls.append(prompt) or {"events": 7, "final": "{}"})
    client = m.app.test_client()

    r = client.post("/push", json=_envelope({"vendor_id": "v-1", "doc_id": "d-9", "text": "t"}))
    assert r.status_code == 204
    assert calls and "Review vendor v-1" in calls[0]

    r = client.post("/push", json={"garbage": True})
    assert r.status_code == 204  # malformed: ack (don't redeliver forever), logged
    assert len(calls) == 1

    m._invoke_fn = None
