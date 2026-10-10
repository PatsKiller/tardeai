"""etf_analyst_enrich pass 2 argument order (API_OVERLAP_CONSOLIDATION Q10, operator-approved 2026-10-10).

db_adapter.save_yahoo_analyst_targets_history(snapshot_date, targets_payload) was called as
(targets_payload, snapshot_date): the writer iterated the date string, raised on "2"["symbol"], the bare
except swallowed it, and every constituent's yfinance .info call (up to CONSTITUENT_CAP=120 a run) was
discarded with constituents_fetched=0. Fakes only: no network, no database, no pandas.
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
    import psycopg2.extras  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import etf_analyst_enrich as eae  # noqa: E402


def test_real_writer_signature_is_date_then_payload():
    tree = ast.parse((ROOT / "scripts" / "db_adapter.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "save_yahoo_analyst_targets_history")
    assert [a.arg for a in fn.args.args] == ["snapshot_date", "targets_payload"]


class _Cur:
    def __init__(self):
        self._rows = []

    def execute(self, sql, params=None):
        if "FROM symbol_profiles" in sql:
            self._rows = [("SPY", "etf", None)]
        else:  # analyst-history reads: nothing stored yet
            self._rows = []

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self):
        self.cur = _Cur()

    def cursor(self):
        return self.cur

    def commit(self):
        pass


class _Top:
    """Minimal stand-in for the funds_data.top_holdings DataFrame (index + last column)."""

    def __init__(self, holdings):
        self.index = [h for h, _ in holdings]
        self._w = [w for _, w in holdings]

    def __len__(self):
        return len(self.index)

    @property
    def iloc(self):
        w = self._w

        class _I:
            def __getitem__(self, _key):
                return w
        return _I()


class _Ticker:
    def __init__(self, sym):
        self.info = {"targetMeanPrice": 110.0, "currentPrice": 100.0, "numberOfAnalystOpinions": 9}
        self.funds_data = types.SimpleNamespace(top_holdings=_Top([("AAA", 0.5), ("BBB", 0.3)])) if sym == "SPY" else None


def test_constituent_fetches_are_saved_not_discarded(monkeypatch):
    saved = []

    def save_yahoo_analyst_targets_history(snapshot_date, targets_payload):  # the real signature
        for t in targets_payload:
            saved.append((snapshot_date, t["symbol"]))

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker))
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(
        _get_conn=lambda: _Conn(), save_yahoo_analyst_targets_history=save_yahoo_analyst_targets_history))
    monkeypatch.setattr(eae, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(eae, "upsert_profile", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda *_a: None)

    res = eae.enrich()

    assert res["constituents_needed"] == 2
    assert res["constituents_fetched"] == 2, "each fetched .info must be written, not swallowed"
    assert sorted(s for _, s in saved) == ["AAA", "BBB"]
    assert all(len(d) == 10 and d[4] == "-" for d, _ in saved)  # YYYY-MM-DD snapshot date
    assert eae.run_failed(res) is False
