"""Momentum-scalp universe fails closed and stops have a minimum distance (operator 2026-10-05).

- A symbol needs a KNOWN float <= float_mm_max and a KNOWN price in the scalp band; bare social rows
  with no float (HPE, DELL, CHPT) leaked in under `float IS NULL OR ...`.
- Before excluding an unknown float, the engine looks it up (Finviz, then Alpha Vantage), bounded per
  run and cached with TTLs. Lookups are faked here: no network, no database, no secrets.
- Stop distance >= max(ATR_1m, 3x spread, 1% of price); XNDU fired with R = $0.01-0.02.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

for _name, _attrs in (("psycopg2", {"connect": lambda *a, **k: None}),
                      ("psycopg2.extras", {"RealDictCursor": object})):
    try:
        __import__(_name)
    except Exception:  # noqa: BLE001
        _m = types.ModuleType(_name)
        for _k, _v in _attrs.items():
            setattr(_m, _k, _v)
        sys.modules[_name] = _m

import scalp_shadow_logger as ssl  # noqa: E402
import scalp_float_lookup as sfl  # noqa: E402

CFG = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text())
U = CFG["universe"]


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql = rows, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return list(self.rows)


class _Conn:
    def __init__(self, rows):
        self.cur = _Cur(rows)

    def cursor(self):
        return self.cur


# (symbol, latest float_mm, latest price, latest route, latest disqualified)
ROWS = [
    ("HPE", None, None, None, False),        # bare social row
    ("DELL", None, None, None, False),
    ("XNDU", 20.68, 4.4, None, False),       # real small cap, float from an older scan
    ("BIGF", 82.6, 7.25, None, False),       # float above max
    ("PRCY", 10.0, 38.2, None, False),       # price above band
    ("PENY", 5.0, 0.6, None, False),         # price below band
    ("RJCT", 8.0, 5.0, "reject", False),
    ("LFSS", 8.0, 5.0, "large_float_social_scout", False),
    ("DSQL", 8.0, 5.0, None, True),
    ("NOPX", 8.0, None, None, False),
]


def test_config_carries_the_operator_rules():
    assert U["require_known_float"] is True and U["float_mm_max"] == 30
    assert (U["price_min"], U["price_max"]) == (1.0, 25.0) and U["require_reference_price"] is False
    assert {"reject", "large_float_social_scout"} <= set(U["excluded_routes"])
    ms = CFG["min_stop"]
    assert ms["enabled"] and (ms["atr_mult"], ms["spread_mult"], ms["pct_of_price"]) == (1.0, 3.0, 0.01)
    fl = U["float_lookup"]
    assert fl["enabled"] and fl["sources"][0] == "finviz" and fl["max_lookups_per_run"] > 0


def test_unknown_float_fails_closed_and_each_exclusion_is_named():
    kept, excluded = ssl.classify_universe(ROWS, U)
    assert kept == ["XNDU", "NOPX"]                             # unknown scan price → live band check
    assert excluded == {"HPE": "float_unknown", "DELL": "float_unknown", "BIGF": "float_above_max",
                        "PRCY": "price_band", "PENY": "price_band", "RJCT": "route_reject",
                        "LFSS": "route_large_float_social_scout", "DSQL": "disqualified"}
    kept2, ex2 = ssl.classify_universe(ROWS, {**U, "require_reference_price": True})
    assert kept2 == ["XNDU"] and ex2["NOPX"] == "price_unknown"


def test_sql_takes_latest_non_null_float_from_any_scan_and_no_null_admission():
    conn = _Conn(ROWS)
    # the universe SQL itself; the 2026-10-09 shared feeds run after it on the same fake cursor
    # (tests/test_trade_ai_scalp_5min_20261009.py covers them)
    cfg = {**CFG, "universe": {**CFG["universe"], "shared_feeds": {"enabled": False}}}
    ssl.resolve_universe_detail(conn, cfg, float_lookup=lambda syms, u: {})
    sql = conn.cur.sql
    assert "IS NULL OR" not in sql                              # the leak is gone
    assert "float_mm IS NOT NULL" in sql and "ORDER BY x.scanned_at DESC LIMIT 1" in sql
    assert "interval '30 days'" in sql and "interval '21 days'" in sql


def test_lookup_rescues_a_real_small_cap_and_still_excludes_large_caps():
    seen = []

    def fake(syms, u):
        seen.append(list(syms))
        return {"CRMX": {"float_mm": 12.0, "price": 6.1, "source": "finviz"},
                "HPE": {"float_mm": 1310.0, "price": 68.0, "source": "finviz"}}
    rows = [("CRMX", None, None, None, False), ("HPE", None, None, None, False),
            ("DELL", None, None, None, False), ("RJCT", None, None, "reject", False)]
    kept, excluded = ssl.resolve_universe_detail(_Conn(rows), CFG, float_lookup=fake)
    assert seen == [["CRMX", "HPE", "DELL"]]                    # excluded routes are not looked up
    assert kept == ["CRMX"]
    assert excluded == {"HPE": "float_above_max", "DELL": "float_unknown", "RJCT": "route_reject"}


def test_lookup_failure_leaves_symbols_excluded():
    def boom(syms, u):
        raise RuntimeError("provider down")
    kept, excluded = ssl.resolve_universe_detail(_Conn([("ABCD", None, 5.0, None, False)]), CFG,
                                                 float_lookup=boom)
    assert kept == [] and excluded == {"ABCD": "float_unknown"}


def test_float_lookup_is_bounded_cached_and_falls_back_to_alpha_vantage(tmp_path):
    path = tmp_path / "cache.json"
    calls = {"fv": [], "av": []}

    def fv(syms):
        calls["fv"].append(list(syms))
        return {"AAA": {"float_mm": 9.0, "price": 3.0}, "BBB": {"float_mm": None, "price": 4.0}}

    def av(sym):
        calls["av"].append(sym)
        return 15.5 if sym == "BBB" else None
    u = {**U, "float_lookup": {**U["float_lookup"], "max_lookups_per_run": 3, "av_max_lookups_per_run": 1}}
    out = sfl.lookup_floats(["AAA", "BBB", "CCC", "DDD"], u, cache_path=path, finviz=fv, av=av, now=1000.0)
    assert calls["fv"] == [["AAA", "BBB", "CCC"]]               # bounded to max_lookups_per_run
    assert calls["av"] == ["BBB"]                               # AV budget 1
    assert out == {"AAA": {"float_mm": 9.0, "price": 3.0, "source": "finviz"},
                   "BBB": {"float_mm": 15.5, "price": 4.0, "source": "alpha_vantage"}}
    cache = json.loads(path.read_text())
    assert cache["CCC"]["float_mm"] is None                     # negative cached
    # within TTL: nothing refetched for cached symbols; DDD (never looked up) is fetched now
    calls["fv"].clear(); calls["av"].clear()
    out2 = sfl.lookup_floats(["AAA", "BBB", "CCC", "DDD"], u, cache_path=path, finviz=lambda s: calls["fv"].append(list(s)) or {},
                             av=lambda s: None, now=1000.0 + 3600)
    assert calls["fv"] == [["DDD"]] and set(out2) == {"AAA", "BBB"}
    # negative TTL expired → CCC retried; positive TTL still fresh
    calls["fv"].clear()
    sfl.lookup_floats(["AAA", "CCC"], u, cache_path=path, finviz=lambda s: calls["fv"].append(list(s)) or {},
                      av=lambda s: None, now=1000.0 + (U["float_lookup"]["negative_ttl_hours"] + 1) * 3600)
    assert calls["fv"] == [["CCC"]]


def test_zero_float_from_finviz_is_unknown():
    assert sfl._positive(0.0) is None and sfl._positive("-") is None and sfl._positive("12.5") == 12.5


def test_min_stop_widens_a_one_cent_stop():
    # XNDU 09:55: entry 4.38 stop 4.36 (R $0.02), ATR tiny, spread 23 bps
    out = ssl.apply_min_stop(4.38, 4.36, 0.01, 23.0, CFG)
    d = max(0.01 * 4.38, 1.0 * 0.01, 3.0 * 23.0 / 1e4 * 4.38)    # 3x spread = $0.302
    assert out["stop_floor_applied"] is True and out["stop_raw"] == 4.36
    assert out["r_dollars"] == pytest.approx(d, abs=1e-4)
    assert out["stop_pct"] == pytest.approx(d / 4.38, abs=1e-4)


def test_min_stop_never_tightens_a_wide_stop():
    out = ssl.apply_min_stop(10.0, 9.0, 0.05, 10.0, CFG)
    assert out["stop"] == 9.0 and out["stop_floor_applied"] is False and out["r_dollars"] == 1.0


def test_min_stop_handles_missing_inputs():
    assert ssl.apply_min_stop(None, None, None, None, CFG)["r_dollars"] is None
    out = ssl.apply_min_stop(5.0, 4.99, None, None, CFG)       # only the 1% leg applies
    assert out["r_dollars"] == pytest.approx(0.05)


def test_live_price_band_guard():
    assert ssl.in_price_band(4.4, CFG) and not ssl.in_price_band(553.0, CFG)
    assert not ssl.in_price_band(None, CFG) and not ssl.in_price_band(0.5, CFG)


def test_universe_profile_is_self_contained():
    import inspect
    src = inspect.getsource(ssl.classify_universe) + inspect.getsource(ssl.resolve_universe_detail)
    for literal in ("25.0", "1.0", "30", "'reject'"):
        assert literal not in src                               # every threshold comes from config
