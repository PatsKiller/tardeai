"""LQ-20261107-2216: the Home v007 exact-observation quote join must be index-usable.

Synthetic symbols only; no database, network or subprocess.
ANCHOR: PAGE_LATENCY_LQ2216_20261112

Before: ``WHERE source = %s AND (upper(symbol), fetched_at) IN (unnest ...)`` gave Postgres no predicate on the
bare ``symbol`` column, so idx_market_quotes_symbol_fetched_at_desc could not be used and every call to
/api/v2/market-risk/latest (and a cold /api/v2/home/cio-card) sequentially scanned all of market_quotes.
After: an added ``symbol = ANY(%s::text[])`` prefilter on the bare column, with the exact pair predicate unchanged.
"""

from datetime import datetime, timedelta, timezone
import importlib.util
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = Path(os.environ.get("LQ2216_HOME_V007_MODULE", str(ROOT / "scripts/lib/market_risk_home_context.py")))
NOW = datetime(2032, 3, 9, 21, 0, tzinfo=timezone.utc)
ASOF = "2032-03-09T20:59:00Z"
OTHER = "2032-03-09T20:58:00Z"


@pytest.fixture
def mod(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real external process or network forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    spec = importlib.util.spec_from_file_location("home_v007_lq2216_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def projection(symbols):
    return {"as_of": ASOF, "score": 50, "tier": "YELLOW", "categories": [], "positions": {}, "history": [],
            "reentry_watch": {s: {"exit_date": "2032-03-01", "exit_price": 10, "as_of": ASOF, "stance": "WATCH",
                                  "headline": "synthetic", "stages": {}} for s in symbols}}


class Reader:
    def __init__(self, symbols):
        self.symbols = symbols

    def regular_session_quotes(self, symbols, *, end):
        return {s: {"schema": "ReentryRegularQuote@v1", "status": "available", "price": 12,
                    "source": "market_quotes:alpaca", "session": "regular", "session_date": "2032-03-09",
                    "as_of": ASOF} for s in self.symbols}

    def extended_quotes(self, symbols, *, start, end):
        return []

    def daily_bars(self, symbols, *, sessions, end):
        return [{"symbol": s, "date": (NOW.date() - timedelta(days=i + 1)).isoformat(), "volume": 100, "close": 11,
                 "source": "synthetic_daily"} for s in self.symbols for i in range(20)]


# Stored market_quotes rows, as Postgres would hold them (one deliberately lower-case spelling).
STORED = [
    {"source": "alpaca", "symbol": "SYNA", "price": 12, "prev_close": 11, "volume": 300, "fetched_at": ASOF},
    {"source": "alpaca", "symbol": "synb", "price": 12, "prev_close": 10, "volume": 400, "fetched_at": ASOF},
    {"source": "alpaca", "symbol": "SYNA", "price": 99, "prev_close": 98, "volume": 999, "fetched_at": OTHER},
    {"source": "finviz", "symbol": "SYNA", "price": 77, "prev_close": 76, "volume": 777, "fetched_at": ASOF},
]


def _exact_join_query(captured):
    hits = [(sql, params) for sql, params in captured if "FROM market_quotes" in sql and "unnest(" in sql]
    assert len(hits) == 1, captured
    return hits[0]


def _evaluate(sql, params):
    """Evaluate the exact-observation query over STORED the way Postgres would, from its own predicates."""
    params = list(params)
    source = params.pop(0)
    prefilter = None
    if re.search(r"\bsymbol\s*=\s*ANY\(%s", sql):
        prefilter = set(params.pop(0))
    pairs = set(zip(params[0], params[1]))
    out = []
    for row in STORED:
        if row["source"] != source:
            continue
        if prefilter is not None and row["symbol"] not in prefilter:
            continue
        if (row["symbol"].upper(), row["fetched_at"]) not in pairs:
            continue
        out.append({**row, "symbol": row["symbol"].upper()})
    return out[:80]


def _run(mod, symbols):
    captured = []

    def read(sql, params):
        captured.append((sql, params))
        if "FROM market_quotes" in sql and "unnest(" in sql:
            return _evaluate(sql, params)
        return []

    result = mod.collect(projection(symbols), {}, reader=Reader(symbols), read_rows=read, now=NOW)
    return result, captured


def test_exact_observation_query_has_an_index_usable_predicate_on_bare_symbol(mod):
    """Fails before LQ-2216: the only symbol predicate was ``upper(symbol)``, which the btree index cannot serve."""
    _, captured = _run(mod, ["SYNA"])
    sql, params = _exact_join_query(captured)
    where = sql.split("WHERE", 1)[1]
    bare = re.search(r"(?<![\w(])symbol\s*=\s*ANY\(%s::text\[\]\)", where)
    assert bare, f"no index-usable predicate on bare symbol: {where}"
    assert "(upper(symbol), fetched_at) IN" in where, "the exact pair predicate must stay"
    assert sql.count("%s") == len(params)


def test_prefilter_carries_both_spellings_so_lower_case_stored_rows_still_join(mod):
    _, captured = _run(mod, ["SYNA", "SYNB"])
    _, params = _exact_join_query(captured)
    spellings = params[1]
    assert {"SYNA", "syna", "SYNB", "synb"} <= set(spellings)


def test_join_result_unchanged_including_lower_case_row_and_other_instant_and_source(mod):
    """Pass before and after: the same rows join. Volume comes only from the alpaca row at the exact instant."""
    result, _ = _run(mod, ["SYNA", "SYNB"])
    assert result["read_errors"] == []
    a = result["symbols"]["SYNA"]
    b = result["symbols"]["SYNB"]
    assert a["quote"]["value"] == 12 and b["quote"]["value"] == 12
    assert a["volume_vs_20d"]["value"]["ratio"] == 3      # 300 / 100, never the 20:58 (999) or finviz (777) row
    assert b["volume_vs_20d"]["value"]["ratio"] == 4      # the lower-case stored row still joins
