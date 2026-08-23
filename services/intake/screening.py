"""Pure screening decision — no cloud, no flask; importable anywhere (incl. CI)."""

from __future__ import annotations


def decide(verdict: dict) -> tuple[bool, str]:
    """(allowed, reason). Blocks on any filter match; fails closed if the
    screen itself did not run successfully."""
    if verdict.get("invocation_result") != "SUCCESS":
        return False, "screen-unavailable (fail closed)"
    if verdict.get("filter_match_state") == "MATCH_FOUND":
        matched = [
            name
            for name, r in verdict.get("filter_results", {}).items()
            if r.get("match_state") == "MATCH_FOUND"
        ]
        return False, f"blocked: {', '.join(matched) or 'filter match'}"
    return True, "clean"
