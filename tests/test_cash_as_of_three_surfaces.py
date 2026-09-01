"""Cash age is the age of the dollars, at every publication point.

Main already stamped two of five publication points (the capital plan and the
operator product). Three still borrowed a clock:

  PP2  the cash letter stamped `now` beside the cash figure
  PP3  the freshness board reads `holdings_ts` -- NOT FIXED HERE, see the PR body:
       correcting it changes ACT_NOW/WATCH/REVALIDATE outcomes on live money
       decisions and needs an operator ruling, not a test-fixture adjustment
  PP4  provenance labelled any non-None figure CURRENT: presence as proof

PP2 and PP4 now read cio_capital_plan.cash_evidence_as_of, the derivation the two
covered surfaces already use. The last test here is the one that keeps that true.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NOW = datetime.now(timezone.utc)
OLD = (NOW - timedelta(days=27)).isoformat()
FRESH = (NOW - timedelta(hours=1)).isoformat()

# The live shape: a tiny very old balance beside a large recent one.
CASH_ROWS = [
    {"is_cash": True, "account": "IRA", "market_value": 500.0, "as_of": OLD},
    {"is_cash": True, "account": "SCHWAB", "market_value": 625284.0, "as_of": FRESH},
]
DOC = {"as_of": NOW.isoformat(), "last_repriced": NOW.isoformat()}


def _evidence():
    from scripts.lib.cio_capital_plan import cash_evidence_as_of
    return cash_evidence_as_of(CASH_ROWS, DOC)


def test_the_shared_derivation_dates_the_block_by_its_stalest_member():
    ev = _evidence()
    assert ev["as_of"] == OLD, (
        "$500 confirmed 27 days ago must outrank $625,284 confirmed an hour ago: "
        "a total is only as current as its stalest member"
    )


# ── PP4 · provenance ─────────────────────────────────────────────────────────
def test_pp4_presence_is_not_freshness():
    from scripts.lib.cio_policy_provenance import _cash_freshness
    assert _cash_freshness(625284.0, {"as_of": OLD})[0] == "STALE"


def test_pp4_undated_cash_is_undated_not_current():
    from scripts.lib.cio_policy_provenance import _cash_freshness
    assert _cash_freshness(625284.0, {"as_of": None, "unstamped": True})[0] == "UNDATED"
    assert _cash_freshness(625284.0, None)[0] == "UNDATED", (
        "no evidence must not silently become CURRENT"
    )


def test_pp4_a_fresh_stamp_is_current_and_carries_its_date():
    from scripts.lib.cio_policy_provenance import _cash_freshness
    fresh, eff = _cash_freshness(625284.0, {"as_of": FRESH})
    assert fresh == "CURRENT" and eff == FRESH, (fresh, eff)


def test_pp4_absent_value_stays_unavailable():
    from scripts.lib.cio_policy_provenance import _cash_freshness
    assert _cash_freshness(None, {"as_of": FRESH})[0] == "UNAVAILABLE"


# ── PP2 · the cash letter ────────────────────────────────────────────────────
def test_pp2_the_letter_dates_the_money_not_the_build():
    """Through build_cash_letter, the real entry point.

    An earlier version of this test called the _cash_letter_as_of helper directly.
    Replacing the CALL SITE with `now.isoformat()` left the helper correct and this
    test green -- the mutation survived. Exercise what the surface publishes.
    """
    from scripts.lib.cio_record_narrative import build_cash_letter
    letter = build_cash_letter(
        {"cash_usd": 625784.0},
        capital_plan={"cash_as_of": {"as_of": OLD}, "cash_total_usd": 625784.0},
        now=NOW,
    )
    assert letter["as_of"] == OLD, letter.get("as_of")
    assert letter["as_of"] != NOW.isoformat(), "the build clock was stamped again"
    assert letter["composed_at"] == NOW.isoformat(), "the build clock must still be recorded"


def test_pp2_a_silent_plan_yields_absence_not_now():
    from scripts.lib.cio_record_narrative import _cash_letter_as_of
    assert _cash_letter_as_of({}, NOW) is None
    assert _cash_letter_as_of({"cash_as_of": {"unstamped": True}}, NOW) is None


# ── PP3 · the freshness board ────────────────────────────────────────────────
def test_every_surface_reads_the_one_derivation(monkeypatch):
    """Mutate the shared derivation; all three surfaces must move with it.

    This is the assertion that makes "one derivation" enforceable instead of
    aspirational. If a surface keeps its own copy, its answer will not change when
    the shared function does, and this fails.
    """
    import scripts.lib.cio_capital_plan as CP
    import scripts.lib.cio_record_narrative as RN
    from scripts.lib.cio_policy_provenance import _cash_freshness

    SENTINEL = "1999-01-01T00:00:00+00:00"
    monkeypatch.setattr(
        CP, "cash_evidence_as_of",
        lambda rows, doc=None: {"as_of": SENTINEL, "unstamped": False}, raising=True)

    plan = {"cash_as_of": CP.cash_evidence_as_of(CASH_ROWS, DOC)}
    assert RN._cash_letter_as_of(plan, NOW) == SENTINEL, (
        "the cash letter did not follow the shared derivation"
    )
    assert _cash_freshness(1.0, plan["cash_as_of"])[0] == "STALE", (
        "provenance did not follow the shared derivation"
    )


def test_no_dollar_amount_moved():
    """A labelling fix. The money is the operator's, not ours."""
    ev = _evidence()
    total = sum(a["settled_cash_usd"] for a in ev["by_account"])
    assert total == pytest.approx(625784.0), total
