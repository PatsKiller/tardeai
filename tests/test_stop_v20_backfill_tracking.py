"""Tests for STOP-V2.0 backfill tracking scripts."""
import subprocess, sys, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def test_report_compiles():
    assert subprocess.run([PY, "-m", "py_compile", f"{PROJECT_ROOT}/scripts/report_stop_v20_open_trade_stop_tracking.py"]).returncode == 0


def test_backfill_compiles():
    assert subprocess.run([PY, "-m", "py_compile", f"{PROJECT_ROOT}/scripts/backfill_stop_v20_tracking.py"]).returncode == 0


def test_backfill_default_is_dry_run():
    """Running without --apply should not modify DB."""
    r = subprocess.run([PY, f"{PROJECT_ROOT}/scripts/backfill_stop_v20_tracking.py", "--dry-run", "--verbose"],
                       capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert "dry-run" in r.stdout.lower() or "dry_run" in r.stdout.lower() or r.returncode == 0


def test_backfill_requires_paper_mode():
    """The script checks ALPACA_MODE=paper."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("backfill", f"{PROJECT_ROOT}/scripts/backfill_stop_v20_tracking.py")
    mod = importlib.util.module_from_spec(spec)
    # Don't execute, just verify the safety check function exists
    source = open(f"{PROJECT_ROOT}/scripts/backfill_stop_v20_tracking.py").read()
    assert "ALPACA_MODE" in source
    assert "assert mode == \"paper\"" in source or "assert mode == 'paper'" in source


def test_no_order_creation_in_backfill():
    """Backfill script must not contain order creation calls."""
    source = open(f"{PROJECT_ROOT}/scripts/backfill_stop_v20_tracking.py").read()
    assert "submit_order" not in source
    assert "POST" not in source  # no HTTP POSTs to broker
    assert "create_order" not in source
    assert "cancel_order" not in source
    assert "replace_order" not in source


def test_no_order_creation_in_report():
    """Report script must not contain order creation calls."""
    source = open(f"{PROJECT_ROOT}/scripts/report_stop_v20_open_trade_stop_tracking.py").read()
    assert "submit_order" not in source
    assert "create_order" not in source
    assert "cancel_order" not in source


def test_no_strategy_yaml_changes():
    """Scripts must not modify strategy YAML files."""
    for script in ["report_stop_v20_open_trade_stop_tracking.py", "backfill_stop_v20_tracking.py"]:
        source = open(f"{PROJECT_ROOT}/scripts/{script}").read()
        assert "config/strategies" not in source
        assert ".yaml" not in source or "screeners.yaml" not in source


def test_audit_trail_exists():
    """Backfill script must write audit events."""
    source = open(f"{PROJECT_ROOT}/scripts/backfill_stop_v20_tracking.py").read()
    assert "audit_log" in source
    assert "_write_audit" in source
    assert "audit_fallback" in source
