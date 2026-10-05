"""ATM decision logging must not leave the caller on a closed cursor, and the
protection quote read must end before quote HTTP.

The 2026-10-05 atm.log line is `approval error: cursor already closed` after
the paper submitter returned, then `ATM protection pass error: connection
already closed`. Commit (and a replaced connection) invalidates the cursor
the cycle was still holding.
"""

from __future__ import annotations

import inspect

import apply_paper_protection_adjustment as ap
import atm_auto_approver as approver


class _Cursor:
    def __init__(self, conn: "_Conn") -> None:
        self.conn = conn
        self.closed = False
        self.executed: list[str] = []

    def execute(self, sql, _params=None):
        if self.closed:
            raise Exception("cursor already closed")
        self.executed.append(sql)
        self.conn.saw_execute = True

    def fetchone(self):
        if self.closed:
            raise Exception("cursor already closed")
        return (42,)


class _Conn:
    """Commit closes every cursor opened so far, matching the failure mode."""

    def __init__(self) -> None:
        self.closed = 0
        self.cursors: list[_Cursor] = []
        self.rollbacks = 0
        self.saw_execute = False

    def cursor(self):
        cur = _Cursor(self)
        self.cursors.append(cur)
        return cur

    def commit(self):
        for cur in self.cursors:
            cur.closed = True

    def rollback(self):
        self.rollbacks += 1


def _log(conn):
    return approver._log_decision(
        conn, 1, "NEM", "pullback", "alpaca_paper", "alpaca", "paper",
        "rejected", [{"gate": "broker_submit_failed"}], 1, 0, 0, 0, 0, 0, 0,
        False, "hash", "active", 9,
    )


def test_decision_commit_closes_the_callers_cursor_and_a_new_one_writes():
    conn = _Conn()
    held = conn.cursor()
    did, live = _log(conn)
    assert did == 42
    assert live is conn
    try:
        held.execute("UPDATE paper_trade_proposals SET status='REJECTED' WHERE id=%s")
        raised = False
    except Exception as exc:
        raised = "cursor already closed" in str(exc)
    assert raised
    live, fresh = approver._live_conn_cursor(live)
    fresh.execute(
        "UPDATE paper_trade_proposals SET atm_evaluation_count = atm_evaluation_count + 1 WHERE id = %s"
    )
    assert fresh.executed
    assert not fresh.closed


def test_closed_connection_is_replaced_before_the_insert(monkeypatch):
    fresh = _Conn()
    monkeypatch.setattr(approver, "get_connection", lambda: fresh)
    dead = _Conn()
    dead.closed = 1
    did, live = _log(dead)
    assert did == 42
    assert live is fresh
    assert fresh.saw_execute


def test_release_read_before_http_rollbacks_and_does_not_commit():
    conn = _Conn()
    approver.release_read_before_http(conn)
    assert conn.rollbacks == 1
    approver.release_read_before_http(None)


def test_active_approve_releases_the_read_before_submit_http():
    src = inspect.getsource(approver._run_cycle_locked)
    release_at = src.find("release_read_before_http")
    approve_at = src.find("approve_proposal(")
    submit_at = src.find("submit_paper(")
    assert 0 <= release_at < approve_at < submit_at
    # The broker-submit failure path is the one in the 13:45 ET log.
    fail_at = src.find("cancelled_broker_submit:")
    rebind_at = src.rfind("_live_conn_cursor", 0, fail_at)
    assert rebind_at != -1


def test_quote_http_is_outside_the_read_transaction(monkeypatch):
    events: list[str] = []

    class Cur:
        def __init__(self) -> None:
            self.n = 0

        def execute(self, _sql, _params=None):
            events.append("execute")
            self.n += 1

        def fetchone(self):
            if self.n == 1:
                return {
                    "id": 1,
                    "trade_id": 9,
                    "symbol": "AAA",
                    "action": "MOVE_STOP_TO_BREAKEVEN",
                    "status": "PROPOSED",
                    "current_stop": 10,
                    "proposed_stop": 11,
                    "proposed_take_profit": None,
                    "profit_locked_before": 0,
                    "profit_locked_after": 0,
                    "giveback_before": 0,
                    "giveback_after": 0,
                    "tradeai_reason": "",
                    "hermes_reason": "",
                    "evidence_refs": {},
                }
            return {
                "status": "open",
                "stop_order_id": "oid",
                "take_profit_order_id": None,
                "take_profit_price": None,
                "entry_price": 10,
                "shares": 1,
                "current_stop": 10,
                "strategy_id": "x",
                "planned_stop": 9,
            }

    class Conn:
        def cursor(self, cursor_factory=None):
            events.append("cursor")
            return Cur()

        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setenv("ALPACA_MODE", "paper")
    monkeypatch.setattr(ap, "load_env", lambda: None)
    monkeypatch.setattr(ap, "db", lambda: Conn())

    def quote(_sym):
        events.append("quote")
        return 1.0, {"last_price": 12.0}

    monkeypatch.setattr(ap, "fresh_quote_age", quote)
    monkeypatch.setattr(ap, "audit", lambda _rec: None)
    result, conn, p, _t, q = ap._common_proposal_context(
        1, "ATM_auto", "because", False, "2026-10-05"
    )
    assert events.index("rollback") < events.index("quote")
    assert conn is not None
    assert p["symbol"] == "AAA"
    assert result["symbol"] == "AAA"
    assert q["last_price"] == 12.0
    assert "close" not in events
