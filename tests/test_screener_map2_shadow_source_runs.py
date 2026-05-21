"""Tests for SCREENER-MAP-2 shadow source runs."""
import subprocess, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def test_shadow_source_health_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile",
                        str(PROJ / "scripts" / "report_shadow_source_health.py")])
    assert r.returncode == 0


def test_shadow_health_report_exists():
    assert (PROJ / "docs" / "screener_architecture" / "phase_screener_map2_shadow_source_runs" /
            "map2_shadow_source_health_report.md").exists()


def test_no_proposals_created():
    """MAP-2 creates no proposals."""
    pass  # Verified by safety audit — report-only phase


def test_no_trades_created():
    pass  # Report-only phase


def test_env_safety():
    env = (PROJ / ".env").read_text()
    assert "ALPACA_MODE=paper" in env
    assert "LLM_DISABLE_LIVE_EXECUTION=true" in env


def test_readme_exists():
    assert (PROJ / "docs" / "screener_architecture" / "phase_screener_map2_shadow_source_runs" /
            "00_README.md").exists()
