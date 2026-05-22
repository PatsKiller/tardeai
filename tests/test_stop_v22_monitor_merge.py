"""Tests for STOP-V2.2 monitor merge."""
import subprocess, sys, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def test_supervisor_compiles():
    assert subprocess.run([PY, "-m", "py_compile",
        f"{PROJECT_ROOT}/scripts/unified_stop_supervisor.py"]).returncode == 0


def test_no_order_creation():
    src = open(f"{PROJECT_ROOT}/scripts/unified_stop_supervisor.py").read()
    assert "submit_order" not in src
    assert "create_order" not in src


def test_no_order_cancellation():
    src = open(f"{PROJECT_ROOT}/scripts/unified_stop_supervisor.py").read()
    assert "cancel_order" not in src


def test_no_stop_movement_direct():
    src = open(f"{PROJECT_ROOT}/scripts/unified_stop_supervisor.py").read()
    assert "replace_stop" not in src
    assert "move_stop" not in src


def test_safety_checks_present():
    src = open(f"{PROJECT_ROOT}/scripts/unified_stop_supervisor.py").read()
    assert '"paper"' in src
    assert "assert" in src
    assert "ALPACA_MODE" in src


def test_uses_reconciliation():
    src = open(f"{PROJECT_ROOT}/scripts/unified_stop_supervisor.py").read()
    assert "reconcile" in src.lower()
    assert "reconcile_stop_v21" in src


def test_after_hours_blocks_trailing():
    src = open(f"{PROJECT_ROOT}/scripts/unified_stop_supervisor.py").read()
    assert "after_hours" in src.lower() or "market_hours" in src.lower()


def test_rollback_syntax():
    assert subprocess.run(["bash", "-n",
        f"{PROJECT_ROOT}/scripts/rollback_stop_v22_monitor_merge.sh"]).returncode == 0


def test_v21_compiles():
    assert subprocess.run([PY, "-m", "py_compile",
        f"{PROJECT_ROOT}/scripts/reconcile_stop_v21_broker_stops.py"]).returncode == 0


def test_v20_compiles():
    assert subprocess.run([PY, "-m", "py_compile",
        f"{PROJECT_ROOT}/scripts/backfill_stop_v20_tracking.py"]).returncode == 0
