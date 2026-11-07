"""LQ-20261107-189 — the Hermes watchlist rank must order the whole list, never just the batch.

DB retest 2026-11-07 12:20 ET (lane hermes-watchlist-scorer):

  11-07 10h (an event-tier rescore of 454 names) — corr(hermes_rank, hermes_composite_score) -0.025,
  hermes_rank up to 4013 on a ~1,044-item list, 39 scored rows with a NULL rank; the 12:00 full run
  read -0.949. The scorer ranked the rows of the batch it had just scored (enumerate 1..N) and left every
  other row holding the rank of an older, larger list. Off-hours it froze `hermes_rank` altogether, so a
  rescored name kept the rank of its previous score.

The contract these tests pin:

  1. after ANY rescore the rank of a name is its position in the whole scoreable list, not in the batch;
  2. a row that carries a score never carries a NULL rank (a stale NULL is repaired by the next run);
  3. the universe is validated symbols only — symbol_profiles, or a portfolio holding the profile sync has
     not caught up with (symbol_validation.gate_watchlist_symbol). The English words OVER / WITH / PICKS
     that the event queue carried in are scored no longer;
  4. the history row records the rank the list actually holds (selected from watchlist_items after the
     rerank, never an in-batch counter);
  5. the price R/R and the history row carry is a MARK, not `wi.price`: the Finviz cache when fresh, else the
     newest market_quotes / ticker_prices row (operator price rule 2026-11-07), and a stale mark is written as
     NULL rather than as if it were a live quote (read-only 11-07: OPLN 39.935 as the watchlist copy against a
     34.35 quote, +16.3%).

Hermetic: fake connection, fake inputs. No DB, no network.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_watchlist_scorer as hws  # noqa: E402

_COLS = ["symbol", "rsi", "trend", "score", "watch_score_kind", "price", "realized_outcome", "thesis_win",
         "target_price", "stop_loss", "hermes_research_score", "options_edge_score", "thesis_outcome_n",
         "options_edge_n", "hermes_research_n", "social_score", "social_sentiment", "rvol", "confluence_score",
         "catalyst", "catalyst_verified", "sector"]


SCORES = {"AAA": 80.0, "BBB": 70.0, "CCC": 90.0, "DDD": 60.0, "EEE": 55.0}


def _row(sym, price="10", **kw):
    base = dict.fromkeys(_COLS)
    base.update(symbol=sym, rsi=55, trend="bullish", score=60, price=Decimal(price))
    base.update(kw)
    return tuple(base[c] for c in _COLS)


class _Cur:
    """Answers the scorer's reads the way the live DB would for a small list."""

    def __init__(self, conn):
        self.conn = conn
        self._one = None
        self._all = []
        self.description = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.conn.sql.append((s, params))
        self._one, self._all, self.description = None, [], None
        if "scope_tier IS NOT NULL" in s:
            self._one = (1,)                                  # the governed (tier) universe
        elif "MAX(wi.hermes_composite_score) AS score" in s:   # the global ranking input
            self._all = list(self.conn.universe)
        elif "MIN(wi.hermes_rank) AS rank" in s:               # the ranks the list holds now
            self._all = list(self.conn.ranks)
        elif s.startswith("SELECT wi.symbol"):
            self.description = [(c,) for c in _COLS]
            self._all = [r for r in self.conn.rows if r[0] in self.conn.validated]
        elif "FROM market_quotes" in s:                        # the mark: newest quote per symbol
            self._all = list(self.conn.quotes)
        elif "FROM ticker_prices" in s:
            self._all = list(self.conn.closes)
        elif "FROM hermes_score_history" in s:
            self._all = []
        head = s.split(" ", 1)[0].upper()
        if head in ("INSERT", "UPDATE", "DELETE") or head == "WITH":
            if self.conn.readonly:
                raise AssertionError(f"write in read-only session: {s[:60]}")
            texts = [x for x in (params or ()) if isinstance(x, str)]
            if self.conn.fail_write_for in texts or (
                    "hermes_rank=%s" in s and self.conn.fail_rank_for in texts):
                raise RuntimeError("boom write")
            self.conn.writes.append((s, params))

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def close(self):
        pass


class _Conn:
    def __init__(self, rows, *, universe, ranks, validated, quotes=(), closes=()):
        self.rows = rows
        self.universe = universe        # [(symbol, stored composite)] — already symbol_profiles-validated
        self.ranks = ranks              # [(symbol, stored hermes_rank)]
        self.validated = validated      # symbols the DB would call scoreable
        self.quotes = list(quotes)      # [(symbol, price, fetched_at)] from market_quotes
        self.closes = list(closes)      # [(symbol, price, price_date)] from ticker_prices
        self.sql, self.writes = [], []
        self.readonly = False
        self.fail_write_for = None      # a symbol whose every write raises
        self.fail_rank_for = None       # a symbol whose hermes_rank UPDATE raises
        self.commits = 0

    def cursor(self, *a, **k):
        return _Cur(self)

    def set_session(self, readonly=False, **k):
        self.readonly = readonly

    def rollback(self):
        pass

    def commit(self):
        self.commits += 1

    def rank_writes(self):
        out = {}
        for s, params in self.writes:
            if s.startswith("UPDATE watchlist_items") and "hermes_rank=%s" in s and params:
                out[params[1]] = params[0]
        return out


@pytest.fixture
def env(monkeypatch):
    import lib
    monkeypatch.setattr(lib, "assert_single_import_identity", lambda: None)
    monkeypatch.setattr(hws, "is_off_hours_et", lambda: True)      # the 10:15 ET run: off-hours
    monkeypatch.setattr(hws, "scoring_top_n", lambda limit=None: None)
    monkeypatch.setattr(hws, "_pills_map", lambda: {})
    monkeypatch.setattr(hws, "_sector_momentum", lambda conn: {})
    monkeypatch.setattr(hws, "_vix", lambda conn: 20.0)
    monkeypatch.setattr(hws, "_weights", lambda: {"technical_momentum": .3, "setup_quality": .3, "risk_reward": .4})
    # the score of a row is the fixture's, so the order under test is the fixture's (not the weighted average)
    monkeypatch.setattr(hws, "_score_row", lambda r, *a, **k: (SCORES[r["symbol"]], {"technical_momentum": 1.0}))
    monkeypatch.setattr(hws, "_tier_plan", lambda now_et=None: ["S0"])
    monkeypatch.setattr(hws, "_pending_event_symbols", lambda cur: ["CCC", "DDD"])
    # no Finviz cache in hermetically-run tests: resolve_mark then uses the market_quotes row the fake returns
    import lib.portfolio_positions as pp
    monkeypatch.setattr(pp, "finviz_cache", lambda *a, **k: {})

    def use(conn):
        monkeypatch.setattr(hws, "_conn", lambda: conn)
        return conn
    return use


def test_a_partial_batch_ranks_against_the_whole_list(env):
    """CCC and DDD are rescored; AAA and BBB are not. Their rank is their position among all four."""
    conn = _Conn([_row("CCC"), _row("DDD")],
                 universe=[("AAA", 80.0), ("BBB", 70.0)],
                 ranks=[("AAA", 2), ("BBB", 3)],
                 validated={"AAA", "BBB", "CCC", "DDD"})
    env(conn)
    out = hws.run()
    assert out["scored"] == 2
    ranks = conn.rank_writes()
    assert ranks["CCC"] == 1 and ranks["DDD"] == 4, ranks


def test_a_scored_row_never_keeps_a_null_rank(env):
    """EEE carries a score from an older run and a NULL rank; the rerank assigns it its position."""
    conn = _Conn([_row("CCC")],
                 universe=[("AAA", 80.0), ("EEE", 55.0)],
                 ranks=[("AAA", 1), ("EEE", None)],
                 validated={"AAA", "EEE", "CCC"})
    env(conn)
    hws.run()
    ranks = conn.rank_writes()
    assert ranks["CCC"] == 1 and ranks["EEE"] == 3, ranks


def test_a_rank_that_no_longer_orders_anything_is_cleared(env):
    """OVER left the validated universe: it must not keep a rank pointing into the old 4,013-item list."""
    conn = _Conn([_row("CCC")],
                 universe=[("AAA", 80.0)],
                 ranks=[("AAA", 1), ("OVER", 660)],
                 validated={"AAA", "CCC"})
    env(conn)
    hws.run()
    cleared = [p for s, p in conn.writes
               if s.startswith("UPDATE watchlist_items") and "hermes_rank=%s" in s and p and p[0] is None]
    assert [p[1] for p in cleared] == ["OVER"], conn.writes


def test_the_universe_read_asks_the_database_for_validated_symbols_only(env):
    """The filter is in SQL (symbol_profiles, or a holding), so the words never reach score_symbol."""
    conn = _Conn([_row("CCC")],
                 universe=[("AAA", 80.0)],
                 ranks=[("AAA", 1)],
                 validated={"AAA", "CCC"})
    env(conn)
    hws.run()
    fetch = next(s for s, _ in conn.sql if s.startswith("SELECT wi.symbol"))
    assert "symbol_profiles" in fetch and "= ANY(%s)" in fetch
    ranked = next((s, p) for s, p in conn.sql if "MAX(wi.hermes_composite_score) AS score" in s)
    assert "symbol_profiles" in ranked[0] and ranked[1] is not None


def test_history_records_the_rank_the_list_holds_and_is_written_after_the_rerank(env):
    """The history INSERT reads hermes_rank back from watchlist_items (never an in-batch counter), and it is
    written only after the rerank — otherwise it would record the rank of the previous list."""
    conn = _Conn([_row("CCC"), _row("DDD")],
                 universe=[("AAA", 80.0)],
                 ranks=[("AAA", 1)],
                 validated={"AAA", "CCC", "DDD"})
    env(conn)
    hws.run()
    inserts = [(s, p) for s, p in conn.writes if s.startswith("INSERT INTO hermes_score_history")]
    assert inserts and all("hermes_rank" in s and "FROM watchlist_items" in s for s, _ in inserts)
    idx = {}
    for i, (s, _p) in enumerate(conn.writes):
        if "hermes_rank=%s" in s:
            idx.setdefault("rank", i)
        elif s.startswith("INSERT INTO hermes_score_history"):
            idx.setdefault("hist", i)
    assert idx["rank"] < idx["hist"], conn.writes


def test_a_symbol_whose_score_write_failed_is_not_ranked(env):
    """ZZZ's composite write raises: it keeps its old rank; CCC's rank still lands (one bad row is isolated)."""
    conn = _Conn([_row("CCC"), _row("DDD")],
                 universe=[("AAA", 80.0)],
                 ranks=[("AAA", 1)],
                 validated={"AAA", "CCC", "DDD"})
    conn.fail_write_for = "DDD"
    env(conn)
    out = hws.run()
    assert out["errored"] == 1 and out["skipped_errors"] == {"write:RuntimeError": 1}, out
    ranks = conn.rank_writes()
    assert "DDD" not in ranks and ranks["CCC"] == 1, ranks


def test_an_unwritable_rank_does_not_roll_back_the_others(env):
    """AAA's rank UPDATE raises: the rerank records one failure and CCC's rank still lands."""
    conn = _Conn([_row("CCC")],
                 universe=[("AAA", 80.0)],
                 ranks=[("AAA", 3)],
                 validated={"AAA", "CCC"})
    conn.fail_rank_for = "AAA"
    env(conn)
    out = hws.run()
    assert out["skipped_errors"] == {"rerank:RuntimeError": 1}, out
    ranks = conn.rank_writes()
    assert ranks["CCC"] == 1 and "AAA" not in ranks, ranks


def test_the_history_price_is_the_mark_not_the_watchlist_copy(env):
    """The row's own `price` (39.935) is not a quote: the fresh market_quotes mark (34.35) is what gets written."""
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    conn = _Conn([_row("CCC", price="39.935")],
                 universe=[("AAA", 80.0)],
                 ranks=[("AAA", 1)],
                 validated={"AAA", "CCC"},
                 quotes=[("CCC", Decimal("34.35"), now)])
    env(conn)
    hws.run()
    hist = [p for s, p in conn.writes if s.startswith("INSERT INTO hermes_score_history")]
    assert hist and float(hist[0][3]) == 34.35, hist


def test_a_stale_mark_is_not_written_as_a_live_price(env):
    """A quote 3 h old is stale (operator rule: 30 min): history gets NULL, never the old number as a quote."""
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    conn = _Conn([_row("CCC", price="39.935")],
                 universe=[("AAA", 80.0)],
                 ranks=[("AAA", 1)],
                 validated={"AAA", "CCC"},
                 quotes=[("CCC", Decimal("34.35"), old)])
    env(conn)
    hws.run()
    hist = [p for s, p in conn.writes if s.startswith("INSERT INTO hermes_score_history")]
    assert hist and hist[0][3] is None, hist


def test_an_event_symbol_outside_the_universe_is_reported_and_drained(env, monkeypatch):
    conn = _Conn([_row("CCC")],
                 universe=[("AAA", 80.0)],
                 ranks=[("AAA", 1)],
                 validated={"AAA", "CCC"})
    monkeypatch.setattr(hws, "_pending_event_symbols", lambda cur: ["CCC", "OVER"])
    env(conn)
    out = hws.run()
    assert out["items"] == 1 and out["scored"] == 1
    assert out["excluded"] == {"not_validated_symbol": 1} and out["excluded_symbols"] == ["OVER"]
    drain = [p for s, p in conn.writes if s.startswith("UPDATE hermes_score_event_queue")]
    assert drain and sorted(drain[0][0]) == ["CCC", "OVER"]  # the junk slot is freed, never wedged
