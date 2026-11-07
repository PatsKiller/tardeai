"""ANCHOR: AGENT_OUTCOME_SCORER_FANOUT_20261107 — one outcome per recommendation.

LQ-20261107-125. ``agent_outcome_scorer.match_and_score`` joined every watchlist recommendation to
every ``trade_closed`` row on the same symbol inside a 90-day window, in every account, so one
recommendation was scored many times. A read-only dry run on 2026-11-07 found 676 outcomes queued
for 170 recommendations (up to 19 for one). Its "already scored?" check was keyed on
``(war_id, trade_id)``, and ``trade_closed`` is reloaded with new ids, so every reload queued the
same recommendations again.

The fix, pinned here:
- a recommendation gets at most one outcome, and "already scored" is keyed on the recommendation
  alone, so a reload of ``trade_closed`` cannot re-score it;
- when the recommendation names its account, only that account's trades count;
- a trade that was open when the recommendation was made beats one opened after it; among those,
  the nearest one wins;
- when the account is unknown and the best matches sit in more than one account, the
  recommendation is held back and counted. It is not guessed.

Hermetic: synthetic symbols, accounts and figures, dated 2030. A stubbed connection; no DB.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_outcome_scorer as aos  # noqa: E402


def _ts(y, m, d):
    return datetime(y, m, d, 15, 0, tzinfo=timezone.utc)


def _row(war_id, trade_id, *, rec_day, open_day, close_day, rec_account=None, trade_account="acct_a",
         rec="BUY", pnl_pct=5.0, symbol="ZZQA"):
    return {
        "war_id": war_id, "agent_name": "agent_x", "symbol": symbol, "recommendation": rec,
        "confidence": 0.7, "recommendation_date": _ts(*rec_day), "rec_account": rec_account,
        "trade_id": trade_id, "trade_account": trade_account,
        "entry_date": date(*open_day), "exit_date": date(*close_day),
        "entry_price": 10.0, "exit_price": 10.5, "realized_pnl": 50.0, "pnl_pct": pnl_pct,
    }


class _Cur:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        self._rows = self.conn.candidates if "watchlist_agent_results" in sql else []

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, candidates):
        self.candidates = candidates
        self.sql: list[str] = []

    def cursor(self, cursor_factory=None):
        return _Cur(self)


def _score(candidates, stats=None):
    return aos.match_and_score(_Conn(candidates), stats)


def test_one_outcome_per_recommendation_across_many_trades():
    # One recommendation, five trades on the symbol in the window: the old join scored it five times.
    cands = [_row("w1", 100 + i, rec_day=(2030, 3, 1), open_day=(2030, 3, 2 + i), close_day=(2030, 4, 1))
             for i in range(5)]
    out = _score(cands)
    assert [r["war_id"] for r in out] == ["w1"]
    assert out[0]["trade_id"] == 100  # the nearest entry after the recommendation


def test_every_recommendation_kept_once_and_no_trade_invented():
    cands = []
    for w in range(4):
        for t in range(3):
            cands.append(_row(f"w{w}", 200 + t, rec_day=(2030, 3, 1), open_day=(2030, 3, 2 + t),
                              close_day=(2030, 4, 1)))
    out = _score(cands)
    assert sorted(r["war_id"] for r in out) == ["w0", "w1", "w2", "w3"]
    assert {r["trade_id"] for r in out} <= {200, 201, 202}


def test_named_account_only_matches_its_own_trades():
    cands = [
        _row("w1", 301, rec_day=(2030, 3, 5), open_day=(2030, 3, 1), close_day=(2030, 3, 20),
             rec_account="acct_b", trade_account="acct_a", pnl_pct=-20.0),
        _row("w1", 302, rec_day=(2030, 3, 5), open_day=(2030, 3, 2), close_day=(2030, 3, 25),
             rec_account="acct_b", trade_account="acct_b", pnl_pct=12.0),
    ]
    out = _score(cands)
    assert len(out) == 1 and out[0]["trade_id"] == 302 and out[0]["verdict"] == "CORRECT"


def test_named_account_with_no_trade_in_it_is_not_scored():
    cands = [_row("w1", 401, rec_day=(2030, 3, 5), open_day=(2030, 3, 1), close_day=(2030, 3, 20),
                  rec_account="acct_b", trade_account="acct_a")]
    stats: dict = {}
    assert _score(cands, stats) == []
    assert stats["held_back"]["no_trade_in_named_account"] == 1


def test_trade_open_at_recommendation_beats_later_entry():
    cands = [
        _row("w1", 501, rec_day=(2030, 3, 10), open_day=(2030, 3, 12), close_day=(2030, 3, 30)),
        _row("w1", 502, rec_day=(2030, 3, 10), open_day=(2030, 3, 1), close_day=(2030, 3, 20)),
        _row("w1", 503, rec_day=(2030, 3, 10), open_day=(2030, 2, 1), close_day=(2030, 3, 15)),
    ]
    out = _score(cands)
    assert out[0]["trade_id"] == 502  # held at the recommendation; the most recent such entry


def test_unknown_account_spanning_two_accounts_is_held_back_not_guessed():
    cands = [
        _row("w1", 601, rec_day=(2030, 3, 10), open_day=(2030, 3, 1), close_day=(2030, 3, 20),
             trade_account="acct_a", pnl_pct=-30.0),
        _row("w1", 602, rec_day=(2030, 3, 10), open_day=(2030, 3, 1), close_day=(2030, 3, 22),
             trade_account="acct_b", pnl_pct=30.0),
    ]
    stats: dict = {}
    assert _score(cands, stats) == []
    assert stats["held_back"]["account_unknown_ambiguous"] == 1


def test_unknown_account_single_account_is_scored():
    cands = [
        _row("w1", 701, rec_day=(2030, 3, 10), open_day=(2030, 3, 1), close_day=(2030, 3, 20)),
        _row("w1", 702, rec_day=(2030, 3, 10), open_day=(2030, 3, 15), close_day=(2030, 3, 29)),
    ]
    out = _score(cands)
    assert [r["trade_id"] for r in out] == [701]


def test_match_note_records_how_it_matched():
    out = _score([_row("w1", 801, rec_day=(2030, 3, 10), open_day=(2030, 3, 1), close_day=(2030, 3, 20))])
    assert out[0]["match_note"] == "match=held_at_recommendation; account=unknown; candidates=1"


def test_already_scored_is_keyed_on_the_recommendation_alone():
    # trade_closed is reloaded with new ids; a (war_id, trade_id) key would queue w1 again.
    conn = _Conn([])
    aos.match_and_score(conn)
    sql = " ".join(conn.sql[0].split())
    assert "aro.war_id = war.id" in sql
    assert "aro.trade_id" not in sql
    assert "LIMIT" not in sql  # a row cap would cut a recommendation's candidate set in half


def test_stats_count_candidates_and_recommendations():
    cands = [_row("w1", 901 + i, rec_day=(2030, 3, 1), open_day=(2030, 3, 2 + i), close_day=(2030, 4, 1))
             for i in range(3)]
    stats: dict = {}
    out = _score(cands, stats)
    assert stats["candidate_rows"] == 3
    assert stats["recommendations"] == 1
    assert len(out) == 1


def test_account_aliases_resolve_before_matching(monkeypatch):
    # The recommendation's snapshot and trade_closed spell one account two ways.
    monkeypatch.setattr(aos, "_canon", lambda raw: {"acct_short": "acct_long"}.get(raw or "", raw or ""))
    cands = [_row("w1", 1001, rec_day=(2030, 3, 5), open_day=(2030, 3, 1), close_day=(2030, 3, 20),
                  rec_account="acct_short", trade_account="acct_long")]
    out = _score(cands)
    assert [r["trade_id"] for r in out] == [1001]
    assert "account=named" in out[0]["match_note"]
