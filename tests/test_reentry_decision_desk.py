"""Criteria unit checks for Re-Entry Decision Desk (no DB required)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.data_broker.reentry_decision_desk import (
    build_advisory,
    derive_intel_state,
    _age_hours,
    _weekend_fresh_ok,
)


def _fresh() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_ready_rsi_in_band():
    out = derive_intel_state(
        price=100.0, rsi=50.0, as_of=_fresh(),
        entry_low=95.0, entry_high=105.0, held=False,
    )
    assert out["state"] == "READY TO REVIEW"


def test_oversold_not_ready():
    out = derive_intel_state(
        price=100.0, rsi=28.0, as_of=_fresh(),
        entry_low=95.0, entry_high=105.0, held=False,
    )
    assert out["state"] == "OVERSOLD REVIEW"
    mid = derive_intel_state(
        price=100.0, rsi=35.0, as_of=_fresh(),
        entry_low=95.0, entry_high=105.0, held=False,
    )
    assert mid["state"] == "WAIT"


def test_overbought_wait():
    out = derive_intel_state(
        price=100.0, rsi=75.0, as_of=_fresh(),
        entry_low=95.0, entry_high=105.0, held=False,
    )
    assert out["state"] == "OVERBOUGHT WAIT"


def test_near_requires_rsi_under_70():
    out = derive_intel_state(
        price=103.0, rsi=55.0, as_of=_fresh(),
        entry_low=95.0, entry_high=100.0, held=False,
    )
    assert out["state"] == "NEAR ENTRY"

    hot = derive_intel_state(
        price=103.0, rsi=72.0, as_of=_fresh(),
        entry_low=95.0, entry_high=100.0, held=False,
    )
    assert hot["state"] == "OVERBOUGHT WAIT"


def test_wash_hard_block():
    out = derive_intel_state(
        price=100.0, rsi=50.0, as_of=_fresh(),
        entry_low=95.0, entry_high=105.0, held=False, wash_blocked=True,
    )
    assert out["state"] == "WASH BLOCK"


def test_stale_blocks_ready():
    old = (datetime.now(timezone.utc) - timedelta(hours=120)).isoformat()
    out = derive_intel_state(
        price=100.0, rsi=50.0, as_of=old,
        entry_low=95.0, entry_high=105.0, held=False,
    )
    assert out["state"] == "STALE"


def test_criteria_marks_deterministic():
    out = derive_intel_state(
        price=100.0, rsi=50.0, as_of=_fresh(),
        entry_low=95.0, entry_high=105.0, held=False,
    )
    assert out["criteria"]["llm_in_path"] is False
    assert "40" in out["criteria"]["rsi_band"]


def test_advisory_ma_touch_with_null_pct():
    """SMA level can exist while pct overlay is None — must not crash format."""
    adv = build_advisory(
        symbol="CSWC",
        state="WAIT",
        price=20.0,
        entry_low=19.0,
        entry_high=21.0,
        stop=18.0,
        target=24.0,
        rr=2.0,
        rsi=55.0,
        sma_20=20.1,
        sma_50=None,
        sma_200=None,
        sma20_pct=None,
        sma50_pct=None,
        sma200_pct=None,
        macd_signal=None,
        resistance={"state": "UNAVAILABLE", "level": None},
        catalyst=None,
        wash_blocked=False,
        wash_until=None,
        earnings_date=None,
        book_equity=1_000_000.0,
        why=["test"],
    )
    ma = next(c for c in adv["criteria"] if c["id"] == "ma_bounce")
    assert ma["met"] is True
    assert "20-SMA" in ma["detail"]


def test_fund_volume_na_and_above_sma_ready_confirmations():
    adv = build_advisory(
        symbol="FCNTX",
        state="READY TO REVIEW",
        price=25.93,
        entry_low=25.75,
        entry_high=26.60,
        stop=25.0,
        target=28.5,
        rr=2.76,
        rsi=65.8,
        sma_20=25.19,
        sma_50=24.23,
        sma_200=None,
        sma20_pct=2.9,
        sma50_pct=7.0,
        sma200_pct=None,
        macd_signal="NEUTRAL",
        alignment="bullish",
        instrument_type="MUTUALFUND",
        resistance={"state": "BELOW", "level": 26.88},
        catalyst=None,
        wash_blocked=False,
        wash_until=None,
        earnings_date=None,
        book_equity=1_250_000.0,
        why=["in zone"],
        company="Large-Cap Growth Fund",
        lookthrough={
            "fund_name": "Fidelity Contrafund",
            "fund_type": "mutual_fund",
            "fetched_date": "2026-07-05",
            "data_source": "yfinance_FCNTX",
            "sector_weights": {"Technology": 25.8, "Communication Services": 22.21},
            "top_holdings": [{"ticker": "META", "name": "Meta Platforms", "pct": 11.29}],
        },
    )
    vol = next(c for c in adv["criteria"] if c["id"] == "volume")
    ma = next(c for c in adv["criteria"] if c["id"] == "ma_bounce")
    assert vol["met"] is True and "N/A" in vol["detail"]
    assert ma["met"] is True
    assert adv["confirmations_complete"] is True
    assert adv["is_fund"] is True
    assert adv["lookthrough"]["available"] is True
    assert adv["lookthrough"]["top_holdings"][0]["ticker"] == "META"
    assert adv["lookthrough"]["sectors"][0]["name"] == "Technology"


def test_advisory_sizing_1pct_rule():
    adv = build_advisory(
        symbol="MSFT",
        state="READY TO REVIEW",
        price=420.0,
        entry_low=420.0,
        entry_high=423.0,
        stop=410.0,
        target=465.0,
        rr=3.5,
        rsi=42.0,
        sma_20=415.0,
        sma_50=410.0,
        sma_200=400.0,
        sma20_pct=1.2,
        sma50_pct=2.4,
        sma200_pct=5.0,
        macd_signal="BULLISH",
        resistance={"state": "ABOVE", "level": 418.0},
        catalyst=None,
        wash_blocked=False,
        wash_until=None,
        earnings_date=None,
        book_equity=100_000.0,
        why=["Price inside zone"],
    )
    assert adv["action"].startswith("Tactical Re-Entry")
    assert adv["sizing"]["max_dollar_risk"] == 1000.0
    # 1% risk → 86 sh, but 10% alloc cap on $100k → 23 sh
    assert adv["sizing"]["shares"] == 23
    assert "Capped" in adv["sizing"]["note"]
    assert any(c["id"] == "rsi_reset" and c["met"] for c in adv["criteria"])


def test_age_hours_parses_et_broker_timestamp():
    # Same form market_quote_provider emits — must not return None (was "Quote age unknown")
    fresh_et = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S ET")
    age = _age_hours(fresh_et)
    assert age is not None
    assert age < 2.0
    assert _weekend_fresh_ok(age) is True
    assert _age_hours("2026-08-01 07:35:12 ET") is not None
