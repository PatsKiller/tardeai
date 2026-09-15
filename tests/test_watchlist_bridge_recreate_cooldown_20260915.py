"""2026-09-15: the bridge does not re-create a watchlist proposal the approval path just closed on the same plan."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
for _name in ("psycopg2", "psycopg2.extras", "dotenv"):
    if _name not in sys.modules:
        try:
            __import__(_name)
        except Exception:
            sys.modules[_name] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None, extras=None)

import watchlist_proposal_bridge as b  # noqa: E402

NOW = datetime(2026, 9, 15, 16, 2, tzinfo=timezone.utc)


def _prev(minutes_ago, entry=4.10, status="EXPIRED"):
    return {"id": 9901, "status": status, "proposed_entry": entry, "updated_at": NOW - timedelta(minutes=minutes_ago)}


def test_same_plan_closed_half_an_hour_ago_is_not_recreated():
    assert b.closed_recently_same_plan(_prev(31), 4.12, NOW) is True


def test_a_materially_new_entry_may_be_proposed_again():
    assert b.closed_recently_same_plan(_prev(31), 4.40, NOW) is False


def test_cooldown_ends_after_six_hours():
    assert b.closed_recently_same_plan(_prev(6 * 60 + 1), 4.10, NOW) is False


def test_no_prior_closed_proposal_means_no_cooldown():
    assert b.closed_recently_same_plan(None, 4.10, NOW) is False


def test_risk_blocked_counts_as_closed():
    assert "RISK_BLOCKED" in b.CLOSED_STATUSES and b.closed_recently_same_plan(_prev(29, status="RISK_BLOCKED"), 4.10, NOW)


class _Cur:
    description = [("id",), ("status",), ("proposed_entry",), ("created_at",), ("updated_at",)]

    def __init__(self, row):
        self.row, self.params = row, None

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchone(self):
        return self.row


def test_latest_closed_proposal_reads_watchlist_origin_closed_statuses():
    cur = _Cur((9901, "EXPIRED", 4.1, NOW, NOW))
    row = b._latest_closed_proposal(cur, "anro", ["alpaca_paper"])
    assert row["id"] == 9901 and cur.params[0] == "ANRO" and cur.params[1] == list(b.CLOSED_STATUSES)
    assert "origin = 'watchlist'" in cur.sql
