"""
Resolve the canonical live server project root directory.

Priority chain:
  1. CURRENT symlink (authoritative — set by deploy_portfolio_server.sh at deploy time)
  2. RuntimeAwareness (dynamic discovery — finds the PID on port 7777 and its working directory)
  3. __file__ fallback (dev directory — the existing behavior, used when no live server is running)

Usage:
    from lib.live_project_root import get_live_project_root
    PROJECT_ROOT = get_live_project_root()
"""
import os
from pathlib import Path

CURRENT_SYMLINK = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
DEV_ROOT = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
DEV_VENV_PYTHON = DEV_ROOT / ".venv" / "bin" / "python"


def get_live_project_root() -> Path:
    """
    Return the Path to the live server's project root.
    Prefers CURRENT symlink > RuntimeAwareness > dev directory fallback.
    """
    # 1. CURRENT symlink (authoritative, set at deploy time)
    if CURRENT_SYMLINK.is_symlink():
        target = CURRENT_SYMLINK.resolve()
        if target.is_dir():
            return target

    # 2. RuntimeAwareness (dynamic discovery)
    try:
        from lib.runtime_awareness import RuntimeAwareness   # type: ignore
        ra = RuntimeAwareness()
        ra.discover()
        live_dir = ra.get_live_directory()
        if live_dir and os.path.isdir(live_dir):
            return Path(live_dir)
    except Exception:
        pass

    # 3. __file__ fallback (dev directory)
    return DEV_ROOT


def venv_python(code_root=None) -> str:
    """The interpreter a scheduled job should launch child Python steps with.

    Release directories (portfolio-server/<sha>-…) ship no .venv, and every cron line `cd`s into the
    served CURRENT release, so `<code_root>/.venv/bin/python` exists in no release: on 2026-10-09
    hermes_coordinator's research_curator / options_research_bridge / embedding_worker steps failed with
    "No such file" on every tick. Order: TRADEAI_VENV_PYTHON (the executor/crontab contract), the code
    root's own .venv (dev tree, worktrees), the canonical dev venv, then the running interpreter.
    """
    import sys

    cands = [os.environ.get("TRADEAI_VENV_PYTHON") or ""]
    if code_root is not None:
        cands.append(str(Path(code_root) / ".venv" / "bin" / "python"))
    cands.append(str(DEV_VENV_PYTHON))
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return sys.executable or "python3"
