"""Resolving due checkpoints without inventing outcomes.

183 checkpoints accumulated and none was ever resolved, so the learning loop had
never once compared a decision against what actually happened.

The dangerous failure here is not missing an outcome — it is recording a wrong
one. A fabricated outcome teaches the system something untrue and leaves no
later signal that it was wrong, so most of these tests are about refusing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib.outcome_resolution import (
    NON_SECURITY_RECOMMENDATIONS,
    due_checkpoints,
    latest_checkpoints,
    price_resolvable,
    realized_state,
    resolution_row,
)

NOW = datetime(2026, 8, 27, 20, 0, tzinfo=timezone.utc)


def _cp(**over):
    base = {
        "checkpoint_id": "cp1",
        "decision_id": "plan_1",
        "status": "SCHEDULED",
        "due_at": (NOW - timedelta(days=1)).isoformat(),
        "horizon": "5_sessions",
        "original_decision_state": {"symbol": "SCHD", "recommendation": "TRIM",
                                    "as_of": "2026-08-20T14:00:00+00:00"},
    }
    base.update(over)
    return base


def _prices(table):
    def lookup(symbol, on_or_before):
        return table.get(symbol)
    return lookup


# ── the trap ───────────────────────────────────────────────────────────────

def test_a_cash_decision_is_not_priced_against_the_ticker_named_cash():
    """The one that would have written 37 wrong outcomes on the first run.

    `HOLD_CASH` with symbol "CASH" means the portfolio's cash sleeve. CASH is
    also a real listed equity (Pathward Financial) and IS in the identity
    registry as CONFIRMED — so neither the symbol string nor the registry can
    tell them apart. Only the recommendation can.
    """
    cp = _cp(original_decision_state={"symbol": "CASH", "recommendation": "HOLD_CASH",
                                      "as_of": "2026-08-20T14:00:00+00:00"})
    ok, reason = price_resolvable(cp, registry_lookup=lambda s: True)

    assert ok is False
    assert reason == "portfolio_cash_decision_hold_cash"


def test_every_cash_recommendation_is_refused_not_just_hold():
    for rec in NON_SECURITY_RECOMMENDATIONS:
        cp = _cp(original_decision_state={"symbol": "CASH", "recommendation": rec,
                                          "as_of": "2026-08-20T14:00:00+00:00"})
        assert price_resolvable(cp, lambda s: True)[0] is False, rec


def test_a_portfolio_entity_type_is_refused_whatever_the_symbol_says():
    cp = _cp(entity_type="PORTFOLIO_CASH")
    ok, reason = price_resolvable(cp, lambda s: True)
    assert ok is False
    assert reason == "entity_type_portfolio_cash"


def test_a_lane_marker_is_refused_on_shape():
    """REENTRY is a lane marker, not an instrument — and not ticker-shaped."""
    cp = _cp(original_decision_state={"symbol": "REENTRY", "recommendation": "WAIT",
                                      "as_of": "2026-08-20T14:00:00+00:00"})
    ok, reason = price_resolvable(cp, registry_lookup=lambda s: s == "SCHD")
    assert ok is False
    assert reason == "no_security_subject"


def test_a_ticker_shaped_symbol_absent_from_the_registry_is_refused():
    """Shape alone is not identity: the registry is the second gate."""
    cp = _cp(original_decision_state={"symbol": "ZZZZ", "recommendation": "TRIM",
                                      "as_of": "2026-08-20T14:00:00+00:00"})
    ok, reason = price_resolvable(cp, registry_lookup=lambda s: s == "SCHD")
    assert ok is False
    assert reason == "subject_not_a_registered_security"


def test_a_real_security_decision_is_resolvable():
    assert price_resolvable(_cp(), lambda s: True) == (True, None)


# ── refusing rather than guessing ──────────────────────────────────────────

def test_missing_price_history_yields_no_outcome():
    """Half a comparison is not an outcome."""
    available, realized, refs = realized_state(_cp(), _prices({}), now=NOW)
    assert available is False
    assert realized == {}
    assert refs == []


def test_a_real_comparison_reports_both_ends_and_its_sources():
    lookup = _prices({"SCHD": (35.03, "2026-08-26")})
    available, realized, refs = realized_state(_cp(), lookup, now=NOW)

    assert available is True
    assert realized["price_at_decision"] == 35.03
    assert realized["change_pct"] == 0.0
    assert refs, "the observation must cite where its numbers came from"


def test_an_unreadable_due_date_is_not_due():
    """Defaulting a bad timestamp to now would resolve the backlog at once."""
    assert due_checkpoints([_cp(due_at="not a date")], now=NOW) == []


def test_a_checkpoint_with_no_due_date_is_unscheduled_not_due():
    assert due_checkpoints([_cp(due_at=None)], now=NOW) == []


def test_a_future_checkpoint_is_not_due():
    future = (NOW + timedelta(days=3)).isoformat()
    assert due_checkpoints([_cp(due_at=future)], now=NOW) == []


# ── append-only, and not re-resolved ───────────────────────────────────────

def test_an_already_resolved_checkpoint_is_not_resolved_again():
    """The resolution appends a row, so raw rows would re-resolve forever."""
    original = _cp()
    resolved = resolution_row(original, "outcome-1", "RESOLVED", now=NOW)

    assert due_checkpoints([original, resolved], now=NOW) == []
    assert latest_checkpoints([original, resolved])["cp1"]["status"] == "RESOLVED"


def test_resolution_preserves_the_original_record():
    original = _cp()
    row = resolution_row(original, "outcome-1", "RESOLVED", now=NOW)

    assert row["checkpoint_id"] == original["checkpoint_id"]
    assert row["decision_id"] == original["decision_id"]
    assert row["original_decision_state"] == original["original_decision_state"]
    assert row["outcome_id"] == "outcome-1"
    assert original["status"] == "SCHEDULED", "the original row must not be mutated"


def test_a_refusal_records_why_and_carries_no_outcome():
    row = resolution_row(_cp(), None, "NOT_PRICE_RESOLVABLE",
                         reason="portfolio_cash_decision_hold_cash", now=NOW)
    assert row["outcome_id"] is None
    assert row["resolution_reason"] == "portfolio_cash_decision_hold_cash"


def test_resolution_stays_observational():
    row = resolution_row(_cp(), "outcome-1", "RESOLVED", now=NOW)
    assert row["observational_only"] is True
    assert row["trading"] is False
    assert row["memory_behavior_influence"] == 0
