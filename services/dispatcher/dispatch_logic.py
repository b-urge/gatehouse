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


def strip_fences(text: str) -> str:
    """Model JSON often arrives fenced; return the bare JSON text."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def extract_review_result(event_lines: list[str]) -> dict | None:
    """Scan streamed engine events for the synthesizer's review_result."""
    for line in reversed(event_lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        delta = (event.get("actions") or {}).get("state_delta") or {}
        raw = delta.get("review_result")
        if raw:
            try:
                review = json.loads(strip_fences(raw)) if isinstance(raw, str) else raw
            except ValueError:
                return None
            return review if isinstance(review, dict) else None
    return None


def approval_decision(review: dict, threshold: float) -> tuple[bool, str]:
    """(approved, reason). Fails closed on a missing/invalid risk_score."""
    score = review.get("risk_score")
    if not isinstance(score, (int, float)):
        return False, "no risk_score in review (held for human review)"
    if float(score) <= threshold:
        return True, f"risk_score {score} <= threshold {threshold}"
    return False, f"risk_score {score} > threshold {threshold} (held for human review)"


def approved_event(review: dict, source_event: dict) -> dict:
    findings = review.get("findings") or []
    return {
        "vendor_id": review.get("vendor_id") or source_event.get("vendor_id", "unknown"),
        "risk_score": review.get("risk_score"),
        "evidence_run": review.get("evidence_run", "unknown"),
        "findings_count": len(findings),
        "source_doc_id": source_event.get("doc_id", "unknown"),
    }


def enablement_prompt(event: dict) -> str:
    return (
        f"Vendor {event.get('vendor_id', 'unknown')} approved "
        f"(risk {event.get('risk_score')}, evidence_run {event.get('evidence_run')}). "
        "Run enablement."
    )
