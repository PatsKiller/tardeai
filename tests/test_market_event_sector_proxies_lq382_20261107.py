"""Sector moves from the reference daily bars as the detector's second sector source (LQ-20261107-382).

Operator ask 17:55 ET 2026-11-07: "market indicators beyond QQQ". Before this, the detector's only sector signal was
the MRE's Finviz-derived ``sectors.groups``, and ``config/market_event_policy.json`` ``index_symbols`` was SPY and
QQQ. These tests pin three things:

* the reference-bars symbol list carries every SPDR sector plus the theme proxies, and every proxy the map names is
  in that list (a proxy missing from ``symbols`` would never get a bar, so the group would read UNKNOWN forever);
* ``MarketEventSectorMoves@v1`` measures a group against the benchmark on the benchmark's own sessions, is honest
  about a missing or stale proxy (UNKNOWN with a reason, never a flat zero), and emits hits only for fresh moves;
* the document's hit shape joins the detector's existing ``sector_hits`` list, and the group keys join
  ``config/market_risk_policy.yaml`` ``sectors.groups`` so ``affected_groups`` resolves in both sources.

Synthetic fixtures only; no network, no DB.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import market_event_sector_proxies as sp  # noqa: E402

SYMBOLS_PATH = ROOT / "config" / "market_reference_symbols.json"
NEW_SPDR = ("XLE", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC")
NEW_THEMES = ("IGV", "KRE", "XBI", "IBB", "ITB", "IYT", "ARKK", "IBIT")
SESSIONS = [f"2026-10-{d:02d}" for d in (1, 2, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 20, 21, 22, 23, 26, 27, 28, 29)]


def _bars(sym: str, closes: list[float], *, source: str = "alpaca", sessions: list[str] | None = None) -> list[dict]:
    ss = sessions or SESSIONS
    return [{"symbol": sym, "session": d, "close": c, "source": source} for d, c in zip(ss, closes, strict=False)]


def _flat(sym: str, n: int = len(SESSIONS), value: float = 100.0, **kw) -> list[dict]:
    return _bars(sym, [value] * n, **kw)


def _groups() -> dict:
    return {
        "tech": {"label": "Technology", "proxy": "XLK", "kind": "sector"},
        "energy": {"label": "Energy", "proxy": "XLE", "kind": "sector"},
        "rates": {"label": "Long Treasuries", "proxy": "TLT", "kind": "macro"},
    }


def _doc(rows, **kw):
    return sp.build_moves(rows, _groups(), as_of="2026-11-07T22:00:00+00:00", **kw)


# ------------------------------------------------------------------------------------------ the shipped config
def test_the_reference_list_carries_all_eleven_spdr_sectors_and_the_theme_proxies():
    doc = json.loads(SYMBOLS_PATH.read_text())
    syms = set(doc["symbols"])
    assert syms >= set(NEW_SPDR), set(NEW_SPDR) - syms
    assert syms >= set(NEW_THEMES), set(NEW_THEMES) - syms
    assert syms >= {"XLK", "SMH", "SOXX", "SPY", "QQQ"}
    # the prior list is untouched (nothing silently dropped while adding)
    assert syms >= {"SPY", "QQQ", "IWM", "DIA", "RSP", "TLT", "HYG", "JNK", "LQD", "UUP", "USO", "GLD", "VIXY", "UVXY"}
    assert len(doc["symbols"]) == len(syms), "a duplicate symbol would fetch and store the same series twice"


def test_the_shipped_config_keeps_its_schema_and_symbol_shape():
    doc = json.loads(SYMBOLS_PATH.read_text())
    assert doc["schema"] == "MarketReferenceSymbols@v1"
    assert all(s == s.upper() and 1 <= len(s) <= 5 and "-" not in s for s in doc["symbols"])


def test_every_proxy_the_map_names_is_in_the_symbol_list():
    """A proxy absent from ``symbols`` never gets a daily bar, so its group would read UNKNOWN forever."""
    doc = json.loads(SYMBOLS_PATH.read_text())
    proxies = sp.load_proxy_groups()
    assert proxies["origin"].endswith("proxy_groups")
    assert proxies["groups"], "the shipped map is empty"
    missing = sorted({g["proxy"] for g in proxies["groups"].values()} - set(doc["symbols"]))
    assert missing == [], missing


def test_the_sector_group_keys_join_the_mre_policy_keys():
    yaml = pytest.importorskip("yaml")
    mre = yaml.safe_load((ROOT / "config" / "market_risk_policy.yaml").read_text())
    mre_keys = {g["key"] for g in (mre.get("sectors") or {}).get("groups") or [] if g.get("kind") == "sector"}
    ours = {k for k, g in sp.load_proxy_groups()["groups"].items() if g["kind"] == "sector"}
    assert ours == mre_keys, (ours ^ mre_keys)


# ------------------------------------------------------------------------------------------ pure computation
def test_a_sector_down_six_percent_against_a_flat_spy_is_underperforming_and_a_hit():
    spy = _flat("SPY")
    xlk = _bars("XLK", [100.0] * (len(SESSIONS) - 5) + [94.0] * 5)
    doc = _doc(spy + xlk)
    g = doc["groups"]["tech"]
    assert g["state"] == sp.STATE_UNDER
    assert g["ret5"] == pytest.approx(-6.0, abs=0.01)
    assert g["rs5"] == pytest.approx(-6.0, abs=0.01)
    assert g["stale"] is False and g["reason"] is None
    hits = sp.sector_hits(doc)
    assert [h["group"] for h in hits] == ["tech"]
    assert hits[0]["rs5"] == pytest.approx(-6.0, abs=0.01)
    assert hits[0]["source"] == "reference_bars"


def test_a_missing_proxy_is_unknown_with_a_reason_never_a_zero():
    doc = _doc(_flat("SPY"))  # no XLK and no XLE rows at all
    for key in ("tech", "energy"):
        g = doc["groups"][key]
        assert g["state"] == sp.STATE_UNKNOWN
        assert g["ret5"] is None and g["rs5"] is None  # never a fabricated 0.0
        assert "no daily bars" in g["reason"] and g["proxy"] in g["reason"]
    assert doc["unknown"] == ["energy", "rates", "tech"]  # every group without a proxy series, named
    assert sp.sector_hits(doc) == []


def test_a_stale_proxy_never_fires_a_hit_even_on_a_big_move():
    spy = _flat("SPY")                                   # last bar 2026-10-29
    xle_sessions = SESSIONS[:-5]                         # last bar 2026-10-22
    xle = _bars("XLE", [100.0] * (len(xle_sessions) - 5) + [80.0] * 5, sessions=xle_sessions)
    g = _doc(spy + xle)["groups"]["energy"]
    assert g["stale"] is True
    assert g["sessions_behind"] == 5
    assert g["state"] == sp.STATE_UNKNOWN
    assert "behind" in g["reason"] and g["last"] == "2026-10-22"
    assert sp.sector_hits(_doc(spy + xle)) == []


def test_without_benchmark_bars_every_group_is_unknown_and_names_the_benchmark():
    doc = _doc(_bars("XLK", [100.0] * len(SESSIONS)))
    assert doc["calendar_last"] is None and doc["benchmark_return"]["ret5"] is None
    assert doc["groups"]["tech"]["state"] == sp.STATE_UNKNOWN
    assert "SPY has no daily bars" in doc["groups"]["tech"]["reason"]
    assert sp.sector_hits(doc) == []


def test_alpaca_beats_yfinance_on_a_duplicate_session_and_the_source_is_reported():
    rows = _flat("SPY", source="alpaca") + [
        {"symbol": "XLK", "session": d, "close": 100.0, "source": "yfinance"} for d in SESSIONS]
    rows += [{"symbol": "XLK", "session": SESSIONS[-1], "close": 50.0, "source": "yfinance"}]  # later, wrong vendor
    series = sp.series_from_rows(rows)
    assert series["XLK"][-1] == (SESSIONS[-1], 50.0, "yfinance")  # same vendor: the later row is the stored one
    rows.append({"symbol": "XLK", "session": SESSIONS[-1], "close": 101.0, "source": "alpaca"})
    series = sp.series_from_rows(rows)
    assert series["XLK"][-1] == (SESSIONS[-1], 101.0, "alpaca")  # alpaca outranks a later yfinance row
    assert len(series["XLK"]) == len(SESSIONS)  # one close per (symbol, session)


def test_a_non_positive_close_is_dropped_not_divided_by():
    rows = _flat("SPY") + _bars("XLK", [0.0] + [100.0] * (len(SESSIONS) - 1))
    doc = _doc(rows)
    assert doc["groups"]["tech"]["close"] == 100.0
    assert doc["groups"]["tech"]["ret20"] is None  # the 20-session endpoint is the dropped 0.0
    assert doc["groups"]["tech"]["reason"] is None  # it still has bars; only that window is unmeasured


def test_a_window_needs_both_endpoints_on_the_benchmark_calendar():
    """XLK is missing session -6 (the 5-session start): ret5 is None, not a 6-session move mislabelled as 5."""
    sess = [d for d in SESSIONS if d != SESSIONS[-6]]
    xlk = _bars("XLK", [100.0] * len(sess), sessions=sess)
    g = _doc(_flat("SPY") + xlk)["groups"]["tech"]
    assert g["ret5"] is None and g["rs5"] is None
    assert g["ret1"] is not None and g["ret20"] is not None


def test_kinds_filter_keeps_macro_out_of_the_sector_hits():
    tlt = _bars("TLT", [100.0] * (len(SESSIONS) - 5) + [90.0] * 5)
    doc = _doc(_flat("SPY") + tlt)
    assert doc["groups"]["rates"]["rs5"] == pytest.approx(-10.0, abs=0.01)
    assert sp.sector_hits(doc) == []                                  # default kinds are sector + theme
    assert [h["group"] for h in sp.sector_hits(doc, kinds=("macro",))] == ["rates"]


def test_merge_keeps_the_mre_hit_for_a_group_both_sources_name():
    """The detector merges the two sources: MRE first (it carries the state), a shared group is named once."""
    mre = [{"group": "tech", "rs5": -6.1}, {"group": "staples", "rs5": -5.2}]
    bars = [{"group": "tech", "proxy": "XLK", "rs5": -5.5, "source": "reference_bars"},
            {"group": "energy", "proxy": "XLE", "rs5": -7.0, "source": "reference_bars"}]
    merged = sp.merge_sector_hits(mre, bars)
    assert [h["group"] for h in merged] == ["tech", "staples", "energy"]
    assert merged[0] == {"group": "tech", "rs5": -6.1}      # MRE's hit, not the bar hit
    assert merged[2]["source"] == "reference_bars"
    assert sp.merge_sector_hits([], []) == []


def test_the_hit_shape_joins_the_detectors_existing_sector_hits():
    """scripts/market_event_detect.py builds ``{"group": key, "rs5": rel}``; a hit from either source must join."""
    xlk = _bars("XLK", [100.0] * (len(SESSIONS) - 5) + [94.0] * 5)
    hit = sp.sector_hits(_doc(_flat("SPY") + xlk))[0]
    assert {"group", "rs5"} <= set(hit)
    assert isinstance(hit["group"], str) and isinstance(hit["rs5"], float)


# ------------------------------------------------------------------------------------------ policy + config map
def test_the_policy_block_wins_over_the_config_file(tmp_path):
    alt = tmp_path / "symbols.json"
    alt.write_text(json.dumps({"schema": "MarketReferenceSymbols@v1", "symbols": ["ZZZ"],
                               "proxy_groups": {"groups": {"zzz": {"proxy": "ZZZ"}}}}))
    policy = {"detector": {"sector_proxies": {"benchmark": "SPY",
                                              "groups": {"energy": {"label": "E", "proxy": "XLE", "kind": "sector"}}}}}
    proxies = sp.load_proxy_groups(policy, alt)
    assert proxies["origin"] == "policy:detector.sector_proxies"
    assert proxies["groups"] == {"energy": {"label": "E", "proxy": "XLE", "kind": "sector"}}


def test_an_empty_policy_block_falls_back_to_the_config_and_says_so(tmp_path):
    doc = {"schema": "MarketReferenceSymbols@v1", "symbols": ["SPY", "XLK"],
           "proxy_groups": {"groups": {"tech": {"label": "Technology", "proxy": "xlk", "kind": "sector"}}}}
    p = tmp_path / "symbols.json"
    p.write_text(json.dumps(doc))
    proxies = sp.load_proxy_groups({"detector": {"sector_proxies": {"groups": {}}}}, p)
    assert proxies["origin"].endswith("proxy_groups")
    assert proxies["groups"]["tech"]["proxy"] == "XLK"  # upper-cased on load


def test_an_unreadable_or_wrong_schema_map_is_named_not_silently_empty(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "Other@v1", "symbols": []}))
    proxies = sp.load_proxy_groups({}, bad)
    assert proxies["groups"] == {} and "wrong schema" in proxies["origin"]
    missing = sp.load_proxy_groups({}, tmp_path / "nope.json")
    assert missing["groups"] == {} and "unreadable" in missing["origin"]


# ------------------------------------------------------------------------------------------ DB reader
class _Cur:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self.cur = _Cur(rows)

    def cursor(self, **_kw):
        return self.cur


def test_read_moves_queries_the_proxies_read_only_and_attaches_hits_and_origin():
    # psycopg2 returns tuples: (symbol, bar_time::date, close, source)
    conn = _Conn([("SPY", d, 100.0, "alpaca") for d in SESSIONS]
                 + [("XLK", d, 100.0 if i < len(SESSIONS) - 5 else 94.0, "alpaca")
                    for i, d in enumerate(SESSIONS)])
    doc = sp.read_moves(conn, {"detector": {"open": {"sector_rel_move_pct": 5.0, "sector_rel_field": "rs5",
                                                     "sector_group_kinds": ["sector", "theme"]}}})
    sql, params = conn.cur.calls[0]
    assert sql.lstrip().upper().startswith("SELECT") and "market_ohlcv_bars" in sql
    assert "timeframe = 'daily'" in sql
    syms = params[0]
    assert "XLK" in syms and "SPY" in syms and "IBIT" in syms  # every proxy, plus the benchmark
    assert doc["schema"] == sp.SCHEMA
    assert doc["origin"].endswith("proxy_groups")
    assert [h["group"] for h in doc["hits"]] == ["tech"]
    assert doc["groups"]["energy"]["proxy"] == "XLE"


def test_read_closes_takes_the_column_shape_the_loader_writes():
    conn = _Conn([("XLK", "2026-11-06", 123.45, "alpaca")])
    rows = sp.read_closes(conn, ["xlk", "XLK", ""], end=__import__("datetime").date(2026, 11, 7))
    assert rows == [{"symbol": "XLK", "session": "2026-11-06", "close": 123.45, "source": "alpaca"}]
    assert conn.cur.calls[0][1][0] == ["XLK"]  # de-duplicated and upper-cased
