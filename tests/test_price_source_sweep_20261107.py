"""LQ-20261107-14 — every reader's current price comes from the operator's ladder.

Operator price rule (2026-11-07): Finviz while its cache row is fresh (<= 30 min), else a fresh
Schwab/Alpaca/moomoo quote; never yfinance, never a stored DB price older than 30 min presented as
current. The sweep routed four readers through `lib.portfolio_positions.resolve_mark` and
`lib.data_broker.market_quote.get_price_batch`.

Hermetic: no DB, no network, no credential file with values, no real symbol. The price helpers and the
DB driver are stubbed; every ticker below is synthetic (AAA/BBB/CCC).
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path, extra_globals: dict | None = None):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if extra_globals:
        mod.__dict__.update(extra_globals)
    spec.loader.exec_module(mod)
    return mod


def _fake_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


@pytest.fixture()
def stub_price_libs(monkeypatch):
    """Stand-in `lib` packages so no real cache file or DB is read. Returns a handle to set the marks."""
    state = {"mark": None, "batch": {}, "batch_calls": []}

    def resolve_mark(position, *, quote=None, finviz=None, now=None, cfg=None):  # noqa: ANN001
        state["last_quote"] = quote
        return state["mark"] or {"price": None, "source": "none", "as_of": None, "age_s": None,
                                 "live": False, "stale": True}

    def get_price_batch(db_query, symbols, max_age_hours=12, **kwargs):  # noqa: ANN001
        state["batch_calls"].append(list(symbols))
        return {s: state["batch"].get(s) for s in symbols if s in state["batch"]}

    monkeypatch.setitem(sys.modules, "lib", _fake_module("lib"))
    monkeypatch.setitem(sys.modules, "lib.portfolio_positions",
                        _fake_module("lib.portfolio_positions", resolve_mark=resolve_mark))
    broker = _fake_module("lib.data_broker")
    monkeypatch.setitem(sys.modules, "lib.data_broker", broker)
    monkeypatch.setitem(sys.modules, "lib.data_broker.market_quote",
                        _fake_module("lib.data_broker.market_quote",
                                     get_price_batch=get_price_batch,
                                     LIVE_FALLBACK_MAX_PER_BATCH=2))
    return state


# ── defense_cash_alternatives ────────────────────────────────────────────────────────────────────────

def _dca(monkeypatch):
    return _load("dca_under_test", SCRIPTS / "defense_cash_alternatives.py")


def test_cash_alternatives_prefers_a_fresh_finviz_mark(stub_price_libs, monkeypatch):
    mod = _dca(monkeypatch)
    stub_price_libs["mark"] = {"price": 111.5, "source": "finviz", "as_of": "2026-11-07 05:55:00 ET",
                               "age_s": 60, "live": True, "stale": False}

    def query(sql, params=None):
        assert "market_quotes" in sql
        return [{"symbol": "AAA", "price": 100.0, "day_change_pct": 1.25, "volume": 4321,
                 "fetched_at": "2026-11-06T20:00:00+00:00"}]

    out = mod.load_prices(query, ["AAA"])
    assert out["AAA"]["price"] == 111.5
    assert out["AAA"]["source"] == "finviz"
    assert out["AAA"]["stale"] is False
    assert out["AAA"]["change_pct"] == 1.25 and out["AAA"]["volume"] == 4321
    # the stored row was handed to the ladder as the fallback quote, never preferred over Finviz
    assert stub_price_libs["last_quote"]["price"] == 100.0


def test_cash_alternatives_marks_a_stale_mark_stale(stub_price_libs, monkeypatch):
    mod = _dca(monkeypatch)
    stub_price_libs["mark"] = {"price": 99.0, "source": "stored_mark", "as_of": "2026-11-06 20:00:00 ET",
                               "age_s": 9 * 3600, "live": False, "stale": True}
    out = mod.load_prices(lambda sql, params=None: [], ["AAA"])
    assert out["AAA"]["price"] == 99.0
    assert out["AAA"]["stale"] is True


def test_cash_alternatives_unpriced_symbol_is_absent_not_zero(stub_price_libs, monkeypatch):
    mod = _dca(monkeypatch)
    stub_price_libs["mark"] = {"price": None, "source": "none", "as_of": None, "age_s": None,
                               "live": False, "stale": True}
    assert mod.load_prices(lambda sql, params=None: [], ["AAA"]) == {}


def test_cash_alternatives_line_reports_fresh_marks(monkeypatch):
    mod = _dca(monkeypatch)
    line = mod._line({"coverage": {"universe": 3, "priced": 2, "fresh_mark": 1, "with_yield": 0},
                      "top3": [{"symbol": "AAA", "total_score": 10, "yield_data": {"div_yield": None}}]})
    assert "2 (1 with a fresh Finviz/broker mark)" in line


# ── previously_traded_watchlist ──────────────────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log

    def execute(self, sql, params=None):
        self._log.append((sql.strip().split()[0].upper(), str(sql)[:60], params))
        self._result = list(self._rows) if "SELECT symbol FROM previously_traded_watchlist" in sql else []

    def fetchall(self):
        return self._result


class _Conn:
    """A DB-API connection recorder: no server, no credential, every statement kept for assertion."""

    def __init__(self, symbols):
        self.log: list = []
        self._symbols = [{"symbol": s} for s in symbols]

    def cursor(self, *args, **kwargs):
        return _Cursor(self._symbols, self.log)

    def commit(self):
        self.log.append(("COMMIT", "", None))

    def close(self):
        self.log.append(("CLOSE", "", None))


def _watchlist_module(monkeypatch, tmp_path, symbols):
    """Exec the script with a throwaway ROOT (empty .env) and a stubbed driver + broker."""
    fake_psycopg2 = _fake_module("psycopg2")
    fake_extras = _fake_module("psycopg2.extras", RealDictCursor=object)
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_extras)
    conn = _Conn(symbols)
    mod = _load("ptw_under_test", SCRIPTS / "previously_traded_watchlist.py",
                extra_globals={"__file__": str(tmp_path / "scripts" / "previously_traded_watchlist.py")})
    mod.ROOT = tmp_path
    mod.get_db = lambda: conn
    return mod, conn


def test_watchlist_prices_come_from_the_shared_batch(stub_price_libs, monkeypatch, tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".env").write_text("", encoding="utf-8")
    mod, conn = _watchlist_module(monkeypatch, tmp_path, ["AAA", "BBB", "CCC"])
    stub_price_libs["batch"] = {"AAA": {"price": 12.5, "source": "finviz_quote_cache"},
                                "CCC": {"price": 0}}
    prices = mod.fetch_current_prices()
    assert prices == {"AAA": 12.5}                     # a zero is not a price
    assert "BBB" not in prices                          # no fresh quote -> stored price left alone
    updates = [e for e in conn.log if e[0] == "UPDATE"]
    assert len(updates) == 1 and "AAA" in updates[0][2]


def test_watchlist_batches_in_bounded_chunks(stub_price_libs, monkeypatch, tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".env").write_text("", encoding="utf-8")
    symbols = [f"A{i}" for i in range(5)]
    mod, _ = _watchlist_module(monkeypatch, tmp_path, symbols)
    mod.fetch_current_prices()
    # LIVE_FALLBACK_MAX_PER_BATCH is stubbed to 2 -> ceil(5/2) = 3 calls, every symbol attempted
    assert [len(c) for c in stub_price_libs["batch_calls"]] == [2, 2, 1]
    assert sum(stub_price_libs["batch_calls"], []) == symbols


def test_watchlist_never_imports_yfinance(stub_price_libs, monkeypatch, tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".env").write_text("", encoding="utf-8")
    mod, _ = _watchlist_module(monkeypatch, tmp_path, ["AAA"])
    fake_yf = _fake_module("yfinance")

    def _boom(*a, **k):
        raise AssertionError("yfinance must never be reached for a live price")

    fake_yf.Ticker = _boom
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    mod.fetch_current_prices()                          # an empty batch is fine; yfinance stays unused
    src = inspect.getsource(mod)
    assert "import yfinance" not in src and "yf.Ticker" not in src


# ── holding_protection_advisor ──────────────────────────────────────────────────────────────────────

def test_protection_advisor_takes_a_fresh_mark_over_the_bar_close(stub_price_libs, monkeypatch):
    mod = _load("hpa_under_test", SCRIPTS / "holding_protection_advisor.py")
    stub_price_libs["mark"] = {"price": 55.25, "source": "data_broker:finviz_quote_cache",
                               "as_of": "2026-11-07T05:55:00+00:00", "age_s": 120, "live": True, "stale": False}
    t = mod._apply_live_mark({"price": 50.0, "rsi": 60.0}, "AAA",
                             {"price": 55.25, "as_of": "2026-11-07T05:55:00+00:00", "source": "finviz_quote_cache"})
    assert t["price"] == 55.25
    assert t["price_source"] == "data_broker:finviz_quote_cache"
    assert t["price_stale"] is False
    assert t["rsi"] == 60.0                              # technicals are untouched


def test_protection_advisor_keeps_the_labelled_bar_close_when_nothing_is_fresh(stub_price_libs, monkeypatch):
    mod = _load("hpa_under_test", SCRIPTS / "holding_protection_advisor.py")
    stub_price_libs["mark"] = {"price": 49.0, "source": "finviz", "as_of": "2026-11-06 16:00:00 ET",
                               "age_s": 14 * 3600, "live": False, "stale": True}
    t = mod._apply_live_mark({"price": 50.0}, "AAA", None)
    assert t["price"] == 50.0
    assert t["price_source"] == "daily_close" and t["price_stale"] is True


def test_protection_advisor_survives_a_broken_mark_helper(stub_price_libs, monkeypatch):
    mod = _load("hpa_under_test", SCRIPTS / "holding_protection_advisor.py")

    def boom(*a, **k):
        raise RuntimeError("cache unreadable")

    monkeypatch.setitem(sys.modules, "lib.portfolio_positions",
                        _fake_module("lib.portfolio_positions", resolve_mark=boom))
    t = mod._apply_live_mark({"price": 50.0}, "AAA", None)
    assert t["price"] == 50.0 and t["price_stale"] is True


# ── holdings_gain_guardian ──────────────────────────────────────────────────────────────────────────

def test_gain_guardian_routes_its_price_through_the_shared_mark():
    """The Guardian's open-gain, giveback and HWM ratchet read the live mark, not the last bar close."""
    src = (SCRIPTS / "holdings_gain_guardian.py").read_text(encoding="utf-8")
    assert "hpa._apply_live_mark(m, sym, quotes.get(sym))" in src
    assert "hpa._live_quotes(" in src
    assert '"price_source"' in src                       # the source travels with the row
