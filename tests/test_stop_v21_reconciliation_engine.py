"""Tests for STOP-V2.1 reconciliation engine."""
import subprocess, sys, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def test_reconciliation_compiles():
    assert subprocess.run([PY, "-m", "py_compile",
        f"{PROJECT_ROOT}/scripts/reconcile_stop_v21_broker_stops.py"]).returncode == 0


def test_no_order_creation():
    src = open(f"{PROJECT_ROOT}/scripts/reconcile_stop_v21_broker_stops.py").read()
    assert "submit_order" not in src
    assert "create_order" not in src
    assert "cancel_order" not in src
    assert "replace_order" not in src
    assert "DELETE" not in src  # no position deletes


def test_no_stop_movement():
    src = open(f"{PROJECT_ROOT}/scripts/reconcile_stop_v21_broker_stops.py").read()
    assert "move_stop" not in src
    assert "replace_stop" not in src
    assert "PATCH" not in src


def test_safety_checks_present():
    src = open(f"{PROJECT_ROOT}/scripts/reconcile_stop_v21_broker_stops.py").read()
    assert 'ALPACA_MODE' in src
    assert 'assert' in src
    assert '"paper"' in src


def test_severity_definitions():
    src = open(f"{PROJECT_ROOT}/scripts/reconcile_stop_v21_broker_stops.py").read()
    for status in ["RECONCILED", "MISSING_BROKER_STOP", "STOP_PRICE_MISMATCH",
                    "STOP_QTY_MISMATCH", "BROKER_STOP_CANCELED", "ORPHANED_BROKER_STOP"]:
        assert status in src, f"Missing status: {status}"


def test_audit_trail():
    src = open(f"{PROJECT_ROOT}/scripts/reconcile_stop_v21_broker_stops.py").read()
    assert "audit_log" in src
    assert "_write_audit" in src
    assert "audit_fallback" in src


def test_no_atm_mode_change():
    src = open(f"{PROJECT_ROOT}/scripts/reconcile_stop_v21_broker_stops.py").read()
    assert "atm_state" not in src.replace("_write_audit", "").replace("audit", "")
    assert "SET mode" not in src


def test_v20_tests_still_compile():
    assert subprocess.run([PY, "-m", "py_compile",
        f"{PROJECT_ROOT}/tests/test_stop_v20_backfill_tracking.py"]).returncode == 0
