"""The freshness trap, as a test: an 18-month-old clean pen test must be
pruned while the current one survives — the D4 demo beat in miniature."""

from datetime import datetime, timedelta

from chronofy import TemporalFact

from retrieval.validity import gate, verify_freshness

NOW = datetime(2026, 8, 20, 23, 0)


def _facts():
    fresh = TemporalFact(
        content="Pen test 2026-07: one medium finding (MFA gap on legacy tier)",
        timestamp=NOW - timedelta(days=30),
        fact_type="pen_test",
    )
    stale = TemporalFact(
        content="Pen test 2025-02: clean result",
        timestamp=NOW - timedelta(days=548),
        fact_type="pen_test",
    )
    policy = TemporalFact(
        content="Policy §3.1: vendors must remediate mediums within 90 days",
        timestamp=NOW - timedelta(days=3650),
        fact_type="policy_clause",
    )
    return fresh, stale, policy


def test_stale_evidence_is_pruned():
    fresh, stale, policy = _facts()
    valid, pruned = gate([fresh, stale, policy], NOW)
    assert stale in pruned
    assert fresh in valid
    assert policy in valid  # invariant fact type never decays


def test_fresh_trace_passes_stl():
    fresh, _, policy = _facts()
    result = verify_freshness("score risk", [fresh, policy], NOW)
    assert result.satisfied
    assert result.robustness >= 0
