"""ANCHOR: RESEARCH_INSIGHT_SYMBOLS_20261107. LQ-20261107-124 — research-insight-extractor wrote topic codes
as symbols, left ``source_id`` NULL on every row, and stored the extractor's neutral default as an observation.

Live observations from the 2026-11-07 audit (read-only), pinned here so they cannot come back:

* 67 of the last 198 rows carried a non-ticker ``symbol`` — ``D194_CLOSED_END_FUNDS_CEFS_LIKE_PTY_PREMIUM_A``
  (x22 on Medicare/IRMAA articles), ``K_SSDI_...``, ``SU_INDUSTRY_OIL_GAS_REFINING_MARKETING`` — because the
  source row's own ``symbol`` column holds a **topic code** (``news_articles.symbol`` is lowercase
  ``d194_closed_end_funds_...`` on 25,964 of 134,039 rows) and the extractor uppercased it straight into the
  insight. 5,197 of 52,520 rows carry such a value.
* ``source_id`` was NULL on all 52,520 rows although ``source_reference`` was populated and
  ``research_sources`` has 2,712 rows (an exact URL-host match resolves 34,778 of 134,004 news rows).
* 47,388 rows (90%) were ``neutral`` at confidence 0.5 — the default when no keyword fires, not an observation.

Hermetic: a fake cursor/connection, synthetic rows, no database, no network.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("TRADE_AI_CI", "1")

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    name = "lq124_research_insight_extractor"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "research_insight_extractor.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── a fake connection that answers exactly the queries this lane issues ──────────────────────────────────────

class _Cur:
    def __init__(self, *, known=(), universe=(), strategy=None, source_ids=None):
        self.known = set(known)
        self.universe = set(universe)
        self.strategy = strategy
        self.source_ids = source_ids            # host -> id, or None
        self.sql = ""
        self.seen: list[str] = []
        self.insert_params: tuple | None = None

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())
        self._params = params
        self.seen.append(self.sql[:40])
        if self.sql.startswith("INSERT INTO research_insights"):
            self.insert_params = params

    def fetchall(self):
        if self.sql.startswith("SELECT upper(symbol) AS s"):
            return [{"s": s} for s in self.universe]
        if self.sql.startswith("SELECT symbol FROM ticker_strategy_classifications"):
            return [{"symbol": s} for s in self.known]
        return []

    def fetchone(self):
        if self.sql.startswith("SELECT strategy_type"):
            return {"strategy_type": self.strategy} if self.strategy else None
        if self.sql.startswith("SELECT id FROM research_sources"):
            host = self.source_ids if isinstance(self.source_ids, dict) else {}
            return {"id": host[self._params[0]]} if self._params[0] in host else None
        if self.sql.startswith("INSERT INTO research_insights"):
            return {"id": 42}
        return None


class _Conn:
    def __init__(self, cur):
        self._cur = cur
        self.commits = 0
        self.closed = False

    def cursor(self, **_kw):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def _conn(monkeypatch, mod, **kw):
    cur = _Cur(**kw)
    conn = _Conn(cur)
    monkeypatch.setattr(mod, "_get_conn", lambda dry_run=False: conn)
    return cur, conn


# ── symbol validation ───────────────────────────────────────────────────────────────────────────────────────

def test_a_topic_code_is_never_a_symbol():
    mod = _load()
    universe = {"AIG", "AAOI", "DGRO"}
    assert mod.validate_symbol("D194_CLOSED_END_FUNDS_CEFS_LIKE_PTY_PREMIUM_A", universe) is None
    assert mod.validate_symbol("k_medicaid_application_planning", universe) is None
    # ticker-shaped but not an instrument: a Medicare acronym must not become a symbol either
    assert mod.validate_symbol("IRMAA", universe) is None


def test_a_known_instrument_is_a_symbol_whatever_its_source_case():
    mod = _load()
    universe = {"AIG", "AAOI"}
    assert mod.validate_symbol("aig", universe) == "AIG"
    assert mod.validate_symbol(" AAOI ", universe) == "AAOI"
    assert mod.validate_symbol(None, universe) is None
    assert mod.validate_symbol("", universe) is None


def test_the_universe_is_the_two_durable_symbol_catalogues():
    mod = _load()
    cur = _Cur(universe={"AIG", "NVDA"})
    assert mod.symbol_universe(cur) == {"AIG", "NVDA"}
    assert "ticker_strategy_classifications" in cur.sql and "watchlist_symbol_master" in cur.sql


# ── source attribution ─────────────────────────────────────────────────────────────────────────────────────

def test_source_id_comes_from_the_articles_own_host():
    mod = _load()
    cur = _Cur(source_ids={"finance.yahoo.com": 1})
    assert mod.source_id_for_url(cur, "https://www.finance.yahoo.com/news/x") == 1


def test_an_unregistered_host_stays_null_rather_than_being_guessed():
    mod = _load()
    cur = _Cur(source_ids={"finance.yahoo.com": 1})
    assert mod.source_id_for_url(cur, "https://unknown-publisher.example/a") is None
    assert mod.source_id_for_url(cur, "") is None
    assert mod.source_id_for_url(cur, None) is None


def test_the_host_lookup_is_cached_per_run():
    mod = _load()
    cur = _Cur(source_ids={"finance.yahoo.com": 1})
    cache: dict = {}
    assert mod.source_id_for_url(cur, "https://finance.yahoo.com/a", cache) == 1
    n = len(cur.seen)
    assert mod.source_id_for_url(cur, "https://finance.yahoo.com/b", cache) == 1
    assert len(cur.seen) == n                      # second row, same host: no query


# ── the neutral default is not an insight ───────────────────────────────────────────────────────────────────

def test_the_neutral_default_has_no_signal():
    mod = _load()
    assert mod.has_signal({"thesis_type": "neutral", "price_target": None, "yield_thesis": None}) is False
    assert mod.has_signal({"thesis_type": "bullish", "price_target": None, "yield_thesis": None}) is True
    assert mod.has_signal({"thesis_type": "neutral", "price_target": 120.0, "yield_thesis": None}) is True
    assert mod.has_signal({"thesis_type": "neutral", "price_target": None, "yield_thesis": "2 income signals"}) is True


# ── end to end through one extraction ───────────────────────────────────────────────────────────────────────

def test_a_topic_code_from_the_source_row_is_not_written_as_a_symbol(monkeypatch):
    mod = _load()
    cur, conn = _conn(monkeypatch, mod, known={"AIG"}, universe={"AIG", "AAOI"},
                      source_ids={"finance.yahoo.com": 1})
    r = mod.extract_insight("Medicare and IRMAA planning for retirees.", symbol="d194_closed_end_funds",
                            source_type="news", source_reference="news:1",
                            source_url="https://finance.yahoo.com/a")
    # LQ-20261107-1081: a topic-slug row is skipped. It is not stored with a null symbol.
    assert r.get("skipped") == "topic_slug"
    assert r["symbol"] is None and r["supporting_entities"] == []
    assert r["source_symbol_not_ticker"] is True
    assert cur.insert_params is None
    assert conn.commits == 0


def test_a_held_or_watched_source_symbol_is_kept_and_the_row_carries_source_id_and_active(monkeypatch):
    mod = _load()
    cur, conn = _conn(monkeypatch, mod, known={"AAOI"}, universe={"AAOI"}, strategy="growth",
                      source_ids={"finance.yahoo.com": 1})
    session = {
        "conn": conn, "cur": cur, "known": {"AAOI"}, "universe": {"AAOI"},
        "held_watch": {"AAOI"}, "names_by_symbol": {}, "source_ids": {},
    }
    r = mod.extract_insight("AAOI upgrade: strong growth and a contract win.", symbol="aaoi",
                            source_type="catalyst", source_reference="catalyst:1",
                            source_url="https://finance.yahoo.com/a", session=session)
    assert r["symbol"] == "AAOI" and r["strategy_type"] == "growth"
    assert r["active"] is True
    params = cur.insert_params
    assert params[0] == "AAOI"
    assert params[2] == 1                          # source_id
    assert params[19] is True                      # active


def test_a_signal_less_row_is_written_inactive(monkeypatch):
    mod = _load()
    cur, conn = _conn(monkeypatch, mod, known=(), universe={"AIG"})
    session = {
        "conn": conn, "cur": cur, "known": set(), "universe": {"AIG"},
        "held_watch": {"AIG"}, "names_by_symbol": {}, "source_ids": {},
    }
    r = mod.extract_insight("The company filed its quarterly paperwork with the regulator today.",
                            symbol="AIG", source_type="news", source_reference="news:2", session=session)
    assert r["symbol"] == "AIG"
    assert r["active"] is False
    assert cur.insert_params[19] is False          # stored, but no consumer reads it as research


def test_a_dry_run_writes_nothing(monkeypatch):
    mod = _load()
    cur, conn = _conn(monkeypatch, mod, known=(), universe={"AIG"})
    r = mod.extract_insight("AAOI upgrade: strong growth.", symbol="AAOI", dry_run=True)
    assert r["id"] is None and cur.insert_params is None
    assert not any(s.startswith("INSERT") for s in cur.seen) and conn.closed


# ── the receipt reports what was skipped, not just what was written ─────────────────────────────────────────

def test_lane_output_counts_only_signal_rows_as_produced():
    mod = _load()
    out = mod.lane_output([{"id": 1, "active": False}, {"id": 2, "active": False}],
                          failed=0, skips={"no_signal": 2}, dry_run=False)
    assert out["produced_count"] == 0 and out["attempted_count"] == 2
    assert out["empty_reason"] == "no_signal"
    assert out["skipped_reasons"] == {"no_signal": 2}


def test_lane_output_counts_a_signal_row_and_keeps_the_run_green():
    mod = _load()
    out = mod.lane_output([{"id": 1, "active": True}, {"id": 2, "active": False}],
                          failed=0, skips={"no_signal": 1}, dry_run=False)
    assert out["produced_count"] == 1 and out["empty_reason"] is None


def test_no_candidates_is_still_no_new_input():
    mod = _load()
    out = mod.lane_output([], failed=0, skips={"text_too_short": 2}, dry_run=False)
    assert out["produced_count"] == 0 and out["attempted_count"] == 0
    assert out["empty_reason"] == "no_new_input"
