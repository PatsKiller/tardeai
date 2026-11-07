"""LQ-20261107-120: a usefulness-backfill run with nothing left to score must SAY so.

The lane is the only writer of ``hermes_external_research.usefulness_score`` (see the DONE note), and it runs
hourly. Most hours there is nothing new to score, so it exits 0 having produced nothing. The Jobs page graded
that EMPTY — "the receipt does not say why" — because the receipt carried only counts. ``run_quality`` already has
the designed answer: a receipt that STATES a reviewed idle reason (``empty_reason``, top level or summary, one of
``config/run_quality_idle_reasons.json``) grades GOOD sub ``idle`` in plain words.

These tests pin both halves: the lane writes ``produced_count`` / ``attempted_count`` and, when it selected nothing,
``empty_reason = "no_new_input"``; and the receipt built that way grades GOOD (idle) rather than EMPTY.

Hermetic: a fake DB cursor, a fake receipt writer, synthetic receipts. The repo is PUBLIC.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from scripts import hermes_external_feedback_loop as fb
from scripts.lib import lane_last_receipt as LLR
from scripts.lib import run_quality as Q

NOW = datetime(2026, 11, 7, 16, 15, tzinfo=timezone.utc)


def z(dt):
    return dt.isoformat().replace("+00:00", "Z")


# ── a fake psycopg2 connection: no database is opened ────────────────────────────────────────────────────────
class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        if "GROUP BY lane" in self.calls[-1][0]:
            return [("chatgpt", 2, 0.5)]
        return self.rows


class FakeConn:
    def __init__(self, rows):
        self.cur = FakeCursor(rows)
        self.committed = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed += 1

    def close(self):
        pass


def args(*, apply=True, max_rows=2000):
    return types.SimpleNamespace(apply=apply, max_rows=max_rows, model="deepseek-flash")


@pytest.fixture()
def no_kill_switch(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "KILL", tmp_path / "HERMES_DISABLED")
    return tmp_path


# ── the lane's result says why it did nothing ───────────────────────────────────────────────────────────────
def test_a_run_with_nothing_eligible_states_the_idle_reason(monkeypatch, no_kill_switch):
    monkeypatch.setattr(fb, "_db", lambda: FakeConn([]))
    result = fb._run_feedback(args())
    assert result["selected"] == 0 and result["scored"] == 0
    assert result["empty_reason"] == "no_new_input", (
        "a run that found nothing to score must state the reviewed idle reason, or the page has to guess")


def test_a_run_with_work_does_not_claim_idle(monkeypatch, no_kill_switch):
    rows = [(1, "chatgpt", "AAA", "q", "rec", None, "2026-11-07T10:00:00Z")]
    monkeypatch.setattr(fb, "_db", lambda: FakeConn(rows))
    monkeypatch.setattr(fb, "_outcome", lambda cur, symbol, created: {})
    monkeypatch.setattr(fb, "_rate", lambda *a: (0.5, "specific and grounded", {"provider": "fake", "model": "m"}))
    result = fb._run_feedback(args())
    assert result["scored"] == 1 and result["selected"] == 1
    assert "empty_reason" not in result or not result["empty_reason"]


def test_an_aborted_run_does_not_claim_idle(monkeypatch, no_kill_switch):
    """A provider refusal leaves eligible rows UNSCORED on purpose: that is a failure, not an idle run."""
    rows = [(1, "chatgpt", "AAA", "q", "rec", None, "2026-11-07T10:00:00Z")]

    def boom(*a):
        raise RuntimeError("BRIDGE_ROUTE_REFUSED: governance refused the request")

    monkeypatch.setattr(fb, "_db", lambda: FakeConn(rows))
    monkeypatch.setattr(fb, "_outcome", lambda cur, symbol, created: {})
    monkeypatch.setattr(fb, "_rate", boom)
    result = fb._run_feedback(args())
    assert result["aborted"] is True
    assert not result.get("empty_reason")


# ── and the receipt it writes carries that reason to the page ───────────────────────────────────────────────
class FakeReceiptModule(types.ModuleType):
    def __init__(self):
        super().__init__("lib.lane_last_receipt")
        self.calls = []

    def now_iso(self):
        return z(NOW)

    def write_lane_receipt(self, *a, **kw):
        self.calls.append((a, kw))
        return None


@pytest.fixture()
def fake_receipt_module(monkeypatch):
    """``main`` imports ``lib.lane_last_receipt`` inside the function; the real ``lib`` package stays, only the
    receipt writer is replaced, so nothing is written to the state root."""
    import lib  # noqa: F401 -- imports the real 'lib' parent package; only its lane_last_receipt is replaced
    mod = FakeReceiptModule()
    monkeypatch.setitem(sys.modules, "lib.lane_last_receipt", mod)
    monkeypatch.setattr(fb, "_load_env", lambda: None)  # no env file is read
    return mod


def test_main_hands_the_reason_and_the_counts_to_the_receipt(monkeypatch, no_kill_switch, fake_receipt_module):
    monkeypatch.setattr(fb, "_db", lambda: FakeConn([]))
    assert fb.main(["--apply", "--max-rows", "2000"]) == 0
    assert fake_receipt_module.calls, "the live run must write its receipt"
    _a, kw = fake_receipt_module.calls[0]
    assert kw["produced_count"] == 0 and kw["attempted_count"] == 0
    assert kw["empty_reason"] == "no_new_input"


# ── the page: the same receipt grades GOOD (idle), not EMPTY ────────────────────────────────────────────────
LANE = {"lane_id": "hermes-usefulness-backfill", "state": "ACTIVE",
        "output_signal": {"kind": "json_key", "path": "data/runtime/hermes-usefulness-backfill_last.json",
                          "key": "ok_at"},
        "scheduler": {"kind": "n8n"}, "dispatch": {"mode": "live"}}
PATH = LANE["output_signal"]["path"]


def row(ago_min=10):
    start = NOW - timedelta(minutes=ago_min)
    return {"lane_id": "hermes-usefulness-backfill", "state": "ACTIVE", "status": "ok",
            "runs": [{"mode": "live", "result": "succeeded", "started_at": z(start),
                      "finished_at": z(start + timedelta(seconds=5)), "duration_s": 0.4,
                      "run_id": "d:hermes-usefulness-backfill:live:20261107T1115", "exit_code": 0,
                      "source": "n8n run ledger"}],
            "last_run": None}


def evidence(receipt):
    return {"receipt": receipt, "receipt_path": PATH, "output_at": NOW - timedelta(minutes=9),
            "ledger": [], "history": [], "contract": None,
            "freshness": [], "freshness_known": True, "plausibility": [], "plausibility_known": True}


def receipt_with(*, empty_reason):
    start = NOW - timedelta(minutes=10)
    return LLR.build_receipt(
        "hermes-usefulness-backfill", ok=True, exit_code=0, started_at=z(start), finished_at=z(NOW),
        script="hermes_external_feedback_loop.py", run_id="d:hermes-usefulness-backfill:live:20261107T1115",
        summary={"selected": 0, "scored": 0, "failed": 0, "aborted": False},
        produced_count=0, attempted_count=0, empty_reason=empty_reason)


def test_a_receipt_that_states_the_idle_reason_grades_good(  ):
    rec = receipt_with(empty_reason="no_new_input")
    out = Q.grade(row(), LANE, evidence(rec), now=NOW)
    assert out["grade"] == "GOOD", (out["grade"], out["headline"])
    assert out["count"]["value"] == 0 and out["count"]["key"] == "produced_count"
    assert "nothing to do: there was no new input" in out["headline"], out["headline"]


def test_the_same_receipt_without_the_reason_stays_empty():
    """The live behaviour before this fix: a correct idle run graded EMPTY because the receipt did not say why."""
    rec = receipt_with(empty_reason=None)
    out = Q.grade(row(), LANE, evidence(rec), now=NOW)
    assert out["grade"] == "EMPTY", (out["grade"], out["headline"])
    assert "the receipt does not say why" in out["headline"], out["headline"]


def test_a_failed_run_with_the_reason_is_still_not_good():
    """The idle reason explains a zero, it does not excuse a failure: the status rule runs first."""
    rec = receipt_with(empty_reason="no_new_input")
    rec["status"] = "failed"
    rec["error"] = "the writer raised"
    out = Q.grade(row(), LANE, evidence(rec), now=NOW)
    assert out["grade"] == "FAILED", (out["grade"], out["headline"])
