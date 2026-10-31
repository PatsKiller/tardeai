"""Market reference ETFs are always in the quote universe (Market Risk Engine, 2026-10-31).

Builder H's read-only audit (PR #2341) found HYG, UUP and VIXY absent from market_quotes because the
universe is only classified, open and watched names. These tests pin the union with
config/market_reference_symbols.json, and that a broken config degrades to the DB universe instead of
breaking the quote run. No network, no database (sqlite shim).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import external_market_data_ingest as ingest  # noqa: E402


class _Cur:
    def __init__(self, db):
        self.db, self.rows = db, []

    def execute(self, sql, params=None):
        self.rows = self.db.execute(sql, params or []).fetchall()

    def fetchall(self):
        return [{"symbol": r[0]} for r in self.rows]


class _Conn:
    def __init__(self, db):
        self.db = db

    def cursor(self, **_kw):
        return _Cur(self.db)

    def close(self):
        pass


def _db():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE ticker_strategy_classifications (symbol TEXT, active BOOLEAN);
        CREATE TABLE paper_trades (symbol TEXT, status TEXT);
        CREATE TABLE watchlist_items (symbol TEXT, in_directive_watch BOOLEAN, status TEXT);
        INSERT INTO ticker_strategy_classifications VALUES ('SPY', 1), ('AAA', 1);
        """
    )
    return db


def _symbols(monkeypatch, path=None):
    monkeypatch.setattr(ingest, "_get_conn", lambda: _Conn(_db()))
    if path is not None:
        monkeypatch.setattr(ingest, "REFERENCE_SYMBOLS_PATH", path)
        monkeypatch.setattr(ingest._reference_symbols, "__defaults__", (path,))
    return ingest._get_symbols()


def test_shipped_config_adds_the_audit_gaps(monkeypatch):
    syms = _symbols(monkeypatch)
    for s in ("HYG", "UUP", "VIXY", "TLT", "LQD", "USO", "GLD", "RSP", "SOXX", "IWM", "DIA", "JNK"):
        assert s in syms, s
    assert "AAA" in syms  # the DB universe is untouched
    assert syms.count("SPY") == 1  # in both sources, quoted once


def test_shipped_config_shape():
    doc = json.loads((ROOT / "config" / "market_reference_symbols.json").read_text())
    assert doc["schema"] == "MarketReferenceSymbols@v1"
    assert all(s == s.upper() and 1 <= len(s) <= 5 and "-" not in s for s in doc["symbols"])


def test_missing_or_wrong_schema_degrades_to_db_universe(monkeypatch, tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert sorted(_symbols(monkeypatch, missing)) == ["AAA", "SPY"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "Other@v1", "symbols": ["HYG"]}))
    assert "HYG" not in _symbols(monkeypatch, bad)
    assert "WARNING market reference symbols unavailable" in capsys.readouterr().out
