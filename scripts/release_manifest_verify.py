#!/usr/bin/env python3
"""Named release-bound manifest + post-activate CODE IDENTITY verifier (sprint 8H-2, operator item 2). Read-only.

Discovers every entry that loads repo code from three sources:

* systemd user services (``systemctl --user show``: ExecStart argv + WorkingDirectory; the Environment is never read);
* the user crontab (``crontab -l``; ``NAME=value`` assignments are expanded into later lines);
* the n8n executor lanes (``config/lane_registry.json`` rows with ``dispatch.mode == "live"``; they run with
  ``cwd = code_root``, which is the executor's own release root unless its argv carries ``--code-root``).

For each entry it proves code identity, not ActiveState:

* a RUNNING process: ``/proc/<pid>/cwd`` and its absolute script argument must both resolve into the release that
  ``CURRENT`` points at, AND the process must have started at or after the activation (``CURRENT`` symlink mtime
  unless ``--activated-at`` is given);
* a NOT-RUNNING timer/oneshot service or a cron line: the next-run code path must name the ``CURRENT`` symlink (it
  resolves at the next start) or the concrete current release dir. A path pinned to another release is FAIL;
* n8n lanes: PASS only when the executor process itself PASSes and has no ``--code-root`` override.

Verdicts: PASS, FAIL, UNKNOWN (could not measure: never green), NOT_RELEASE (loads code from the canonical checkout
or an agent worktree, not from a release; listed so the drift is visible, not counted as release-bound).

The python interpreter path (often the canonical ``.venv``) is recorded as a note and excluded from the code root:
it supplies the interpreter and site-packages, not repo code. Nothing here restarts, writes to systemd or edits a
crontab; the only output is stdout and, with ``--out``, the named report files.

  python scripts/release_manifest_verify.py [--current <link>] [--activated-at ISO] [--out <file.md>] [--json]
Exit: 0 no FAIL, 1 any FAIL, 2 discovery failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import current_bound_units as cbu  # noqa: E402

RELEASES_BASE = cbu.RELEASES_BASE
DEFAULT_CANONICAL = Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild"
WORKTREE_MARKERS = ("/data/worktrees/", "/tradeai-wt-")
_INTERP = re.compile(r"\S*/(?:\.venv|venv|bin)/python[0-9.]*\b|\S*/\.venv/bin/\S+")

PASS, FAIL, UNKNOWN, NOT_RELEASE = "PASS", "FAIL", "UNKNOWN", "NOT_RELEASE"


@dataclass
class Entry:
    name: str
    kind: str  # service-running | service-next-run | cron | n8n-lanes
    expected: str
    observed: str
    evidence: str
    verdict: str
    lifecycle: str = ""


# ---------------------------------------------------------------- pure classification


def strip_interpreters(text: str) -> tuple[str, list[str]]:
    """Remove interpreter tokens (``…/.venv/bin/python``) from ``text``; return (rest, interpreters)."""
    found = _INTERP.findall(text or "")
    return _INTERP.sub(" ", text or ""), found


def code_roots(text: str, releases_base: str, canonical: str) -> set[str]:
    """Which code roots a command/path text names: CURRENT, REL:<dir>, CANONICAL, WORKTREE:<dir>."""
    roots: set[str] = set()
    base = releases_base.rstrip("/") + "/"
    for m in re.finditer(re.escape(base) + r"([A-Za-z0-9_.-]+)", text or ""):
        seg = m.group(1)
        roots.add("CURRENT" if seg == "CURRENT" else f"REL:{seg}")
    if canonical and (canonical.rstrip("/") + "/" in (text or "") or re.search(re.escape(canonical.rstrip("/")) + r"(?=$|[\s'\";])", text or "")):
        roots.add("CANONICAL")
    for marker in WORKTREE_MARKERS:
        for m in re.finditer(r"(\S*" + re.escape(marker) + r"[^/\s'\";]*)", text or ""):
            roots.add(f"WORKTREE:{m.group(1)}")
    return roots


def code_text(rest: str, wd: str) -> str:
    """The text that names the code a command loads: its .py/.sh script tokens (a relative one resolves against a
    preceding ``cd <dir>`` or the WorkingDirectory); with no script token (``-m``/``-c``), the command plus the
    WorkingDirectory. Paths passed as plain arguments (``--repo <checkout>``) are not code roots."""
    m = re.search(r"\bcd\s+([^\s;&|]+)", rest or "")
    base = (m.group(1) if m else wd or "").rstrip("/")
    toks = re.findall(r"[^\s'\";=()]+\.(?:py|sh)\b", rest or "")
    if toks:
        return " ".join(t if t.startswith(("/", "$")) else f"{base}/{t}" for t in toks)
    return f"{rest} {wd}"


_LOOP = re.compile(r"for\s+(\w+)\s+in\s+([^;]+);\s*do\s+if\s+\[\s+-f\s+\"?\$\{?\1\}?/([^\"\s\]]+)\"?\s*\]")


def resolve_candidate_loop(text: str, exists: Callable[[str], bool] = os.path.isfile) -> Optional[tuple[str, str]]:
    """``for CAND in A B C; do if [ -f "$CAND/<rel>" ]; then cd "$CAND"; exec …`` runs from the FIRST candidate
    holding <rel>. Returns (chosen_dir/<rel>, evidence) by applying the same ``-f`` test, or None if no such loop.
    No candidate holding the file => ("", evidence): the next run exits 1 before loading code."""
    m = _LOOP.search(text or "")
    if not m:
        return None
    cands, rel = m.group(2).split(), m.group(3)
    for c in cands:
        if exists(f"{c.rstrip('/')}/{rel}"):
            return f"{c.rstrip('/')}/{rel}", f"candidate loop: first of {len(cands)} holding {rel} is {c}"
    return "", f"candidate loop: none of {len(cands)} candidates holds {rel}"


def missing_roots(roots: set[str], wd: str, releases_base: str, canonical: str,
                  dir_exists: Callable[[str], bool] = os.path.isdir) -> list[str]:
    """Directories the next run needs that do not exist (WorkingDirectory, a release, the checkout, a worktree).
    A unit or cron line whose code root is gone cannot load code: it is dead on start, not merely NOT_RELEASE."""
    wd = (wd or "").strip("'\"")
    if wd.startswith("-"):   # systemd: "-" = missing directory is ignored
        wd = ""
    wd = wd.lstrip("!")      # systemctl show prints "!" before a home-relative/unchecked value
    if wd == "~" or wd.startswith("~/"):
        wd = os.path.expanduser(wd)
    need = [wd] if wd else []
    for r in sorted(roots):
        if r == "CURRENT":
            need.append(f"{releases_base.rstrip('/')}/CURRENT")
        elif r.startswith("REL:"):
            need.append(f"{releases_base.rstrip('/')}/{r[4:]}")
        elif r == "CANONICAL" and canonical:
            need.append(canonical)
        elif r.startswith("WORKTREE:"):
            need.append(r[len("WORKTREE:"):])
    need = [d.strip("'\"") for d in need]
    return [d for d in dict.fromkeys(need) if d and "$" not in d and not dir_exists(d)]


def next_run_verdict(roots: set[str], current_real_name: str) -> tuple[str, str]:
    """Verdict for an entry that will (re)load code at its next start."""
    if "NO_CANDIDATE" in roots:
        return FAIL, "no candidate directory holds the script: the next run exits before loading code"
    rel = {r for r in roots if r == "CURRENT" or r.startswith("REL:")}
    other = roots - rel
    if not roots:
        return UNKNOWN, "no code root found in ExecStart/WorkingDirectory"
    if other and not rel:
        return NOT_RELEASE, ", ".join(sorted(other))
    if other:
        return FAIL, f"mixed code roots: {', '.join(sorted(roots))}"
    pinned = sorted(r[4:] for r in rel if r.startswith("REL:"))
    stale = [p for p in pinned if p != current_real_name]
    if stale:
        return FAIL, f"pinned to another release: {', '.join(stale)}"
    if pinned:
        return PASS, f"pinned to the current release {pinned[0]} (a later activation strands it)"
    return PASS, f"names CURRENT -> {current_real_name} at next start"


def running_verdict(cwd_real: Optional[str], script_real: Optional[str], started_at: Optional[datetime],
                    activated_at: datetime, current_real: str, canonical: str,
                    releases_base: str = str(RELEASES_BASE)) -> tuple[str, str, str]:
    """(verdict, observed, evidence) for a running process."""
    if not cwd_real or started_at is None:
        return UNKNOWN, "unreadable", "/proc/<pid> not readable (cwd or start time)"

    def where(p: str) -> str:
        if p == current_real or p.startswith(current_real.rstrip("/") + "/"):
            return Path(current_real).name
        base = releases_base.rstrip("/") + "/"
        if p.startswith(base):
            return p[len(base):].split("/")[0]
        if canonical and (p == canonical or p.startswith(canonical.rstrip("/") + "/")):
            return "CANONICAL"
        if any(m in p for m in WORKTREE_MARKERS):
            return f"WORKTREE:{p}"
        return f"OTHER:{p}"

    cur = Path(current_real).name
    w_cwd = where(cwd_real)
    w_script = where(script_real) if script_real else None
    observed = w_cwd if w_script in (None, w_cwd) else f"cwd={w_cwd} script={w_script}"
    ev = f"cwd={w_cwd}" + (f"; script={w_script}" if w_script else "") + f"; started {started_at.isoformat()}"
    rel_base = releases_base.rstrip("/") + "/"
    in_rel = lambda p: bool(p) and (p == current_real or p.startswith(rel_base))  # noqa: E731
    if w_script and w_script.startswith("OTHER:") and in_rel(cwd_real):
        # an out-of-tree overlay (e.g. a host shim that resolves CURRENT and runpy's the release daemon): the code
        # identity is the cwd plus the start time; the overlay is named in the evidence.
        ev += " (out-of-tree overlay script; judged by cwd + start time)"
        w_script = None
        observed = w_cwd
    if not in_rel(cwd_real) and not (script_real and in_rel(script_real)):
        return NOT_RELEASE, observed, ev
    if w_cwd != cur or (w_script and w_script != cur):
        return FAIL, observed, ev + " (code not in the current release)"
    if started_at < activated_at:
        return FAIL, observed, ev + f" (started before activation {activated_at.isoformat()})"
    return PASS, observed, ev


def parse_crontab(text: str) -> list[tuple[int, str, str]]:
    """[(line_no, schedule, expanded_command)] for each job line; NAME=value lines expand into later lines."""
    env: dict[str, str] = {}
    out = []
    for i, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if m and not re.match(r"^[@*0-9]", line):
            env[m.group(1)] = m.group(2).strip().strip("'\"")
            continue
        if line.startswith("@"):
            sched, _, cmd = line.partition(" ")
        else:
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            sched, cmd = " ".join(parts[:5]), parts[5]
        for k, v in sorted(env.items(), key=lambda kv: -len(kv[0])):
            cmd = cmd.replace("${" + k + "}", v).replace("$" + k, v)
        out.append((i, sched, cmd))
    return out


def cron_name(line_no: int, cmd: str) -> str:
    rest, _ = strip_interpreters(cmd.split(">>")[0].split(" > ")[0])
    scripts = re.findall(r"[\w./-]+\.(?:py|sh)\b", rest)
    mod = re.search(r"-m\s+([\w.]+)", rest)
    tag = Path(scripts[-1]).name if scripts else (mod.group(1) if mod else rest.split()[0] if rest.split() else "?")
    return f"cron:L{line_no}:{tag}"


def command_part(cmd: str) -> str:
    """The command without its log redirections (a log path is not a code root)."""
    return re.split(r"\s\d?>>?\s?|\s2>&1", cmd)[0]


# ---------------------------------------------------------------- host readers (injectable)


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False).stdout


def _proc_start(pid: int) -> Optional[datetime]:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        ticks = int(fields[19])
        btime = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines() if line.startswith("btime"))
        return datetime.fromtimestamp(btime + ticks / os.sysconf("SC_CLK_TCK"), tz=timezone.utc)
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _proc_cwd(pid: int) -> Optional[str]:
    try:
        return os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
    except OSError:
        return None


def _proc_cmdline(pid: int) -> list[str]:
    try:
        return [a for a in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0") if a]
    except OSError:
        return []


def _script_of(argv: list[str], cwd: Optional[str]) -> Optional[str]:
    """realpath of the first .py/.sh argument after the interpreter (relative ones resolve against cwd)."""
    for a in argv[1:]:
        if a.endswith((".py", ".sh")):
            p = a if a.startswith("/") else os.path.join(cwd or "/", a)
            return os.path.realpath(p)
    return None


def _units(run: Callable[[list[str]], str]) -> list[dict[str, str]]:
    names = [ln.split()[0] for ln in run(["systemctl", "--user", "list-unit-files", "--type=service", "--no-legend"]).splitlines()
             if ln.strip() and "@" not in ln.split()[0]]
    if not names:
        return []
    props = ["Id", "ExecStart", "WorkingDirectory", "ActiveState", "Type", "TriggeredBy", "MainPID", "FragmentPath",
             "Transient"]
    text = run(["systemctl", "--user", "show", *names, *[f"-p{p}" for p in props]])
    out = []
    for block in text.split("\n\n"):
        d = dict(line.split("=", 1) for line in block.strip().splitlines() if "=" in line)
        if d.get("Id"):
            out.append(d)
    return out


def _argv_text(exec_start: str) -> str:
    m = re.search(r"argv\[\]=(.*?)\s;\s", exec_start or "")
    return m.group(1) if m else (exec_start or "")


# ---------------------------------------------------------------- the manifest


def build(current_link: Path, activated_at: datetime, canonical: str, *, run=_run, proc_cwd=_proc_cwd,
          proc_start=_proc_start, proc_cmdline=_proc_cmdline, exists=os.path.isfile, dir_exists=os.path.isdir, crontab_text: Optional[str] = None,
          lane_rows: Optional[list] = None) -> list[Entry]:
    current_real = os.path.realpath(str(current_link))
    cur_name = Path(current_real).name
    base = str(current_link.parent)
    entries: list[Entry] = []
    executor: Optional[Entry] = None
    executor_override = False
    for u in _units(run):
        name, argv = u["Id"], _argv_text(u.get("ExecStart", ""))
        wd = u.get("WorkingDirectory", "")
        rest, interps = strip_interpreters(argv)
        loop = resolve_candidate_loop(argv, exists)
        roots = code_roots(code_text(rest, wd), base, canonical) or code_roots(f"{rest} {wd}", base, canonical)
        if loop is not None and roots:
            roots = code_roots(loop[0], base, canonical) or {"NO_CANDIDATE"}
        if not roots:
            continue
        restart, reason = cbu.decide(name, argv=argv, wd=wd, env="", installed=True, current_link=str(current_link),
                                     is_market_open=False)
        lifecycle = "restart" if restart else f"page-only:{reason}"
        note = (f"; {loop[1]}" if loop else "") + (f"; interpreter {interps[0]}" if interps else "")
        pid = int(u.get("MainPID") or 0)
        if pid > 0:
            cwd = proc_cwd(pid)
            argv_live = proc_cmdline(pid)
            verdict, observed, ev = running_verdict(cwd, _script_of(argv_live, cwd), proc_start(pid), activated_at,
                                                    current_real, canonical, base)
            e = Entry(name, "service-running", cur_name, observed, f"pid {pid}; {ev}{note}", verdict, lifecycle)
            if name == "tradeai-n8n-run-executor.service":
                executor, executor_override = e, "--code-root" in argv_live
        else:
            verdict, why = next_run_verdict(roots, cur_name)
            gone = missing_roots(roots, wd, base, canonical, dir_exists)
            if gone:
                verdict, why = FAIL, f"dead on start: {', '.join(gone)} does not exist; {why}"
            state = u.get("ActiveState", "?")
            simple = u.get("Type") in ("simple", "exec", "notify") and not (u.get("TriggeredBy") or "").strip()
            if simple and verdict == PASS:
                verdict, why = UNKNOWN, f"long-running service not running ({state}); {why}"
            e = Entry(name, "service-next-run", cur_name, ",".join(sorted(roots)),
                      f"{state}; trigger={u.get('TriggeredBy') or '-'}; {why}{note}", verdict, lifecycle)
        entries.append(e)
    if crontab_text is None:
        crontab_text = run(["crontab", "-l"])
    for line_no, sched, cmd in parse_crontab(crontab_text):
        rest, interps = strip_interpreters(command_part(cmd))
        loop = resolve_candidate_loop(cmd, exists)
        roots = code_roots(code_text(rest, ""), base, canonical) or code_roots(rest, base, canonical)
        if loop is not None and roots:
            roots = code_roots(loop[0], base, canonical) or {"NO_CANDIDATE"}
        if not roots:
            continue
        verdict, why = next_run_verdict(roots, cur_name)
        cd = re.search(r"\bcd\s+([^\s;&|]+)", rest)
        gone = missing_roots(roots, cd.group(1) if cd else "", base, canonical, dir_exists)
        if gone:
            verdict, why = FAIL, f"dead on start: {', '.join(gone)} does not exist; {why}"
        note = (f"; {loop[1]}" if loop else "") + (f"; interpreter {interps[0]}" if interps else "")
        entries.append(Entry(cron_name(line_no, cmd), "cron", cur_name, ",".join(sorted(roots)),
                             f"'{sched}'; {why}{note}", verdict, "cron (no restart; next run)"))
    if lane_rows is None:
        try:
            lane_rows = json.loads((Path(current_real) / "config" / "lane_registry.json").read_text())["lanes"]
        except (OSError, ValueError, KeyError):
            lane_rows = None
    if lane_rows is None:
        entries.append(Entry("n8n-lanes", "n8n-lanes", cur_name, "unreadable", "lane_registry.json unreadable", UNKNOWN))
    else:
        live = [r for r in lane_rows if (r.get("dispatch") or {}).get("mode") == "live" and r.get("state") == "ACTIVE"]
        if executor is None:
            v, obs, ev = UNKNOWN, "executor not running", "tradeai-n8n-run-executor has no MainPID"
        elif executor_override:
            v, obs, ev = FAIL, executor.observed, "executor argv carries --code-root (lanes do not run from its root)"
        else:
            v, obs = executor.verdict, executor.observed
            ev = f"{len(live)} ACTIVE live-dispatch lanes run with cwd=code_root=executor ROOT (no --code-root); " \
                 f"executor {executor.verdict}: {executor.evidence}"
        entries.append(Entry(f"n8n-lanes ({len(live)})", "n8n-lanes", cur_name, obs, ev, v, "via executor restart"))
    return entries


def render_md(entries: Iterable[Entry], current_real: str, activated_at: datetime) -> str:
    entries = list(entries)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.verdict] = counts.get(e.verdict, 0) + 1
    order = {FAIL: 0, UNKNOWN: 1, PASS: 2, NOT_RELEASE: 3}
    lines = [f"CURRENT -> `{Path(current_real).name}`; activation {activated_at.isoformat()}; "
             + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: order.get(kv[0], 9))),
             "", "| name | kind | expected release | observed | evidence | lifecycle | verdict |",
             "|---|---|---|---|---|---|---|"]
    for e in sorted(entries, key=lambda e: (order.get(e.verdict, 9), e.kind, e.name)):
        cells = [e.name, e.kind, e.expected, e.observed, e.evidence, e.lifecycle, f"**{e.verdict}**"]
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--current", type=Path, default=RELEASES_BASE / "CURRENT")
    ap.add_argument("--activated-at", help="ISO time; default = mtime of the CURRENT symlink itself")
    ap.add_argument("--canonical", default=str(DEFAULT_CANONICAL))
    ap.add_argument("--out", type=Path, help="write the markdown table here (and <out>.json)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        act = (datetime.fromisoformat(a.activated_at) if a.activated_at
               else datetime.fromtimestamp(os.lstat(a.current).st_mtime, tz=timezone.utc))
    except (OSError, ValueError) as exc:
        print(f"cannot establish the activation time: {exc}", file=sys.stderr)
        return 2
    if act.tzinfo is None:
        print("--activated-at needs a timezone offset", file=sys.stderr)
        return 2
    entries = build(a.current, act, a.canonical)
    if not entries:
        print("discovery found no entries", file=sys.stderr)
        return 2
    md = render_md(entries, os.path.realpath(str(a.current)), act)
    if a.out:
        a.out.write_text(md, encoding="utf-8")
        a.out.with_suffix(".json").write_text(json.dumps([asdict(e) for e in entries], indent=1), encoding="utf-8")
    print(json.dumps([asdict(e) for e in entries], indent=1) if a.json else md)
    return 1 if any(e.verdict == FAIL for e in entries) else 0


if __name__ == "__main__":
    sys.exit(main())
