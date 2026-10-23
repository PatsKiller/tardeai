"""Open Trades accuracy (audit 2026-10-22) — scripts/open_trades_intelligence.py.

ANCHOR: OPEN_TRADES_ACCURACY_20261022

The audit measured, on the served page: the mark was the holdings `price` alias (SRNE $0.0005 from
10-16) instead of `canonical_mark`; P/L was the broker's cached gain field, priced at another time
than the mark beside it; the day move showed for marks days old; "last price update" was a lexical
max over mixed naive-ET and UTC strings; SRNE's −$13k write-off sat inside the headline P/L; "large
gain unprotected" fired for a mutual fund and for fractional positions too small to take a stop;
the account column showed raw keys. These tests pin each fix against an in-memory fake store: no
database, no broker, no file under data/.
"""
from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

NOW = datetime.now(timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


class _Cur:
    def __init__(self, quotes):
        self._quotes = quotes
        self._rows: list = []

    def execute(self, sql, params=None):
        self._rows = list(self._quotes) if "FROM market_quotes" in sql else []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return None


class _Conn:
    def __init__(self, quotes):
        self._quotes = quotes

    def cursor(self, cursor_factory=None):
        return _Cur(self._quotes)

    def rollback(self):
        pass

    def close(self):
        pass


def _holding(symbol, account, shares, *, mark, mark_as_of=None, ingested=None, price=None, basis=None,
             mv=None, dcp=None, source="broker_api", **extra):
    row = {"symbol": symbol, "account": account, "shares": shares, "price": price if price is not None else mark,
           "current_price": mark, "canonical_mark": mark, "canonical_mark_as_of": mark_as_of,
           "canonical_mark_ingested_at": ingested, "updated_at": _iso(5), "day_change_pct": dcp,
           "market_value": mv if mv is not None else round(shares * (price if price is not None else mark), 2),
           "cost_basis": basis, "cost_basis_source": source, "gain_loss": 123456.0}
    row.update(extra)
    return row


def _build(monkeypatch, holdings, quotes=(), labels=None):
    oti = importlib.reload(importlib.import_module("open_trades_intelligence"))
    hj = {"holdings": holdings, "last_repriced": "2026-10-22 15:30:02 ET"}
    import json as _json
    import builtins

    real_open = builtins.open

    def fake_open(path, *a, **kw):
        if str(path) == oti.HOLDINGS_JSON:
            import io
            return io.StringIO(_json.dumps(hj))
        if str(path).startswith(str(ROOT / "data")) or str(path).startswith(str(ROOT / "config" / "strategies")):
            raise FileNotFoundError(path)  # no production state is read
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(oti, "_conn", lambda: _Conn(quotes))
    monkeypatch.setattr(oti, "_broker_protective_stops", lambda accts, force=False: {})
    monkeypatch.setattr(oti, "broker_stop_read_ok", lambda: set())
    monkeypatch.setattr(oti, "broker_stops_fetched_at", lambda: None)
    monkeypatch.setattr(oti, "_account_labels", lambda: labels if labels is not None else {
        "schwab_rollover_ira": {"label": "Schwab Rollover IRA", "environment": "live"},
        "schwab_roth_ira": {"label": "Schwab Roth IRA", "environment": "live"},
        "tradeai_automated": {"label": "Alpaca Paper", "environment": "paper"},
    })
    # CI runners have no psycopg2; the connection is faked above, so only the cursor-factory name is needed.
    extras = types.SimpleNamespace(RealDictCursor=object)
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(extras=extras))
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: (_ for _ in ()).throw(RuntimeError("no db"))))
    return oti.build_intelligence(), oti


def _row(out, symbol, account=None):
    return next(p for p in out["positions"] if p["symbol"] == symbol and (account is None or p["account"] == account))


def test_mark_is_canonical_mark_with_its_own_age_not_the_price_alias(monkeypatch):
    out, _ = _build(monkeypatch, [
        _holding("SPCX", "schwab_rollover_ira", 600, mark=145.75, price=148.515, ingested=_iso(0.5), basis=90855.0, dcp=-8.51),
    ])
    p = _row(out, "SPCX")
    assert p["current_price"] == 145.75
    assert p["quote_source"].startswith("holdings.canonical_mark")
    assert p["mark_age_hours"] is not None and p["mark_age_hours"] < 1
    assert p["mark_stale"] is False
    assert p["price_updated_at"] == p["mark_as_of"]


def test_pnl_is_shares_times_mark_minus_basis_not_cached_gain(monkeypatch):
    out, _ = _build(monkeypatch, [
        _holding("SCHD", "schwab_rollover_ira", 6000.2529, mark=35.38, ingested=_iso(0.2), basis=201373.07, dcp=2.09),
    ])
    p = _row(out, "SCHD")
    assert p["market_value"] == 6000.2529 * 35.38
    assert abs(p["unrealized_pnl"] - (6000.2529 * 35.38 - 201373.07)) < 0.01
    assert p["unrealized_pnl"] != 123456.0
    assert abs(out["summary"]["total_unrealized_pnl"] - p["unrealized_pnl"]) < 0.01


def test_day_move_hidden_when_mark_is_stale(monkeypatch):
    out, oti = _build(monkeypatch, [
        _holding("AMANX", "schwab_rollover_ira", 63.366, mark=79.35, mark_as_of="2026-10-16", basis=1229.8, dcp=1.5),
        _holding("V", "schwab_roth", 130.4985, mark=412.43, ingested=_iso(1), basis=40125.75, dcp=1.12),
    ])
    amanx, v = _row(out, "AMANX"), _row(out, "V")
    assert amanx["mark_stale"] is True and amanx["today_move_pct"] is None
    assert amanx["mark_age_hours"] > oti.PRICE_STALE_HOURS
    assert v["mark_stale"] is False and v["today_move_pct"] == 1.12


def test_last_price_update_compares_datetimes_not_strings(monkeypatch):
    # Lexically "…T15:00…+00:00" > "…T07:30…" even when the naive ET value is the later instant.
    out, oti = _build(monkeypatch, [
        _holding("XLB", "schwab_rollover_ira", 10, mark=51.0, mark_as_of="2099-01-01T07:30:00", basis=500.0),
        _holding("XAR", "schwab_rollover_ira", 10, mark=217.0, mark_as_of="2099-01-01T15:00:00+00:00", basis=2000.0),
    ])
    s = out["summary"]
    # 07:30 ET (naive, host-local) = 12:30 UTC, earlier than 15:00 UTC
    assert s["last_price_update"].startswith("2099-01-01T15:00:00")
    assert s["oldest_price_update"].startswith("2099-01-01T12:30:00")
    assert oti._parse_ts("2026-10-22 15:30:02 ET").utcoffset() is not None


def test_write_off_leaves_headline_totals(monkeypatch):
    out, _ = _build(monkeypatch, [
        _holding("SRNE", "schwab_rollover_ira", 1000, mark=0.0007, ingested=_iso(0.5), basis=13177.95, mv=0.5),
        _holding("XLB", "schwab_rollover_ira", 506.3274, mark=51.54, ingested=_iso(0.5), basis=27011.39),
    ])
    s = out["summary"]
    xlb = _row(out, "XLB")
    assert _row(out, "SRNE")["worthless"] is True
    assert s["write_off_count"] == 1 and s["active_positions"] == 1 and s["total_positions"] == 2
    assert abs(s["total_unrealized_pnl"] - xlb["unrealized_pnl"]) < 0.01
    assert s["write_off_unrealized_pnl"] < -13000
    assert [w["symbol"] for w in out["write_offs"]] == ["SRNE"]


def test_large_gain_unprotected_suppressed_for_funds_and_small_positions(monkeypatch):
    import holding_family
    monkeypatch.setattr(holding_family, "is_unstoppable_fund", lambda sym: sym == "AMANX")
    out, oti = _build(monkeypatch, [
        _holding("AMANX", "schwab_rollover_ira", 63.366, mark=79.35, ingested=_iso(0.5), basis=1229.8),
        _holding("V", "schwab_rollover_ira", 0.7963, mark=412.43, ingested=_iso(0.5), basis=277.89),
        _holding("NVDX", "schwab_roth", 100, mark=50.0, ingested=_iso(0.5), basis=2000.0),
    ])
    amanx, small_v, big = _row(out, "AMANX"), _row(out, "V"), _row(out, "NVDX")
    assert "large_gain_unprotected" not in amanx["risk_flags"]
    assert small_v["small_position"] is True and "large_gain_unprotected" not in small_v["risk_flags"]
    assert "large_gain_unprotected" in big["risk_flags"]
    assert small_v["operator_decision"] != "Needs protection review"
    assert big["operator_decision"] == "Needs protection review"
    assert out["summary"]["risk_counts"]["large_gain_unprotected"] == 1
    assert out["summary"]["small_position_count"] == 1


def test_account_labels_come_from_broker_accounts(monkeypatch):
    out, _ = _build(monkeypatch, [
        _holding("V", "schwab_roth", 130.4985, mark=412.43, ingested=_iso(0.5), basis=40125.75),
    ])
    assert _row(out, "V")["account_label"] == "Schwab Roth IRA"
    assert out["summary"]["account_labels"]["schwab_roth"] == "Schwab Roth IRA"


def test_row_without_holdings_mark_uses_one_quote_row(monkeypatch):
    quotes = [{"symbol": "NAVN", "price": 26.29, "prev_close": 26.6, "day_change_pct": -1.25,
               "volume": None, "avg_volume": None, "fetched_at": NOW - timedelta(minutes=10)}]
    h = _holding("NAVN", "schwab_rollover_ira", 500, mark=None, price=0.0, basis=12820.0, mv=13524.95)
    h["current_price"] = None
    out, _ = _build(monkeypatch, [h], quotes=quotes)
    p = _row(out, "NAVN")
    assert p["quote_source"] == "market_quotes"
    assert p["current_price"] == 26.29 and p["today_move_pct"] == -1.25
    assert p["mark_stale"] is False


def test_stop_distance_uses_the_rows_mark():
    import open_trades_intelligence as oti
    assert oti._position_pnl(10, 5.0, 40.0) == (10.0, 25.0)
    assert oti._position_pnl(10, None, 40.0) == (None, None)
    m = oti._mark_fields({"mark": 1.0, "as_of": None, "day_change_pct": 3.0})
    assert m["mark_stale"] is True and m["today_move_pct"] is None
