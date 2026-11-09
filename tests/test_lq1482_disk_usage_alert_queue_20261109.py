"""ANCHOR: LQ1482_DISK_USAGE_ALERT_QUEUE_20261109. LQ-20261107-1482.

A critical mount queues exactly one host intent. A mount under the warn threshold queues none.
A coordination ledger that is busy for one attempt is retried, so the breach is still queued.
A ledger that stays busy exits 75, not 1. Synthetic measurements and a temp ledger. No send.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import disk_usage_monitor as M  # noqa: E402
from scripts.lib.n8n_fabric_store import CommsIntentStore  # noqa: E402

NOW = datetime(2026, 11, 9, 9, 30, tzinfo=timezone.utc)
RULES = {
    "monitor": {
        "mounts": ["/"],
        "warn_pct": 80.0,
        "critical_pct": 90.0,
        "realert_minutes": 60.0,
        "state_name": "disk_usage_monitor_state.json",
        "producer": "disk_usage_monitor",
        "intent_domain": "host",
        "intent_kinds": {
            "warn": "disk_usage_warn",
            "critical": "disk_usage_critical",
            "ok": "disk_usage_recovered",
        },
    }
}


def _measure(pct):
    def measure(mount):
        return {
            "mount": mount,
            "used_pct": pct,
            "used_bytes": 90,
            "avail_bytes": 10,
            "size_bytes": 100,
        }
    return measure


def _intent_count(ledger: Path) -> int:
    conn = sqlite3.connect(ledger)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'comms_intents'"
        ).fetchone()
        if row is None:
            return 0
        return int(conn.execute("SELECT COUNT(*) FROM comms_intents").fetchone()[0])
    finally:
        conn.close()


def _run(tmp_path, monkeypatch, pct):
    monkeypatch.setattr(M, "measure", _measure(pct))
    monkeypatch.setattr(M, "measure_inodes", lambda mount: None)
    ledger = tmp_path / "ledger.sqlite"
    sqlite3.connect(ledger).close()
    rc = M.run(
        rules=RULES,
        state_root=tmp_path,
        ledger=ledger,
        apply=True,
        now=NOW,
    )
    return rc, _intent_count(ledger)


def test_a_breach_queues_exactly_one_alert(tmp_path, monkeypatch):
    rc, n = _run(tmp_path, monkeypatch, 91.7)
    assert rc == 0
    assert n == 1


def test_a_quiet_mount_queues_no_alert(tmp_path, monkeypatch):
    rc, n = _run(tmp_path, monkeypatch, 55.0)
    assert rc == 0
    assert n == 0


def test_a_busy_ledger_is_retried_and_still_queues_one_alert(tmp_path, monkeypatch):
    real = CommsIntentStore.accept
    calls = {"n": 0}

    def accept(self, request, *, caller_id, now):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(self, request, caller_id=caller_id, now=now)

    monkeypatch.setattr(CommsIntentStore, "accept", accept)
    rc, n = _run(tmp_path, monkeypatch, 91.7)
    assert calls["n"] >= 2
    assert rc == 0
    assert n == 1


def test_a_ledger_that_stays_busy_is_not_a_terminal_exit(tmp_path, monkeypatch):
    def accept(self, request, *, caller_id, now):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(CommsIntentStore, "accept", accept)
    rc, n = _run(tmp_path, monkeypatch, 91.7)
    assert rc == M.EX_TEMPFAIL
    assert n == 0
