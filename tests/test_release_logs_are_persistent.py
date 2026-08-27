"""A release must not start its evidence stores from empty.

`logs/` is gitignored, so every release directory began with an EMPTY one and
accumulated only what ran after that deploy. That orphaned far more than logs:
claude_escalation_queue.json, health_agent.jsonl, health_agent_remediation.jsonl,
claude_escalation_retry_cmd.jsonl and safe_flock_events.jsonl all live there.

Measured 2026-08-27: the 18:48 deploy abandoned an 18-entry escalation queue and
restarted the health agent's append-only history from zero (1735 -> 579 bytes);
147 of 160 release dirs hold such a fork. It also made "did that cron job run?"
answer ABSENT for a job that had run 28 minutes earlier.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "scripts/cio_phase2_exact_main_deploy.sh"


def _linked_dirs() -> list[str]:
    """The dirs array that link_pipeline_data symlinks to canonical storage."""
    src = DEPLOY.read_text(encoding="utf-8")
    block = src.split("local dirs=(", 1)[1].split(")", 1)[0]
    return re.findall(r'"([^"]+)"', block)


def test_logs_is_linked_to_canonical_storage():
    assert "logs" in _linked_dirs(), (
        "a release-local logs/ forks the escalation queue and health history")


def test_the_existing_data_links_are_not_disturbed():
    """Additive change only -- these five were already correct."""
    dirs = _linked_dirs()
    for rel in ("data/portfolios/state", "state/data_broker",
                "data/runtime", "data/health", "data/cio"):
        assert rel in dirs, rel


def test_the_deploy_script_still_parses():
    assert subprocess.run(["bash", "-n", str(DEPLOY)]).returncode == 0


def test_the_link_mechanism_replaces_a_directory_with_a_symlink(tmp_path):
    """Exercise the loop's actual semantics: rm -rf, mkdir -p, ln -sfn.

    A release arrives with a real (empty) logs dir; the deploy must replace it
    with a link to canonical storage, not merge into it.
    """
    canonical = tmp_path / "persistent" / "logs"
    canonical.mkdir(parents=True)
    (canonical / "health_agent.jsonl").write_text("kept\n", encoding="utf-8")

    dest = tmp_path / "release"
    (dest / "logs").mkdir(parents=True)
    (dest / "logs" / "stale.log").write_text("from the rsync\n", encoding="utf-8")

    rel, target, source = "logs", dest / "logs", canonical
    subprocess.run(["bash", "-c",
                    f'rm -rf "{target}"; mkdir -p "$(dirname "{target}")"; '
                    f'ln -sfn "{source}" "{target}"'], check=True)

    assert target.is_symlink()
    assert target.resolve() == canonical.resolve()
    assert (target / "health_agent.jsonl").read_text() == "kept\n"
    assert not (canonical / "stale.log").exists(), "release-local content must not leak in"
