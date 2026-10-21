"""indicator_engine --universe failed 2026-10-20 and 2026-10-21 08:00 ET: a bare NaN reached a Postgres json column.

Log (persistent-state/logs/indicator_engine.log):
  psycopg2.errors.InvalidTextRepresentation: invalid input syntax for type json
  DETAIL:  Token "NaN" is invalid.
  CONTEXT: JSON data, line 1: ... "pivots_weekly": {"pp": NaN ...      (2026-10-21; 10-20: "ema": {"value": NaN})

Reproduced read-only 2026-10-21: the dry-run selection's 24th stale symbol is GP (after MIMI, where both logs stop);
analyze_confluence("GP", "swing") returns ok=True with NaN pivots_weekly pp/r1..r3/s1..s3 in both ``signals`` and
``key_levels`` (short history: no complete prior week). ``upsert_params`` json.dumps'd them (allow_nan defaults to
True, which emits the bare token NaN), Postgres rejected the row, and the exception -- not one of the lane's
connection-loss classes -- escaped ``run()``: every later symbol in the batch was never attempted.

Fix: ``indicator_engine.json_safe`` maps every non-finite float (NaN/±Inf, numpy included, nested in dicts/lists)
to None; ``analyze_confluence`` returns a json-safe result (all four cache writers read it); the lane serialises with
``allow_nan=False`` so a regression raises in tests instead of reaching Postgres, and stores non-finite scalar
columns as NULL; a row Postgres rejects as data (SQLSTATE class 22) is rolled back and skipped as
``row_rejected`` instead of aborting the batch.

Hermetic: no database, network, broker or model. numpy/pandas parts skip where CI lacks them.

COVERS = ["scripts/indicator_engine.py", "scripts/lib/indicator_universe_lane.py", "scripts/lib/json_finite.py"]
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import indicator_universe_lane as iul  # noqa: E402

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
CFG = {"profile": "swing", "stale_after_hours": 6, "max_symbols": 10, "cache_ttl_minutes": 60}
NAN, INF = float("nan"), float("inf")


def _strict_loads(text: str):
    """Postgres json grammar: NaN / Infinity / -Infinity are not tokens."""
    def bad(tok):
        raise ValueError(f"non-JSON token {tok}")
    return json.loads(text, parse_constant=bad)


def _gp_like(**over):
    """The shape of analyze_confluence('GP', 'swing') on 2026-10-21 (values abridged)."""
    r = {
        "ok": True, "symbol": "GP", "profile": "swing", "confluence_score": 0, "confluence_tier": "NONE",
        "signals_bullish": 1, "signals_bearish": 1, "signals_neutral": 3,
        "strategy_badges": ["RSI"], "bearish_badges": ["ADX"],
        "signals": {"pivots_weekly": {"signal": "NEUTRAL", "value": NAN,
                                      "details": {"pp": NAN, "r1": NAN, "s1": -INF}},
                    "ema": {"signal": "NEUTRAL", "value": NAN, "details": {"series": [1.0, NAN, INF]}}},
        "key_levels": {"pivots_weekly": {"pp": NAN, "r1": NAN, "s1": NAN},
                       "fibonacci": {"0.618": NAN, "0.5": 1.5}},
        "stop_price": 1.37, "target_price": 1.82, "atr": 0.1002, "adx_regime": "trending",
        "entry_quality": "good", "computed_at": "2026-10-21T12:00:00+00:00",
    }
    r.update(over)
    return r


# ── 1. the serialisation boundary ───────────────────────────────────────────────────────────────────────────────────
def test_upsert_params_emit_postgres_valid_json_with_nan_as_null():
    params = iul.upsert_params("GP", "swing", _gp_like(), 60)
    key_levels, full_result = params[9], params[15]
    kl = _strict_loads(key_levels)
    fr = _strict_loads(full_result)
    assert kl["pivots_weekly"] == {"pp": None, "r1": None, "s1": None}
    assert kl["fibonacci"] == {"0.618": None, "0.5": 1.5}
    assert fr["signals"]["pivots_weekly"]["details"]["s1"] is None
    assert fr["signals"]["ema"]["details"]["series"] == [1.0, None, None]
    assert fr["stop_price"] == 1.37 and fr["symbol"] == "GP"


def test_non_finite_scalar_columns_are_null():
    # 2026-10-20 log: stop_price/target_price went in as 'NaN'::float (a release before the 10-18 ATR guard).
    params = iul.upsert_params("GP", "swing", _gp_like(stop_price=NAN, target_price=INF, atr=-INF,
                                                       confluence_score=NAN), 60)
    assert params[10] is None and params[11] is None and params[12] is None
    assert params[2] is None or params[2] == 0  # score: NULL rather than NaN (the column default is never NaN)
    for p in params:
        assert not (isinstance(p, float) and not math.isfinite(p)), params


def _json_safe():
    """``lib.json_finite.json_safe`` (import-light: CI has no numpy/pandas/yfinance); the lane re-exports it."""
    from lib import json_finite
    assert iul.json_safe is json_finite.json_safe
    return json_finite.json_safe


def test_json_safe_nested_values():
    js = _json_safe()
    out = js({"a": [NAN, 1, 2.5, (INF, "x")], "b": {"c": -INF, "d": True, "e": None, "f": "NaN"}})
    assert out == {"a": [None, 1, 2.5, [None, "x"]], "b": {"c": None, "d": True, "e": None, "f": "NaN"}}
    json.dumps(out, allow_nan=False)  # must not raise


def test_json_safe_numpy_scalars_and_arrays():
    np = pytest.importorskip("numpy")
    js = _json_safe()
    out = js({"f": np.float64("nan"), "g": np.float32(2.5), "i": np.int64(7), "b": np.bool_(True),
              "arr": np.array([1.0, np.nan, np.inf])})
    assert out == {"f": None, "g": 2.5, "i": 7, "b": True, "arr": [1.0, None, None]}
    assert type(out["i"]) is int and type(out["b"]) is bool and type(out["g"]) is float
    json.dumps(out, allow_nan=False)


def test_serialisation_refuses_a_bare_nan_instead_of_shipping_it():
    """allow_nan=False is the tripwire: anything json_safe misses raises here, never at Postgres."""
    with pytest.raises(ValueError):
        iul._dumps({"x": NAN}, sanitize=False)
    assert _strict_loads(iul._dumps({"x": NAN})) == {"x": None}


def test_engine_returns_a_json_safe_result(monkeypatch):
    """analyze_confluence is the shared source for all four indicator_confluence_cache writers."""
    pd = pytest.importorskip("pandas")
    pytest.importorskip("yfinance")
    import indicator_engine as ie

    idx = pd.date_range("2026-09-01", periods=40, freq="B")
    df = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1000.0}, index=idx)
    monkeypatch.setattr(ie, "_fetch_ohlcv", lambda *a, **k: df)

    def nan_strategy(_df, _cfg):
        return {"signal": "NEUTRAL", "value": float("nan"),
                "details": {"pp": float("nan"), "r1": float("inf"), "s1": 1.0}}

    monkeypatch.setattr(ie, "STRATEGY_FUNCTIONS", {"pivots_weekly": nan_strategy})
    monkeypatch.setattr(ie, "CONFIG", {"profiles": {"swing": {"active_strategies": ["pivots_weekly"]}},
                                       "strategies": {}, "confluence": {}})
    r = ie.analyze_confluence("GP", "swing")
    assert r["ok"] is True
    json.dumps(r, allow_nan=False, default=str)  # raised ValueError before the fix
    assert r["key_levels"]["pivots_weekly"] == {"pp": None, "r1": None, "s1": 1.0}
    assert r["signals"]["pivots_weekly"]["value"] is None


# ── 2. one bad row must not abort the batch ─────────────────────────────────────────────────────────────────────────
class _DataError(Exception):
    """psycopg2.errors.InvalidTextRepresentation carries pgcode '22P02' (SQLSTATE class 22: data exception)."""
    pgcode = "22P02"


class _Conn:
    def __init__(self, universe, reject):
        self.universe, self.reject = universe, set(reject)
        self.log: list = []
        self.landed: list = []

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                s = " ".join(sql.split())
                if "watchlist_symbol_master" in s:
                    self._rows = [(x,) for x in conn.universe]
                elif "trade_ai_scans" in s:
                    self._rows = []
                elif s.startswith("SELECT symbol, computed_at FROM indicator_confluence_cache"):
                    self._rows = []
                elif s.startswith("INSERT INTO indicator_confluence_cache"):
                    if params[0] in conn.reject:
                        raise _DataError('invalid input syntax for type json DETAIL: Token "NaN" is invalid.')
                    conn.landed.append(params[0])
                    self._rows = []

            def fetchall(self):
                return list(self._rows)

        return C()

    def commit(self):
        self.log.append("commit")

    def rollback(self):
        self.log.append("rollback")


def test_a_row_postgres_rejects_is_skipped_and_the_batch_continues():
    conn = _Conn(["AAA", "GP", "ZZZ"], reject=["GP"])

    def analyze(sym, profile):
        return {"ok": True, "symbol": sym, "confluence_score": 5, "key_levels": {}}

    out = iul.run(get_conn=lambda: conn, analyze=analyze, rate_limited=lambda: False, config=CFG, now=NOW,
                  exclude=[])
    assert conn.landed == ["AAA", "ZZZ"]
    assert out["output"]["produced_count"] == 2 and out["output"]["skipped_reasons"] == {"row_rejected": 1}
    assert "rollback" in conn.log and iul.work_ok(out)


def test_a_non_data_error_still_propagates():
    class Boom(Exception):
        pgcode = "42P01"  # undefined_table: a schema fault, not a bad row

    conn = _Conn(["AAA"], reject=[])
    orig = conn.cursor

    def cursor():
        c = orig()
        real = c.execute

        def execute(sql, params=None):
            if sql.lstrip().startswith("INSERT"):
                raise Boom("relation does not exist")
            return real(sql, params)
        c.execute = execute
        return c
    conn.cursor = cursor
    with pytest.raises(Boom):
        iul.run(get_conn=lambda: conn, analyze=lambda s, p: {"ok": True, "symbol": s, "key_levels": {}},
                rate_limited=lambda: False, config=CFG, now=NOW, exclude=[])
