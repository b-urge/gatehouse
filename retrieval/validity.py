"""Chronofy temporal-validity gate (plan §5): the slice is Layers 2–3 only.

Firestore find_nearest returns candidates -> this module decides what is still
true enough to rely on -> reviewers see valid facts only. STL verdicts are
recorded as pollard nodes on D4 wiring.

Decay rates are claims: each half-life below encodes a TPRM convention and is
justified in the write-up (SOC 2 / pen tests carry ~12-month relevance;
certifications ~24; policy clauses are invariant until superseded).
"""

from __future__ import annotations

import math
from datetime import datetime

from chronofy import (
    EpistemicFilter,
    ExponentialDecay,
    ReasoningStep,
    ReasoningTrace,
    STLVerifier,
    TemporalFact,
)

_LN2 = math.log(2)

DECAY = ExponentialDecay(
    beta={
        "soc2_report": _LN2 / 365.0,
        "pen_test": _LN2 / 365.0,
        "certification": _LN2 / 730.0,
        "policy_clause": 0.0,  # invariant until superseded
    },
    default_beta=_LN2 / 365.0,
    time_unit="days",
)

FILTER_THRESHOLD = 0.5  # below half-validity, evidence is pruned
VERIFY_THRESHOLD = 0.5

_filter = EpistemicFilter(decay_fn=DECAY, threshold=FILTER_THRESHOLD)
_verifier = STLVerifier(decay_fn=DECAY, threshold=VERIFY_THRESHOLD)


def gate(candidates: list[TemporalFact], query_time: datetime):
    """Partition candidates into (valid, stale). Stale evidence never reaches
    the reviewer; a pruned fact becomes a re-acquisition finding upstream."""
    return _filter.partition(candidates, query_time)


def verify_freshness(step_name: str, facts: list[TemporalFact], query_time: datetime):
    """STL check over one reasoning step: robustness >= 0 means every fact used
    is fresh enough; < 0 names the weakest link for re-acquisition."""
    trace = ReasoningTrace(
        steps=[ReasoningStep(step_index=0, content=step_name, facts_used=facts)],
        query_time=query_time,
    )
    return _verifier.verify(trace)
