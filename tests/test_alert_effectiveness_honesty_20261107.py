"""An alert score is a measurement or it is NULL — never a manufactured zero.

LQ-20261107-48, 2026-11-07. ``alert_effectiveness`` held 1057 rows and every one of them
said ``action_taken = false, effectiveness_score = 0.00``. None carried an
``action_description``: the old writer only filled it in when it found an action, so 1057
zeros are "the rule found nothing OR there was no rule". The audit behind this fix:

* 14 of the 18 notification types have no action rule at all, and fell through to
  ``action_taken = False`` (863 of the 1057 rows);
* both evidence sources are dead — ``john_decision_queue`` has never held a row, and
  ``agent_feedback_log``'s last row is 2026-07-18 (the other 194 rows);
* the insert was ``ON CONFLICT (notification_type, symbol, alert_date) DO NOTHING`` with a
  NULL symbol, which PostgreSQL never matches, so the guard was inert; the pre-check above
  it made the first (false) score permanent;
* the dashboard consumer (``api_v2.py`` AVG(effectiveness_score)) therefore reported a
  confident 0.00 for alerts nobody could answer. AVG() ignores NULL, so NULL is the honest
  representation of "unmeasurable".

Hermetic: scripted cursors, no DB, no network.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import feedback_loop_processor as flp   # noqa: E402

D = date(2026, 11, 6)


@pytest.fixture(autouse=True)
def _fresh_liveness_cache():
    """The liveness answer is cached per run; a test must not inherit another's."""
    flp._liveness_cache.clear()
    yield
    flp._liveness_cache.clear()


def _norm(sql: str) -> str:
    return " ".join(str(sql).split())


class ScriptedCursor:
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


# ── the measurement ─────────────────────────────────────────────────────────

def test_a_type_with_no_rule_is_unmeasurable_not_zero():
    cur = ScriptedCursor(lambda sql, params: [])
    action, desc, score = flp._alert_measurement(cur, "daily_digest", D)
    assert action is None and score is None
    assert "no action rule" in desc and "daily_digest" in desc
    assert not cur.calls, "no rule means no query — there is nothing to ask"


def test_a_dead_evidence_source_is_unmeasurable_not_zero():
    cur = ScriptedCursor(lambda sql, params: [])          # liveness: no rows in 30 days
    action, desc, score = flp._alert_measurement(cur, "urgent_alert", D)
    assert action is None and score is None
    assert "john_decision_queue" in desc and "no rows" in desc


def test_a_live_source_with_no_action_is_a_real_zero():
    def handler(sql, params):
        if sql.startswith("SELECT 1 FROM john_decision_queue"):
            return [{"?column?": 1}]
        return [{"cnt": 0}]

    cur = ScriptedCursor(handler)
    action, desc, score = flp._alert_measurement(cur, "urgent_alert", D)
    assert action is False and score == 0.0
    assert desc == "0 decision(s) resolved"


def test_a_live_source_with_an_action_scores_one():
    def handler(sql, params):
        if sql.startswith("SELECT 1 FROM "):
            return [{"?column?": 1}]
        return [{"cnt": 3}]

    action, desc, score = flp._alert_measurement(ScriptedCursor(handler), "proposal_aging", D)
    assert action is True and score == 1.0 and desc == "3 proposal feedback"


# ── rescoring and the legacy repair ────────────────────────────────────────

def _alert_run_handler(existing_row, new_alerts):
    def handler(sql, params):
        if sql.startswith("SELECT id, action_taken, effectiveness_score FROM alert_effectiveness"):
            return [existing_row] if existing_row else []
        if sql.startswith("SELECT notification_type, notification_date"):
            return new_alerts
        if sql.startswith("SELECT id, notification_type, alert_date"):
            return []
        if sql.startswith("SELECT 1 FROM "):
            return [{"?column?": 1}]           # a live source
        return [{"cnt": 1}]
    return handler


def test_a_measured_row_is_never_overwritten():
    conn = FakeConn(_alert_run_handler({"id": 5, "action_taken": False},
                                       [{"notification_type": "urgent_alert",
                                         "notification_date": D, "payload_text": None}]))
    flp.score_alert_effectiveness(conn, dry_run=False)
    assert not conn.cur.writes("UPDATE") and not conn.cur.writes("INSERT")


def test_a_previously_unmeasurable_row_is_filled_in_when_a_source_is_live():
    conn = FakeConn(_alert_run_handler({"id": 5, "action_taken": None},
                                       [{"notification_type": "urgent_alert",
                                         "notification_date": D, "payload_text": None}]))
    flp.score_alert_effectiveness(conn, dry_run=False)
    update, params = conn.cur.writes("UPDATE")[0]
    assert params[0] is True and float(params[2]) == 1.0 and params[3] == 5


def test_the_legacy_repair_only_touches_zeros_no_source_could_testify_to():
    def handler(sql, params):
        if sql.startswith("SELECT id, notification_type, alert_date"):
            return [
                {"id": 1, "notification_type": "daily_digest",     # no rule at all
                 "alert_date": D, "action_taken": False, "effectiveness_score": 0},
                {"id": 2, "notification_type": "urgent_alert",     # dead source
                 "alert_date": D, "action_taken": False, "effectiveness_score": 0},
            ]
        if sql.startswith("SELECT 1 FROM "):
            return []                                              # no source rows either
        return [{"cnt": 0}]

    cur = ScriptedCursor(handler)
    repaired = flp.repair_unmeasurable_alert_scores(cur, dry_run=False)
    assert repaired == 2
    updates = cur.writes("UPDATE")
    assert len(updates) == 2
    # the legacy value is preserved in the description; the row becomes unmeasurable
    assert all("0.00" in params[0] and "unmeasurable" in params[0] for _sql, params in updates)
    assert sorted(params[1] for _sql, params in updates) == [1, 2]


def test_a_zero_from_a_live_source_is_left_alone():
    def handler(sql, params):
        if sql.startswith("SELECT id, notification_type, alert_date"):
            return [{"id": 3, "notification_type": "proposal_aging",
                     "alert_date": D, "action_taken": False, "effectiveness_score": 0}]
        if sql.startswith("SELECT 1 FROM "):
            return [{"?column?": 1}]                               # source is live
        return [{"cnt": 0}]

    cur = ScriptedCursor(handler)
    assert flp.repair_unmeasurable_alert_scores(cur, dry_run=False) == 0
    assert not cur.writes("UPDATE")
