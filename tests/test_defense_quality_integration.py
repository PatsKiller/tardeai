"""Integration-level guards for the data-quality contract as it is actually wired.

tests/test_defense_data_quality.py covers the pure helpers. These cover the properties
that only hold once the helpers are connected to producers, and that would regress
silently: the absence of a legacy fallback, deterministic duplicate handling, the exact
session count, scope labelling of the capped movers feed, and separation of the shadow
lane from live eligibility.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from defense_data_quality import (  # noqa: E402
    CALC_VERSION, Quality, canonical_json_hash, canonical_industry_sector,
    exact_session_breadth, field_ledger, fund_lookthrough_quality,
    industry_window_quality, label_market_internals, quarantine_stale_rows,
    stock_quality_gate, target_gap,
)


def _series(symbol: str, n: int, start: float = 100.0, step: float = 1.0,
            first: dt.date = dt.date(2026, 6, 1)):
    """n consecutive daily closes for one symbol."""
    return [(symbol, first + dt.timedelta(days=i), start + i * step) for i in range(n)]


# --- breadth: exact sessions, duplicates, coverage ---------------------------------

def test_duplicate_dates_collapse_last_observation_wins():
    """Same-day repricer double-writes must not count twice, and the LAST value wins.

    The pre-change SQL averaged every row it found, so a symbol written twice on one day
    was weighted double. Order dependence here is deliberate and must stay deterministic.
    """
    rows = _series("AAA", 20) + [("AAA", dt.date(2026, 6, 20), 999.0)]
    out = exact_session_breadth(rows, sessions=20, min_members=1)

    assert out["duplicate_dates_removed"] == 1
    assert out["membership_n"] == 1
    # 999 is the last write for that date, so it wins and drags the symbol above its mean.
    assert out["breadth_pct"] == 100


def test_uses_exactly_twenty_sessions_not_a_calendar_window():
    """A 40-session series must be judged on its last 20 closes only.

    Built so the two windows disagree: the last 20 sessions fall, the 40-session mean is
    dragged up by the earlier rally. A calendar-window average would call this "above".
    """
    rising = _series("BBB", 20, start=100.0, step=5.0)
    falling = [("BBB", dt.date(2026, 6, 21) + dt.timedelta(days=i), 200.0 - i * 2.0)
               for i in range(20)]
    out = exact_session_breadth(rising + falling, sessions=20, min_members=1)

    assert out["sessions"] == 20
    assert out["breadth_pct"] == 0  # last close sits below the 20-session mean


def test_insufficient_coverage_withholds_and_never_falls_back():
    """Below the floor the answer is an explicit state, not a number from another method."""
    out = exact_session_breadth(_series("CCC", 20), sessions=20, min_members=8)

    assert out["breadth_pct"] is None
    assert out["quality"]["state"] == "insufficient_coverage"
    assert any("eligible_members" in r for r in out["quality"]["reasons"])


def test_symbol_with_too_little_history_is_named_not_silently_dropped():
    rows = _series("AAA", 25) + _series("SHORT", 5, first=dt.date(2026, 7, 1))
    out = exact_session_breadth(rows, sessions=20, min_members=1)

    assert "SHORT" in out["insufficient_symbols"]
    assert out["coverage_n"] == 1
    assert out["membership_n"] == 2


# --- NH/NL scope -------------------------------------------------------------------

def test_capped_movers_feed_is_never_called_comprehensive_breadth():
    out = label_market_internals({"source": "market_movers", "rows": [1] * 15})

    assert out["scope"] == "top_movers_sample"
    assert out["quality"]["state"] == "sample_only"
    assert "not comprehensive breadth" in out["quality"]["reasons"]
    assert "comprehensive" not in out["display_label"].lower()


def test_uncapped_source_keeps_the_comprehensive_label():
    out = label_market_internals({"source": "full_exchange_feed"})

    assert out["scope"] == "comprehensive_universe"
    assert out["quality"]["state"] == "ok"


# --- stale quarantine --------------------------------------------------------------

def test_stale_rows_are_quarantined_but_never_deleted():
    as_of = dt.date(2026, 7, 24)
    rows = [{"sector": "Utilities", "as_of": "2026-07-23"},
            {"sector": "Energy", "as_of": "2026-07-17"}]
    out = quarantine_stale_rows(rows, as_of=as_of, max_age_days=4)

    assert len(out["current"]) == 1 and len(out["quarantined"]) == 1
    # Nothing is dropped: every input row still appears somewhere in the output.
    assert len(out["current"]) + len(out["quarantined"]) == len(rows)
    assert out["quarantined"][0]["sector"] == "Energy"
    assert out["quarantined"][0]["age_days"] == 7
    assert out["quarantined"][0]["quality"]["state"] == "stale"


def test_unparseable_as_of_is_treated_as_stale_not_as_fresh():
    """Fail closed: an unreadable timestamp must not buy eligibility."""
    out = quarantine_stale_rows([{"sector": "X", "as_of": "not-a-date"}],
                                as_of=dt.date(2026, 7, 24))

    assert len(out["quarantined"]) == 1
    assert out["quarantined"][0]["age_days"] is None


# --- provenance --------------------------------------------------------------------

def test_snapshot_hash_is_stable_and_value_sensitive():
    a = field_ledger(source="s", source_as_of="2026-07-23", cadence="daily", value={"x": 1, "y": 2})
    b = field_ledger(source="s", source_as_of="2026-07-23", cadence="daily", value={"y": 2, "x": 1})
    c = field_ledger(source="s", source_as_of="2026-07-23", cadence="daily", value={"x": 2, "y": 2})

    assert a["snapshot_hash"] == b["snapshot_hash"]  # key order must not matter
    assert a["snapshot_hash"] != c["snapshot_hash"]  # a changed value must show
    assert a["calculation_version"] == CALC_VERSION


def test_ledger_defaults_provider_to_source_and_carries_coverage():
    out = field_ledger(source="sector_momentum_state", source_as_of=None, cadence="daily_close",
                       value=[], coverage_n=9, coverage_total=12,
                       quality=Quality("partial_stale", ("stale_sectors=3",)))

    assert out["provider"] == "sector_momentum_state"
    assert (out["coverage_n"], out["coverage_total"]) == (9, 12)
    assert out["quality"]["state"] == "partial_stale"


def test_canonical_hash_is_order_independent_for_nested_structures():
    assert canonical_json_hash({"a": [1, 2], "b": {"c": 3}}) == \
           canonical_json_hash({"b": {"c": 3}, "a": [1, 2]})


# --- industry window quality -------------------------------------------------------

def test_intraday_capture_is_not_labelled_close_confirmed():
    q = industry_window_quality(industry_provider="finviz", benchmark_provider="finviz",
                                industry_as_of="2026-07-24", benchmark_as_of="2026-07-24",
                                capture_kind="intraday")

    assert q.state == "approximate_mixed_windows"
    assert "intraday_refresh_not_close_confirmed" in q.reasons


def test_close_capture_from_one_provider_on_one_date_is_clean():
    q = industry_window_quality(industry_provider="finviz", benchmark_provider="finviz",
                                industry_as_of="2026-07-24", benchmark_as_of="2026-07-24",
                                capture_kind="close")

    assert q.state == "ok" and q.reasons == ()


def test_mixed_provider_and_date_mismatch_are_both_reported():
    q = industry_window_quality(industry_provider="finviz", benchmark_provider="yahoo",
                                industry_as_of="2026-07-24", benchmark_as_of="2026-07-23",
                                capture_kind="close")

    assert set(q.reasons) == {"mixed_provider", "timestamp_mismatch"}


# --- canonical industry mapping ----------------------------------------------------

def test_unknown_industry_stays_unmapped_and_is_not_invented():
    out = canonical_industry_sector("Quantum Widget Fabrication", {})

    assert out["sector"] is None
    assert out["quality"]["state"] == "unmapped"
    assert out["mapping_version"] == "gics-canonical-v1"


def test_known_industry_maps_with_a_version_stamp():
    out = canonical_industry_sector("Oil & Gas Midstream", {"Oil & Gas Midstream": "Energy"})

    assert out["sector"] == "Energy"
    assert out["quality"]["state"] == "ok"
    assert out["mapping_version"]


# --- fund look-through freshness ---------------------------------------------------

def test_missing_factsheet_metadata_is_unknown_not_assumed_fresh():
    out = fund_lookthrough_quality(provider=None, factsheet_date=None,
                                   coverage_pct=None, unmapped_pct=None,
                                   now=dt.date(2026, 7, 24))

    assert out["quality"]["state"] == "review_required"
    assert {"provider_missing", "factsheet_date_missing", "coverage_missing",
            "unmapped_weight_missing"} <= set(out["quality"]["reasons"])
    assert out["factsheet_date"] is None  # no invented date


def test_stale_factsheet_is_flagged_against_the_sla():
    out = fund_lookthrough_quality(provider="issuer", factsheet_date="2026-01-01",
                                   coverage_pct=99.0, unmapped_pct=1.0,
                                   max_age_days=120, now=dt.date(2026, 7, 24))

    assert "factsheet_stale" in out["quality"]["reasons"]


def test_fresh_complete_factsheet_passes():
    out = fund_lookthrough_quality(provider="issuer", factsheet_date="2026-07-01",
                                   coverage_pct=99.0, unmapped_pct=1.0,
                                   max_age_days=120, now=dt.date(2026, 7, 24))

    assert out["quality"]["state"] == "ok"


# --- shadow-only policy fields -----------------------------------------------------

def test_target_gap_is_advisory_only_and_respects_the_tilt_cap():
    out = target_gap(actual_pct=2.0, benchmark_pct=30.0, active_tilt_cap_pct=5.0,
                     mandate="growth")

    assert out["advisory_only"] is True
    assert out["raw_gap_pct"] == 28.0
    assert out["bounded_gap_pct"] == 5.0          # cap binds
    assert abs(out["risk_adjusted_gap_pct"]) <= 5.0


def test_volatility_and_correlation_only_shrink_the_gap():
    base = target_gap(actual_pct=0.0, benchmark_pct=10.0, active_tilt_cap_pct=10.0,
                      mandate="balanced")
    damped = target_gap(actual_pct=0.0, benchmark_pct=10.0, active_tilt_cap_pct=10.0,
                        mandate="balanced", volatility_multiplier=0.5,
                        correlation_penalty=0.5)

    assert damped["risk_adjusted_gap_pct"] < base["risk_adjusted_gap_pct"]
    assert damped["risk_adjusted_gap_pct"] >= 0


# --- shadow stock quality ----------------------------------------------------------

def test_missing_inputs_fail_closed_and_are_named_never_defaulted():
    """No fabricated neutral score: absent evidence must be listed, not imputed."""
    out = stock_quality_gate({"roic": 15})

    assert out["eligible"] is False
    assert "earnings_revision_3m" in out["missing"]
    assert "roic" not in out["missing"]
    assert out["quality"]["state"] == "withheld"
    assert out["failures"] == []  # cannot judge criteria while inputs are missing


def test_complete_and_healthy_inputs_pass():
    features = {"earnings_revision_3m": 2.0, "forward_pe_vs_sector": -5.0, "fcf_margin": 12.0,
                "roic": 18.0, "net_debt_ebitda": 1.0, "interest_coverage": 9.0, "beta": 1.0,
                "book_correlation": 0.4, "short_interest_pct": 2.0, "crowding_percentile": 40,
                "catalyst_days": 30, "dollar_volume_m": 150.0, "extension_sma50_pct": 3.0}
    out = stock_quality_gate(features)

    assert out["missing"] == [] and out["failures"] == []
    assert out["eligible"] is True


@pytest.mark.parametrize("field,bad,flag", [
    ("earnings_revision_3m", -1.0, "negative_revisions"),
    ("roic", 2.0, "low_roic"),
    ("net_debt_ebitda", 9.0, "high_leverage"),
    ("crowding_percentile", 99, "crowded"),
    ("catalyst_days", 2, "near_catalyst"),
    ("extension_sma50_pct", 40.0, "extended"),
])
def test_each_failure_reason_is_reported_individually(field, bad, flag):
    features = {"earnings_revision_3m": 2.0, "forward_pe_vs_sector": -5.0, "fcf_margin": 12.0,
                "roic": 18.0, "net_debt_ebitda": 1.0, "interest_coverage": 9.0, "beta": 1.0,
                "book_correlation": 0.4, "short_interest_pct": 2.0, "crowding_percentile": 40,
                "catalyst_days": 30, "dollar_volume_m": 150.0, "extension_sma50_pct": 3.0}
    features[field] = bad
    out = stock_quality_gate(features)

    assert flag in out["failures"]
    assert out["eligible"] is False


def test_legacy_screen_is_explicitly_not_conviction():
    """The shadow gate must keep saying it does not replace the legacy screen."""
    assert stock_quality_gate({})["legacy_screen_is_not_conviction"] is True


# --- legacy vs shadow separation ---------------------------------------------------

def test_shadow_outputs_carry_no_authority_to_change_live_eligibility():
    """Every shadow-lane output must be self-describing as advisory/withheld.

    This is the guard that stops a later refactor from quietly promoting the shadow
    lane into the live recommendation path.
    """
    gap = target_gap(actual_pct=1.0, benchmark_pct=5.0, active_tilt_cap_pct=3.0,
                     mandate="income")
    gate = stock_quality_gate({})

    assert gap["advisory_only"] is True
    assert gate["eligible"] is False
    assert gate["quality"]["state"] == "withheld"
    assert "eligible" not in gap  # a gap must never express eligibility on its own
