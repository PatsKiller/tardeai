"""Reports redesign v001 (operator-approved 2026-11-06) — read-path changes in scripts/reports_portal.py.

  1. _resolve_docx never links a different date's .docx (no same-month / name / newest fallback,
     except a monthly report inside its own month); no exact match → no Word link.
  2. market_reports category: own ai_reports types, plus a selloff / market-move row stored as 'weekly'
     (read-path mapping, no migration); weekly_reviews excludes those rows.
  3. get_item('ar', …) returns the category and the exact-date docx.

No DB: _scan_docx_files and _conn are monkeypatched. PUBLIC repo: made-up file names and titles only.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reports_portal as rp  # noqa: E402


def _f(name: str, date: str | None, kind: str) -> dict:
    return {"filename": name, "url": f"/files/{name}", "size_kb": 10.0, "modified": 0, "date": date, "kind": kind}


FILES = [
    _f("weekly_2026-01-02.docx", "2026-01-02", "weekly"),
    _f("weekly_2026-01-09.docx", "2026-01-09", "weekly"),
    _f("monthly_2026-01-31.docx", "2026-01-31", "monthly"),
    _f("portfolio_brief_2026-01-05.docx", "2026-01-05", "portfolio"),
    _f("trade_ai_brief_2026-01-06.docx", "2026-01-06", "trade_ai"),
    _f("misc_undated.docx", None, "other"),
]


def _patch(monkeypatch, files=FILES):
    monkeypatch.setattr(rp, "_scan_docx_files", lambda: list(files))


def test_docx_exact_date_match(monkeypatch):
    _patch(monkeypatch)
    hit = rp._resolve_docx({"category": "weekly_reviews", "type": "strategy_weekly", "created_at": "2026-01-09T18:00:00"})
    assert hit and hit["filename"] == "weekly_2026-01-09.docx"


def test_docx_no_other_date_fallback_for_weekly(monkeypatch):
    _patch(monkeypatch)
    # 01-07 has no weekly file: the old resolver returned the same-month 01-09/01-02 file or the newest one.
    assert rp._resolve_docx({"category": "weekly_reviews", "type": "weekly", "created_at": "2026-01-07T18:00:00"}) is None


def test_docx_no_fallback_for_briefs(monkeypatch):
    _patch(monkeypatch)
    assert rp._resolve_docx({"category": "portfolio_briefs", "type": "portfolio_brief", "created_at": "2026-01-06"}) is None
    assert rp._resolve_docx({"category": "morning_briefs", "type": "aegis_morning_brief", "created_at": "2026-01-07"}) is None
    hit = rp._resolve_docx({"category": "morning_briefs", "type": "trade_ai_brief", "created_at": "2026-01-06"})
    assert hit and hit["filename"] == "trade_ai_brief_2026-01-06.docx"


def test_docx_no_cross_kind_same_day(monkeypatch):
    _patch(monkeypatch)
    # an alert on 01-09 must not pick up the weekly report's Word file from the same day
    assert rp._resolve_docx({"category": "alerts", "type": "urgent_alert", "created_at": "2026-01-09"}) is None


def test_docx_monthly_may_match_its_own_month_only(monkeypatch):
    _patch(monkeypatch)
    hit = rp._resolve_docx({"category": "monthly", "type": "monthly", "created_at": "2026-01-15"})
    assert hit and hit["filename"] == "monthly_2026-01-31.docx"
    assert rp._resolve_docx({"category": "monthly", "type": "monthly", "created_at": "2026-02-01"}) is None


def test_docx_no_date_no_link(monkeypatch):
    _patch(monkeypatch)
    assert rp._resolve_docx({"category": "weekly_reviews", "type": "weekly", "created_at": None}) is None


def test_docx_market_report_never_takes_the_weekly_file(monkeypatch):
    _patch(monkeypatch)
    it = {"category": "market_reports", "type": "weekly", "title": "Zeta Selloff Deep Dive", "created_at": "2026-01-09"}
    assert rp._resolve_docx(it) is None
    it2 = {"category": "", "type": "weekly", "title": "Zeta Selloff Deep Dive", "created_at": "2026-01-09"}
    assert rp._resolve_docx(it2) is None


def test_market_reports_category_first_and_ar_mapping():
    assert rp.CATEGORIES[0]["key"] == "market_reports"
    assert rp.ar_category("weekly", "Selloff Deep Dive + Monday Plan — Fri 01-09") == "market_reports"
    assert rp.ar_category("weekly", "Market move report — Tue") == "market_reports"
    assert rp.ar_category("market_move", "anything") == "market_reports"
    assert rp.ar_category("weekly", "Weekly portfolio review") == "weekly_reviews"
    assert rp.ar_category("monthly", "January") == "monthly"
    assert rp.ar_category("unknown_type", "x") is None


def test_ar_where_clauses():
    w, params = rp._ar_where(rp._BY_KEY["market_reports"])
    assert "report_type = ANY(%s)" in w and "~*" in w and w.count("%s") == len(params) == 3
    assert params[0] == ["market_move", "market_selloff"] and params[1] == ["weekly"]
    w2, p2 = rp._ar_where(rp._BY_KEY["weekly_reviews"])
    assert "NOT" in w2 and w2.count("%s") == len(p2) == 2
    w3, p3 = rp._ar_where(rp._BY_KEY["monthly"])
    assert w3 == "report_type = ANY(%s)" and len(p3) == 1


class _Cur:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.c = _Cur(row)

    def cursor(self):
        return self.c


def test_get_item_ar_carries_category_and_exact_docx(monkeypatch):
    _patch(monkeypatch)
    row = (75, datetime(2026, 1, 9, 18, 0), "weekly", "Zeta Selloff Deep Dive + Monday Plan", "# T\n## Bottom line\n- x", "local")
    monkeypatch.setattr(rp, "_conn", lambda: _Conn(row))
    it = rp.get_item("ar", 75)
    assert it["category"] == "market_reports"
    assert "docx_file" not in it   # the same-day weekly .docx belongs to a different report

    row2 = (76, datetime(2026, 1, 9, 18, 0), "weekly", "Weekly portfolio review", "body", "local")
    monkeypatch.setattr(rp, "_conn", lambda: _Conn(row2))
    it2 = rp.get_item("ar", 76)
    assert it2["category"] == "weekly_reviews"
    assert it2["docx_file"]["filename"] == "weekly_2026-01-09.docx"

    row3 = (77, datetime(2026, 1, 8, 18, 0), "weekly", "Weekly portfolio review", "body", "local")
    monkeypatch.setattr(rp, "_conn", lambda: _Conn(row3))
    assert "docx_file" not in rp.get_item("ar", 77)
