"""Grammar check for remediation command lines that still run through a shell (injection triage 21, 2026-11-06).

Several self-heal paths run a command line read from a runtime store (``config_documents``, ``pipeline_schedule``,
``pipeline_stages``) with ``shell=True``. Anyone who can write one of those rows could run any command on the host.
The real command lines need a shell (``>> log 2>&1`` redirects, ``flock`` prefixes, ``bash -c 'a && b'`` chains),
so instead of an argument list they are checked against the one narrow shape they all share, and refused otherwise:

    cmd     := [ 'cd' ROOT '&&' ] [ prefix ] body [ '>>' 'logs/<name>.log' '2>&1' ]
    prefix  := 'flock' '-n' LOCK | 'bash' 'scripts/safe_flock.sh' LOCK
    body    := pyinv | 'bash' '-c' '<pyinv> [&& <pyinv>]*'
    pyinv   := PY 'scripts/<path>.py' ARG* | 'bash' 'linux_launchers/<name>.sh' ARG*

``PY`` is ``python``/``python3`` on PATH or the project venv's (relative, or under an allowed root). ``LOCK`` is a
``/tmp/<name>.lock`` file. ``ARG`` is a plain word (letters, digits, ``_ . / = : , @ % + -``). Any character a shell
treats as syntax outside that grammar (``$`` backtick ``;`` ``|`` ``<`` newline backslash, a lone ``&`` or ``>``) is
refused before parsing.
"""
from __future__ import annotations

import re
import shlex
from typing import Iterable

_FORBIDDEN = ("`", "$", ";", "|", "<", "\n", "\r", "\\", "\x00")
_LOCK = re.compile(r"^/tmp/[A-Za-z0-9_.-]+\.lock$")
_SCRIPT = re.compile(r"^scripts/[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*\.py$")
_ARG = re.compile(r"^[A-Za-z0-9_./=:,@%+-]+$")
_LOG = re.compile(r"^logs/[A-Za-z0-9_.-]+\.log$")
_LAUNCHER = re.compile(r"^linux_launchers/[A-Za-z0-9_]+\.sh$")
_PY_REL = re.compile(r"^(?:(?:\./)?\.venv/bin/)?python3?$")


def _py_ok(tok: str, roots: tuple[str, ...]) -> bool:
    if _PY_REL.match(tok):
        return True
    return any(tok in (f"{r}/.venv/bin/python", f"{r}/.venv/bin/python3") for r in roots)


def _pyinv(toks: list[str], roots: tuple[str, ...]) -> str | None:
    """None when ``toks`` is one interpreter call of a repo script with plain args; else the reason."""
    if len(toks) < 2:
        return "expected '<python> scripts/<name>.py [args]'"
    if toks[0] == "bash" and _LAUNCHER.match(toks[1]):
        pass
    elif not _py_ok(toks[0], roots):
        return f"interpreter not allowed: {toks[0][:80]!r}"
    elif ".." in toks[1] or not _SCRIPT.match(toks[1]):
        return f"script not allowed: {toks[1][:80]!r}"
    for a in toks[2:]:
        if ".." in a.split("/") or not _ARG.match(a):
            return f"argument not allowed: {a[:80]!r}"
    return None


def _split(text: str) -> list[str] | str:
    try:
        return shlex.split(text, posix=True)
    except ValueError as exc:
        return f"unparseable: {exc}"


def check_command(cmd: object, roots: Iterable[str] = ()) -> tuple[bool, str]:
    """(True, "ok") when ``cmd`` fits the grammar above, else (False, reason). Never raises."""
    if not isinstance(cmd, str) or not cmd.strip():
        return False, "empty or non-string command"
    if len(cmd) > 2000:
        return False, "command too long"
    bad = [c for c in _FORBIDDEN if c in cmd]
    if bad:
        return False, f"shell syntax not allowed: {bad!r}"
    roots_t = tuple(str(r).rstrip("/") for r in roots if r)
    toks = _split(cmd)
    if isinstance(toks, str):
        return False, toks

    if toks[:1] == ["cd"]:
        if len(toks) < 4 or toks[2] != "&&":
            return False, "'cd' must be 'cd <root> && ...'"
        if toks[1].rstrip("/") not in roots_t:
            return False, f"cd target not allowed: {toks[1][:80]!r}"
        toks = toks[3:]

    if len(toks) >= 3 and toks[-3] == ">>" and toks[-1] == "2>&1":
        if not _LOG.match(toks[-2]):
            return False, f"log path not allowed: {toks[-2][:80]!r}"
        toks = toks[:-3]

    if toks[:2] == ["flock", "-n"] or toks[:2] == ["bash", "scripts/safe_flock.sh"]:
        if len(toks) < 3 or not _LOCK.match(toks[2]):
            return False, "lock file must be /tmp/<name>.lock"
        toks = toks[3:]

    if toks[:2] == ["bash", "-c"]:
        if len(toks) != 3:
            return False, "'bash -c' takes exactly one quoted command"
        inner = _split(toks[2])
        if isinstance(inner, str):
            return False, inner
        parts: list[list[str]] = [[]]
        for t in inner:
            if t == "&&":
                parts.append([])
            else:
                parts[-1].append(t)
        for p in parts:
            why = _pyinv(p, roots_t)
            if why:
                return False, why
        return True, "ok"

    why = _pyinv(toks, roots_t)
    return (False, why) if why else (True, "ok")
