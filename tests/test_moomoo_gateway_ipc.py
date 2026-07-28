from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import json
from datetime import datetime, timedelta, timezone

import pytest

from moomoo.gateway_ipc import (
    INTENT_CONTRACT,
    OwnerLock,
    OwnerLockError,
    SnapshotClient,
    SnapshotPublisher,
    atomic_write_json,
    merge_intents,
    read_json,
)


def test_atomic_snapshot_is_valid_and_mode_private(tmp_path):
    path = tmp_path / "snapshot.json"
    SnapshotPublisher(path).publish({"heartbeat_at": datetime.now(timezone.utc).isoformat(), "owner": {"exclusive_lock_held": True}})
    payload = read_json(path)
    assert payload and payload["generation"] == 1
    assert path.stat().st_mode & 0o777 == 0o600


def test_snapshot_fresh_stale_and_future_clock_skew(tmp_path):
    path = tmp_path / "snapshot.json"
    now = datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc)
    base = {"contract": "moomoo-l2-gateway-snapshot-v1", "owner": {"exclusive_lock_held": True}}
    atomic_write_json(path, {**base, "heartbeat_at": now.isoformat()})
    assert SnapshotClient(path, max_age_seconds=5).read(now=now).fresh is True
    atomic_write_json(path, {**base, "heartbeat_at": (now - timedelta(seconds=7)).isoformat()})
    assert SnapshotClient(path, max_age_seconds=5).read(now=now).reason == "SNAPSHOT_STALE"
    atomic_write_json(path, {**base, "heartbeat_at": (now + timedelta(seconds=3)).isoformat()})
    assert SnapshotClient(path, max_age_seconds=5).read(now=now).reason == "HEARTBEAT_FUTURE_CLOCK_SKEW"


def test_snapshot_requires_owner_lock_evidence(tmp_path):
    path = tmp_path / "snapshot.json"
    atomic_write_json(path, {"contract": "moomoo-l2-gateway-snapshot-v1", "heartbeat_at": datetime.now(timezone.utc).isoformat(), "owner": {"exclusive_lock_held": False}})
    assert SnapshotClient(path).read().reason == "OWNER_LOCK_UNPROVEN"


def test_owner_lock_rejects_second_owner(tmp_path):
    path = tmp_path / "owner.lock"
    first = OwnerLock(path).acquire({"test": 1})
    try:
        with pytest.raises(OwnerLockError):
            OwnerLock(path).acquire({"test": 2})
    finally:
        first.release()
    OwnerLock(path).acquire().release()


def test_merge_intents_filters_expired_and_preserves_highest_priority(tmp_path):
    legacy = tmp_path / "legacy.json"
    explicit = tmp_path / "explicit.json"
    legacy.write_text(json.dumps({"armed": {"aapl": {"expires_at": 200, "priority": "P2"}, "OLD": {"expires_at": 90}}}))
    explicit.write_text(json.dumps({"contract": INTENT_CONTRACT, "desired": {"AAPL": {"expires_at": 250, "priority": "P0", "require_tape": True}}}))
    merged = merge_intents([legacy, explicit], now_epoch=100)
    assert list(merged) == ["AAPL"]
    assert merged["AAPL"]["priority"] == "P0"
    assert merged["AAPL"]["require_tape"] is True
    assert merged["AAPL"]["expires_at"] == 250
