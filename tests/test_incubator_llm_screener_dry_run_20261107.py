"""incubator-llm-screener's ``--dry-run`` is the n8n cutover's write-free proof (LQ-20261107-25).

The lane is an n8n llm-class member (its own docstring names the governed bridge and the allowlist ``llm_route``),
so the onboarding step is the shadow dry run. On 2026-11-07 that step could not run at all: ``main()`` called
``get_db()`` before it looked at the flag, so ``--dry-run`` died with

    psycopg2.OperationalError: connection to server at "127.0.0.1", port 5432 failed: fe_sendauth: no password supplied

and a dry run that cannot run is not a proof. The fix puts the arm before the ``.env`` load, argparse and the DB
connection -- the same shape the other onboarded lanes use (scripts/agent_watchlist_engine.py).

Proved by execution, not by reading the flag: the script is run as a subprocess in a directory with no ``.env`` and
no database credentials, and it must exit 0, print its plan, emit one ``LaneOutput@v1`` line on stderr with
``empty_reason`` dry_run, and leave the state tree and the code tree byte-identical.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "incubator_llm_screener.py"


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__")]
        for f in files:
            p = Path(d) / f
            try:
                st = p.stat()
            except OSError:
                continue
            out[str(p)] = (st.st_mtime_ns, st.st_size)
    return out


def _env_without_credentials() -> dict[str, str]:
    """A clean environment: no DB/LLM variables, no .env on the path -- the worst case for the arm."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("DB_", "PG", "DEEPSEEK", "OPENAI", "ANTHROPIC", "TRADEAI_LLM"))}
    env["DOTENV_LOADED"] = "0"
    return env


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--dry-run"], cwd=tmp_path,
                          capture_output=True, text=True, env=_env_without_credentials(), timeout=120)


def test_dry_run_is_an_offline_plan_that_needs_no_database(tmp_path):
    before_state = _tree(tmp_path)
    before_code = _tree(PROJECT_ROOT / "scripts")
    proc = _run(tmp_path)
    assert proc.returncode == 0, f"the onboarding dry run must exit 0, got {proc.returncode}: {proc.stderr[-800:]}"
    assert "DRY-RUN incubator-llm-screener" in proc.stdout
    assert "nothing read from env/DB/network" in proc.stdout
    assert "psycopg2" not in proc.stderr and "OperationalError" not in proc.stderr
    assert _tree(tmp_path) == before_state, "the dry run wrote into its working directory"
    assert _tree(PROJECT_ROOT / "scripts") == before_code, "the dry run wrote into the code tree"


def test_dry_run_emits_the_lane_output_block_the_executor_reads(tmp_path):
    proc = _run(tmp_path)
    lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("LANE_OUTPUT ")]
    assert lines, f"no LaneOutput@v1 line on stderr: {proc.stderr[-500:]!r}"
    payload = json.loads(lines[-1].split(" ", 1)[1])
    assert payload["schema"] == "LaneOutput@v1"
    assert payload["lane_id"] == "incubator-llm-screener"
    assert payload["mode"] == "dry_run"
    assert payload["produced_count"] == 0
    assert payload["empty_reason"] == "dry_run"
    assert payload["unit"] == "incubator_candidate"


def test_dry_run_wins_over_the_live_flag(tmp_path):
    """`--run --dry-run` plans; it never reaches the live path that would need the database."""
    proc = subprocess.run([sys.executable, str(SCRIPT), "--run", "--dry-run"], cwd=tmp_path,
                          capture_output=True, text=True, env=_env_without_credentials(), timeout=120)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "DRY-RUN incubator-llm-screener" in proc.stdout
