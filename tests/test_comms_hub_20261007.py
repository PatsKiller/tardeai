"""Communications hub — decision support, re-entry focus, lifecycle (operator 2026-10-07).

Every message: category (11 operator categories + operator conversation), priority, five scores, TTL + expiry,
status, actionability; re-entry items carry a re-entry status; newer data on the same symbol/topic supersedes;
expired items are hidden, then archived (jsonl.gz) and removed — the delete is refused unless the archive count
matches. Fakes only: no database, no network, no Telegram.
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms import classify as cl  # noqa: E402
import communications_portal as cp  # noqa: E402
import comms_lifecycle as lc  # noqa: E402

C = lambda body, **k: cl.classify(body=body, **k)  # noqa: E731


# ── categories, TTLs and rules on real message shapes ───────────────────────

def test_operator_categories_and_ttls():
    cats = {c["id"]: c["ttl_hours"] for c in cl.categories()}
    for c in ("re_entry", "risk", "reward", "high_conviction_opportunity", "watchlist_candidate", "threat",
              "market_event", "news", "security_alert", "system_alert", "operational_issue"):
        assert c in cats
    assert cats["operational_issue"] == 72 and cats["system_alert"] == 72          # operational: 72 h
    assert cats["re_entry"] == cats["risk"] == cats["market_event"] == 96         # market / securities: 96 h
    assert cats["watchlist_candidate"] == 168                                     # watchlist / correlation: 1 week


@pytest.mark.parametrize("body,category,priority,actionable", [
    ("🏥 Health Inspector [DEGRADED]\nLive: /x", "operational_issue", "medium", False),
    ("🔐 *Approval requested*\n\nScope: release-write", "security_alert", "high", True),
    ("🚨 STOP HEALTH — ORPHANED: DT (schwab_rollover_ira)", "threat", "critical", True),
    ("ACTIVE TRADER · SCALP ALERT\n🔵 APPROACHING · XNDU · about to fire", "reward", "high", True),
    ("🟡 CIO ENTRY ALERT — ALLE · New position\nCIO VIEW\n🟡 BUY READY\nPrice $153.65 · inside entry zone",
     "high_conviction_opportunity", "high", True),
    ("👀 WATCH — CIO stance RESEARCH_MORE\n🟡 CIO ENTRY ALERT — EIKN · New position\n🟡 READY", "reward", "medium", True),
    ("📋 P1 digest — 22 suppressed messages in the last 24h", "system_alert", "low", False),
    ("Trade AI — Executive Brief\nas_of: x", "system_alert", "low", False),
    ("⏰ *Watchpool: BANL*", "watchlist_candidate", "low", False),
    ("🚨 SIEM P1: rotation_autopilot — PIPELINE_FAILURE", "operational_issue", "high", True),
])
def test_families_classify(body, category, priority, actionable):
    x = C(body)
    assert (x["category"], x["priority"], x["actionable"]) == (category, priority, actionable)
    assert x["ttl_hours"] in (72.0, 96.0, 168.0)


def test_inbound_is_operator_conversation():
    assert C("track leap options for netflix", direction="INBOUND")["category"] == "operator_conversation"


@pytest.mark.parametrize("body,status", [
    ("TDG Reentry Status Downgraded\n🟡 TDG · Reentry downgraded · REENTER → WAIT", "invalidated"),
    ("ANET Removed From Reentry Book\n⚪ ANET · Removed from Reentry · WAIT →", "invalidated"),
    ("TDG Reentry Status Upgraded\n🔴 TDG · Reentry upgraded · WAIT → REENTER", "confirmed"),
    ("• RE_ENTER_IF RKLB — RE_ENTER_IF  re-entry", "potential"),
    ("*Re-entry Signal: VJET*\nPrice: $1.03 (zone $0.89-$1.10)", "opportunity"),
])
def test_reentry_status(body, status):
    x = C(body)
    assert x["category"] == "re_entry" and x["reentry_status"] == status
    assert x["actionable"] is (status != "invalidated")


def test_symbols_from_stored_bodies():
    assert C("🟡 CIO ENTRY ALERT — ALLE · New position (https://h/v3/trading?tab=Scalp&symbol=ALLE)")["symbols"] == ["ALLE"]
    assert C("ACTIVE TRADER · SCALP ALERT\n🔵 APPROACHING · XNDU · about")["symbols"] == ["XNDU"]
    assert C("Entry state PEW\n\nEntry state BUY_READY for PEW")["symbols"][0] == "PEW"
    assert C("🚨 SYSTEM HEALTH: Telegram Bot Daemon — MISSING")["symbols"] == []
    assert "CI" not in C("x CI:e4b0098d HST:fbd144af TDG:387f8e0e")["symbols"]


def test_body_signals_refine_scores():
    x = C("🟡 CIO ENTRY ALERT — ALLE · New position\nBUY READY · inside entry zone\nR:R current 9.09 · confidence 0.82")
    assert x["confidence"] == 0.82 and x["reward_score"] == 1.0
    assert 0 < x["priority_score"] <= 100


def test_topic_supersede_except_approvals():
    assert C("🚨 STOP HEALTH — 2 alert(s)")["topic_key"] == C("🚨 STOP HEALTH — 3 alert(s)")["topic_key"]
    assert C("🔐 *Approval requested*")["topic_key"] is None


# ── portal: filters, board, bulk actions ────────────────────────────────────

def test_default_view_hides_expired_and_superseded():
    where, _ = cp.hub_where({})
    assert "status IN ('active', 'acknowledged')" in where and "expires_at" in where


def test_expired_reentry_filter_shows_expired_items():
    where, params = cp.hub_where({"reentry_status": "expired"})
    assert "status IN ('active', 'acknowledged')" not in where and ["expired"] in params


def test_filters_are_parameterised():
    where, params = cp.hub_where({"q": "x'; DROP TABLE t; --", "symbol": "spcx,tdg", "category": "re_entry",
                                  "min_risk": "0.7", "actionable": "1"})
    assert "DROP" not in where and ["SPCX", "TDG"] in params and 0.7 in params and "actionable" in where


def test_sorts_cover_every_score():
    for s in ("priority_score", "confidence", "risk_score", "reward_score", "time_sensitivity"):
        assert s in cp.HUB_SORTS


def test_board_answers_the_six_questions():
    assert list(cp.BOARD_PANELS) == ["attention", "reward", "reentry", "risk", "expiring", "recent"]


def test_bulk_actions():
    sql, extra = cp.bulk_sql("retain", 24)
    assert "retain_until" in sql and extra == [24.0]
    assert "legal_hold=TRUE" in cp.bulk_sql("retain")[0]
    assert "status='expired'" in cp.bulk_sql("expire")[0]
    with pytest.raises(ValueError):
        cp.bulk_sql("delete")


def test_bulk_route_goes_through_the_guarded_admin_write():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    blk = src[src.index('base_path == "/api/v2/communications/events/bulk"'):][:2000]
    assert "admin_write(" in blk and "_cp.HUB_ACTIONS" in blk and '"/api/v2/communications/board"' in src


# ── lifecycle: grace, archive-then-delete, refusal ──────────────────────────

def test_purge_waits_for_the_grace_window():
    assert "interval '24 hours'" in lc.purge_where(24)


class _Conn:
    def __init__(self):
        self.commits = self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Cur:
    """Enough of a cursor for step_purge: ids, per-table counts, archived rows (optionally short), deletes."""

    def __init__(self, short_table=None):
        self.connection, self.short, self._rows, self.deleted = _Conn(), short_table, [], []
        self.rowcount, self._ids_served = 0, False

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT count(*) FROM communication_events WHERE status IN"):
            self._rows = [(2,)]
        elif s.startswith("SELECT event_id FROM communication_events"):
            self._rows = [] if self._ids_served else [("e1",), ("e2",)]
            self._ids_served = True
        elif s.startswith("SELECT count(*) FROM"):
            self._rows = [(2,)]
        elif s.startswith("SELECT row_to_json"):
            table = s.split(" FROM ")[1].split()[0]
            n = 1 if table == self.short else 2
            self._rows = [({"t": table, "i": i},) for i in range(n)]
        elif s.startswith("DELETE FROM"):
            self.deleted.append(s.split()[2])
            self.rowcount = 2

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


def test_purge_archives_then_deletes_children_first(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    cur = _Cur()
    out = lc.step_purge(cur, apply=True)
    assert cur.deleted[-1] == "communication_events" and cur.deleted[0] == "communication_deliveries"
    assert out["archived"]["communication_events"] == 2 and cur.connection.commits == 1
    f = next((tmp_path / "archive" / "comms_lifecycle" / "communication_events").glob("*.jsonl.gz"))
    assert len(gzip.open(f, "rt").read().splitlines()) == 2


def test_purge_refuses_when_the_archive_is_short(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    cur = _Cur(short_table="communication_outbox")
    with pytest.raises(RuntimeError, match="delete refused"):
        lc.step_purge(cur, apply=True)
    assert cur.deleted == [] and cur.connection.rollbacks == 1


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    cur = _Cur()
    out = lc.step_purge(cur, apply=False)
    assert out["eligible"] == 2 and cur.deleted == [] and not (tmp_path / "archive").exists()


# ── writer: classification never costs the event ────────────────────────────

def test_writer_classifies_behind_a_savepoint():
    from scripts.lib.comms import client

    log = []

    class Cur:
        def execute(self, sql, params=None):
            log.append(sql.split()[0] + (" " + sql.split()[1] if sql.split()[0] in ("SAVEPOINT", "ROLLBACK") else ""))
            if sql.lstrip().startswith("UPDATE"):
                raise RuntimeError("column category does not exist")

    client._classify_in_tx(Cur(), "e1", {"sanitized_body": "🔐 *Approval requested*", "direction": "OUTBOUND",
                                          "created_at": datetime.now(timezone.utc)})
    assert log[0] == "SAVEPOINT comms_classify" and log[-1] == "ROLLBACK TO"
