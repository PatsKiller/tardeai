"""WAVE B1 — earnings renderer: dates that exist must appear on the brief.

Break: collect_earnings_events produced items, but morning_text only printed a
count ("Earnings (D): N upcoming") so the brief read as empty of events. OP
fallback also called collect without holdings, labeling every row scope=watch.

Rails: READ_ONLY_ADVISORY · MBI=0 · no invented commentary · dry-run only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib.cio_investment_product import collect_earnings_events
from scripts.lib.cio_operator_product import build_operator_product
from scripts.lib.cio_operator_renderers import (
    command_center_view,
    earnings_lines,
    morning_text,
)


def _now() -> datetime:
    return datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


def _write_earnings(root: Path, rows: dict) -> None:
    path = root / "data" / "portfolios" / "state" / "earnings_dates.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")


def _write_holdings(root: Path, symbols: list[str]) -> None:
    path = root / "data" / "portfolios" / "state" / "holdings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    holdings = [
        {"symbol": sym, "account": "ira", "market_value": 10_000}
        for sym in symbols
    ]
    holdings.append(
        {"symbol": "CASH", "account": "ira", "market_value": 40_000, "is_cash": True}
    )
    path.write_text(json.dumps({"holdings": holdings}), encoding="utf-8")


def _write_brief(root: Path, brief: dict) -> None:
    path = root / "data" / "cio" / "cio_investment_brief.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brief), encoding="utf-8")


def test_collect_fills_held_scope_when_holdings_passed(tmp_path: Path):
    _write_earnings(
        tmp_path,
        {
            "NOC": {"earnings_date": "2026-10-20", "fetched_at": "2026-08-28T00:00:00"},
            "NKE": {"earnings_date": "2026-09-25", "fetched_at": "2026-08-28T00:00:00"},
            "SCHG": {"earnings_date": None},
        },
    )
    out = collect_earnings_events(
        root=tmp_path,
        holdings={"holdings": [{"symbol": "NOC", "quantity": 5, "asset_type": "EQUITY"}]},
        watch_symbols=["NKE"],
        now=_now(),
    )
    assert out["quality"] == "OK"
    assert out["count"] >= 1
    by_sym = {r["symbol"]: r for r in out["items"]}
    assert by_sym["NOC"]["scope"] == "held"
    assert by_sym["NOC"]["earnings_date"] == "2026-10-20"
    assert isinstance(by_sym["NOC"]["days_to_event"], int)
    # No invented transcript commentary.
    assert by_sym["NOC"]["commentary"] == "UNAVAILABLE"


def test_collect_missing_file_is_data_unavailable(tmp_path: Path):
    out = collect_earnings_events(root=tmp_path, holdings={"holdings": []}, now=_now())
    assert out["items"] == []
    assert out["quality"] == "DATA_UNAVAILABLE"
    assert out["reason"]


def test_earnings_lines_lists_symbol_and_date():
    product = {
        "earnings": [
            {
                "symbol": "NOC",
                "earnings_date": "2026-10-20",
                "days_to_event": 50,
                "scope": "held",
                "class": "D",
            },
            {
                "symbol": "V",
                "earnings_date": "2026-10-27",
                "days_to_event": 57,
                "scope": "held",
                "class": "D",
            },
        ],
        "earnings_quality": {"quality": "OK", "class": "D"},
    }
    lines = earnings_lines(product)
    text = "\n".join(lines)
    assert "Earnings (D): 2 upcoming" in text
    assert "NOC · 2026-10-20 · 50d · held" in text
    assert "V · 2026-10-27 · 57d · held" in text


def test_earnings_lines_data_unavailable_when_empty():
    lines = earnings_lines(
        {
            "earnings": [],
            "earnings_quality": {
                "quality": "DATA_UNAVAILABLE",
                "reason": "earnings_dates.json missing",
                "class": "D",
            },
        }
    )
    text = "\n".join(lines)
    assert "DATA_UNAVAILABLE" in text
    assert "earnings_dates.json missing" in text


def test_morning_text_renders_dates_not_count_only():
    product = {
        "available": True,
        "executive_summary": "Standing posture.",
        "cash": {"status": "PRESENT", "cash_usd": 10},
        "portfolio": {"holdings_n": 2},
        "action_now": [],
        "standing_decisions": [],
        "earnings": [
            {
                "symbol": "BAH",
                "earnings_date": "2026-10-23",
                "days_to_event": 53,
                "scope": "held",
                "class": "D",
            }
        ],
        "earnings_quality": {"quality": "OK", "class": "D"},
    }
    text = morning_text(product)
    assert "Earnings (D): 1 upcoming" in text
    assert "BAH" in text
    assert "2026-10-23" in text
    # Must not invent analysis beyond the dated event row.
    assert "beat" not in text.lower()
    assert "miss" not in text.lower()


def test_command_center_view_carries_earnings_quality():
    view = command_center_view(
        {
            "available": True,
            "earnings": [{"symbol": "V", "earnings_date": "2026-10-27", "class": "D"}],
            "earnings_quality": {"quality": "OK", "class": "D", "source": "earnings_dates.json"},
            "decisions": [],
        }
    )
    assert view["earnings"]
    assert view["earnings_quality"]["quality"] == "OK"
    assert view["earnings_quality"]["class"] == "D"


def test_op_projects_earnings_when_brief_field_empty(tmp_path: Path):
    """Brief earnings=[] but dates file present → OP fills items with held scope."""
    _write_earnings(
        tmp_path,
        {
            "NOC": {"earnings_date": "2026-10-20", "fetched_at": "2026-08-28T00:00:00"},
            "RTX": {"earnings_date": "2026-10-20", "fetched_at": "2026-08-28T00:00:00"},
        },
    )
    _write_holdings(tmp_path, ["NOC", "RTX"])
    _write_brief(
        tmp_path,
        {
            "schema": "CIOInvestmentProduct@v1",
            "as_of": "2026-08-31T00:00:00+00:00",
            "authority": "READ_ONLY_ADVISORY",
            "summary": {"headline": "Standing posture."},
            "recommendations": [],
            "earnings": [],
            "financial_action": False,
            "memory_behavior_influence": 0,
        },
    )
    product = build_operator_product(root=tmp_path, persist=False)
    assert product.get("available") is True
    items = product.get("earnings") or []
    assert len(items) >= 1
    assert all(isinstance(r, dict) and r.get("earnings_date") for r in items)
    assert any(r.get("scope") == "held" for r in items)
    assert (product.get("earnings_quality") or {}).get("quality") == "OK"
    text = morning_text(product)
    assert "upcoming" in text
    # At least one concrete dated event line, not count-only.
    assert any(
        line.startswith("- ") and "·" in line and "2026-" in line
        for line in text.splitlines()
    )
