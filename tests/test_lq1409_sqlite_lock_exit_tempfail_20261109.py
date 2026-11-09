"""ANCHOR: lq1409_sqlite_lock_exit_tempfail — LQ-20261107-1409 batch2 REWORK.

sqlite lock / ledger busy must exit EX_TEMPFAIL (75), not 1.
transient-2 retries {69, 75, 111} only; exit 1 is terminal on attempt 1.

REWORK (grok-b review): prove the connect_rw open path, not only string helpers;
drive disk counters through HostIntentError; gate must be CiGate@v1.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


CLI = _load("lq1409_comms", "scripts/n8n_comms_intent_consumer.py")
DISK = _load("lq1409_disk", "scripts/disk_usage_monitor.py")


def test_comms_ex_tempfail_constant_is_75():
    assert CLI.EX_TEMPFAIL == 75


@pytest.mark.parametrize(
    "err",
    [
        "OperationalError: database is locked",
        "sqlite3.OperationalError: database is locked",
        "SQLITE_BUSY",
        "database is busy",
    ],
)
def test_comms_sqlite_lock_error_detected(err):
    assert CLI._is_sqlite_lock_error(err) is True


def test_comms_non_lock_error_not_tempfail():
    assert CLI._is_sqlite_lock_error("FabricStoreError: routes_unreadable") is False
    assert CLI._failure_exit({"error": "routes_unreadable"}) == 1


def test_comms_lock_error_exits_tempfail():
    assert CLI._failure_exit({"error": "OperationalError: database is locked"}) == 75


def test_comms_only_transient_intents_exit_tempfail():
    assert CLI._failure_exit({"failed_transient": 2}) == 75
    assert CLI._failure_exit({"failed_transient": 0, "error": "routes_unreadable"}) == 1
    # missing / non-int failed_transient must NOT coerce via `or 0`
    assert CLI._failure_exit({}) == 1
    assert CLI._failure_exit({"failed_transient": "2"}) == 1


def test_comms_connect_rw_lock_exits_tempfail(monkeypatch, tmp_path):
    """REWORK: lock while opening the ledger (connect_rw) must exit 75.

    A truncated ``OperationalError: ledger`` string used to miss _is_sqlite_lock_error
    and exit 1 (terminal under transient-2).
    """
    import scripts.lib.n8n_comms_intent_consumption as C

    monkeypatch.setattr(C, "load_routes", lambda _p=None: {"sha256": "deadbeef", "max_per_hour": 10})
    monkeypatch.setattr(
        C,
        "load_delivery_evidence",
        lambda _sr: {
            "status": "ok",
            "receipt_status": "ok",
            "notified": set(),
            "acked_keys": set(),
        },
    )

    def _boom(_ledger):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(C, "connect_rw", _boom)

    import scripts.lib.lane_last_receipt as R

    receipt = tmp_path / "n8n-comms-intent-consumer_last.json"
    monkeypatch.setattr(R, "write_lane_receipt", lambda *a, **k: receipt)

    rc = CLI.run(
        ledger=tmp_path / "ledger.sqlite",
        state_root=tmp_path,
        apply=True,
        max_intents=5,
        now=datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc),
        receipt=receipt,
    )
    assert rc == CLI.EX_TEMPFAIL == 75


def test_comms_connect_rw_non_lock_stays_exit_1(monkeypatch, tmp_path):
    import scripts.lib.n8n_comms_intent_consumption as C

    monkeypatch.setattr(C, "load_routes", lambda _p=None: {"sha256": "deadbeef", "max_per_hour": 10})
    monkeypatch.setattr(
        C,
        "load_delivery_evidence",
        lambda _sr: {
            "status": "ok",
            "receipt_status": "ok",
            "notified": set(),
            "acked_keys": set(),
        },
    )
    monkeypatch.setattr(C, "connect_rw", lambda _l: (_ for _ in ()).throw(FileNotFoundError("no ledger")))

    import scripts.lib.lane_last_receipt as R

    receipt = tmp_path / "n8n-comms-intent-consumer_last.json"
    monkeypatch.setattr(R, "write_lane_receipt", lambda *a, **k: receipt)

    rc = CLI.run(
        ledger=tmp_path / "missing.sqlite",
        state_root=tmp_path,
        apply=True,
        max_intents=5,
        now=datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc),
        receipt=receipt,
    )
    assert rc == 1


def test_disk_ex_tempfail_constant_is_75():
    assert DISK.EX_TEMPFAIL == 75
    assert "intent_store_unavailable" in DISK._LEDGER_BUSY_REASONS


def _monitor_rules(mounts: list[str]) -> dict:
    return {
        "monitor": {
            "state_name": "disk_usage_monitor_state.json",
            "producer": "disk_usage_monitor",
            "intent_domain": "host",
            "intent_kinds": {
                "warn": "disk_usage_warn",
                "critical": "disk_usage_critical",
                "ok": "disk_usage_ok",
            },
            "mounts": mounts,
            "warn_pct": 80.0,
            "critical_pct": 90.0,
            "bands": {"warn": 80, "critical": 90},
            "inodes": None,
            "standing_hygiene": None,
            "standing_pressure": None,
            "consumer_snapshot": None,
            "measure_consumers_on": "never",
        }
    }


def _stub_disk_apply_path(monkeypatch, tmp_path):
    monkeypatch.setattr(DISK, "band_of", lambda pct, _mon: "critical")
    monkeypatch.setattr(DISK, "alert_for", lambda *a, **k: True)
    monkeypatch.setattr(DISK, "latest_manifest", lambda *_a, **_k: None)
    monkeypatch.setattr(DISK, "metric_policy", lambda *_a, **_k: {})
    monkeypatch.setattr(DISK, "intent_text", lambda *a, **k: ("subj", "summ"))
    monkeypatch.setattr(DISK, "top_consumers", lambda *a, **k: [])
    monkeypatch.setattr(
        DISK,
        "standing_hygiene_status",
        lambda *a, **k: {"status": "idle"},
    )
    monkeypatch.setattr(
        DISK, "_state_lock", lambda _p: MagicMock(__enter__=lambda s: None, __exit__=lambda *a: False)
    )
    import scripts.lib.lane_last_receipt as R

    monkeypatch.setattr(R, "write_lane_receipt", lambda *a, **k: tmp_path / "receipt.json")
    monkeypatch.setattr(R, "receipt_path", lambda *a, **k: tmp_path / "receipt.json")
    monkeypatch.setattr(R, "runtime_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(
        "scripts.lib.atomic_json_store.atomic_write_json",
        lambda *a, **k: None,
        raising=False,
    )
    # import path used inside _run_locked
    import sys
    from types import ModuleType

    fake = ModuleType("scripts.lib.atomic_json_store")
    fake.atomic_write_json = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "scripts.lib.atomic_json_store", fake)
    monkeypatch.setitem(sys.modules, "lib.atomic_json_store", fake)


def test_disk_ledger_busy_only_via_counter(monkeypatch, tmp_path):
    """REWORK: drive the real failure counters, not a reimplemented if-expression."""
    rules = _monitor_rules(["/"])
    _stub_disk_apply_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        DISK,
        "measure",
        lambda mount: {
            "mount": mount,
            "used_pct": 95.0,
            "total_bytes": 100,
            "used_bytes": 95,
            "avail_bytes": 5,
        },
    )

    def _busy(*_a, **_k):
        raise DISK.HostIntentError("intent_store_unavailable")

    monkeypatch.setattr(DISK, "queue_host_intent", _busy)
    state_path = tmp_path / "disk_usage_monitor_state.json"
    state_path.write_text("{}")

    rc = DISK._run_locked(
        rules=rules,
        state_root=tmp_path,
        ledger=tmp_path / "ledger.sqlite",
        apply=True,
        now=datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc),
        state_path=state_path,
    )
    assert rc == DISK.EX_TEMPFAIL == 75


def test_disk_mixed_statvfs_and_ledger_busy_exits_1(monkeypatch, tmp_path):
    """statvfs_failed (+1 failures only) mixed with ledger-busy → exit 1."""
    rules = _monitor_rules(["/", "/data"])
    _stub_disk_apply_path(monkeypatch, tmp_path)

    def _measure(mount):
        if mount == "/":
            return None  # triggers failures += 1 (statvfs_failed path)
        return {
            "mount": mount,
            "used_pct": 95.0,
            "total_bytes": 100,
            "used_bytes": 95,
            "avail_bytes": 5,
        }

    monkeypatch.setattr(DISK, "measure", _measure)
    monkeypatch.setattr(
        DISK,
        "queue_host_intent",
        lambda *a, **k: (_ for _ in ()).throw(DISK.HostIntentError("intent_store_unavailable")),
    )
    state_path = tmp_path / "disk_usage_monitor_state.json"
    state_path.write_text("{}")

    rc = DISK._run_locked(
        rules=rules,
        state_root=tmp_path,
        ledger=tmp_path / "ledger.sqlite",
        apply=True,
        now=datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc),
        state_path=state_path,
    )
    assert rc == 1
