"""Additive L3 off-peak / DST boundary tests (reuses deepseek_offpeak helpers)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.lib.deepseek_offpeak import (
    is_bulk_deepseek_window,
    is_deepseek_peak_utc,
    in_operator_bulk_window_et,
)
from scripts.lib.judgment_schema import OFFPEAK_DEFERRED
from scripts.lib.l3_judgment_pipeline import run_l3_judgment_pipeline
from scripts.lib.model_policy import evaluate_offpeak_eligibility
from tests.helpers.l3_fixtures import (
    DEFERRED_SUMMER_ET,
    OFFICIAL_PEAK_UTC,
    OFFPEAK_SUMMER_ET,
    OFFPEAK_WINTER_ET,
    make_author_call_fn,
    make_critic_call_fn,
    make_grounded_input,
)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def test_summer_edt_bulk_window_boundaries():
    # 15:00 ET August — inside 10–21 ET, not official UTC peak
    assert in_operator_bulk_window_et(OFFPEAK_SUMMER_ET) is True
    assert is_deepseek_peak_utc(OFFPEAK_SUMMER_ET) is False
    assert is_bulk_deepseek_window(OFFPEAK_SUMMER_ET) is True
    assert evaluate_offpeak_eligibility(OFFPEAK_SUMMER_ET).eligible is True

    # 22:00 ET August — outside bulk
    assert in_operator_bulk_window_et(DEFERRED_SUMMER_ET) is False
    assert is_bulk_deepseek_window(DEFERRED_SUMMER_ET) is False
    assert evaluate_offpeak_eligibility(DEFERRED_SUMMER_ET).eligible is False


def test_winter_est_bulk_window_eligible():
    # 15:00 ET January (EST = UTC-5) still inside operator bulk
    assert OFFPEAK_WINTER_ET.utcoffset().total_seconds() == -5 * 3600
    assert in_operator_bulk_window_et(OFFPEAK_WINTER_ET) is True
    assert is_bulk_deepseek_window(OFFPEAK_WINTER_ET) is True
    assert evaluate_offpeak_eligibility(OFFPEAK_WINTER_ET).eligible is True


def test_official_peak_utc_weekday():
    assert OFFICIAL_PEAK_UTC.weekday() < 5
    assert is_deepseek_peak_utc(OFFICIAL_PEAK_UTC) is True
    assert is_bulk_deepseek_window(OFFICIAL_PEAK_UTC) is False
    d = evaluate_offpeak_eligibility(OFFICIAL_PEAK_UTC)
    assert d.eligible is False
    assert d.reason == "official_deepseek_peak_utc"


def test_pipeline_defers_outside_offpeak_zero_calls():
    author_calls: list[int] = []
    critic_calls: list[int] = []
    result = run_l3_judgment_pipeline(
        make_grounded_input(),
        author_call_fn=make_author_call_fn(counter=author_calls),
        critic_call_fn=make_critic_call_fn(counter=critic_calls),
        now=DEFERRED_SUMMER_ET,
    )
    assert result.ok is False
    assert result.output["status"] == "REFUSED"
    assert result.output["refusal_state"] == OFFPEAK_DEFERRED
    assert result.provider_calls == 0
    assert author_calls == []
    assert critic_calls == []


def test_dst_transition_edge_hours():
    # 10:00 ET inclusive, 21:00 ET exclusive — summer
    ten = datetime(2026, 8, 15, 10, 0, tzinfo=ET)
    twenty_one = datetime(2026, 8, 15, 21, 0, tzinfo=ET)
    assert in_operator_bulk_window_et(ten) is True
    assert in_operator_bulk_window_et(twenty_one) is False
    # winter equivalents
    ten_w = datetime(2026, 1, 15, 10, 0, tzinfo=ET)
    twenty_one_w = datetime(2026, 1, 15, 21, 0, tzinfo=ET)
    assert in_operator_bulk_window_et(ten_w) is True
    assert in_operator_bulk_window_et(twenty_one_w) is False
