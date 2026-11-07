"""The weekly report must survive present-but-None metrics.

The period/enrichment JSON carries ``None`` for figures the producer could not
fetch, and ``dict.get("key", 0)`` does NOT substitute for a present-but-None
value. ``_generate_narrative`` formatted those Nones with ``:+.1f`` and raised
``TypeError: unsupported format string passed to NoneType.__format__``, so the
weekly report exited rc=1 (2026-11-02) and the monthly launcher — which runs
the weekly report first — exited rc=1 as well (2026-11-01). Both cadence
pipelines recorded overall_status=degraded.

Synthetic fixtures only: no live store, no broker, no network (the LLM call is
stubbed).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import portfolio_weekly_report as pwr  # noqa: E402


def _null_perf():
    return {
        "total_value": None,
        "cash_pct": None,
        "cash_total": None,
        "periods": {
            "1W": {"change_pct": None, "change": None},
            "1M": {"change_pct": None, "change": None},
            "YTD": {"change_pct": None, "change": None},
            "1Y": {"change_pct": None, "change": None},
        },
        "accounts": {"Acct A": {"value": None, "change_pct": None, "change": None}},
        "top_movers": [{"symbol": "V", "change_pct": None, "value": None}],
    }


def _null_analyst_intel():
    return {"positions": [{
        "symbol": "V", "analyst_rating": None, "recom_score": None,
        "rsi": None, "sma200_pct": None, "inst_trans_pct": None,
        "portfolio_pct": None,
    }]}


def _generate(monkeypatch, *, prev=None):
    monkeypatch.setattr(pwr, "_report_llm", lambda prompt, **kw: "narrative text")
    monkeypatch.setattr(pwr, "_load_previous_weeklies", lambda n=3: prev or [])
    return pwr._generate_narrative(
        _null_perf(),
        {"positions": [{"symbol": "V", "rsi": None, "sma200_pct": None,
                        "market_value": None, "trend": None}]},
        {"pnl": None, "win_rate": None},
        holdings_data={},
        enrichment={},
        risk_data={"portfolio_beta": None, "total_to_rebalance": None},
        analyst_intel=_null_analyst_intel(),
        rebal_rationale=[{"action": "BUY", "symbol": "V", "amount": None,
                          "analyst_rating": None, "reasons": None}],
        brave_commentary={"V": [{"source": None, "snippet": None}]},
    )


def test_generate_narrative_survives_all_null_metrics(monkeypatch):
    narratives = _generate(monkeypatch)
    assert narratives  # every prompt produced a narrative instead of raising
    assert "analyst_intelligence" in narratives


def test_generate_narrative_survives_null_metrics_with_previous_week(monkeypatch):
    prev = [{"date": "2026-10-30", "total_value": None, "1w_change_pct": None,
             "ytd_change_pct": None, "tech_above_200": None,
             "narratives": {"action": ""}}]
    narratives = _generate(monkeypatch, prev=prev)
    assert narratives


def test_fmt_num_keeps_unknown_distinct_from_zero():
    assert pwr._fmt_num(None, "+.1f") == "—"
    assert pwr._fmt_num("n/a", "+.1f") == "—"
    assert pwr._fmt_num(0, "+.1f") == "+0.0"
    assert pwr._fmt_num(1.25, "+.1f") == "+1.2"


def test_momentum_shift_is_unknown_without_a_previous_week():
    assert pwr._momentum_shift({"change_pct": 1.5}, None) == "—"
    assert pwr._momentum_shift({"change_pct": None}, [{"1w_change_pct": 1.0}]) == "—"
    assert pwr._momentum_shift({"change_pct": 2.5}, [{"1w_change_pct": 1.0}]) == "1.5"
