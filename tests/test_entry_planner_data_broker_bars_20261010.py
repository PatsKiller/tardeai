"""Entry planner bars fallback goes through the host Data Broker — no broker credentials in the lane process.

Operator ruling 2026-10-10 ~00:20 ET (n8n-maturity REMEDIATION_PLAN §7 ruling 3): the entry planner (L473/L474,
scripts/watchlist_entry_planner.py) fetches bars through the host data broker; no broker credentials in the lane
environment. It used to fall back from yfinance to the Alpaca market-data API with ALPACA_API_KEY /
ALPACA_SECRET_KEY read from its own env or the repo .env. The fallback is now the Data Broker read model
lib.data_broker.ohlc_bars.get_daily_ohlc (market_ohlcv_bars daily candles, zero provider calls, read-only).

Asserted here, hermetically (fake yfinance, fake db_query, no DB, no network):
  * the planner never reads an ALPACA_* env var and never imports any alpaca module (trading adapter
    included) — enforced with an import hook and an environ that records every key read;
  * the fallback still returns {high, low, close} bars via the broker; stale / close-only / short / failed
    broker reads give None (the planner then skips the symbol, as before);
  * yfinance stays first; the broker is not called when yfinance answers;
  * the CLI surface (there is no --dry-run on this script) is unchanged.
"""
from __future__ import annotations

import importlib
import importlib.abc
import os
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SRC_PATH = ROOT / "scripts" / "watchlist_entry_planner.py"
SRC = SRC_PATH.read_text(encoding="utf-8")


class _AlpacaImportBlocker(importlib.abc.MetaPathFinder):
    """Refuses any module whose dotted name mentions alpaca (alpaca_paper_adapter, alpaca_trade_api, ...)."""

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(self, fullname, path=None, target=None):  # noqa: D401
        if "alpaca" in fullname.lower():
            self.attempts.append(fullname)
            raise ImportError(f"blocked by test: {fullname}")
        return None


class _RecordingEnviron(dict):
    """os.environ stand-in that records every key read (os.getenv -> environ.get)."""

    def __init__(self, base) -> None:
        super().__init__(base)
        self.reads: list[str] = []

    def __getitem__(self, key):
        self.reads.append(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)

    def __contains__(self, key):
        self.reads.append(key)
        return super().__contains__(key)


def _candle_rows(n: int, *, last_age_days: int = 0) -> list[dict]:
    end = datetime.now(timezone.utc) - timedelta(days=last_age_days)
    return [{"bar_time": end - timedelta(days=n - 1 - i), "open": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i,
             "close": 10.5 + i, "volume": 1000.0} for i in range(n)]


class _FakeDB:
    def __init__(self, candles: list[dict] | None = None, closes: list[dict] | None = None, boom: bool = False):
        self.candles, self.closes, self.boom = candles or [], closes or [], boom
        self.calls: list[tuple[str, tuple]] = []

    def __call__(self, sql, params=None, fetch="all"):
        self.calls.append((sql, params))
        assert sql.lstrip().upper().startswith("SELECT"), sql      # read-only
        if self.boom:
            raise RuntimeError("db down")
        return self.candles if "market_ohlcv_bars" in sql else self.closes


def _failing_yfinance():
    yf = types.ModuleType("yfinance")

    class _T:
        def __init__(self, *_a, **_k):
            raise RuntimeError("Too Many Requests (rate limited)")

    yf.Ticker = _T
    return yf


@pytest.fixture()
def guarded(monkeypatch):
    """Fresh planner import under the alpaca import blocker and a recording environ."""
    blocker = _AlpacaImportBlocker()
    env = _RecordingEnviron(os.environ)
    env["ALPACA_API_KEY"] = "must-not-be-read"
    env["ALPACA_SECRET_KEY"] = "must-not-be-read"
    monkeypatch.setattr(os, "environ", env)
    monkeypatch.setitem(sys.modules, "yfinance", _failing_yfinance())
    before = {m for m in sys.modules if "alpaca" in m.lower()}
    sys.meta_path.insert(0, blocker)
    sys.modules.pop("watchlist_entry_planner", None)
    try:
        wep = importlib.import_module("watchlist_entry_planner")
        yield wep, blocker, env, before
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.pop("watchlist_entry_planner", None)


def _alpaca_reads(env: _RecordingEnviron) -> list[str]:
    return [k for k in env.reads if str(k).upper().startswith(("ALPACA", "APCA"))]


# ── no broker credentials, no alpaca import ──────────────────────────────────────────────────────────

def test_source_names_no_alpaca_credential_endpoint_or_env_file():
    low = SRC.lower()
    assert "alpaca" not in low, [ln for ln in SRC.splitlines() if "alpaca" in ln.lower()]
    assert "apca-" not in low
    assert "data.alpaca.markets" not in low
    assert not re.search(r"""["']\.env["']""", SRC), "the planner must not read the repo .env for keys"


def test_fallback_returns_broker_bars_without_alpaca_env_or_import(guarded, monkeypatch):
    wep, blocker, env, before = guarded
    db = _FakeDB(candles=_candle_rows(120))
    monkeypatch.setattr(wep, "_broker_db_query", lambda: db)
    bars = wep._bars("aapl", days=70)
    assert bars is not None and len(bars) == 70
    assert set(bars[0]) == {"high", "low", "close"}
    assert bars[-1] == {"high": 11.0 + 119, "low": 9.0 + 119, "close": 10.5 + 119}
    assert len(db.calls) == 1 and "market_ohlcv_bars" in db.calls[0][0] and db.calls[0][1][0] == "AAPL"
    assert _alpaca_reads(env) == []
    assert blocker.attempts == []
    assert {m for m in sys.modules if "alpaca" in m.lower()} == before


def test_tech_math_runs_on_broker_bars(guarded, monkeypatch):
    wep, _blocker, env, _before = guarded
    monkeypatch.setattr(wep, "_broker_db_query", lambda: _FakeDB(candles=_candle_rows(120)))
    t = wep._tech(wep._bars("MSFT"))
    assert t["price"] == pytest.approx(10.5 + 119) and t["atr"] > 0 and t["sma50"] > 0
    assert _alpaca_reads(env) == []


@pytest.mark.parametrize("db", [
    _FakeDB(candles=_candle_rows(40)),                                      # too few candles
    _FakeDB(candles=_candle_rows(120, last_age_days=40)),                   # stale (> 120 h)
    _FakeDB(closes=[{"price_date": datetime.now(timezone.utc).date(), "close_price": 10.0}] * 80),  # close-only
    _FakeDB(boom=True),                                                     # broker read failed
    _FakeDB(),                                                              # no coverage
], ids=["short", "stale", "closes_only", "error", "none"])
def test_fallback_refuses_unusable_broker_reads(guarded, monkeypatch, db):
    wep, blocker, env, _before = guarded
    monkeypatch.setattr(wep, "_broker_db_query", lambda: db)
    assert wep._bars("NVDA") is None
    assert _alpaca_reads(env) == [] and blocker.attempts == []


def test_weekend_aged_candles_are_accepted(guarded, monkeypatch):
    """The envelope's 26 h window would refuse Friday's candle on Monday; the planner's own window accepts it."""
    wep, _blocker, env, _before = guarded
    monkeypatch.setattr(wep, "_broker_db_query", lambda: _FakeDB(candles=_candle_rows(120, last_age_days=3)))
    assert len(wep._bars("IBM")) == 70
    assert _alpaca_reads(env) == []


def test_yfinance_first_broker_untouched_when_it_answers(guarded, monkeypatch):
    wep, _blocker, env, _before = guarded

    class _Hist(dict):
        pass

    n = 80
    h = _Hist(High=[2.0 + i for i in range(n)], Low=[1.0 + i for i in range(n)], Close=[1.5 + i for i in range(n)])
    yf = types.ModuleType("yfinance")
    yf.Ticker = lambda _s: types.SimpleNamespace(history=lambda period: h)
    monkeypatch.setitem(sys.modules, "yfinance", yf)

    def _no_broker():
        raise AssertionError("broker must not be consulted when yfinance answers")

    monkeypatch.setattr(wep, "_broker_db_query", _no_broker)
    bars = wep._bars("AMD", days=70)
    assert len(bars) == 70 and bars[-1]["close"] == 1.5 + n - 1
    assert _alpaca_reads(env) == []


def test_default_db_query_is_the_db_adapter_read(monkeypatch):
    """The production fallback reads through db_adapter._execute (the lane's existing DB session) — no keys."""
    sys.modules.pop("watchlist_entry_planner", None)
    wep = importlib.import_module("watchlist_entry_planner")
    seen = {}
    fake = types.ModuleType("db_adapter")
    fake._execute = lambda sql, params=None, fetch=None: seen.setdefault("call", (sql, params, fetch)) and []
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    q = wep._broker_db_query()
    q("SELECT 1", ("X",))
    assert seen["call"] == ("SELECT 1", ("X",), "all")


def test_fallback_uses_the_registered_data_broker_entrypoint():
    from scripts.lib.data_broker import catalog

    entry = next(e for e in catalog.PROJECTIONS if e.get("id") == "ohlc_bars")
    assert entry["read_only"] is True and entry["provider_calls"] == 0
    assert "get_daily_ohlc" in entry["entrypoints"]
    assert any("watchlist_entry_planner" in c for c in entry["consumers"])
    assert "get_daily_ohlc" in SRC and "data_broker.ohlc_bars" in SRC


# ── CLI / dry-run surface unchanged ──────────────────────────────────────────────────────────────────

def test_cli_surface_is_unchanged():
    flags = re.findall(r'ap\.add_argument\("(--[a-z-]+)"', SRC)
    assert flags == ["--lane", "--symbols", "--limit", "--scope", "--buy-rated-cap", "--no-alert", "--dry-run"]  # --dry-run: refactor wave 2
