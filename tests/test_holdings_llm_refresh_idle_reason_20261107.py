"""holdings-llm-refresh: a run that finds nothing due says why, and only then may read as idle (LQ QR2-3).

Live evidence (2026-11-07): the lane's receipt read
``{"holdings": 27, "candidates": 0, "refreshed": 0, "errors": 0, "statuses": {}}`` and the quality page
graded it EMPTY, "Ran live 22 h ago and exited ok but produced nothing (summary.candidates = 0; the
receipt does not say why)". The receipt was not wrong about the count — it was silent about the reason,
so an idle run and a broken one were indistinguishable (lib/run_quality.py: a zero run with no stated
reason stays EMPTY; a reviewed idle token makes it GOOD/idle).

The fix gives the receipt a LaneRunReceipt@v2 output block, and computes ``empty_reason`` from the
selection itself: ``nothing_due`` (the reviewed token in config/run_quality_idle_reasons.json) only when
every considered holding really was assessed inside the 12 h window; every other zero — an empty
portfolio, a ``--symbol`` that is not held — gets a sentence that keeps the EMPTY grade but names the
cause.

Fakes only: no database, no network, no LLM.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import holdings_llm_refresh as hlr  # noqa: E402

IDLE_REASONS = ROOT / "config" / "run_quality_idle_reasons.json"


class _Cur:
    """Answers the candidate query with the rows given; records the statement."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.statements: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self.cur = _Cur(rows)

    def cursor(self):
        return self.cur


def _holding(sym):
    return {"symbol": sym, "shares": 100, "price": 10.0, "market_value": 1000.0}


def _row(sym, age_s):
    return {"symbol": sym, "holdings_llm_summary": None,
            "holdings_llm_at": datetime.now(timezone.utc) - timedelta(seconds=age_s)}


def test_every_holding_assessed_inside_the_window_is_idle_and_says_so():
    rows = [_row("AAA", 60), _row("BBB", hlr.FRESH_WINDOW_S - 5)]
    candidates, stats = hlr.select_holdings(_Conn(rows), [_holding("AAA"), _holding("BBB")])
    assert candidates == []
    assert (stats["considered"], stats["fresh"], stats["stale"]) == (2, 2, 0)
    assert hlr.empty_reason([_holding("AAA"), _holding("BBB")], stats) == "nothing_due"


def test_nothing_due_is_a_reviewed_idle_token():
    """If the token ever leaves the reviewed list, an idle run silently turns back into EMPTY."""
    reasons = json.loads(IDLE_REASONS.read_text())["reasons"]
    assert "nothing_due" in reasons


def test_a_stale_holding_is_a_candidate_and_has_no_empty_reason():
    rows = [_row("AAA", 60), _row("BBB", hlr.FRESH_WINDOW_S + 60)]
    holdings = [_holding("AAA"), _holding("BBB")]
    candidates, stats = hlr.select_holdings(_Conn(rows), holdings)
    assert [c["symbol"] for c in candidates] == ["BBB"]
    assert (stats["fresh"], stats["stale"]) == (1, 1)
    assert hlr.empty_reason(holdings, stats) is None


def test_a_holding_with_no_watchlist_row_is_always_a_candidate():
    rows = [_row("AAA", 60)]
    holdings = [_holding("AAA"), _holding("ZZZ")]
    candidates, stats = hlr.select_holdings(_Conn(rows), holdings)
    assert [c["symbol"] for c in candidates] == ["ZZZ"]
    assert stats["no_watchlist_row"] == 1


def test_a_never_assessed_row_is_a_candidate():
    rows = [{"symbol": "AAA", "holdings_llm_summary": None, "holdings_llm_at": None}]
    candidates, stats = hlr.select_holdings(_Conn(rows), [_holding("AAA")])
    assert [c["symbol"] for c in candidates] == ["AAA"]
    assert stats["stale"] == 1


def test_the_cap_truncates_candidates_but_not_the_counts():
    rows = [_row(s, 60) for s in ("AAA", "BBB")]
    holdings = [_holding(s) for s in ("AAA", "BBB", "CCC", "DDD")]  # CCC/DDD have no row -> stale
    candidates, stats = hlr.select_holdings(_Conn(rows), holdings, limit=2)
    assert [c["symbol"] for c in candidates] == ["CCC", "DDD"]
    assert stats["stale"] == 2 and stats["cap_reached"] is False
    more, stats2 = hlr.select_holdings(_Conn(rows), holdings, limit=1)
    assert [c["symbol"] for c in more] == ["CCC"] and stats2["cap_reached"] is True


def test_an_empty_portfolio_is_not_idle_but_names_the_cause():
    candidates, stats = hlr.select_holdings(_Conn([]), [])
    assert candidates == []
    reason = hlr.empty_reason([], stats)
    assert reason != "nothing_due"
    assert "no stock holding" in reason


def test_a_requested_symbol_that_is_not_held_names_itself():
    holdings = [_holding("AAA"), _holding("BBB")]
    candidates, stats = hlr.select_holdings(_Conn([_row("AAA", 60)]), holdings, symbol="QQQ")
    assert candidates == []
    reason = hlr.empty_reason(holdings, stats)
    assert reason != "nothing_due" and "QQQ" in reason


def test_the_symbol_filter_narrows_the_query_and_the_counts():
    holdings = [_holding("AAA"), _holding("BBB")]
    conn = _Conn([_row("BBB", 60)])
    candidates, stats = hlr.select_holdings(conn, holdings, symbol="bbb")
    assert stats["considered"] == 1
    assert candidates == []
    assert conn.cur.statements[0][1][0] == ["BBB"]


def test_only_a_genuinely_empty_selection_reaches_the_idle_token():
    """A run holding candidates never carries an empty_reason — the receipt must not both work and say idle."""
    rows = [_row("AAA", hlr.FRESH_WINDOW_S + 1)]
    holdings = [_holding("AAA")]
    candidates, stats = hlr.select_holdings(_Conn(rows), holdings)
    assert candidates and hlr.empty_reason(holdings, stats) is None


# ── the grade the receipt earns (the consumer) ────────────────────────────────────────────────────────────────

from scripts.lib import lane_last_receipt as LR  # noqa: E402
from scripts.lib import run_quality as Q  # noqa: E402

NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = NOW - timedelta(seconds=30)
FINISH = NOW - timedelta(seconds=29)
LANE = {"lane_id": "holdings-llm-refresh", "state": "ACTIVE", "scheduler": {"kind": "cron"},
        "output_signal": {"kind": "json_key", "path": "data/runtime/holdings_llm_refresh_last.json", "key": "ok_at"}}
RUN = {"mode": "live", "result": "succeeded", "started_at": START.isoformat(), "finished_at": FINISH.isoformat(),
       "duration_s": 1.0, "run_id": "r1", "exit_code": 0, "reason": None, "source": "cron wrapper journal"}


def _grade(receipt_doc):
    row = {"lane_id": "holdings-llm-refresh", "state": "ACTIVE", "status": "ok", "runs": [RUN], "last_run": RUN}
    evidence = {"receipt": receipt_doc, "receipt_path": None, "output_at": FINISH, "ledger": [], "history": [],
                "contract": None, "freshness": [], "freshness_known": True, "plausibility": [],
                "plausibility_known": True}
    return Q.grade(row, LANE, evidence, now=NOW)


def test_the_old_receipt_grades_empty_and_the_new_one_grades_good():
    """Exactly the live symptom and its fix: same counts, one states the reason."""
    old = LR.build_receipt("holdings_llm_refresh", ok=True, started_at=START, finished_at=FINISH.isoformat(),
                           summary={"holdings": 27, "candidates": 0, "refreshed": 0, "errors": 0, "statuses": {}})
    new = LR.build_receipt("holdings_llm_refresh", ok=True, started_at=START, finished_at=FINISH.isoformat(),
                           summary={"holdings": 27, "candidates": 0, "refreshed": 0, "errors": 0, "statuses": {}},
                           output={"produced_count": 0, "attempted_count": 0,
                                   "skipped_reasons": {"fresh_within_window": 27, "no_watchlist_row": 0},
                                   "empty_reason": "nothing_due"})
    assert hlr.empty_reason([_holding("A")] * 27, {"considered": 27, "stale": 0}) == "nothing_due"
    old_q, new_q = _grade(old), _grade(new)
    assert (old_q["grade"], old_q["sub"]) == ("EMPTY", "unexpected")
    assert "does not say why" in old_q["reasons"][0]
    assert (new_q["grade"], new_q["sub"]) == ("GOOD", "idle"), new_q["reasons"]
