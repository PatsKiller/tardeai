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
STDIN_ENV = "TRADEAI_DEEPSEEK_KEY_STDIN"


def read_key_line(fd: int = 0, limit: int = 4096) -> bytes:
    """The key is the FIRST LINE of stdin. Read byte-by-byte: a buffered reader would swallow prompt bytes."""
    out = bytearray()
    while len(out) <= limit:
        b = os.read(fd, 1)
        if not b or b == b"\n":
            break
        out += b
    return bytes(out)


def seal_key(key: bytes) -> int:
    """Copy the key into an anonymous memfd the CLI can read by descriptor. No path, no file, no env value."""
    fd = os.memfd_create("tradeai-deepseek-key", 0)
    os.write(fd, key)
    os.lseek(fd, 0, os.SEEK_SET)
    os.set_inheritable(fd, True)
    return fd


def build_env(environ: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """(env for the CLI, problems). The key stays in the descriptor; only its number is named."""
    env = dict(environ)
    problems: list[str] = []
    fd = str(env.get(FD_ENV) or "").strip()
    if not fd.isdigit():
        problems.append(f"{FD_ENV} is not a descriptor number")
    env["ANTHROPIC_BASE_URL"] = BASE_URL
    env["ANTHROPIC_MODEL"] = env.get("TRADEAI_DEEPSEEK_MODEL") or DEFAULT_MODEL
    # the CLI is not on the sandbox PATH; the fixer names the exact binary it bound read-only
    cli = env.pop("TRADEAI_CLAUDE_BIN", "") or "claude"
    env["_TRADEAI_CLAUDE_BIN"] = cli
    if fd.isdigit():
        env["CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR"] = fd
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "TRADEAI_DEEPSEEK_MODEL"):
        env.pop(k, None)
    return env, problems


def main(argv: list[str]) -> int:
    raw = dict(os.environ)
    if raw.get(STDIN_ENV) == "1":
        key = read_key_line()
        if not key:
            print("self_heal_deepseek_launch: empty key line on stdin", file=sys.stderr)
            return 2
        raw[FD_ENV] = str(seal_key(key))
        raw.pop(STDIN_ENV, None)
    env, problems = build_env(raw)
    if problems:
        print("self_heal_deepseek_launch: " + "; ".join(problems), file=sys.stderr)
        return 2
    # cwd is inherited unchanged on purpose: the fixer runs this with the candidate worktree as cwd.
    cli = env.pop("_TRADEAI_CLAUDE_BIN", "claude")
    # exec, not a subprocess: the contract is to keep the caller's cwd, stdin and the sealed key descriptor.
    os.execvpe(cli, [cli, *argv], env)  # noqa: S606 — exec is the point, not a shell-out
    return 127  # execvpe only returns by raising


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
