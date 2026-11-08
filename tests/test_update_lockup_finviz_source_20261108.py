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
    ("11/2/2026 4:30:00 PM", date(2026, 11, 2)),   # the real export cell (view 161)
    ("10/13/2026 8:30:00 AM", date(2026, 10, 13)),
    ("-", None), ("", None), (None, None), ("garbage", None), ("Feb 30", None),
])
def test_parse_finviz_earnings(raw, want):
    assert U.parse_finviz_earnings(raw, TODAY) == want


def _stub(monkeypatch, rows):
    import finviz_enrichment as fe
    monkeypatch.setattr(fe, "_fetch_view", lambda tickers, view, root, **kw: rows)


def test_next_earnings_reads_view_161(monkeypatch):
    _stub(monkeypatch, {"SPCX": {"earnings_date": "2999-01-02"}})
    assert U._next_earnings("SPCX") == date(2999, 1, 2)


def test_not_announced_is_none_but_no_row_raises(monkeypatch):
    _stub(monkeypatch, {"SPCX": {"earnings_date": None}})
    assert U._next_earnings("SPCX") is None
    _stub(monkeypatch, {})
    with pytest.raises(RuntimeError, match="no row"):
        U._next_earnings("SPCX")


def test_source_has_no_yfinance():
    assert "yfinance" not in (ROOT / "scripts" / "update_lockup_earnings_dates.py").read_text().replace("never yfinance", "")


def test_real_client_path_keeps_the_earnings_cell(monkeypatch):
    """Through the REAL _fetch_view parsing (HTTP faked), the date survives; the default view map drops it."""
    import finviz_enrichment as fe

    class R:
        status_code = 200
        ok = True
        headers = {}
        text = '"No.","Ticker","Earnings Date"\n"1","SPCX","1/2/2999 4:30:00 PM"\n'

    monkeypatch.setattr(fe, "_env", lambda name, default="": "fixture" if name == "FINVIZ_API_TOKEN" else default)
    monkeypatch.setattr(fe, "_load_env", lambda root: None)
    monkeypatch.setattr(fe.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(fe, "REQUEST_DELAY", 0)
    assert U._next_earnings("SPCX") == date(2999, 1, 2)
    assert fe._fetch_view(["SPCX"], 161, ROOT).get("SPCX", {}).get("earnings_date2") is None   # why the narrow map
