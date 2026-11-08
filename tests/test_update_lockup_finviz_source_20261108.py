"""LQ-20261107-1101: update-lockup-earnings-dates reads Finviz, never yfinance; silence is an error."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import update_lockup_earnings_dates as U  # noqa: E402

TODAY = date(2026, 11, 8)


@pytest.mark.parametrize("raw,want", [
    ("Nov 12 AMC", date(2026, 11, 12)),
    ("Jan 28 BMO", date(2027, 1, 28)),
    ("Nov 05 AMC", date(2026, 11, 5)),   # a report a few days ago stays this year
    ("11/12/2026 AMC", date(2026, 11, 12)),
    ("2026-11-12", date(2026, 11, 12)),
    ("Nov 12, 2026", date(2026, 11, 12)),
    ("-", None), ("", None), (None, None), ("garbage", None), ("Feb 30", None),
])
def test_parse_finviz_earnings(raw, want):
    assert U.parse_finviz_earnings(raw, TODAY) == want


def _stub(monkeypatch, rows):
    import finviz_enrichment as fe
    monkeypatch.setattr(fe, "_fetch_view", lambda tickers, view, root, **kw: rows)


def test_next_earnings_reads_view_161(monkeypatch):
    _stub(monkeypatch, {"SPCX": {"earnings_date2": "2999-01-02"}})
    assert U._next_earnings("SPCX") == date(2999, 1, 2)


def test_not_announced_is_none_but_no_row_raises(monkeypatch):
    _stub(monkeypatch, {"SPCX": {"earnings_date2": None}})
    assert U._next_earnings("SPCX") is None
    _stub(monkeypatch, {})
    with pytest.raises(RuntimeError, match="no row"):
        U._next_earnings("SPCX")


def test_source_has_no_yfinance():
    assert "yfinance" not in (ROOT / "scripts" / "update_lockup_earnings_dates.py").read_text().replace("never yfinance", "")
