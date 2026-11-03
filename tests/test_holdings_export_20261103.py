"""holdings_export — generated backup writer: regenerates from the DB, never reads the store, keeps the last good file."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("holdings_export_under_test", ROOT / "scripts/holdings_export.py")
he = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = he
_spec.loader.exec_module(he)

COLUMNS = ["account_key", "symbol", "broker", "qty", "cost_basis_total", "avg_cost",
           "broker_market_value", "is_cash", "asset_type", "source", "as_of"]
NOW = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)  # 11:00 ET, market open


def rows(*extra):
    base = [
        ("acct_a", "CASH", "schwab", 1000.0, None, None, 1000.0, True, "cash", "schwab_position_sync", NOW - timedelta(minutes=5)),
        ("acct_a", "NVDA", "schwab", 10.0, 500.0, 50.0, 1200.0, False, "equity", "schwab_position_sync", NOW - timedelta(minutes=5)),
    ]
    return base + list(extra)


QUOTES = [
    # symbol, price, bar_end, inserted_at, session, reference_close, reference_basis, change_pct, feed
    ("NVDA", 120.5, NOW - timedelta(minutes=1), NOW - timedelta(minutes=1), "regular", 118.0, "prior_session_close", 2.12, "sip"),
]
PROFILES = [
    # symbol, sector, industry, source, updated_at
    ("NVDA", "Technology", "Semiconductors", "yfinance", NOW - timedelta(days=1)),
]
LOOKTHROUGH = [
    # etf, holding, name, weight, as_of, source
    ("SMH", "NVDA", "NVIDIA", 12.4, NOW - timedelta(days=1), "yfinance"),
]


class Cursor:
    def __init__(self, conn):
        self._conn = conn
        self.description = []
        self._result = []
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        if self._conn.fail:
            raise RuntimeError("connection refused")
        low = " ".join(sql.split()).lower()
        if "to_regclass" in low:
            self.description = [("to_regclass",)]
            self._result = [(("etf_holdings_snapshot" if self._conn.lookthrough else None),)]
        elif "sum(broker_market_value)" in low:
            self.description = [("sum",)]
            self._result = [(sum(float(r[6] or 0) for r in self._conn.positions if len(r) > 6),)]
        elif "from positions_current" in low:
            self.description = [(c,) for c in COLUMNS]
            self._result = list(self._conn.positions)
        elif "from market_quotes_extended" in low:
            self.description = [("symbol",), ("price",), ("bar_end",), ("inserted_at",), ("session",),
                                ("reference_close",), ("reference_basis",), ("change_pct",), ("feed",)]
            self._result = list(self._conn.quotes)
        elif "from symbol_profiles" in low:
            self.description = [("symbol",), ("sector",), ("industry",), ("source",), ("updated_at",)]
            self._result = list(self._conn.profiles)
        elif "from etf_holdings_snapshot" in low:
            self.description = [("etf",), ("holding",), ("name",), ("weight",), ("as_of",), ("source",)]
            self._result = list(self._conn.lookthrough_rows)
        else:
            self.description = [("x",)]
            self._result = []

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class Conn:
    def __init__(self, data=None, *, fail=False, quotes=None, profiles=None,
                 lookthrough=False, lookthrough_rows=None):
        self.positions = data if data is not None else rows()
        self.fail = fail
        self.quotes = quotes if quotes is not None else QUOTES
        self.profiles = profiles if profiles is not None else PROFILES
        self.lookthrough = lookthrough
        self.lookthrough_rows = lookthrough_rows or LOOKTHROUGH

    def cursor(self):
        return Cursor(self)


def _dicts(data=None):
    return [dict(zip(COLUMNS, r)) for r in (data if data is not None else rows())]


def test_render_totals_from_rows_only():
    doc = he.render_document(_dicts(), generated_at=NOW)
    assert doc["schema"] == "HoldingsExport@v1" and doc["source"] == "positions_current"
    totals = doc["portfolio_totals"]
    assert totals["total_cash"] == 1000.0 and totals["total_value"] == 2200.0 and totals["positions"] == 2
    assert doc["holdings"][0]["account"] == "acct_a" and doc["holdings"][0]["shares"] == 1000.0


def test_a_zero_byte_store_is_regenerated_without_being_read(tmp_path, monkeypatch):
    store = tmp_path / "holdings.json"
    store.write_bytes(b"")
    real_open, real_read_text = Path.open, Path.read_text

    def guarded_open(self, *a, **k):
        if self == store:
            raise AssertionError("the export must never read the existing store")
        return real_open(self, *a, **k)

    def guarded_read_text(self, *a, **k):
        if self == store:
            raise AssertionError("the export must never read the existing store")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    receipt = he.export(conn=Conn(), store=store, backups=tmp_path / "backups", now=NOW)
    monkeypatch.undo()
    with open(store, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert receipt["ok"] and len(doc["holdings"]) == 2 and doc["portfolio_totals"]["positions"] == 2


def test_a_corrupt_store_is_regenerated(tmp_path):
    store = tmp_path / "holdings.json"
    store.write_text("{not valid json", encoding="utf-8")
    he.export(conn=Conn(), store=store, backups=tmp_path / "backups", now=NOW)
    assert json.loads(store.read_text())["schema"] == "HoldingsExport@v1"


def test_db_unreachable_refuses_and_leaves_the_last_good_file(tmp_path):
    store = tmp_path / "holdings.json"
    he.export(conn=Conn(), store=store, backups=tmp_path / "backups", now=NOW)
    good = store.read_bytes()
    with pytest.raises(he.ExportError):
        he.export(conn=Conn(fail=True), store=store, backups=tmp_path / "backups", now=NOW + timedelta(minutes=15))
    assert store.read_bytes() == good


def test_no_rows_refuses_and_leaves_the_last_good_file(tmp_path):
    store = tmp_path / "holdings.json"
    he.export(conn=Conn(), store=store, backups=tmp_path / "backups", now=NOW)
    good = store.read_bytes()
    with pytest.raises(he.ExportError):
        he.export(conn=Conn([]), store=store, backups=tmp_path / "backups", now=NOW)
    assert store.read_bytes() == good


def test_the_write_is_atomic_mode_600_and_leaves_no_temp(tmp_path):
    store = tmp_path / "holdings.json"
    he.export(conn=Conn(), store=store, backups=tmp_path / "backups", now=NOW)
    assert oct(store.stat().st_mode & 0o777) == oct(0o600)
    assert list(tmp_path.glob(".*.tmp")) == []


def test_retention_keeps_48_hourly_and_30_daily(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    for i in range(60):
        (backups / f"holdings-hourly-202610{(i % 28) + 1:02d}T{i % 24:02d}.json").write_text("{}")
    for i in range(40):
        (backups / f"holdings-daily-{20260101 + i:08d}.json").write_text("{}")
    he.write_backups("{}\n", backups, now=NOW)
    assert len(list(backups.glob("holdings-hourly-*.json"))) == 48
    assert len(list(backups.glob("holdings-daily-*.json"))) == 30


def test_size_cap_prunes_oldest_and_keeps_the_new_one(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    for i in range(10):
        (backups / f"holdings-hourly-2026100{i}T00.json").write_bytes(b"x" * 1000)
    newest = he.write_backups("{}\n", backups, now=NOW, size_cap_bytes=5000)
    total = sum(p.stat().st_size for p in backups.glob("*.json"))
    assert total <= 5000
    assert Path(newest["hourly"]).exists()


def test_alert_fires_only_when_stale_during_market_hours(tmp_path):
    store = tmp_path / "holdings.json"
    he.export(conn=Conn(), store=store, backups=tmp_path / "b", now=NOW)
    old = (NOW - timedelta(minutes=31)).timestamp()
    os.utime(store, (old, old))

    calls = []
    out = he.maybe_alert_stale(store=store, now=NOW, send=lambda text, priority="P1": calls.append(priority) or {"delivered": True})
    assert out["sent"] is True and calls == ["P1"]

    calls.clear()
    fresh = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(store, (fresh, fresh))
    assert he.maybe_alert_stale(store=store, now=NOW, send=lambda *a, **k: calls.append(1))["sent"] is False
    assert calls == []

    os.utime(store, (old, old))
    saturday = datetime(2026, 11, 7, 16, 0, tzinfo=timezone.utc)  # Saturday
    assert he.maybe_alert_stale(store=store, now=saturday, send=lambda *a, **k: calls.append(1))["sent"] is False
    assert calls == []


def test_metadata_and_quote_fields_are_rendered_with_provenance(tmp_path):
    store = tmp_path / "holdings.json"
    he.export(conn=Conn(lookthrough=False), store=store, backups=tmp_path / "b", now=NOW)
    doc = json.loads(store.read_text())
    nvda = next(h for h in doc["holdings"] if h["symbol"] == "NVDA")
    assert nvda["sector"] == "Technology" and nvda["industry"] == "Semiconductors"
    assert nvda["profile_source"] == "yfinance" and nvda["profile_updated_at"]
    assert nvda["price"] == 120.5 and nvda["prior_close"] == 118.0 and nvda["day_change_pct"] == 2.12
    assert nvda["quote_session"] == "regular" and nvda["quote_source"] == "market_quotes_extended"
    # the look-through table is absent live: a stated gap, never an invented row
    assert nvda["lookthrough"] == []
    assert any("etf_holdings_snapshot is not applied" in g for g in doc["gaps"])


def test_lookthrough_is_carried_with_provenance_when_the_table_exists(tmp_path):
    store = tmp_path / "holdings.json"
    data = rows() + [("acct_a", "SMH", "schwab", 5.0, 1000.0, 200.0, 1100.0, False, "etf",
                      "schwab_position_sync", NOW)]
    he.export(conn=Conn(data=data, lookthrough=True), store=store, backups=tmp_path / "b", now=NOW)
    doc = json.loads(store.read_text())
    smh = next(h for h in doc["holdings"] if h["symbol"] == "SMH")
    assert smh["lookthrough"] == [{"holding": "NVDA", "name": "NVIDIA", "weight": 12.4,
                                   "as_of": smh["lookthrough"][0]["as_of"], "source": "yfinance"}]
    assert not doc["gaps"]


def test_alert_on_empty_export_even_outside_market_hours(tmp_path):
    store = tmp_path / "holdings.json"
    store.write_text(json.dumps({"holdings": [], "portfolio_totals": {}}))
    calls = []
    out = he.maybe_alert_stale(store=store, now=datetime(2026, 11, 7, 6, 0, tzinfo=timezone.utc),
                               send=lambda *a, **k: calls.append(1) or {"delivered": True})
    assert out["sent"] is True and calls


def test_alert_on_totals_mismatch_over_one_dollar(tmp_path):
    store = tmp_path / "holdings.json"
    he.export(conn=Conn(), store=store, backups=tmp_path / "b", now=NOW)
    doc = json.loads(store.read_text())
    doc["portfolio_totals"]["total_value"] = float(doc["portfolio_totals"]["total_value"]) - 2.0
    store.write_text(json.dumps(doc))
    calls = []
    out = he.maybe_alert_stale(store=store, now=NOW, conn=Conn(),
                               send=lambda *a, **k: calls.append(1) or {"delivered": True})
    assert out["sent"] is True and calls


def test_no_alert_when_fresh_and_totals_match(tmp_path):
    store = tmp_path / "holdings.json"
    he.export(conn=Conn(), store=store, backups=tmp_path / "b", now=NOW)
    out = he.maybe_alert_stale(store=store, now=NOW + timedelta(minutes=1), conn=Conn(),
                               send=lambda *a, **k: {"delivered": True})
    assert out["sent"] is False and out["status"] == "fresh"


def test_missing_store_alerts_during_market_hours(tmp_path):
    out = he.maybe_alert_stale(store=tmp_path / "absent.json", now=NOW, send=lambda *a, **k: {"delivered": True})
    assert out["sent"] is True and out["age_minutes"] is None
