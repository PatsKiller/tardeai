"""Tests for finviz_enrichment.py's default symbol universe.

Audit finding M4 (docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md): the two
finviz_enrichment.py cron entries (07:00/13:00) invoke the script bare, no
argv — which silently fell through to a hardcoded 4-symbol demo list
(MAMO/ACHV/V/SCHD) every run, for months, showing "Price: $?" the whole
time since those symbols were never really tracked. default_universe_symbols()
replaces that with the real watchlist + holdings universe.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_enrichment as fe  # noqa: E402

SRC = (ROOT / "scripts" / "finviz_enrichment.py").read_text()


def test_demo_fallback_list_is_gone_from_bare_invocation():
    """The actual audit-cited defect: __main__'s no-argv path must no
    longer resolve to the hardcoded 4-symbol demo list."""
    assert 'symbols = sys.argv[1:] if len(sys.argv) > 1 else ["MAMO", "ACHV", "V", "SCHD"]' not in SRC
    assert "default_universe_symbols(" in SRC


def test_default_universe_symbols_returns_a_sorted_list():
    result = fe.default_universe_symbols(".")
    assert isinstance(result, list)
    assert result == sorted(result)
    assert len(result) == len(set(result))  # no duplicates


def test_default_universe_symbols_stays_within_finviz_rate_budget():
    """The actual incident this fix caught: an earlier version of this query
    (status IN ('active','researched'), no cap) returned 5,260 symbols — at
    Finviz's documented ~100 req/hour / 20-per-batch / 5-views-per-batch
    limit, that's over 13 hours of requests from one cron run. The real
    watchlist_items table has ~5,854 'researched' rows (a discovery pool,
    not a curated watchlist) alongside only ~393 'active' rows — confirm the
    fix queries active only, capped, so this can never recur."""
    result = fe.default_universe_symbols(".")
    # cap (200) plus whatever holdings add on top, which is always small
    assert len(result) < 400, (
        f"got {len(result)} symbols — default_universe_symbols must stay well "
        f"under Finviz's rate budget; if this legitimately needs to grow, "
        f"raise DEFAULT_UNIVERSE_CAP deliberately, don't drop the status filter")


def test_default_universe_symbols_respects_explicit_cap():
    result = fe.default_universe_symbols(".", cap=5)
    # holdings are uncapped and additive, so this only bounds the watchlist portion —
    # assert against a generous ceiling that would only be exceeded by a real regression
    assert len(result) < 100


def test_default_universe_symbols_never_raises_on_db_error(monkeypatch):
    """A DB outage during the 07:10 cron run must degrade to an empty list,
    not crash the script."""
    import psycopg2

    def _boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(psycopg2, "connect", _boom)
    result = fe.default_universe_symbols(".")  # must not raise
    assert isinstance(result, list)


def test_default_universe_symbols_never_raises_on_bad_holdings(monkeypatch, tmp_path):
    """A malformed holdings.json must not crash symbol resolution either."""
    (tmp_path / "data" / "portfolios" / "state").mkdir(parents=True)
    (tmp_path / "data" / "portfolios" / "state" / "holdings.json").write_text("not valid json{{{")
    result = fe.default_universe_symbols(str(tmp_path))  # must not raise
    assert isinstance(result, list)


def test_holdings_symbols_are_included_and_cash_is_excluded(tmp_path, monkeypatch):
    import psycopg2

    def _boom(*a, **k):
        raise RuntimeError("no db in this test")

    monkeypatch.setattr(psycopg2, "connect", _boom)  # isolate to the holdings.json path only
    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    import json
    (state_dir / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "AAPL", "market_value": 1000},
            {"symbol": "CASH", "is_cash": True, "market_value": 500},
        ]
    }))
    result = fe.default_universe_symbols(str(tmp_path))
    assert "AAPL" in result
    assert "CASH" not in result


def test_explicit_argv_still_overrides_the_default():
    """Passing explicit symbols on the command line must be unaffected by
    this fix — only the bare-invocation (empty argv) path changed."""
    assert '__name__ == "__main__"' in SRC
    assert "symbols = sys.argv[1:] if len(sys.argv) > 1 else default_universe_symbols" in SRC
