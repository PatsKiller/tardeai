"""ANCHOR: MOVE_RETRACES_SCORING_20261107 — LQ-20261107-54. Synthetic prices only."""
from datetime import date, timedelta

from scripts.lib.move_retraces_scoring import score_move_retraces

D0 = date(2026, 1, 5)


def _closes(vals):
    return [(D0 + timedelta(days=i), v) for i, v in enumerate(vals)]


def _c(base, peak):
    return {"commitment_id": "syn", "baseline": base, "observed": peak, "as_of": D0, "due_on": D0 + timedelta(days=5)}


def test_retrace_inside_window_is_true():
    r = score_move_retraces(_c(50.0, 52.0), _closes([52.0, 51.5, 50.9, 51.0]), today=D0 + timedelta(days=9))
    assert r["outcome"] == "TRUE" and r["evidence"]["trigger_level"] == 51.0 and r["evidence"]["retraced_close"] == 50.9


def test_no_retrace_after_due_is_false_and_before_due_pending():
    px = _closes([52.0, 52.5, 53.0, 53.5, 54.0, 54.5])
    assert score_move_retraces(_c(50.0, 52.0), px, today=D0 + timedelta(days=9))["outcome"] == "FALSE"
    assert score_move_retraces(_c(50.0, 52.0), px, today=D0 + timedelta(days=2))["outcome"] == "PENDING"


def test_non_price_baseline_is_unscoreable_not_a_verdict():
    r = score_move_retraces(_c(0.43, 22.6), _closes([72.0, 71.5, 71.0]), today=D0 + timedelta(days=30))
    assert r["outcome"] == "UNSCOREABLE" and r["reason"] == "baseline_not_a_price_level" and r["writes"] == 0


def test_missing_inputs_are_unscoreable():
    assert score_move_retraces(_c(None, 52.0), _closes([50.0]), today=D0)["reason"].startswith("missing")
