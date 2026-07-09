#!/usr/bin/env python3
"""ATM expiry must transition PENDING→EXPIRED at most once (no duplicate Telegram batches)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from atm_auto_approver import (  # noqa: E402
    ATM_CYCLE_LOCK,
    _EXPIRY_TG_RECENT,
    _acquire_atm_cycle_lock,
    _expire_proposal_atomic,
    _release_atm_cycle_lock,
    _telegram_expiry_batch,
)


class _FakeCursor:
    def __init__(self, rowcounts):
        self._rowcounts = list(rowcounts)
        self.calls = 0
        self.last_sql = None
        self.last_args = None

    @property
    def rowcount(self):
        idx = min(self.calls - 1, len(self._rowcounts) - 1)
        return self._rowcounts[idx] if self._rowcounts else 0

    def execute(self, sql, args=None):
        self.calls += 1
        self.last_sql = sql
        self.last_args = args


def test_expire_proposal_atomic_wins_race_once():
    cur = _FakeCursor([1, 0])
    assert _expire_proposal_atomic(cur, 42, "persistent_approval_failure (5 attempts)",
                                   "EXPIRED", "ATM expired") is True
    assert _expire_proposal_atomic(cur, 42, "persistent_approval_failure (5 attempts)",
                                   "EXPIRED", "ATM expired") is False
    assert "status = 'PENDING'" in cur.last_sql
    assert "atm_expired_at IS NULL" in cur.last_sql


def test_cycle_lock_serializes_concurrent_entry():
    fd1 = _acquire_atm_cycle_lock()
    assert fd1 is not None
    try:
        fd2 = _acquire_atm_cycle_lock()
        assert fd2 is None
    finally:
        _release_atm_cycle_lock(fd1)
    # Lock file path matches cron safe_flock guard
    assert ATM_CYCLE_LOCK == "/tmp/tradeai_atm.lock"


def test_expiry_telegram_symbol_dedup(monkeypatch):
    _EXPIRY_TG_RECENT.clear()
    sent = []

    def _fake_send(msg):
        sent.append(msg)
        return True

    monkeypatch.setattr("telegram_alert.send_telegram", _fake_send)
    _telegram_expiry_batch(["DOC (persistent_approval_failure (6 attempts))"])
    assert len(sent) == 1
    _telegram_expiry_batch(["DOC (persistent_approval_failure (6 attempts))"])
    assert len(sent) == 1  # same symbol within 24h — suppressed
    _telegram_expiry_batch(["BLZE (persistent_approval_failure (5 attempts))"])
    assert len(sent) == 2


if __name__ == "__main__":
    test_expire_proposal_atomic_wins_race_once()
    test_cycle_lock_serializes_concurrent_entry()
    test_expiry_telegram_symbol_dedup()
    print("OK: atm expiry telegram dedup tests passed")