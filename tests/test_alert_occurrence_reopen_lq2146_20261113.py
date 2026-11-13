"""ANCHOR: ALERT_OCCURRENCE_REOPEN_LQ2146_20261113 -- a reopened incident restarts first_seen_at; occurrence_count stays monotonic (LQ-2667).

DB-less: a scripted cursor stands in for Postgres, so this proves WHICH statement and parameters record_occurrence
issues (reopen flag, first_seen CASE, placeholder/param alignment). It does not prove Postgres evaluates the CASE:
that is the non-author DB run in the READY note. Synthetic ids only.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import alert_occurrence_store as aos  # noqa: E402
from operator_alert_policy_v2 import AlertEvent  # noqa: E402

T = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
COLS = ["incident_id", "dedupe_key", "status", "severity", "operator_action_required", "state_version",
        "last_notified_at", "last_seen_at", "resolved_at", "acknowledged_at", "occurrence_count",
        "notified_count", "suppressed_count", "route_mode", "logical_destination", "digest_bucket",
        "correlation_key"]


class Cur:
    def __init__(self, status):
        self.status, self.updates, self._last, self.description = status, [], None, [(c,) for c in COLS]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self._last = sql
        if "UPDATE alert_incidents" in sql:
            self.updates.append((sql, params))

    def fetchone(self):
        sql = self._last
        if "FROM alert_incidents" in sql:
            if self.status is None or ("status = 'open'" in sql and self.status != "open"):
                return None
            return ("inc1", "dk", self.status, "critical", True, "1", T, T, None if self.status == "open" else T,
                    None, 7, 7, 0, "IMMEDIATE", "x", None, None)
        if "RETURNING occurrence_id" in sql:
            return (99,)
        if "RETURNING incident_id" in sql:
            return ("inc1",)
        return (1,)


class Conn:
    def __init__(self, status):
        self.cur = Cur(status)

    def cursor(self):
        return self.cur

    def commit(self):
        pass


ROUTE = SimpleNamespace(dedupe_window_seconds=60, escalate_after_seconds=None, route_mode="IMMEDIATE",
                        logical_destination="x", digest_bucket=None, policy_version="v", ttl_seconds=86400,
                        suppression_reason=None)


def go(status, resolving=False):
    ev = AlertEvent(alert_type="position_unprotected", source_system="s", source_producer="p", account_id="a",
                    symbol="AAA", severity="critical", operator_action_required=True, payload={}, created_at=T)
    conn = Conn(status)
    aos.record_occurrence(conn, incident_id="inc1", alert_id="al1", dedupe_key="dk", event=ev, route=ROUTE,
                          observed_at=T, resolving=resolving)
    sql, params = conn.cur.updates[0]
    return sql, params


def test_update_placeholders_match_params():
    for st in (None, "open", "resolved"):
        sql, params = go(st)
        assert sql.count("%s") == len(params)


def test_reopened_resolved_incident_resets_first_seen_but_never_the_count():
    sql, params = go("resolved")
    assert "first_seen_at = CASE WHEN %s THEN %s ELSE first_seen_at END" in sql
    assert "occurrence_count = occurrence_count + 1" in sql and "THEN 1 ELSE occurrence_count" not in sql
    assert params[1] is True and params[2] == T


def test_reopened_expired_incident_resets_too():
    assert go("expired")[1][1] is True


def test_open_incident_keeps_first_seen_and_counts_up():
    assert go("open")[1][1] is False


def test_new_incident_is_not_a_reopen():
    assert go(None)[1][1] is False


def test_resolving_occurrence_on_a_resolved_row_is_not_a_reopen():
    assert go("resolved", resolving=True)[1][1] is False
