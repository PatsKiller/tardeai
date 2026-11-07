"""A proposal's outcome is its OWN trade, and every closed trade reaches the agent outcomes.

LQ-20261107-48, 2026-11-07. ``feedback_loop_processor`` matched a proposal to a trade with
``symbol = %s AND strategy_id = %s AND created_at >= proposal.created_at ORDER BY created_at
ASC LIMIT 1`` — the first same-symbol, same-strategy trade after the proposal, whoever it
belonged to. Live read-only evidence on 2026-11-07:

* 966 of the 1458 chains that named a trade named ANOTHER proposal's trade (checked against
  ``paper_trades.proposal_id``);
* 114 chains stayed ``linked`` while their proposal's own trade was closed, so they could
  never be fed; ``closed`` chains totalled 18 and the last one was 2026-06-10;
* 8 chains read ``closed`` for a trade that is now ``cancelled``/``dedup_removed`` — the
  chain was never re-checked after it was written;
* the candidate query was ``ORDER BY p.created_at DESC LIMIT 100``, so 1644 eligible
  proposals from June–August 2026 could never be reached: newer proposals always filled
  the window first;
* ``feed_outcomes_to_agents`` wrote ``round(pnl / 100, 2)`` as ``pnl_pct`` — an invented
  percentage (a -0.09 "pct" for a real -9%) — and stamped NOW() as both the recommendation
  and entry date.

Hermetic: scripted cursors, no DB, no network.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import feedback_loop_processor as flp   # noqa: E402


# ── fakes ────────────────────────────────────────────────────────────────────

def _norm(sql: str) -> str:
    return " ".join(str(sql).split())


class ScriptedCursor:
    """Answers SELECTs from a handler; records every statement and its params."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, object]] = []
        self._rows: list = []

    def execute(self, sql, params=None):
        sql = _norm(sql)
        self.calls.append((sql, params))
        self._rows = self.handler(sql, params) or []

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def writes(self, verb: str) -> list[tuple[str, object]]:
        return [c for c in self.calls if c[0].startswith(verb)]


class FakeConn:
    def __init__(self, handler):
        self.cur = ScriptedCursor(handler)
        self.commits = 0

    def cursor(self, *args, **kwargs):
        return self.cur

    def commit(self):
        self.commits += 1


def _chain_handler(revalued, proposals):
    """Only answer the two SELECTs of link_proposal_outcomes; writes return [].

    The new code never asks for a symbol/strategy lookalike trade: a test that scripts a
    lookalike has nothing to answer it, which is the point."""
    def handler(sql, params):
        if sql.startswith("SELECT 1 FROM information_schema.columns"):
            return []
        if "FROM paper_trade_proposals p" in sql or "FROM paper_trade_proposals p " in sql:
            return proposals
        if "FROM proposal_outcome_chain c" in sql and "LEFT JOIN paper_trades t" not in sql:
            return revalued
        return []
    return handler


# ── the state rule ──────────────────────────────────────────────────────────

def test_a_closed_own_trade_makes_the_chain_closed():
    assert flp._chain_state("APPROVED", "closed", True) == "closed"


def test_an_open_own_trade_makes_the_chain_linked():
    assert flp._chain_state("APPROVED", "cancelled", True) == "linked"


def test_a_rejected_proposal_without_a_trade_is_orphaned():
    assert flp._chain_state("REJECTED", None, False) == "orphaned"
    assert flp._chain_state("EXPIRED", None, False) == "orphaned"


def test_an_approved_proposal_without_a_trade_is_pending():
    assert flp._chain_state("APPROVED", None, False) == "pending"


def test_zero_pnl_is_neutral_not_wrong():
    """The old code: ``CORRECT if pnl > 0 else WRONG`` — a flat trade scored -1.0."""
    assert flp._verdict_for(0.0) == ("NEUTRAL", 0.0)
    assert flp._verdict_for(0) == ("NEUTRAL", 0.0)
    assert flp._verdict_for(4.2) == ("CORRECT", 1.0)
    assert flp._verdict_for(-4.2) == ("WRONG", -1.0)


# ── re-evaluation of chains already stored ──────────────────────────────────

def test_a_linked_chain_whose_own_trade_closed_is_revalued_to_closed():
    row = {"id": 77, "proposal_id": 500, "symbol": "NVDA", "strategy_id": "momo",
           "proposing_agent": "maria", "proposal_created": None,
           "proposal_status": "APPROVED", "paper_trade_id": 9, "trade_status": "cancelled",
           "trade_pnl": None, "trade_r_multiple": None, "chain_status": "linked",
           "outcome_fed_back": False, "trade_id": 42, "own_status": "closed",
           "pnl": 12.5, "pnl_pct": 6.25, "r_multiple": 1.4, "new_status": "closed"}
    conn = FakeConn(_chain_handler([row], []))
    assert flp.link_proposal_outcomes(conn, dry_run=False) == 1
    update, params = conn.cur.writes("UPDATE")[0]
    # paper_trade_id, trade_status, trade_pnl, trade_r_multiple, chain_status, fed_back, id
    assert params[0] == 42 and params[1] == "closed" and float(params[2]) == 12.5
    assert params[4] == "closed" and params[5] is False and params[6] == 77


def test_a_chain_that_stops_being_closed_stops_being_a_fed_outcome():
    row = {"id": 110, "proposal_id": 118, "symbol": "NVDA", "strategy_id": "s",
           "proposing_agent": "maria", "proposal_created": None,
           "proposal_status": "APPROVED", "paper_trade_id": 29, "trade_status": "closed",
           "trade_pnl": -4.9, "trade_r_multiple": None, "chain_status": "closed",
           "outcome_fed_back": True, "trade_id": 29, "own_status": "dedup_removed",
           "pnl": 0, "pnl_pct": 0, "r_multiple": None, "new_status": "linked"}
    conn = FakeConn(_chain_handler([row], []))
    flp.link_proposal_outcomes(conn, dry_run=False)
    _update, params = conn.cur.writes("UPDATE")[0]
    assert params[4] == "linked"
    assert params[5] is False, "a chain that is no longer closed must be feedable again"


def test_a_fabricated_lookalike_trade_is_not_used():
    """No own trade + REJECTED: the chain is orphaned and the trade fields are cleared.

    The old matcher would have written whichever same-symbol trade followed the proposal."""
    proposal = {"id": 900, "symbol": "AAPL", "strategy_id": "x", "status": "REJECTED",
                "proposed_by": "maria", "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                "trade_id": None, "own_status": None, "pnl": None, "r_multiple": None}
    conn = FakeConn(_chain_handler([], [proposal]))
    flp.link_proposal_outcomes(conn, dry_run=False)
    # the lookalike query must not even be asked
    assert not any("symbol = %s AND strategy_id = %s" in sql for sql, _ in conn.cur.calls)
    insert, params = conn.cur.writes("INSERT")[0]
    assert "paper_trade_id" in insert
    assert params[6] is None, "no lookalike trade may be recorded"
    assert params[10] == "orphaned"


def test_the_backlog_is_drained_oldest_first_not_newest_100():
    conn = FakeConn(_chain_handler([], []))
    flp.link_proposal_outcomes(conn, dry_run=True)
    candidates = [c for c in conn.cur.calls if "FROM paper_trade_proposals p" in c[0]]
    assert candidates, "the candidate query must run"
    sql = candidates[0][0]
    assert "ORDER BY p.created_at ASC" in sql
    assert "LIMIT 100" not in sql


# ── feeding outcomes ────────────────────────────────────────────────────────

def test_the_feed_carries_the_trades_real_pnl_pct_and_its_own_dates():
    closed = {"id": 77, "proposal_id": 500, "symbol": "NVDA", "strategy_id": "momo",
              "proposing_agent": "maria", "trade_pnl": 12.5, "trade_r_multiple": 1.4,
              "paper_trade_id": 42,
              "proposal_created": datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc),
              "trade_pnl_pct": 6.25,
              "entry_time": datetime(2026, 10, 2, 13, 31, tzinfo=timezone.utc),
              "exit_time": datetime(2026, 10, 9, 19, 59, tzinfo=timezone.utc)}

    def handler(sql, params):
        if "FROM proposal_outcome_chain c LEFT JOIN paper_trades t" in sql:
            return [closed]
        return []          # the dedupe SELECT: nothing recorded yet

    conn = FakeConn(handler)
    assert flp.feed_outcomes_to_agents(conn, dry_run=False) == 1
    insert, params = conn.cur.writes("INSERT")[0]
    assert "trade_id" in insert and "scoring_method" in insert
    # agent, symbol, rec_date, trade_id, entry_date, exit_date, pnl, pnl_pct, verdict, score
    assert params[3] == 42
    assert float(params[7]) == 6.25, "pnl_pct must be the trade's own, not pnl/100"
    assert params[8] == "CORRECT" and float(params[9]) == 1.0


def test_a_flat_trade_is_fed_as_neutral():
    closed = {"id": 1, "proposal_id": 2, "symbol": "BWEN", "strategy_id": "s",
              "proposing_agent": "maria", "trade_pnl": 0.0, "trade_r_multiple": None,
              "paper_trade_id": 53, "proposal_created": None, "trade_pnl_pct": 0.0,
              "entry_time": None, "exit_time": None}
    conn = FakeConn(lambda sql, params: [closed] if "LEFT JOIN paper_trades t" in sql else [])
    flp.feed_outcomes_to_agents(conn, dry_run=False)
    _insert, params = conn.cur.writes("INSERT")[0]
    assert params[8] == "NEUTRAL" and float(params[9]) == 0.0


def test_a_closed_chain_with_no_agent_is_named_not_silently_dropped():
    closed = {"id": 1, "proposal_id": 2, "symbol": "X", "strategy_id": None,
              "proposing_agent": None, "trade_pnl": 3.0, "trade_r_multiple": None,
              "paper_trade_id": 5, "proposal_created": None, "trade_pnl_pct": 1.0,
              "entry_time": None, "exit_time": None}
    conn = FakeConn(lambda sql, params: [closed] if "LEFT JOIN paper_trades t" in sql else [])
    assert flp.feed_outcomes_to_agents(conn, dry_run=False) == 0
    assert not conn.cur.writes("INSERT")
    assert not conn.cur.writes("UPDATE"), "an unfed chain must not be marked settled"
