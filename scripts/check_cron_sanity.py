#!/usr/bin/env python3
"""check_cron_sanity.py — verify every scripts/*.py reference in the crontab exists.

Prevents the C8 class bug (dead cron entries referencing non-existent scripts) from
recurring.  Also warns on scripts referenced without flock guards where appropriate.

Exit 0 if clean, exit 1 if stale references found.  Designed to be called both as a
standalone checker and imported as a health_agent collector.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_crontab_script_refs(crontab_text: str) -> list[tuple[str, str]]:
    """Return [(script_path, cron_line_short)] for every scripts/*.py reference."""
    refs = []
    for line in crontab_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # Find all scripts/*.py or scripts/*.sh references
        import re
        for m in re.finditer(r'scripts/[\w/-]+\.(?:py|sh)', stripped):
            refs.append((m.group(0), stripped[:120]))
    return refs


def resolve_script_refs(crontab_text: str, project_root: Path) -> list[tuple[str, Path, str]]:
    """[(script_ref, resolved_path, cron_line_short)], resolved the way cron will run the line.

    parse_crontab_script_refs() yields bare `scripts/x.py` matches, and check() joined every one onto
    this repo. Lines that `cd` into another project (nyc-dof-auction, a review worktree) or call a
    script by absolute path (~/.openclaw/skills/...) were reported as dead although they run
    (6 of 12 cron_dead_script_ref findings on 2026-09-15). Resolution order: an absolute or
    $VAR-prefixed path as written, else relative to the line's first `cd <dir>`, else the repo.
    """
    import os
    import re
    env = {"HOME": os.path.expanduser("~")}
    refs: list[tuple[str, Path, str]] = []
    for line in crontab_text.splitlines():
        stripped = line.strip()
        m_var = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
        if m_var and " " not in m_var.group(2).strip():
            env[m_var.group(1)] = m_var.group(2).strip().strip('"')
            continue
        if stripped.startswith("#") or not stripped:
            continue
        # A trailing comment is not part of the command ("# lane x (was scripts/old.py)").
        stripped = re.split(r"\s#", stripped, maxsplit=1)[0].rstrip()

        def expand(text: str) -> str:
            return re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: env.get(m.group(1), m.group(0)), text)

        m_cd = re.search(r"(?:^|[;&|]\s*|\s)cd\s+(\S+)", stripped)
        base_text = expand(m_cd.group(1).strip("\"'")) if m_cd else str(project_root)
        for m in re.finditer(r"(\S*?)(scripts/[\w/-]+\.(?:py|sh))", stripped):
            prefix, ref = m.group(1), m.group(2)
            prefix = prefix.split("=")[-1]
            written = expand(prefix.strip("\"'") + ref)
            target = written if written.startswith("/") else f"{base_text}/{ref}"
            if "$" in target:
                continue  # resolved only at run time (e.g. cd "$CUR" from readlink): not provable dead here
            refs.append((ref, Path(target), stripped[:120]))
    return refs


# ── P1 audit linters (2026-09-26) ─────────────────────────────────────────────
# Findings measured on the live crontab (467 schedule lines) that this checker
# did not see because it only tested that scripts/*.py files exist:
#   R-02  three CURRENT crons run a RELATIVE `.venv/bin/python` inside a release
#         that ships no .venv (rsync excludes it since 2026-09-25) -> `flock:
#         failed to execute .venv/bin/python`, next failure Sun 09:00 ET.
#   R-05  alpaca_stop_manager.py scheduled on two lines with different locks
#         (one with none), colliding at 09:00/10:00 -> concurrent broker stop
#         mutations possible.
#   R-10  a line with no `cd` runs a relative scripts/ path from $HOME (fails
#         32x/day); `python3 -c "..."` one-liners whose inner double quotes end
#         the shell string (NameError every run).
# All checks are pure functions of the crontab text plus an injectable
# `exists` predicate so tests never touch the host.

_CRON_VAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_CD_RE = re.compile(r"\bcd\s+(\S+)")
_REL_PY_RE = re.compile(r"(?<![\w/.$])(\.venv/bin/python3?|python3?)\s+(scripts/[\w./-]+\.py)")
_FLOCK_RE = re.compile(r"flock\s+(?:-[a-zA-Z]+\s+)*(\S+)")
_SCRIPT_RE = re.compile(r"scripts/[\w/-]+\.py")
_MUTATING_FLAGS = ("--apply", "--repair-oco", "--execute", "--write", "--place")
_BROKER_TOUCHING = ("stop", "order", "oco", "schwab", "alpaca", "broker", "moomoo", "position_sync")


def cron_env(crontab_text: str) -> dict[str, str]:
    """Variable assignments at the top of a crontab (PROJ=, PY=, ...)."""
    env: dict[str, str] = {}
    for line in crontab_text.splitlines():
        m = _CRON_VAR_RE.match(line.strip())
        if m and not line.strip().startswith("#"):
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def _expand(value: str, env: dict[str, str]) -> str:
    out = value
    for k, v in env.items():
        out = out.replace(f"${{{k}}}", v).replace(f"${k}", v)
    return os.path.expanduser(out.replace("$HOME", os.path.expanduser("~")))


def _schedule_lines(crontab_text: str) -> list[tuple[int, str]]:
    rows = []
    for i, line in enumerate(crontab_text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or _CRON_VAR_RE.match(s):
            continue
        rows.append((i, s))
    return rows


def _cd_target(line: str, env: dict[str, str]) -> str | None:
    m = _CD_RE.search(line)
    return _expand(m.group(1), env) if m else None


def check_relative_interpreters(crontab_text: str, *, exists=os.path.exists) -> list[dict]:
    """R-02: a relative interpreter (`.venv/bin/python`) must exist under the line's cwd."""
    env = cron_env(crontab_text)
    out = []
    for n, line in _schedule_lines(crontab_text):
        cwd = _cd_target(line, env)
        for m in _REL_PY_RE.finditer(line):
            interp = m.group(1)
            if not interp.startswith(".venv"):
                continue
            base = cwd or os.path.expanduser("~")
            target = os.path.join(base, interp)
            if not exists(target):
                out.append({
                    "category": "execution_health", "type": "cron_interpreter_missing",
                    "severity": "warning", "line": n,
                    "message": (f"cron line {n}: relative interpreter {interp} does not exist under "
                                f"{base} — use $PY or ship a venv ({line[:100]})"),
                })
    return out


def check_relative_paths_without_cd(crontab_text: str) -> list[dict]:
    """R-10: a relative scripts/ path with no `cd` runs from $HOME."""
    out = []
    for n, line in _schedule_lines(crontab_text):
        if _CD_RE.search(line):
            continue
        if re.search(r"(?<![\w/])scripts/[\w./-]+\.(?:py|sh)", line) and "$PROJ/scripts" not in line \
                and "/scripts/" not in line.split("scripts/", 1)[0][-1:] + "x":
            # relative reference and no absolute prefix immediately before it
            if re.search(r"(^|\s)scripts/", line):
                out.append({
                    "category": "execution_health", "type": "cron_relative_path_no_cd",
                    "severity": "warning", "line": n,
                    "message": f"cron line {n}: relative scripts/ path with no `cd` — runs from $HOME ({line[:100]})",
                })
    return out


def check_shared_script_locks(crontab_text: str, *, mutating_only: bool = True) -> list[dict]:
    """R-05: one mutating script on several lines must share ONE flock lock."""
    by_script: dict[str, list[tuple[int, str | None]]] = {}
    for n, line in _schedule_lines(crontab_text):
        scripts = set(_SCRIPT_RE.findall(line))
        if not scripts:
            continue
        if mutating_only and not any(f in line for f in _MUTATING_FLAGS):
            continue
        m = _FLOCK_RE.search(line)
        lock = m.group(1) if m else None
        for sc in scripts:
            if sc.endswith(("market_day_gate.sh", "safe_flock.sh", "llm_priority_guard.sh")):
                continue
            by_script.setdefault(sc, []).append((n, lock))
    out = []
    for sc, rows in by_script.items():
        if len(rows) < 2:
            continue
        locks = {lock for _, lock in rows}
        if len(locks) > 1 or None in locks:
            # Broker/stop/order-touching scripts overlapping is a safety defect;
            # other overlaps (digest vs notify, --type fan-out) are reported as info.
            broker = any(k in sc.lower() for k in _BROKER_TOUCHING)
            out.append({
                "category": "execution_health", "type": "cron_shared_script_lock_conflict",
                "severity": "warning" if broker else "info", "lines": [n for n, _ in rows],
                "message": (f"{sc} is scheduled on lines {[n for n, _ in rows]} with locks "
                            f"{sorted(str(lk) for lk in locks)} — mutating runs can overlap; use one lock"),
            })
    return out


def check_inline_python_quoting(crontab_text: str) -> list[dict]:
    """R-10: `python3 -c "..."` whose body contains unescaped double quotes."""
    out = []
    for n, line in _schedule_lines(crontab_text):
        m = re.search(r"python3?\s+-c\s+\"(.*)$", line)
        if not m:
            continue
        body = m.group(1)
        # the closing quote plus any inner unescaped quote means the shell string ended early
        inner = body.rstrip().rstrip(";")
        closing = inner.rfind('"')
        if closing > 0 and '"' in inner[:closing].replace('\\"', ""):
            out.append({
                "category": "execution_health", "type": "cron_inline_python_quoting",
                "severity": "warning", "line": n,
                "message": f"cron line {n}: python -c body contains unescaped double quotes — the shell string ends early ({line[:100]})",
            })
    return out


def lint_crontab(crontab_text: str, *, exists=os.path.exists) -> list[dict]:
    """All P1 linters over one crontab text (pure; used by tests and by check())."""
    return (check_relative_interpreters(crontab_text, exists=exists)
            + check_relative_paths_without_cd(crontab_text)
            + check_shared_script_locks(crontab_text)
            + check_inline_python_quoting(crontab_text))


def check() -> list[dict]:
    """Return findings list (health_agent collector format).  Empty = clean."""
    findings = []
    try:
        try:
            from lib.crontab_snapshot import read_crontab
        except ImportError:
            from scripts.lib.crontab_snapshot import read_crontab  # type: ignore
        read = read_crontab(root=PROJECT_ROOT)
    except Exception as e:
        return [{"category": "execution_health", "type": "cron_sanity_check_failed",
                 "severity": "warning",
                 "message": f"Could not read crontab: {e}"}]
    if not read.ok:
        # Hardened user-systemd (NoNewPrivileges) strips crontab setgid, so
        # /var/spool/cron/crontabs/$USER is unreadable. R-03 (2026-09-26): that
        # used to silence every cron check as "info". With no fresh snapshot
        # either, say so as a WARNING — the checks are not running.
        return [{
            "category": "execution_health",
            "type": "cron_sanity_check_hardened",
            "severity": "warning",
            "message": (f"cron checks NOT run: {read.error}. Install the snapshot cron line "
                        f"(lib.crontab_snapshot.SNAPSHOT_CRON_LINE) so the hardened agent can read it."),
        }]
    class _Proc:  # keep the downstream shape (proc.stdout)
        stdout = read.text
    proc = _Proc()
    if read.source == "snapshot":
        findings.append({"category": "execution_health", "type": "cron_sanity_via_snapshot",
                         "severity": "info",
                         "message": f"crontab read from snapshot ({(read.age_s or 0)/60:.0f}m old); crontab -l denied"})

    for script_path, full_path, cron_line in resolve_script_refs(proc.stdout, PROJECT_ROOT):
        if not full_path.is_file():
            findings.append({
                "category": "execution_health",
                "type": "cron_dead_script_ref",
                "severity": "warning",
                "message": f"Crontab references non-existent script: {script_path} "
                           f"({'…' + cron_line[-80:] if len(cron_line) > 80 else cron_line})",
            })

    findings.extend(lint_crontab(proc.stdout))
    return findings


def main() -> int:
    findings = check()
    if not findings:
        print("✓ Crontab clean — all script references exist")
        return 0
    for f in findings:
        print(f"[{f['severity'].upper()}] {f['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
