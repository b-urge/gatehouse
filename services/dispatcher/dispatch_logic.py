"""Pure dispatch logic — no cloud, no flask; importable anywhere (incl. CI)."""

from __future__ import annotations

import base64
import json


def decode_push(body: dict) -> dict:
    """Pub/Sub push envelope -> the intake event dict. Raises ValueError on
    anything malformed (push retries are cheap; silent drops are not)."""
    try:
        data = body["message"]["data"]
        event = json.loads(base64.b64decode(data).decode())
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"malformed push envelope: {e}") from e
    if not event.get("vendor_id"):
        raise ValueError("event missing vendor_id")
    return event


def kickoff_prompt(event: dict) -> str:
    return (
        f"Review vendor {event['vendor_id']}. "
        f"Trigger: document {event.get('doc_id', 'unknown')} passed intake screening."
    )
