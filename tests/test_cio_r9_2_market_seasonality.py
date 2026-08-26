from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.lib.cio_market_context_state import build_market_context_state
from scripts.lib.cio_seasonality_state import build_seasonality_state, compute_symbol_seasonality


NOW = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)


def _regime(**overrides):
    base = {
        "generated_at": "2026-08-21T20:05:02+00:00",
        "regime_label": "risk_on_trend",
        "regime_score": 2,
        "confidence": 0.33,
        "volatility_state": "neutral",
        "trend_state": "bearish",
        "breadth_state": "broad",
        "liquidity_state": "unknown",
        "leadership_state": "unknown",
        "risk_appetite_state": "bearish",
        "stale_data": False,
        "missing_data": [],
    }
    return {**base, **overrides}


def _fred(series_id: str, value: float, observed: str):
    return {
        "series_id": series_id,
        "value": value,
        "observation_date": observed,
        "fetched_at": "2026-08-23T10:15:02+00:00",
    }


def test_market_context_is_structured_partial_and_never_llm_truth():
    state = build_market_context_state(
        regime_snapshot=_regime(),
        fred_rows=[
            _fred("DFF", 3.63, "2026-08-20"),
            _fred("T10Y2Y", 0.5, "2026-08-21"),
            _fred("VIXCLS", 16.01, "2026-08-20"),
            _fred("CPIAUCSL", 332.813, "2026-07-01"),
            _fred("UNRATE", 4.1, "2026-07-01"),
        ],
        evaluated_at=NOW,
    )
    assert state["schema"] == "MarketContextState@v1"
    assert state["truth_quality"] == "PARTIAL"
    assert state["fields"]["fed_funds_rate_pct"]["value"] == 3.63
    assert state["fields"]["liquidity"]["state"] == "UNAVAILABLE"
    assert state["fields"]["credit_spread_pct"]["state"] == "UNAVAILABLE"
    assert state["llm_generated_state"] is False


def test_required_stale_macro_field_makes_context_stale():
    state = build_market_context_state(
        regime_snapshot=_regime(),
        fred_rows=[
            _fred("DFF", 3.63, "2026-07-01"),
            _fred("T10Y2Y", 0.5, "2026-08-21"),
            _fred("VIXCLS", 16.01, "2026-08-20"),
        ],
        evaluated_at=NOW,
    )
    assert state["truth_quality"] == "STALE"
    assert "fed_funds_rate_pct" in state["stale_fields"]


def _monthly_bars(years: int = 10):
    bars = []
    close = 100.0
    for year in range(2017, 2017 + years):
        for month in range(1, 13):
            close *= 1.01 if month != 9 else 0.97
            bars.append({
                "bar_time": f"{year}-{month:02d}-28T00:00:00+00:00",
                "close": close,
                "source": "verified_fixture",
            })
    return bars


def test_seasonality_computes_month_quarter_statistics_and_drawdown():
    result = compute_symbol_seasonality("SPY", _monthly_bars())
    assert result["truth_quality"] == "VERIFIED"
    assert result["monthly"]["9"]["sample_count"] == 10
    assert result["monthly"]["9"]["mean_return_pct"] < 0
    assert result["monthly"]["1"]["win_rate_pct"] == 100
    assert result["quarterly"]["Q1"]["sample_count"] >= 9
    assert result["max_drawdown_pct"] < 0


def test_seasonality_is_thin_or_unavailable_when_history_does_not_support_claims():
    thin = compute_symbol_seasonality("XLI", _monthly_bars(years=4))
    assert thin["truth_quality"] == "THIN"
    empty = build_seasonality_state({"XLI": []}, benchmark="SPY", evaluated_at=NOW)
    assert empty["truth_quality"] == "UNAVAILABLE"
    assert empty["seasonality_is_authority"] is False
    assert empty["llm_generated_statistics"] is False


def test_duplicate_daily_bars_do_not_inflate_samples():
    bars = _monthly_bars()
    bars.append({**bars[-1], "source": "duplicate_source"})
    result = compute_symbol_seasonality("SPY", bars)
    assert result["daily_bar_count"] == 120


def test_market_context_and_seasonality_sources_have_no_financial_mutation_imports():
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "scripts/lib/cio_market_context_state.py",
        "scripts/lib/cio_seasonality_state.py",
        "scripts/materialize_cio_seasonality_history.py",
    ):
        source = (root / rel).read_text(encoding="utf-8").lower()
        for forbidden in ("place_order", "cancel_order", "modify_stop", "broker_client", "2fa"):
            assert forbidden not in source


def test_unavailable_calendars_do_not_change_version_with_wall_clock():
    first = build_market_context_state(
        regime_snapshot=_regime(),
        fred_rows=[
            _fred("DFF", 3.63, "2026-08-20"),
            _fred("T10Y2Y", 0.5, "2026-08-21"),
            _fred("VIXCLS", 16.01, "2026-08-20"),
        ],
        evaluated_at=NOW,
    )
    second = build_market_context_state(
        regime_snapshot=_regime(),
        fred_rows=[
            _fred("DFF", 3.63, "2026-08-20"),
            _fred("T10Y2Y", 0.5, "2026-08-21"),
            _fred("VIXCLS", 16.01, "2026-08-20"),
        ],
        evaluated_at=NOW.replace(minute=NOW.minute + 1),
    )
    assert first["version"] == second["version"]
    assert first["fields"]["macro_calendar"]["as_of"] is None
    assert first["fields"]["portfolio_earnings_calendar"]["as_of"] is None
