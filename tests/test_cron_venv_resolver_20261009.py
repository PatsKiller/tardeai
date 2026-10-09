"""Scheduled jobs resolve their child interpreter without assuming the release ships a .venv (2026-10-09).

Every cron line `cd`s into the served CURRENT release, and releases carry no .venv: rotation_autopilot fell back to
system python3 and died on `import dotenv` every 15 min (470x), and hermes_coordinator's research_curator /
options_research_bridge / embedding_worker steps failed "No such file: <release>/.venv/bin/python" every tick.
Fakes only: temp files stand in for interpreters; nothing is launched but bash running the helper.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import live_project_root as lpr  # noqa: E402

RELEASE_RELATIVE = re.compile(r'str\(\s*\w+\s*/\s*"\.venv"\s*/\s*"bin"|str\(\s*\w+\s*/\s*"\.venv/bin/python')

FIXED_PY = [
    "hermes_coordinator", "hermes_think_tank", "catalyst_momentum_engine", "research_critique_pipeline",
    "sector_research_universe", "think_tank_prospect_discovery", "ingest_reground_retirement_gaps",
    "shadow_strategy_job", "auto_proposal_generator", "disk_pressure_guard", "weekly_disk_cleanup_notify",
    "agent_event_router", "iris_taxonomy_agent", "trade_ai_orchestrator", "run_proactive_quote_refresh", "send_no_leads_diagnostic_alert", "run_regime_cron1_health",
    "holdings_change_trigger",
]
FIXED_SH = [
    "linux_launchers/run_rotation_autopilot.sh", "linux_launchers/run_ensemble_worker.sh",
    "linux_launchers/run_inference_cycle.sh", "scripts/run_research_intelligence_overnight.sh",
    "scripts/run_scheduled_a1a_check.sh", "scripts/run_scheduled_maturity_control_board.sh",
    "scripts/run_scheduled_system_facts.sh",
]


def fake_python(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_env_contract_wins(tmp_path, monkeypatch):
    env_py = fake_python(tmp_path / "env" / "python")
    fake_python(tmp_path / "rel" / ".venv" / "bin" / "python")
    monkeypatch.setenv("TRADEAI_VENV_PYTHON", str(env_py))
    assert lpr.venv_python(tmp_path / "rel") == str(env_py)


def test_code_root_venv_then_dev_venv_then_running_interpreter(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEAI_VENV_PYTHON", raising=False)
    dev = fake_python(tmp_path / "dev" / ".venv" / "bin" / "python")
    monkeypatch.setattr(lpr, "DEV_VENV_PYTHON", dev)
    own = fake_python(tmp_path / "tree" / ".venv" / "bin" / "python")
    assert lpr.venv_python(tmp_path / "tree") == str(own)
    release = tmp_path / "release"                     # a served release: no .venv
    release.mkdir()
    assert lpr.venv_python(release) == str(dev)
    monkeypatch.setattr(lpr, "DEV_VENV_PYTHON", tmp_path / "missing" / "python")
    assert lpr.venv_python(release) == (sys.executable or "python3")


def run_helper(tmp_path, root, **env):
    script = f'. "{ROOT}/scripts/lib/venv_python.sh"; tradeai_venv_python "{root}"'
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path / "home")}
    base.update(env)
    return subprocess.run(["bash", "-c", script], env=base, capture_output=True, text=True, check=True).stdout.strip()


def test_shell_helper_order(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    canon = fake_python(tmp_path / "home" / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild" / ".venv" / "bin" / "python")
    assert run_helper(tmp_path, release) == str(canon)                    # release without .venv → canonical venv
    cron_py = fake_python(tmp_path / "cron" / "python")
    assert run_helper(tmp_path, release, PY=str(cron_py)) == str(cron_py)  # crontab-exported $PY
    env_py = fake_python(tmp_path / "env" / "python3")
    assert run_helper(tmp_path, release, PY=str(cron_py), TRADEAI_VENV_PYTHON=str(env_py)) == str(env_py)
    assert run_helper(tmp_path, release, PY="bash") == str(canon)          # a non-python $PY is ignored


def test_scheduled_python_jobs_no_longer_assume_a_release_venv():
    for name in FIXED_PY:
        src = (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert not RELEASE_RELATIVE.search(src), name
        assert "from lib.live_project_root import venv_python" in src, name


def test_scheduled_launchers_use_the_helper():
    for rel in FIXED_SH:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert 'PY="$(tradeai_venv_python "$PROJ")"' in src, rel
        assert '[ -x "$PY" ] || PY="python3"' not in src, rel
