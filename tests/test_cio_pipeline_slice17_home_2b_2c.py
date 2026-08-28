"""Slice 17: home + briefs expose 2B+2C keys. Dashboard brief must not claim Telegram sent."""
from __future__ import annotations

from scripts.lib.cio_operator_renderers import command_center_view, morning_text


def _product():
    return {
        "available": True,
        "executive_summary": "[T] Standing posture. [D] Nothing requires action today.",
        "earnings": [{"symbol": "V", "earnings_date": "2026-10-27"}],
        "new_position_if": [{"symbol": "NKE", "thesis_status": "CURRENT"}],
        "cash": {"status": "OK", "cash_pct": 44.8},
        "temperament": {"cash": "hold reserve"},
        "case_summaries": {
            "class": "A",
            "count": 1,
            "items": [{"subject": "research_case:SCHD", "symbols": ["SCHD"]}],
        },
        "action_now": [],
        "standing_decisions": [],
        "decisions": [],
    }


def test_command_center_view_exposes_2b_2c_and_not_telegram_sent():
    v = command_center_view(_product())
    assert v["earnings"]
    assert v["new_position_if"][0]["symbol"] == "NKE"
    assert v["cash"]["cash_pct"] == 44.8
    assert v["case_summaries"]["class"] == "A"
    assert v["telegram_sent"] is False
    assert v["delivery"] == "dashboard"


def test_morning_brief_dashboard_does_not_print_telegram_sent():
    text = morning_text(_product())
    assert "Telegram sent" not in text
    assert "NEW_POSITION_IF" in text
    assert "Earnings" in text
    assert "Research cases" in text
