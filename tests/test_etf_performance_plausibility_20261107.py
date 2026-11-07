"""ANCHOR: ETF_PERFORMANCE_PLAUSIBILITY_20261107 — an implausible return is not a return.

LQ-20261107-184. ``etf-performance-enrich`` wrote YTD performance and dividend yield from yfinance onto
``symbol_profiles`` and the watchlist API served them unchanged. Measured on the live DB 2026-11-07:

    instrument_type IN ('etf','fund','inverse_etf')                            439 rows
    abs(ytd_return_pct) > 150                                                    4  DVIN 1649.37,
                                                                                    CRED 1424.59,
                                                                                    DVAL 894.82,
                                                                                    DLLL 542.77
    dividend_yield_pct > 25                                                     10  UNWPX 95.02,
                                                                                    MTYY 89.13, PLYY 55.46,
                                                                                    QBTX 49.66, SMCZ 39.41,
                                                                                    MARO 39.38, AMDY 38.35,
                                                                                    CRWU 34.56, CRWG 31.45,
                                                                                    CRSH 28.36
    symbols refreshed by one run                                        300 of 439

None of those is a return a reader can use — they are split/adjustment artefacts — and the same numbers
reproduce from Finviz, so this is not fetch noise: the writer never asked whether the number was possible.
Three rules, pinned here:

  1. a value outside its bound is **never written** (``rejected_implausible``), and a stored value that is
     outside its bound is **cleared** to NULL when no plausible replacement arrives — "unknown" is honest,
     +1424% is not. A plausible stored value is never cleared for want of a fresh source.
  2. the source is the shared Finviz enrichment cache (``data/state/ticker_enrichment_cache.json``,
     ``perf_ytd_pct`` / ``div_yield_pct``); the operator price rule forbids yfinance.
  3. every target is visited each run: the 300-symbol cap was a politeness bound for a network loop that no
     longer exists, and it left 139 of 439 rows refreshed only every other week.

Hermetic: a cache dict and a standing of stored values are passed in; no database, network or file.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from etf_performance_enrich import (  # noqa: E402
    PERF_BOUNDS,
    SYMBOL_CAP,
    cache_entry,
    enrich,
    perf_payload,
)

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)


def entry(ytd=None, dy=None, *, days_old=0):
    return {"perf_ytd_pct": ytd, "div_yield_pct": dy,
            "cached_at": (NOW - timedelta(days=days_old)).isoformat()}


# ── 1. the plausibility filter ──────────────────────────────────────────────────────────────────────────

def test_an_implausible_finviz_ytd_is_never_written_and_the_served_value_is_cleared():
    """CRED: Finviz and the DB agree on 1424.59 — the number is impossible, so it is neither written nor kept."""
    fields, notes = perf_payload(entry(ytd=1424.59), {"ytd_return_pct": 1424.59, "dividend_yield_pct": None})
    assert fields["ytd_return_pct"] is None          # cleared, not left at +1424%
    assert notes["ytd_return_pct"].startswith("rejected_implausible")


def test_an_implausible_stored_value_is_cleared_when_the_source_has_nothing():
    """A row that already serves junk is cleared even if today's fetch returns no YTD at all."""
    fields, notes = perf_payload({"perf_ytd_pct": None, "div_yield_pct": None},
                                 {"ytd_return_pct": 1649.37, "dividend_yield_pct": 1.0})
    assert fields == {"ytd_return_pct": None}
    assert notes["ytd_return_pct"].startswith("cleared_implausible")


def test_an_implausible_yield_is_cleared_too():
    fields, _notes = perf_payload(entry(dy=95.02), {"ytd_return_pct": None, "dividend_yield_pct": 95.02})
    assert fields == {"dividend_yield_pct": None}


def test_a_plausible_value_replaces_the_stored_one():
    fields, notes = perf_payload(entry(ytd=28.22, dy=2.99),
                                 {"ytd_return_pct": 12.0, "dividend_yield_pct": 1.0})
    assert fields == {"ytd_return_pct": 28.22, "dividend_yield_pct": 2.99}
    assert notes == {}


def test_a_plausible_stored_value_is_never_cleared_for_want_of_a_source():
    """32 of 439 targets have no cache entry; their usable stored numbers must survive."""
    fields, notes = perf_payload(None, {"ytd_return_pct": 12.0, "dividend_yield_pct": 1.5})
    assert fields == {}
    assert notes["ytd_return_pct"] == "no_source_value"


def test_the_bound_is_inclusive_and_the_reason_names_the_value():
    assert PERF_BOUNDS["ytd_return_pct"] == 150.0 and PERF_BOUNDS["dividend_yield_pct"] == 25.0
    ok, _ = perf_payload(entry(ytd=150.0, dy=25.0), {})
    assert ok == {"ytd_return_pct": 150.0, "dividend_yield_pct": 25.0}
    bad, notes = perf_payload(entry(ytd=150.01, dy=25.01), {})
    assert bad == {}
    assert "150.01" in notes["ytd_return_pct"] and "25.01" in notes["dividend_yield_pct"]


def test_a_negative_implausible_ytd_is_caught():
    fields, _ = perf_payload(entry(ytd=-412.5), {})
    assert fields == {}


def test_nan_and_inf_are_unknown_not_implausible():
    """NaN is missing data (NaN is already refused at the writer); it must not clear a good stored value."""
    for junk in (float("nan"), float("inf"), "n/a"):
        fields, notes = perf_payload({"perf_ytd_pct": junk, "div_yield_pct": None},
                                     {"ytd_return_pct": 12.0, "dividend_yield_pct": None})
        assert fields == {}
        assert notes["ytd_return_pct"] == "no_source_value"


# ── 2. the source is the shared Finviz cache, and it has to be young enough to mean anything ───────────

def test_a_fresh_entry_is_used():
    got, why = cache_entry({"SPY": entry(ytd=7.78, days_old=1)}, "SPY", NOW)
    assert got["perf_ytd_pct"] == 7.78 and why is None


def test_a_missing_entry_is_named_not_guessed():
    got, why = cache_entry({}, "CRED", NOW)
    assert got is None and why == "no_source_value"


def test_an_entry_older_than_the_max_age_is_not_used():
    got, why = cache_entry({"X": entry(ytd=5.0, days_old=45)}, "X", NOW)
    assert got is None and why == "stale_source_value"


def test_an_entry_without_a_readable_timestamp_is_not_used():
    got, why = cache_entry({"X": {"perf_ytd_pct": 5.0}}, "X", NOW)
    assert got is None and why == "stale_source_value"


# ── 3. every target is visited; yfinance is gone ───────────────────────────────────────────────────────

def test_the_cap_is_a_runaway_guard_not_a_politeness_bound():
    """439 targets exist today; the old 300 left 139 refreshed only every other week."""
    assert SYMBOL_CAP >= 439


def test_every_target_reaches_the_writer(monkeypatch, tmp_path):
    syms = [f"E{i:03d}" for i in range(439)]
    cache = {s: entry(ytd=1.0, dy=1.0) for s in syms}
    written: list[str] = []

    class Receipt:
        rows_written, rows_rejected = 1, 0

    monkeypatch.setattr("etf_performance_enrich._get_conn", lambda: _Conn(syms))
    monkeypatch.setattr("etf_performance_enrich.finviz_cache", lambda _root=None: cache)
    monkeypatch.setattr("etf_performance_enrich.upsert_profile",
                        lambda cur, sym, fields, **kw: (written.append(sym), Receipt())[1])

    res = enrich()

    assert len(written) == 439 and res["attempted"] == 439 and res["updated"] == 439


def test_the_module_no_longer_fetches_from_yfinance():
    src = (ROOT / "scripts" / "etf_performance_enrich.py").read_text()
    assert "import yfinance" not in src and "yfinance as yf" not in src


# ── fixture: a connection whose two SELECTs answer targets then stored values ──────────────────────────

class _Store:
    def __init__(self, syms, stored=None):
        self.syms = syms
        self.stored = stored or {}


class _Cur:
    def __init__(self, store):
        self.store = store
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        if "ytd_return_pct" in self.sql:
            return [(s, self.store.stored.get(s, {}).get("ytd_return_pct"),
                     self.store.stored.get(s, {}).get("dividend_yield_pct")) for s in self.store.syms]
        return [(s,) for s in self.store.syms]

    def close(self):
        pass


class _Conn(_Store):
    def __init__(self, syms, stored=None):
        super().__init__(syms, stored)

    def cursor(self):
        return _Cur(self)

    def commit(self):
        pass

    def rollback(self):
        pass
