"""LQ-20261107-2600 — the headline VIX is judged against the session, not a wall clock the source cannot meet.

ANCHOR: VIX_HEADLINE_SETTLED_LQ2600_20261112

The lead's 17:30 DB-integrity slice read ``header-market-freshness-health`` REGRESSED: "vix last 16:15 ET". The check
was right about the clock and wrong about the rule. Measured 2026-11-12 (read-only):

* ``market_quotes:schwab:$VIX`` holds 15-min prints 03:15..16:15 ET and NOTHING between 16:15 and 03:15 (53
  prints/day) — Cboe stops calculating at the settlement;
* the writer lane ``vix-index-quotes-schwab`` fired every 15 min all evening (105/105 RUN_DONE since 11-11 16:00 ET)
  and its 18:00 receipt reads the 16:15 print and names ``cboe_not_calculating``.

So the 113-minute evening age was correct source behaviour, not a stall. The rule now comes from
``config/market_regime_vix_complex.yaml`` (``printing_window``): inside [start_et, official close + settlement offset)
the configured minute line applies; outside it the last settlement is the newest print any source could carry, and
reaching it is current-for-session while predating it is STALE (a missed settle write). The settlement hour follows
the exchange calendar, so an early close settles at 13:15.

Synthetic values only (public repo). No DB, no network.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import header_market_freshness_health as hmf  # noqa: E402
from lib import vix_headline as vh  # noqa: E402
from lib.market_regime import vix_complex as vc  # noqa: E402

ET = ZoneInfo("America/New_York")
WINDOW = vh.parse_printing_window(vc.load_config()["printing_window"])


def _at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=ET)


def _head(obs: str, now: str, *, window: dict | None = None, minutes=None) -> dict:
    rec = {"vix": {"value": 18.0, "source": "market_quotes:schwab:$VIX", "as_of": obs}}
    return vh.from_record(rec, now=_at(now), stale_after_hours=26.0, printing_window=window or WINDOW,
                          session_fresh_after_minutes=minutes)


# ── after the close: the settlement is current-for-session ──────────────────────────────────────────────────


def test_the_113_minute_evening_age_that_raised_the_alarm_is_fresh():
    """Production 2026-11-12 18:07: the check said DEGRADED, 'last print 16:15 ET 11-12, 113 min ago, past 30 min'."""
    h = _head("2026-11-12T16:15:01-05:00", "2026-11-12T18:08:00")
    assert (h["vix"], h["vix_state"], h["vix_stale"]) == (18.0, "FRESH", False)
    assert h["vix_fresh_rule"] == "settled"
    assert h["vix_expected_print"] == "2026-11-12T16:15:00-05:00"
    assert h["vix_observation_time"] == "2026-11-12T16:15:01-05:00"  # the clock is still shown, just not condemned
    assert h["vix_reason"] is None


def test_a_print_that_predates_the_settlement_is_stale_and_names_the_settlement_missed():
    h = _head("2026-11-12T16:10:00-05:00", "2026-11-12T18:08:00")
    assert (h["vix_state"], h["vix_fresh_rule"]) == ("STALE", "settled")
    assert h["vix_reason"] == ("last print 16:10 ET 11-12 predates the 11-12 16:15 ET settlement; "
                              "no print since"), h["vix_reason"]


def test_the_last_print_before_the_first_print_holds_the_prior_settlement():
    # 02:00 Monday is outside the printing window that starts at 03:15: Friday's settlement is still the newest print.
    h = _head("2026-11-06T16:15:01-05:00", "2026-11-09T02:00:00")
    assert (h["vix_state"], h["vix_expected_print"]) == ("FRESH", "2026-11-06T16:15:00-05:00")
    # A Thursday settlement at 02:00 Monday is not: Friday's was the one that went missing.
    h = _head("2026-11-05T16:15:01-05:00", "2026-11-09T02:00:00")
    assert h["vix_state"] == "STALE" and "11-06 16:15 ET settlement" in h["vix_reason"], h["vix_reason"]


def test_weekend_and_holiday_keep_the_last_settlement():
    for obs, now, expected in (
            ("2026-11-06T16:15:01-05:00", "2026-11-07T12:00:00", "2026-11-06T16:15:00-05:00"),  # Saturday
            ("2026-11-06T16:15:01-05:00", "2026-11-08T18:30:00", "2026-11-06T16:15:00-05:00"),  # Sunday evening
            ("2026-11-25T16:15:01-05:00", "2026-11-26T14:00:00", "2026-11-25T16:15:00-05:00")):  # Thanksgiving
        h = _head(obs, now)
        assert (h["vix_state"], h["vix_fresh_rule"], h["vix_expected_print"]) == ("FRESH", "settled", expected), h
    # Thursday's settlement on Sunday is a MISSED Friday settle, not the weekend's newest print.
    h = _head("2026-11-05T16:15:01-05:00", "2026-11-08T18:30:00")
    assert h["vix_state"] == "STALE" and "11-06 16:15 ET settlement" in h["vix_reason"], h["vix_reason"]


def test_an_early_close_settles_when_the_calendar_says_not_at_four():
    """2026-11-27 (day after Thanksgiving) closes at 13:00 ET, so its settlement is 13:15, not 16:15."""
    h = _head("2026-11-27T13:15:01-05:00", "2026-11-27T15:00:00")
    assert (h["vix"], h["vix_state"], h["vix_expected_print"]) == (18.0, "FRESH", "2026-11-27T13:15:00-05:00")
    # 15:00 is past the early settlement, so the minute line does not apply any more.
    assert h["vix_fresh_rule"] == "settled"
    h = _head("2026-11-27T13:00:00-05:00", "2026-11-27T15:00:00")
    assert (h["vix_state"], h["vix_expected_print"]) == ("STALE", "2026-11-27T13:15:00-05:00")


# ── inside the printing window the operator's minute line still binds ───────────────────────────────────────


def test_inside_the_printing_window_the_minute_line_is_unchanged():
    h = _head("2026-11-12T14:00:00-05:00", "2026-11-12T14:30:00")
    assert (h["vix_state"], h["vix_fresh_rule"], h["vix_stale_after_hours"]) == ("FRESH", "continuous_30m", 0.5)
    h = _head("2026-11-12T14:00:00-05:00", "2026-11-12T14:31:00")
    assert h["vix_state"] == "STALE"
    assert h["vix_expected_print"] is None  # the minute line is an age, not a print to reach
    assert "past the 30 min line" in h["vix_reason"], h["vix_reason"]


def test_the_window_boundaries_are_the_configured_ones():
    # First print: one second before the configured start is still the prior settlement's span.
    h = _head("2026-11-11T16:15:01-05:00", "2026-11-12T03:14:59")
    assert h["vix_fresh_rule"] == "settled"
    h = _head("2026-11-12T03:15:01-05:00", "2026-11-12T03:20:00")
    assert h["vix_fresh_rule"] == "continuous_30m"


# ── the window is config, never an hour in the module ───────────────────────────────────────────────────────


def test_the_settlement_offset_and_the_start_come_from_the_window():
    later = vh.parse_printing_window({"start_et": "03:15", "settlement_after_close_minutes": 45})
    h = _head("2026-11-12T16:45:01-05:00", "2026-11-12T17:00:00", window=later)
    assert (h["vix_state"], h["vix_expected_print"]) == ("FRESH", "2026-11-12T16:45:00-05:00"), h
    h = _head("2026-11-12T16:30:00-05:00", "2026-11-12T17:00:00", window=later)
    assert (h["vix_state"], h["vix_expected_print"]) == ("STALE", "2026-11-12T16:45:00-05:00"), h
    early = vh.parse_printing_window({"start_et": "02:00", "settlement_after_close_minutes": 15})
    assert _head("2026-11-12T02:10:00-05:00", "2026-11-12T02:20:00", window=early)["vix_fresh_rule"] == "continuous_30m"


@pytest.mark.parametrize("window", [
    None, {}, {"start_et": "03:15"}, {"start_et": "3:15 am", "settlement_after_close_minutes": 15},
    {"start_et": "03:15", "settlement_after_close_minutes": 0},
    {"start_et": "03:15", "settlement_after_close_minutes": -5},
    {"start_et": "03:15", "settlement_after_close_minutes": 121},
    {"start_et": "03:15", "settlement_after_close_minutes": True},
    {"start_et": "03:15", "settlement_after_close_minutes": "15"},
])
def test_a_malformed_window_is_refused_never_guessed(window):
    with pytest.raises(ValueError):
        vh.parse_printing_window(window)


def test_a_config_without_a_window_names_the_config_error_and_serves_no_value():
    def q(sql, params=None):
        return [] if "fred_economic_series" in sql else [
            ("$VIX", 20.0, "regular", "2026-11-12", _at("2026-11-12T16:15:01"), None, "schwab")]

    cfg = dict(vc.load_config())
    cfg.pop("printing_window")
    h = vh.vix_headline(db_query=q, now=_at("2026-11-12T18:08:00"), cfg=cfg)
    assert (h["vix"], h["vix_state"]) == (None, "UNAVAILABLE")
    assert h["vix_reason"] == "vix_complex config: ValueError", h["vix_reason"]


def test_the_shipped_config_declares_its_window_and_the_loader_validates_it(tmp_path):
    cfg = vc.load_config()
    assert cfg["printing_window"] == {"start_et": "03:15", "settlement_after_close_minutes": 15}
    doc = (ROOT / "config" / "market_regime_vix_complex.yaml").read_text(encoding="utf-8")
    doc = doc.replace("settlement_after_close_minutes: 15", "settlement_after_close_minutes: 15.5")
    p = tmp_path / "vix_complex.yaml"
    p.write_text(doc, encoding="utf-8")
    assert vc.load_config(p)["printing_window"]["settlement_after_close_minutes"] == 15.5
    p.write_text(doc.replace("start_et: \"03:15\"", "start_et: \"later\""), encoding="utf-8")
    with pytest.raises(vc.ConfigError, match="start_et"):
        vc.load_config(p)


def test_the_module_carries_no_hardcoded_session_hours():
    """The retired span (18:00 ET the evening before -> 20:00 ET) must not survive in the rule as a literal hour."""
    src = (ROOT / "scripts" / "lib" / "vix_headline.py").read_text(encoding="utf-8")
    assert "CONTINUOUS_START_ET" not in src and "CONTINUOUS_END_ET" not in src
    assert "time(18" not in src and "time(20" not in src and "hour=18" not in src and "hour=20" not in src


# ── the health check grades a settled print OK and names the rule it used ───────────────────────────────────


def _surfaces(h: dict) -> tuple[dict, dict]:
    header = {"vix": h["vix"], "vix_source": h["vix_source"], "vix_observation_time": h["vix_observation_time"]}
    card = {"vix": h["vix"], "vix_source": h["vix_source"], "vix_as_of": h["vix_observation_time"]}
    return header, card


def test_the_health_contract_reads_a_settled_print_as_ok():
    h = _head("2026-11-12T16:15:01-05:00", "2026-11-12T18:08:00")
    header, card = _surfaces(h)
    res = hmf.vix_contract(headline=h, header=header, card=card)
    assert res["verdict"] == "OK", res
    assert (res["headline"]["rule"], res["headline"]["expected_print"]) == ("settled", "2026-11-12T16:15:00-05:00")


def test_the_health_contract_degrades_a_missed_settlement_with_its_reason():
    h = _head("2026-11-12T16:10:00-05:00", "2026-11-12T18:08:00")
    header, card = _surfaces(h)
    res = hmf.vix_contract(headline=h, header=header, card=card)
    assert res["verdict"] == "DEGRADED", res
    assert "predates the 11-12 16:15 ET settlement" in res["reason"], res["reason"]
