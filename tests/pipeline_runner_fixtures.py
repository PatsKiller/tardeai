"""Scratch source and environment fixtures for pipeline subprocess tests (AGENTS.md §24.6)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def sandbox_runner(root: Path, runner: Path) -> Path:
    """Copy source so common-library initialization cannot write checkout logs."""
    dest = root / "scripts" / "pipelines"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (runner.name, "_manifest_runner.sh", "_pipeline_common.sh", "pipeline_manifest.py"):
        shutil.copyfile(runner.parent / name, dest / name)
    return dest / runner.name


def runner_env(root: Path) -> dict[str, str]:
    for name in ("home", "tmp", "locks", "persistent-state"):
        (root / name).mkdir(parents=True, exist_ok=True)
    dotenv_fixture = root / "empty-dotenv-fixture"
    dotenv_fixture.write_text("", encoding="utf-8")
    return {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "HOME": str(root / "home"),
        "TMPDIR": str(root / "tmp"),
        "LANG": "C.UTF-8",
        "LOGNAME": "tester",
        "SHELL": "/bin/bash",
        "PY": sys.executable,
        "TRADEAI_PY": sys.executable,
        "TRADE_AI_CI": "1",
        "M2_SKIP_DOCKER": "1",
        "CIO_TELEGRAM_INTERDICT": "1",
        "ENABLE_TELEGRAM": "0",
        "TRADEAI_STATE_ROOT": str(root / "persistent-state"),
        "TRADEAI_ENV_BOOTSTRAP_FILES": str(dotenv_fixture),
        "PIPELINE_LOCK_DIR": str(root / "locks"),
        "PIPELINE_TODAY_DOW": "3",
    }
