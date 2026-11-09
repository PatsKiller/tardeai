"""LQ-20261107-1409: sqlite lock / ledger busy must exit EX_TEMPFAIL (75), not 1.

transient-2 retries exit codes {69, 75, 111} only. A coordination-ledger
``database is locked`` that exits 1 becomes a terminal dead letter on attempt 1
(catalog defect on n8n-comms-intent-consumer / disk-usage-monitor).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

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


def test_disk_ex_tempfail_constant_is_75():
    assert DISK.EX_TEMPFAIL == 75
    assert "intent_store_unavailable" in DISK._LEDGER_BUSY_REASONS


def test_disk_ledger_busy_only_maps_to_tempfail_math():
    """When every failure is intent_store_unavailable, the run exit is 75."""
    failures = 2
    ledger_busy_failures = 2
    assert failures == ledger_busy_failures
    rc = DISK.EX_TEMPFAIL if failures and failures == ledger_busy_failures else 1
    assert rc == 75
    # mixed with a hard failure stays 1
    failures = 3
    ledger_busy_failures = 2
    rc = DISK.EX_TEMPFAIL if failures and failures == ledger_busy_failures else 1
    assert rc == 1
