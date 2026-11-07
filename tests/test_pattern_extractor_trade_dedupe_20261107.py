"""ANCHOR: PATTERN_EXTRACTOR_TRADE_DEDUPE_20261107 — a pattern is computed from trades, not rows.

LQ-20261107-132 (audit78 batch 2). ``pattern_library`` said "gap_flat: 864 trades, 27% wins" when the
database holds 118 closed trades. Measured read-only on 2026-11-07:

    scored agent_recommendation_outcomes rows             9,241
    distinct outcomes.trade_id                              315
    distinct trades by symbol/entry/exit/prices/pnl         118
    five pattern_library rows with identical stats          17 trades, 17 wins, E[x] = $45.59

Three causes, all measured:

1. ``agent_outcome_scorer.match_and_score`` cross-joins *every* watchlist recommendation to *every*
   ``trade_closed`` row for the same symbol inside a 90-day window, so one closed trade produces
   hundreds of outcome rows: LDOS -336.91 has 658 rows, 297 war_ids, 4 agents, 22 recommendation dates.
2. ``trade_id`` is the id ``trade_closed`` had when the outcome was scored — not a stable trade
   identity. ``trade_closed`` has since been reloaded six times (id bands 78-98801, 125875-182534,
   216087-273212, 301351-381768, 420632-482901, 503805-584085) and **1 of 9,231 scored rows still
   joins to a current row**. One trade carries several ids: SPCX 2026-10-07..10-14, -3,218.62, is
   503846 *and* 544274 *and* 583949. Dedupe on trade_id still leaves 316 "trades" where 118 exist.
3. ``rvol = 0.0`` and ``float_m = 0.0`` mean "this scan row has no data", but they bucket as
   ``rvol_low`` and ``float_nano``. All 16 trades in ``float_nano`` carry ``float_m = 0.0`` — the
   bucket, and its KILLED label, was missing data wearing a number.

So the natural key of a trade is the trade itself — symbol, the session it opened and closed in, its
entry and exit price, and the dollars it made or lost — and a statistic computed over rows is not a
statistic over trades. ``realized_pnl`` is part of the key because it is not implied by the prices:
CSWC 2026-02-27..2026-07-23 left at 22.9714 and 23.3100 made both $3.78 and $5.75 (two sizes, two
trades).

Hermetic: synthetic rows and a stubbed connection. No network, no DB.
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pattern_extractor as pe  # noqa: E402


def _row(**kw):
    """One scored outcome row: the columns the extractor's query selects."""
    base = dict(
        id=1, agent_name="steph", symbol="LDOS", recommendation="BUY", strategy_type="swing",
        recommendation_date=date(2026, 6, 26), war_id="war-1", trade_id=98790,
        entry_date=date(2026, 3, 3), exit_date=date(2026, 7, 24),
        entry_price=Decimal("150.00"), exit_price=Decimal("147.60"),
        realized_pnl=Decimal("-336.91"), pnl_pct=Decimal("-1.60"), hold_days=143,
        verdict="WRONG", rvol=Decimal("1.83"), float_m=Decimal("18.40"),
        gap_pct=Decimal("2.19"), catalyst=None, catalyst_verified=False,
    )
    base.update(kw)
    return base


# ── one trade, however many times it was scored ────────────────────────────────────────────────

def test_hundreds_of_recommendations_for_one_trade_are_one_trade():
    """The LDOS row: 658 outcomes, 4 agents, 297 war_ids, one closed trade."""
    agents = ["steph", "maria", "risk_agent", "full_chain"]
    rows = [_row(id=i, agent_name=agents[i % 4], war_id=f"war-{i}", trade_id=98790)
            for i in range(1, 659)]
    assert len(rows) == 658
    assert len(pe.dedupe_to_trades(rows)) == 1


def test_the_same_trade_under_three_trade_closed_generations_is_one_trade():
    """SPCX 2026-10-07..2026-10-14 -3218.62, scored as 503846, 544274 and 583949."""
    rows = [_row(id=i, symbol="SPCX", trade_id=tid, entry_date=date(2026, 10, 7),
                 exit_date=date(2026, 10, 14), entry_price=Decimal("31.20"),
                 exit_price=Decimal("28.55"), realized_pnl=Decimal("-3218.62"))
            for i, tid in enumerate((503846, 544274, 583949), start=1)]
    assert pe.dedupe_to_trades(rows) == [rows[0]]


def test_trades_that_differ_only_in_size_stay_separate():
    """CSWC 2026-02-27..2026-07-23: same symbol, session and prices, $3.78 and $5.75."""
    small = _row(id=1, symbol="CSWC", entry_date=date(2026, 2, 27), exit_date=date(2026, 7, 23),
                 entry_price=Decimal("22.9714"), exit_price=Decimal("23.3100"),
                 realized_pnl=Decimal("3.78"))
    large = _row(id=2, symbol="CSWC", entry_date=date(2026, 2, 27), exit_date=date(2026, 7, 23),
                 entry_price=Decimal("22.9714"), exit_price=Decimal("23.3100"),
                 realized_pnl=Decimal("5.75"))
    assert len(pe.dedupe_to_trades([small, large])) == 2


def test_a_different_session_or_price_is_a_different_trade():
    a = _row(id=1)
    b = _row(id=2, exit_date=date(2026, 7, 25))
    c = _row(id=3, exit_price=Decimal("147.61"))
    d = _row(id=4, symbol="NOC")
    assert len(pe.dedupe_to_trades([a, b, c, d])) == 4


def test_a_row_without_prices_is_still_one_trade():
    """The 10 legacy rows carry no entry/exit price; three BWEN rows on one day are one trade."""
    rows = [_row(id=i, symbol="BWEN", entry_date=date(2026, 6, 4), exit_date=None,
                 entry_price=None, exit_price=None, realized_pnl=Decimal("0.0"), trade_id=None)
            for i in (11, 12, 13)]
    assert len(pe.dedupe_to_trades(rows)) == 1


def test_the_representative_is_the_lowest_id_and_does_not_depend_on_order():
    rows = [_row(id=i, war_id=f"war-{i}") for i in (7, 3, 9, 1, 5)]
    kept = pe.dedupe_to_trades(rows)
    assert [r["id"] for r in kept] == [1]
    shuffled = rows[:]
    random.Random(132).shuffle(shuffled)
    assert [r["id"] for r in pe.dedupe_to_trades(shuffled)] == [1]


# ── a statistic over duplicates is not a statistic over trades ─────────────────────────────────

def test_duplicates_cannot_move_the_win_rate():
    win = _row(id=1, symbol="AAA", realized_pnl=Decimal("100.00"))
    loss = _row(id=2, symbol="BBB", realized_pnl=Decimal("-100.00"))
    rows = [win] + [_row(id=i, symbol="BBB", realized_pnl=Decimal("-100.00"), war_id=f"w{i}")
                    for i in range(3, 103)]
    stats = pe._compute_pattern_stats(pe.dedupe_to_trades(rows))
    assert stats["trade_count"] == 2
    assert stats["win_count"] == 1
    assert stats["win_rate"] == 0.5


def test_run_analyses_trades_not_rows(monkeypatch):
    """The wiring, not just the helper: run() must feed statistics one row per trade."""
    rows = []
    for t in range(5):
        for dup in range(4):
            rows.append(_row(id=t * 10 + dup, symbol=f"SYM{t}", war_id=f"w{t}-{dup}",
                             realized_pnl=Decimal("10.00"), rvol=Decimal("1.10"),
                             float_m=None, gap_pct=None, trade_id=1000 + t))
    stub = _StubConn(rows)
    monkeypatch.setattr(pe.psycopg2, "connect", lambda **kw: stub)

    result = pe.run(min_trades=5, dry_run=True)

    assert result["outcome_rows"] == 20
    assert result["trades_analysed"] == 5
    assert result["patterns_found"] == 1          # rvol_low, five trades, not twenty rows
    assert result["upserted"] == 1                # dry run: would upsert


class _StubConn:
    """Just enough psycopg2 connection for run(): one cursor, one SELECT, no writes in dry-run."""

    def __init__(self, rows):
        self.rows = rows
        self.autocommit = True
        self.statements = []
        self.closed = False

    def cursor(self, **_kw):
        return _StubCur(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class _StubCur:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.statements.append(" ".join(str(sql).split()))
        self._rows = [] if "INSERT" in str(sql).upper() else self.conn.rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


# ── a zero is not a bucket ──────────────────────────────────────────────────────────────────────

def test_missing_rvol_is_not_low_rvol():
    assert pe._rvol_bucket(None) is None
    assert pe._rvol_bucket(Decimal("0.0")) is None
    assert pe._rvol_bucket(Decimal("1.10")) == "low"


def test_missing_float_is_not_a_nano_float():
    """No company has a 0.0M float; SPCX, SCHG, V and WMT are not nano-caps."""
    assert pe._float_bucket(None) is None
    assert pe._float_bucket(Decimal("0.0")) is None
    assert pe._float_bucket(Decimal("0.4")) == "nano"


def test_a_zero_gap_is_a_real_observation():
    """A 0.00% gap is a flat open, not missing data — unlike rvol and float, it stays a bucket."""
    assert pe._gap_bucket(Decimal("0.0")) == "flat"
