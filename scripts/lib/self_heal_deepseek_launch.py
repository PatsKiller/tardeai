#!/usr/bin/env python3
"""Repo-owned DeepSeek launcher for the self-heal fixer (2026-11-03).

The fixer must run the coding model on DeepSeek without ever putting the key where the model
can read it: not in the agent env whitelist, not in the pytest wrapper it can execute, not in
any tool output. So the key arrives on an inherited file descriptor (opened OUTSIDE the bwrap
sandbox by the fixer), and this launcher only:

* sets the DeepSeek endpoint and model for the CLI,
* names the descriptor for the CLI (`CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR`) instead of setting
  ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY in the environment,
* preserves the caller's working directory (the candidate worktree — the old operator wrapper
  did `cd $REPO`, which silently moved edits to the live tree),
* execs the CLI.

The key itself is never read here, never printed, and never written to a file.
"""
from __future__ import annotations

import os
import sys

BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_MODEL = "deepseek-flash[1m]"
FD_ENV = "TRADEAI_DEEPSEEK_KEY_FD"


def build_env(environ: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """(env for the CLI, problems). The key stays in the descriptor; only its number is named."""
    env = dict(environ)
    problems: list[str] = []
    fd = str(env.get(FD_ENV) or "").strip()
    if not fd.isdigit():
        problems.append(f"{FD_ENV} is not a descriptor number")
    env["ANTHROPIC_BASE_URL"] = BASE_URL
    env["ANTHROPIC_MODEL"] = env.get("TRADEAI_DEEPSEEK_MODEL") or DEFAULT_MODEL
    if fd.isdigit():
        env["CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR"] = fd
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "TRADEAI_DEEPSEEK_MODEL"):
        env.pop(k, None)
    return env, problems


def main(argv: list[str]) -> int:
    env, problems = build_env(dict(os.environ))
    if problems:
        print("self_heal_deepseek_launch: " + "; ".join(problems), file=sys.stderr)
        return 2
    # cwd is inherited unchanged on purpose: the fixer runs this with the candidate worktree as cwd.
    os.execvpe("claude", ["claude", *argv], env)
    return 127  # execvpe only returns by raising


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
