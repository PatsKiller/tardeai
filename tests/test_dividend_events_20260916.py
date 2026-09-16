"""C2 (2026-09-16): ex-dividend events surface on the daily morning brief.

Mirrors the earnings collector: the dividend calendar the pipeline already
writes (dividend_calendar.json) is read, its ex_div_alerts become D-class items
with symbol · ex_date · days_to_event · total_income, and the morning brief
renders them. Never invents a date or an amount.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.cio_investment_product import collect_dividend_events
from scripts.lib import cio_operator_renderers as r


def test_ex_div_alerts_collected_with_days_and_income(tmp_path, monkeypatch):
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "dividend_calendar.json").write_text(json.dumps({
        "total_annual": 12345.0,
        "ex_div_alerts": [
            {"symbol": "SCHD", "ex_date": "2026-09-22", "days_until": 6,
             "total_income": 44.20, "urgent": False},
            {"symbol": "V", "ex_date": "2026-09-18", "days_until": 2,
             "total_income": 5.10, "urgent": True},
        ],
    }))
    out = collect_dividend_events(root=tmp_path)
    assert out["quality"] == "OK"
    assert out["source"].endswith("dividend_calendar.json")
    assert len(out["items"]) == 2
    schd = out["items"][0]
    assert schd["symbol"] == "SCHD"
    assert schd["ex_date"] == "2026-09-22"
    assert schd["days_to_event"] == 6
    assert schd["total_income"] == "$44.20"
    assert schd["scope"] == "held"


def test_missing_file_is_data_unavailable(tmp_path, monkeypatch):
    out = collect_dividend_events(root=tmp_path)
    assert out["items"] == []
    assert out["quality"] == "DATA_UNAVAILABLE"


def test_renderer_lists_ex_div_and_honors_unavailable(tmp_path):
    product = {
        "dividends": [
            {"symbol": "SCHD", "ex_date": "2026-09-22", "days_to_event": 6,
             "total_income": "$44.20", "urgent": False},
        ],
        "dividends_quality": {"quality": "OK", "class": "D"},
    }
    lines = r.dividend_lines(product)
    assert any("Dividends (D): 1 ex-div upcoming" in l for l in lines)
    assert any("SCHD · 2026-09-22 · 6d · $44.20" in l for l in lines)

    empty = {"dividends": [], "dividends_quality": {"quality": "DATA_UNAVAILABLE",
                                                     "reason": "no ex-dividend alerts in dividend_calendar.json"}}
    ulines = r.dividend_lines(empty)
    assert any("Dividends (D): DATA_UNAVAILABLE" in l for l in ulines)


def test_morning_text_includes_dividend_section():
    # The renderer wires dividend_lines into morning_text after earnings_lines.
    src = Path(r.__file__).read_text(encoding="utf-8")
    assert "lines.extend(dividend_lines(product))" in src
