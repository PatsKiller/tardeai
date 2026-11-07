"""LQ-20261107-54: the deterministic MOVE_RETRACES scorer for ``agent_commitments`` (pure, no I/O).

"X gives back 50% of this excursion within N trading days": ``baseline`` is the price before the
excursion, ``observed`` the excursion peak, the trigger is the midpoint, and the claim is TRUE when a
close at or below the trigger lands inside the window. This mirrors how the 1957 settled rows
are evidenced (baseline, observed, trigger_level, retraced_on, days_observed).

The 13 LIVE rows open since 2026-09-14/17 carry a ``baseline`` and ``observed`` that are not price
levels (a baseline of 0.43 on a ~72 instrument, an observed of 22.6). Scoring them against closes
would invent a verdict, so such a row is UNSCOREABLE with a named reason, never TRUE or FALSE.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

SCHEMA = "MoveRetracesScore@v1"
#: baseline must sit within this fraction of the close on the as-of date to be read as a price level.
PRICE_BAND = 0.25


def score_move_retraces(commitment: dict[str, Any], closes: Sequence[tuple[date, float]], *,
                        today: date) -> dict[str, Any]:
    """Return a verdict dict: outcome TRUE | FALSE | PENDING | UNSCOREABLE plus the reason and evidence."""
    base, peak = commitment.get("baseline"), commitment.get("observed")
    as_of, due = commitment["as_of"], commitment["due_on"]
    out = {"schema": SCHEMA, "commitment_id": commitment.get("commitment_id"), "outcome": "UNSCOREABLE",
           "reason": "", "writes": 0}
    series = sorted((d, float(c)) for d, c in closes if c is not None)
    anchor = [c for d, c in series if d <= as_of]
    if base is None or peak is None or not anchor:
        out["reason"] = "missing_baseline_observed_or_price_at_as_of"
        return out
    base, peak = float(base), float(peak)
    ref = anchor[-1]
    if ref <= 0 or abs(base - ref) / ref > PRICE_BAND or abs(peak - ref) / ref > 1.0:
        out["reason"] = "baseline_not_a_price_level"
        out["evidence"] = {"baseline": base, "observed": peak, "close_at_as_of": ref}
        return out
    if peak == base:
        out["reason"] = "no_excursion"
        return out
    trigger = base + (peak - base) * 0.5
    window = [(d, c) for d, c in series if as_of < d <= due]
    hit = next(((d, c) for d, c in window if (c <= trigger if peak > base else c >= trigger)), None)
    out["evidence"] = {"baseline": base, "observed": peak, "trigger_level": trigger, "days_observed": len(window)}
    if hit:
        out.update(outcome="TRUE", reason="retraced_in_window", evidence=dict(out["evidence"], retraced_on=str(hit[0]),
                                                                              retraced_close=hit[1]))
    elif today <= due:
        out.update(outcome="PENDING", reason="window_open")
    else:
        out.update(outcome="FALSE", reason="no_retrace_by_due")
    return out
