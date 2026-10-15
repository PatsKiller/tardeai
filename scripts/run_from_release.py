#!/usr/bin/env python3
"""Run-from-release tooling: move cron and user units off the dev tree (WS7-01 / WS8-14).

    python3 scripts/run_from_release.py inventory   [--crontab-file F] [--json OUT]
    python3 scripts/run_from_release.py crontab     --cohorts c1 --out DIR [--crontab-file F]
    python3 scripts/run_from_release.py crontab     --final --out DIR
    python3 scripts/run_from_release.py crontab     --revert c1 --out DIR
    python3 scripts/run_from_release.py dropins     --out DIR [--units u1,u2]
    python3 scripts/run_from_release.py verify      --crontab-file CANDIDATE [--cohorts c1 | --all] --python PY
    python3 scripts/run_from_release.py write-paths [--json OUT]

Why: every crontab line's ``$PY`` and most user units execute the dev checkout's ``.venv`` (and 98 wrapper
scripts inside CURRENT hard-code ``PROJ=<dev tree>``), while coding agents move that checkout. The served
release has no venv of its own.

What it does. Nothing here installs, enables, reloads or restarts anything; no subcommand writes outside
``--out`` (or the scratch directory the verifier sandboxes into).

* ``inventory`` classifies every active crontab line and every user service by the code root it runs
  (dev / worktree / CURRENT / pinned release / external) and by interpreter (dev venv, release venv, system
  python, shell wrapper, other venv, none). Wrappers are followed one level: a wrapper that hard-codes the
  dev tree is reported as such even when the crontab line names CURRENT.
* ``crontab`` writes a candidate crontab plus a unified diff. A cohort's lines get one exact, strippable
  prefix ``export PY=$RPY TRADEAI_VENV_PYTHON=$RPY TRADEAI_RUN_FROM_RELEASE=<id>; `` and the header gains
  literal ``RPY=`` and ``TRADEAI_CODE_ROOT=`` assignments (cron does not expand variables in assignments; no
  code reads either yet, so the header change is a no-op for every line outside the cohort).
  ``--revert`` strips one cohort's prefix; ``--final`` repoints the header ``PY`` itself and strips every
  prefix. The candidate is gated with ``lane_registry.find_undeclared``: it may not add an undeclared line.
* ``dropins`` writes one ``95-run-from-release.conf`` per dev-tree unit into ``--out/<unit>.d/``.
* ``verify`` dry-runs each rewritten line's primary command from CURRENT: python scripts get ``--help``
  only when an AST check finds argparse/click and no module-level side effects, and then only inside
  ``bwrap`` with a read-only filesystem, a private /tmp and no network. Shell wrappers get ``bash -n`` and
  the wrapper dev-root scan; they are never executed.
* ``write-paths`` lists every path python code writes relative to its own code root, and whether that
  path is linked to persistent-state in CURRENT or is a release-local directory lost at promote (WS6-08).

AUTHORITY: READ_ONLY_ADVISORY. No broker. Reads ``crontab -l`` and ``systemctl --user cat`` only.
"""

from __future__ import annotations

NO_CONSUMER_REASON = (
    "operator tool for the run-from-release migration: its candidate crontab, drop-ins and JSON reports are "
    "read by the operator packet docs/ops/packets/run-from-release-cohort1-20261015, not by a lane."
)

import argparse
import ast
import difflib
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO / "config" / "run_from_release_cohorts.json"
BROKER_RULES = REPO / "config" / "agents_guard_hook_rules.json"
HOME = str(Path.home())

PREFIX_RX = re.compile(
    r"export PY=\$RPY TRADEAI_VENV_PYTHON=\$RPY TRADEAI_RUN_FROM_RELEASE=(?P<cohort>[A-Za-z0-9_-]+); "
)
PY_RX = re.compile(r"\$\{PY\}|\$PY(?![A-Za-z0-9_])")
RPY_RX = re.compile(r"\$\{RPY\}|\$RPY(?![A-Za-z0-9_])")
DROPIN_NAME = "95-run-from-release.conf"
# NOT TRADEAI_ROOT: that name already means the STATE root in CIO code (`_STATE_ROOT_ENV_NAMES`, cio_paths) and
# the code root in others; exporting it as CURRENT would move CIO state resolution into the release dir.
CODE_ROOT_VAR = "TRADEAI_CODE_ROOT"
STATE_ENV_RX = re.compile(r"(HOME|DIR|STATE|JOURNAL|_DB|DB_PATH|LOG|CACHE|STORE|LEDGER|QUEUE)$")
UNIT_KEYS = (
    "WorkingDirectory",
    "ExecStart",
    "ExecStartPre",
    "ExecStartPost",
    "ExecStop",
    "Environment",
    "EnvironmentFile",
)
EXEC_KEYS = ("ExecStart", "ExecStartPre", "ExecStartPost", "ExecStop")
SCHEDULE_RX = re.compile(r"^(?P<lead>\s*)(?P<sched>@\w+|(?:\S+\s+){4}\S+)(?P<sep>\s+)(?P<cmd>.*)$")
ASSIGN_RX = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")


# --------------------------------------------------------------------------- config / layout


@dataclass
class Layout:
    dev_root: str
    releases_base: str
    current_name: str = "CURRENT"
    release_venv_relpath: str = ".venv/bin/python"
    worktree_patterns: tuple[str, ...] = ()
    non_release_names: tuple[str, ...] = ("CURRENT", "EXPECTED_RELEASE", "ACTIVE_RELEASE")

    @property
    def current(self) -> str:
        return f"{self.releases_base}/{self.current_name}"

    @property
    def dev_venv_python(self) -> str:
        return f"{self.dev_root}/.venv/bin/python"

    @property
    def release_python(self) -> str:
        return f"{self.current}/{self.release_venv_relpath}"


@dataclass
class Cohort:
    id: str
    title: str
    match: list[str]
    exclude: list[str] = field(default_factory=list)
    broker_adjacent_allowed: bool = False


@dataclass
class Config:
    layout: Layout
    cohorts: list[Cohort]
    broker_markers: tuple[str, ...]
    broker_globs: tuple[str, ...]
    exclude_units: tuple[str, ...] = ()


def load_config(path: Path = DEFAULT_CONFIG, broker_rules: Path = BROKER_RULES) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    lay = raw.get("layout") or {}
    layout = Layout(
        dev_root=lay["dev_root"].rstrip("/"),
        releases_base=lay["releases_base"].rstrip("/"),
        current_name=lay.get("current_name", "CURRENT"),
        release_venv_relpath=lay.get("release_venv_relpath", ".venv/bin/python"),
        worktree_patterns=tuple(lay.get("worktree_root_patterns") or ()),
        non_release_names=tuple(lay.get("non_release_names") or ("CURRENT",)),
    )
    globs: list[str] = []
    try:
        rules = json.loads(Path(broker_rules).read_text(encoding="utf-8"))
        for rule in rules.get("rules", []):
            if rule.get("id") == "broker.execution_code_edit":
                globs = list(rule.get("path_globs") or [])
    except (OSError, ValueError):
        globs = []
    if not globs:
        # Fail closed: without the broker file set nothing may be classified as safe to move early.
        raise SystemExit(f"broker.execution_code_edit globs unreadable in {broker_rules} — refusing")
    cohorts = [
        Cohort(
            id=c["id"],
            title=c.get("title", ""),
            match=list(c.get("match") or []),
            exclude=list(c.get("exclude") or []),
            broker_adjacent_allowed=bool(c.get("broker_adjacent_allowed")),
        )
        for c in raw.get("cohorts") or []
    ]
    return Config(
        layout,
        cohorts,
        tuple(raw.get("broker_adjacent_markers") or ()),
        tuple(globs),
        tuple(raw.get("exclude_units") or ()),
    )


# --------------------------------------------------------------------------- classification


def normalize(text: str) -> str:
    """Expand the home spellings cron and systemd use so one regex sees every path."""
    out = text.replace("%h", HOME).replace("${HOME}", HOME).replace("$HOME", HOME)
    out = re.sub(r"(?<![\w/])~/", HOME + "/", out)
    return out


def expand_vars(text: str, env: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        return env.get(name, m.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", sub, text)


def code_roots(text: str, layout: Layout) -> set[str]:
    """Which code roots a (normalized, expanded) command or directive names."""
    t = normalize(text)
    roots: set[str] = set()
    dev = re.escape(layout.dev_root)
    if re.search(dev + r"(?!/\.venv)(?:/|\b|$)", t):
        roots.add("dev")
    rel = re.escape(layout.releases_base)
    for m in re.finditer(rel + r"/([A-Za-z0-9._-]+)", t):
        roots.add("current" if m.group(1) in layout.non_release_names else "pinned")
    for pat in layout.worktree_patterns:
        if re.search(pat, t):
            roots.add("worktree")
    return roots


def interpreters(text: str, layout: Layout) -> list[str]:
    """Interpreters a command uses, most dev-exposed first."""
    t = normalize(text)
    found: list[str] = []
    if layout.dev_venv_python in t or f"{layout.dev_root}/.venv/bin" in t:
        found.append("dev_venv")
    elif re.search(re.escape(layout.dev_root) + r"/\S+/\.venv/bin/python", t):
        found.append("dev_other_venv")
    if f"{layout.current}/.venv" in t:
        found.append("release_venv")
    for m in re.finditer(r"(\S*)/\.venv/bin/python\S*", t):
        if not m.group(1).startswith(layout.dev_root) and not m.group(1).startswith(layout.current):
            found.append("other_venv")
            break
    if re.search(r"(^|[\s;&|(`'\"])(/usr/bin/)?python3?(\.\d+)?(\s|$)", t):
        found.append("system_python")
    if re.search(r"\.sh\b", t):
        found.append("shell_wrapper")
    return found or ["none"]


def broker_reason(text: str, cfg: Config) -> str:
    low = normalize(text).lower()
    for marker in cfg.broker_markers:
        if marker.lower() in low:
            return f"marker {marker!r}"
    pats = [g.replace("**/", "*/").replace("/**", "/*") for g in cfg.broker_globs]
    for tok in re.findall(r"[^\s'\";|&()<>]+", low):
        if "/" not in tok:
            continue
        for pat, glob in zip(pats, cfg.broker_globs):
            if fnmatch.fnmatch(tok, pat) or fnmatch.fnmatch("/" + tok.lstrip("/"), pat):
                return f"path {tok} matches {glob}"
    return ""


# Wrapper scan: one level. A shell wrapper that ASSIGNS the dev tree unconditionally pins it; one that only
# defaults to it (`${PROJ:-<dev>}`) follows the exported environment; one that names it nowhere is clean.
_DEV_ASSIGN_HARD = r"^\s*(?:readonly\s+|export\s+|local\s+)?(?P<var>[A-Za-z_][A-Za-z0-9_]*)=[\"']?{dev}"
_DEV_DEFAULT = r"\$\{{[A-Za-z_][A-Za-z0-9_]*:-[^}}]*{dev}"


def scan_wrapper(path: Path, layout: Layout) -> dict[str, Any]:
    try:
        text = normalize(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return {"path": str(path), "verdict": "missing", "detail": str(exc)}
    dev = re.escape(layout.dev_root)
    hard: list[str] = []
    soft = 0
    other = 0
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#") or layout.dev_root not in line:
            continue
        if re.search(_DEV_ASSIGN_HARD.format(dev=dev), line) or re.search(r"^\s*cd\s+[\"']?" + dev, line):
            hard.append(f"{i}: {line.strip()[:160]}")
        elif re.search(_DEV_DEFAULT.format(dev=dev), line):
            soft += 1
        else:
            other += 1
    if hard:
        verdict = "pins_dev"
    elif soft or other:
        verdict = "dev_default"
    else:
        verdict = "clean"
    return {"path": str(path), "verdict": verdict, "hard": hard, "soft_defaults": soft, "other_refs": other}


def primary_target(command: str, env: dict[str, str], layout: Layout) -> dict[str, Any]:
    """The script a cron command ultimately runs: (kind, path) where kind is python|shell|inline|other."""
    expanded = normalize(expand_vars(command, env))
    cwd = None
    m = re.match(r"\s*cd\s+(\S+)\s*&&", expanded)
    if m:
        cwd = m.group(1).strip("\"'")
    body = expanded.split("#", 1)[0] if "'" not in expanded and '"' not in expanded else expanded
    if re.search(r"python3?\s+-c\s", body):
        return {"kind": "inline", "path": None, "cwd": cwd}
    # Last .sh / .py token that is a real script (wrappers such as market_day_gate.sh take the next one too:
    # the FIRST .sh after a gate is the gate itself, so prefer a .py anywhere, else the last .sh).
    py = re.findall(r"(?:^|[\s\"'])([^\s\"']+\.py)(?=[\s\"';>)]|$)", body)
    sh = [
        s
        for s in re.findall(r"(?:^|[\s\"'])([^\s\"']+\.sh)(?=[\s\"';>)]|$)", body)
        if not s.endswith("run_with_deepseek_offpeak.sh")
    ]
    pick: Optional[tuple[str, str]] = None
    if py and not sh:
        pick = ("python", py[0])
    elif sh:
        gates = ("market_day_gate.sh", "non_trading_hours_gate.sh", "safe_flock.sh")
        real = [s for s in sh if not s.endswith(gates)] or sh
        pick = ("shell", real[0])
        if py and real is sh and all(s.endswith(gates) for s in sh):
            pick = ("python", py[0])
    if pick is None:
        return {"kind": "other", "path": None, "cwd": cwd}
    kind, p = pick
    p = p.strip("\"'")
    if not p.startswith("/"):
        base = cwd or layout.current
        p = f"{base.rstrip('/')}/{p}"
    return {"kind": kind, "path": p, "cwd": cwd}


# --------------------------------------------------------------------------- crontab


@dataclass
class CronLine:
    lineno: int
    raw: str
    kind: str  # job | env | comment | blank
    schedule: str = ""
    command: str = ""
    name: str = ""
    value: str = ""
    head: str = ""  # leading whitespace + schedule + separator, byte-exact (a rewrite never reflows it)


def parse_crontab(text: str) -> list[CronLine]:
    out: list[CronLine] = []
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s:
            out.append(CronLine(i, raw, "blank"))
            continue
        if s.startswith("#"):
            out.append(CronLine(i, raw, "comment"))
            continue
        am = ASSIGN_RX.match(s)
        if am and not s[0].isdigit() and not s.startswith(("*", "@")):
            out.append(CronLine(i, raw, "env", name=am.group("name"), value=am.group("value").strip().strip("\"'")))
            continue
        sm = SCHEDULE_RX.match(raw)
        if sm:
            out.append(
                CronLine(
                    i,
                    raw,
                    "job",
                    schedule=sm.group("sched"),
                    command=sm.group("cmd"),
                    head=sm.group("lead") + sm.group("sched") + sm.group("sep"),
                )
            )
        else:
            out.append(CronLine(i, raw, "comment"))
    return out


def cron_env_at(lines: list[CronLine]) -> list[dict[str, str]]:
    """Environment each line sees (cron applies an assignment to the entries after it)."""
    env: dict[str, str] = {"HOME": HOME}
    snaps: list[dict[str, str]] = []
    for ln in lines:
        if ln.kind == "env":
            env = dict(env)
            env[ln.name] = ln.value
        snaps.append(env)
    return snaps


def classify_job(ln: CronLine, env: dict[str, str], cfg: Config, wrapper_cache: dict[str, dict]) -> dict[str, Any]:
    lay = cfg.layout
    cmd = PREFIX_RX.sub("", ln.command)
    expanded = normalize(expand_vars(cmd, env))
    roots = code_roots(expanded, lay)
    interp = interpreters(expanded, lay)
    target = primary_target(cmd, env, lay)
    wrapper = None
    if target["kind"] == "shell" and target["path"]:
        resolved = target["path"]
        if resolved not in wrapper_cache:
            wrapper_cache[resolved] = scan_wrapper(Path(resolved), lay)
        wrapper = wrapper_cache[resolved]
    trade_ai = bool(roots) or "dev_venv" in interp or "release_venv" in interp
    if not roots:
        root = "external"
    elif "dev" in roots:
        root = "dev"
    elif "worktree" in roots:
        root = "worktree"
    elif "pinned" in roots:
        root = "pinned"
    else:
        root = "current"
    effective_dev = root == "dev" or "dev_venv" in interp or bool(wrapper and wrapper["verdict"] == "pins_dev")
    cohort_m = PREFIX_RX.search(ln.command)
    return {
        "lineno": ln.lineno,
        "schedule": ln.schedule,
        "command": ln.command,
        "root": root,
        "interpreter": interp[0],
        "interpreters": interp,
        "trade_ai": trade_ai,
        "target": target,
        "wrapper": wrapper,
        "broker_adjacent": broker_reason(cmd, cfg),
        "executes_dev": effective_dev,
        "migrated_cohort": cohort_m.group("cohort") if cohort_m else None,
    }


def assign_cohort(job: dict[str, Any], cfg: Config, wanted: Optional[Iterable[str]] = None) -> Optional[str]:
    if not job["trade_ai"] or job["root"] in {"worktree", "pinned", "external"}:
        return None
    cmd = PREFIX_RX.sub("", job["command"])
    for c in cfg.cohorts:
        if job["broker_adjacent"] and not c.broker_adjacent_allowed:
            continue
        if not any(re.search(p, cmd) for p in c.match):
            continue
        if any(re.search(x, cmd, re.IGNORECASE) for x in c.exclude):
            continue
        if wanted is not None and c.id not in set(wanted):
            return None
        return c.id
    return None


def rewrite_dev_paths(text: str, layout: Layout) -> str:
    """Dev-tree literal paths → CURRENT (venv first, so the venv lands on the release venv)."""
    out = text
    for spell in (
        layout.dev_root,
        layout.dev_root.replace(HOME, "%h"),
        layout.dev_root.replace(HOME, "$HOME"),
        layout.dev_root.replace(HOME, "${HOME}"),
    ):
        out = out.replace(f"{spell}/.venv/bin/", f"{layout.current}/.venv/bin/")
        out = out.replace(spell, layout.current)
    return out


@dataclass
class CrontabResult:
    text: str
    diff: str
    changed: list[dict[str, Any]]
    summary: dict[str, Any]


def generate_crontab(
    text: str,
    cfg: Config,
    *,
    cohorts: Iterable[str] = (),
    revert: Iterable[str] = (),
    final: bool = False,
    keep_declared: Optional[Callable[[str, str], bool]] = None,
) -> CrontabResult:
    """``keep_declared(old_line, new_line)`` — when given and False for the `$PY` → `$RPY` form, the line gets
    the prefix only (its lane-registry expression names `$PY`; rewriting it would make the line undeclared)."""
    lay = cfg.layout
    wanted = set(cohorts)
    unknown = wanted - {c.id for c in cfg.cohorts}
    if unknown:
        raise SystemExit(f"unknown cohort(s): {sorted(unknown)}")
    revert = set(revert)
    lines = parse_crontab(text)
    envs = cron_env_at(lines)
    cache: dict[str, dict] = {}
    out_lines: list[str] = []
    changed: list[dict[str, Any]] = []
    has = {ln.name for ln in lines if ln.kind == "env"}
    py_seen = False
    for ln, env in zip(lines, envs):
        if ln.kind == "env":
            if ln.name == "PY" and final:
                out_lines.append(f"PY={lay.release_python}")
                changed.append({"lineno": ln.lineno, "change": "header PY → release venv"})
            else:
                out_lines.append(ln.raw)
            if ln.name == "PY":
                if "RPY" not in has:
                    out_lines.append(f"RPY={lay.release_python}")
                    changed.append({"lineno": ln.lineno, "change": "header + RPY"})
                if CODE_ROOT_VAR not in has:
                    out_lines.append(f"{CODE_ROOT_VAR}={lay.current}")
                    changed.append({"lineno": ln.lineno, "change": f"header + {CODE_ROOT_VAR}"})
                py_seen = True
            continue
        if ln.kind != "job":
            out_lines.append(ln.raw)
            continue
        job = classify_job(ln, env, cfg, cache)
        cmd = ln.command
        m = PREFIX_RX.match(cmd)
        if m and (final or m.group("cohort") in revert):
            new_cmd = RPY_RX.sub("$PY", cmd[m.end() :])
            out_lines.append(f"{ln.head}{new_cmd}")
            changed.append({"lineno": ln.lineno, "change": "strip prefix", "cohort": m.group("cohort")})
            continue
        if m:
            out_lines.append(ln.raw)
            continue
        cid = assign_cohort(job, cfg, wanted) if wanted else None
        if cid and code_roots(normalize(cmd), lay) & {"dev"}:
            # A literal dev-tree path is not reversible by stripping a prefix: it is reported, never rewritten here.
            out_lines.append(ln.raw)
            changed.append({"lineno": ln.lineno, "change": "refused: literal dev path", "cohort": cid})
        elif cid:
            # `$PY` → `$RPY` survives a wrapper or `bash -c '. env'` that re-sets PY; the exported PY reaches
            # wrappers that read it. Both are undone exactly by --revert (no line holds $RPY before this tool).
            prefix = f"export PY=$RPY TRADEAI_VENV_PYTHON=$RPY TRADEAI_RUN_FROM_RELEASE={cid}; "
            new_line = f"{ln.head}{prefix}{PY_RX.sub('$RPY', cmd)}"
            mode = "prefix+rpy"
            if keep_declared is not None and not keep_declared(ln.raw, new_line):
                new_line = f"{ln.head}{prefix}{cmd}"
                mode = "prefix-only (lane expression names $PY)"
                if not keep_declared(ln.raw, new_line):
                    # The registry pins this exact line text: it moves only with a lane_registry edit in the
                    # same change (AGENTS "Editing a crontab line needs the lane registry in the same change").
                    out_lines.append(ln.raw)
                    changed.append(
                        {
                            "lineno": ln.lineno,
                            "change": "refused: lane registry pins the line text",
                            "cohort": cid,
                            "command": cmd,
                        }
                    )
                    continue
            out_lines.append(new_line)
            changed.append({"lineno": ln.lineno, "change": "prefix", "mode": mode, "cohort": cid, "command": cmd})
        elif final and job["trade_ai"] and job["root"] == "dev":
            out_lines.append(f"{ln.head}{rewrite_dev_paths(cmd, lay)}")
            changed.append({"lineno": ln.lineno, "change": "dev paths → CURRENT"})
        else:
            out_lines.append(ln.raw)
    if not py_seen and (wanted or final):
        raise SystemExit("crontab has no PY= header line; refusing to generate a candidate that cannot resolve $RPY")
    if revert and not wanted and not final and not any(PREFIX_RX.search(x) for x in out_lines):
        # Last cohort reverted: drop the two header lines this tool added, so revert(generate(x)) == x.
        added = {f"RPY={lay.release_python}", f"{CODE_ROOT_VAR}={lay.current}"}
        out_lines = [x for x in out_lines if x not in added]
        changed.append({"lineno": 0, "change": "header - RPY/" + CODE_ROOT_VAR})
    new_text = "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")
    diff = "".join(
        difflib.unified_diff(text.splitlines(True), new_text.splitlines(True), "crontab.live", "crontab.candidate")
    )
    summary = {
        "cohorts": sorted(wanted),
        "revert": sorted(revert),
        "final": final,
        "lines_prefixed": sum(1 for c in changed if c["change"] == "prefix"),
        "lines_stripped": sum(1 for c in changed if c["change"] == "strip prefix"),
        "lines_refused": sum(1 for c in changed if c["change"].startswith("refused")),
        "lines_prefix_only": sum(1 for c in changed if c.get("mode", "").startswith("prefix-only")),
        "header_changes": sum(1 for c in changed if c["change"].startswith("header")),
        "jobs_total": sum(1 for ln in lines if ln.kind == "job"),
    }
    return CrontabResult(new_text, diff, changed, summary)


def lane_declared_checker() -> Optional[Callable[[str, str], bool]]:
    """(old_line, new_line) -> False when new_line would be undeclared in the lane registry while old_line is not."""
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from lib import lane_registry as lr  # type: ignore
    except Exception:  # pragma: no cover - import guard
        return None
    reg = lr.load_registry()

    def undeclared(line: str) -> bool:
        found = {"cron": lr.discover_cron(line + "\n"), "systemd": [], "systemd_services": []}
        return bool(lr.find_undeclared(reg, found, n8n_known_ids=[]))

    return lambda old, new: undeclared(old) or not undeclared(new)


def lane_gate(before: str, after: str) -> dict[str, Any]:
    """The candidate may not add an undeclared crontab line (AGENTS 'Editing a crontab line needs the lane
    registry in the same change')."""
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from lib import lane_registry as lr  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        return {"ok": False, "error": f"lane_registry import failed: {exc}"}
    reg = lr.load_registry()

    def und(t: str) -> list[str]:
        found = {"cron": lr.discover_cron(t), "systemd": [], "systemd_services": []}
        return sorted(u["expression"] for u in lr.find_undeclared(reg, found, n8n_known_ids=[]))

    a, b = und(before), und(after)
    added = [x for x in b if x not in a]
    return {
        "ok": len(b) <= len(a) and not [x for x in added if not PREFIX_RX.search(x)],
        "undeclared_before": len(a),
        "undeclared_after": len(b),
        "added": added[:50],
    }


# --------------------------------------------------------------------------- units


@dataclass
class Directive:
    key: str
    value: str
    source: str


def parse_systemctl_cat(text: str) -> list[Directive]:
    """`systemctl --user cat <unit>` output → directives in effective order (fragment, then drop-ins)."""
    out: list[Directive] = []
    source = ""
    section = ""
    pending = ""
    for raw in text.splitlines():
        if raw.startswith("# /"):
            source = raw[2:].strip()
            section = ""
            continue
        line = pending + raw.strip() if pending else raw.strip()
        if line.endswith("\\"):
            pending = line[:-1].rstrip() + " "
            continue
        pending = ""
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Service" or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out.append(Directive(k.strip(), v.strip(), source))
    return out


def effective(directives: list[Directive]) -> dict[str, Any]:
    eff: dict[str, Any] = {k: [] for k in UNIT_KEYS}
    eff["WorkingDirectory"] = None
    eff["Type"] = None
    eff["Restart"] = None
    for d in directives:
        if d.key == "WorkingDirectory":
            eff["WorkingDirectory"] = d
        elif d.key in ("Type", "Restart"):
            eff[d.key] = d.value
        elif d.key in EXEC_KEYS:
            if d.value == "":
                eff[d.key] = []
            else:
                eff[d.key].append(d)
        elif d.key in ("Environment", "EnvironmentFile"):
            if d.value == "":
                eff[d.key] = []
            else:
                eff[d.key].append(d)
    return eff


def _env_assignments(value: str) -> list[tuple[str, str]]:
    try:
        toks = shlex.split(value)
    except ValueError:
        toks = value.split()
    return [tuple(t.split("=", 1)) for t in toks if "=" in t]  # type: ignore[misc]


def classify_unit(name: str, cat_text: str, cfg: Config, state: str = "") -> dict[str, Any]:
    lay = cfg.layout
    eff = effective(parse_systemctl_cat(cat_text))
    texts: list[str] = []
    if eff["WorkingDirectory"]:
        texts.append(eff["WorkingDirectory"].value)
    for k in EXEC_KEYS + ("Environment", "EnvironmentFile"):
        texts.extend(d.value for d in eff[k])
    joined = "\n".join(texts)
    roots = code_roots(joined, lay)
    exec_text = "\n".join(d.value for d in eff["ExecStart"])
    env_text = "\n".join(d.value for d in eff["Environment"])
    interp = interpreters(exec_text, lay)
    # `python` resolved through PATH / PY= in Environment.
    if interp == ["none"] or "system_python" in interp:
        if f"{lay.dev_root}/.venv/bin" in normalize(env_text):
            interp = ["dev_venv(via env)"] + [i for i in interp if i != "none"]
    if not roots:
        root = "external"
    elif "dev" in roots:
        root = "dev"
    elif "worktree" in roots:
        root = "worktree"
    elif "pinned" in roots:
        root = "pinned"
    else:
        root = "current"
    is_daemon = (eff["Type"] or "simple") != "oneshot" and bool(eff["ExecStart"])
    reason = broker_reason(name + "\n" + joined, cfg)
    if reason or root == "worktree":
        cohort = "u3"
    elif is_daemon:
        cohort = "u2"
    else:
        cohort = "u1"
    dev_refs = [
        asdict(d) for k in UNIT_KEYS if k != "WorkingDirectory" for d in eff[k] if lay.dev_root in normalize(d.value)
    ]
    if eff["WorkingDirectory"] and lay.dev_root in normalize(eff["WorkingDirectory"].value):
        dev_refs.insert(0, asdict(eff["WorkingDirectory"]))
    return {
        "unit": name,
        "state": state,
        "root": root,
        "interpreter": interp[0],
        "type": eff["Type"] or "simple",
        "restart": eff["Restart"],
        "daemon": is_daemon,
        "broker_adjacent": reason,
        "unit_cohort": cohort,
        "dev_refs": dev_refs,
        "_eff": eff,
    }


def path_blockers(text: str, layout: Layout) -> list[str]:
    """Rewritten CURRENT paths that would not work: absent in the release, or release-local state that the
    next promote abandons (WS6-08). The release venv itself is a declared prerequisite, not a blocker."""
    out: list[str] = []
    real = Path(os.path.realpath(layout.current))
    for tok in sorted(set(re.findall(re.escape(layout.current) + r"(/[^\s:'\";]*)?", text))):
        rel_path = tok.lstrip("/")
        if not rel_path or rel_path.startswith(".venv"):
            continue
        status = release_status(rel_path, real)
        if status == "absent":
            # A file the job creates on first run is fine when its directory is linked or real.
            parent = str(Path(rel_path).parent)
            pstatus = release_status(parent, real) if parent not in ("", ".") else "release-local"
            if pstatus == "absent":
                out.append(f"{rel_path}: absent in CURRENT")
            elif pstatus == "release-local" and parent.split("/")[0] in ("data", "state", "logs"):
                out.append(f"{rel_path}: state under a release-local dir ({parent}) — lost at promote")
        elif status == "release-local" and rel_path.split("/")[0] in ("data", "state") and "." in Path(rel_path).name:
            out.append(f"{rel_path}: release-local state file — lost at promote")
    return out


def render_dropin(info: dict[str, Any], cfg: Config, excluded: Iterable[str] = ()) -> Optional[str]:
    """One drop-in that overrides every effective dev-tree directive with its CURRENT form."""
    lay = cfg.layout
    eff = info["_eff"]
    if info["unit"] in set(excluded):
        return None
    body: list[str] = []
    wd = eff["WorkingDirectory"]
    if wd and lay.dev_root in normalize(wd.value):
        body.append(f"WorkingDirectory={rewrite_dev_paths(normalize(wd.value), lay)}")
    env_over: dict[str, str] = {}
    for d in eff["Environment"]:
        for k, v in _env_assignments(normalize(d.value)):
            if lay.dev_root in v:
                env_over[k] = rewrite_dev_paths(v, lay)
            elif k in env_over:
                env_over.pop(k)
    for k, v in env_over.items():
        body.append(f'Environment="{k}={v}"')
    if any(lay.dev_root in normalize(d.value) for d in eff["Environment"]):
        body.append(f'Environment="TRADEAI_VENV_PYTHON={lay.release_python}"')
    for d in eff["EnvironmentFile"]:
        if lay.dev_root in normalize(d.value):
            body.append(
                f"# EnvironmentFile={d.value} reads the dev tree: operator decision (WS6-08 rec 3), not rewritten here"
            )
    for key in EXEC_KEYS:
        items = eff[key]
        if any(lay.dev_root in normalize(d.value) for d in items):
            body.append(f"{key}=")
            body.extend(f"{key}={rewrite_dev_paths(normalize(d.value), lay)}" for d in items)
    if not body:
        return None
    blockers = path_blockers("\n".join(body), lay)
    for k, v in env_over.items():
        if STATE_ENV_RX.search(k) and k not in ("PATH", "PYTHONPATH", "VIRTUAL_ENV", "TRADEAI_VENV_PYTHON"):
            blockers.append(
                f"Environment {k}={v}: a state location would move into the release dir (lost at "
                "promote) — map it to persistent-state instead"
            )
    info["blockers"] = blockers
    head = [
        f"# {DROPIN_NAME} — generated by scripts/run_from_release.py dropins (candidate; NOT installed)",
        f"# unit cohort {info['unit_cohort']}; root was {info['root']}; interpreter was {info['interpreter']}",
    ]
    if blockers:
        head.append("# BLOCKED — do not install until each path below is fixed in code or linked by prepare:")
        head.extend(f"#   {b}" for b in blockers)
    head += [
        "# Install: install -m 0600 <this> ~/.config/systemd/user/<unit>.d/ && systemctl --user daemon-reload",
        "# Rollback: move this file under ~/.config/systemd/user/.run-from-release-archive/ && daemon-reload",
    ]
    if info["daemon"]:
        head.append(
            "# DAEMON: resolves CURRENT once at start; add to TRADEAI_CURRENT_BOUND_UNITS so promote restarts it"
        )
    return "\n".join(head + ["[Service]"] + body) + "\n"


def list_user_services(unit_dir: Path) -> list[str]:
    return sorted(p.name for p in unit_dir.glob("*.service") if p.is_file())


def systemctl_cat(unit: str) -> str:
    r = subprocess.run(["systemctl", "--user", "cat", unit], capture_output=True, text=True, timeout=30)
    return r.stdout


def unit_states() -> dict[str, str]:
    r = subprocess.run(
        ["systemctl", "--user", "list-unit-files", "--type=service", "--no-legend", "--no-pager"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


# --------------------------------------------------------------------------- verifier

_SAFE_TOPLEVEL_CALLS = re.compile(
    r"^(Path|os\.environ\.get|os\.getenv|logging\.getLogger|re\.compile|frozenset|set|dict|tuple|list|"
    r"str|int|float|bool|namedtuple|collections\.namedtuple|TypeVar|field|dataclass|"
    r"os\.path\.(join|dirname|abspath|realpath|expanduser|basename)|sys\.path\.(insert|append)|"
    r"Path\(.*\)\.(resolve|parent|parents)|timezone|timedelta|ZoneInfo|getLogger|logging\.basicConfig|"
    r"warnings\.filterwarnings|load_dotenv|object)"
)


def _parse(src: str) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(src)


def help_safety(script: Path) -> tuple[bool, str]:
    """True when `--help` is very likely to exit before any side effect: argparse/click present, a main
    guard, and every module-level statement is an import, def, class, constant or a whitelisted call."""
    try:
        src = script.read_text(encoding="utf-8", errors="replace")
        tree = _parse(src)
    except (OSError, SyntaxError) as exc:
        return False, f"unparseable: {exc.__class__.__name__}"
    if "argparse" not in src and "click" not in src and "typer" not in src:
        return False, "no argparse/click: --help would run the job"
    has_main_guard = False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.If):
            test = ast.unparse(node.test)
            if "__name__" in test and "__main__" in test:
                has_main_guard = True
                continue
            continue  # module-level `if X:` config switches; bodies are checked loosely below
        if isinstance(node, ast.Try):
            continue  # import fallbacks
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            value = node.value
            if value is None:
                continue
            for call in [n for n in ast.walk(value) if isinstance(n, ast.Call)]:
                fn = ast.unparse(call.func)
                if not _SAFE_TOPLEVEL_CALLS.match(fn) and not fn.endswith(
                    (
                        "resolve",
                        "parent",
                        "joinpath",
                        "get",
                        "strip",
                        "split",
                        "lower",
                        "upper",
                        "format",
                        "compile",
                        "getLogger",
                        "expanduser",
                        "is_file",
                        "exists",
                        "get_live_project_root",
                        "venv_python",
                        "dirname",
                        "abspath",
                    )
                ):
                    return False, f"module-level call {fn}() at line {node.lineno}"
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            fn = ast.unparse(node.value.func)
            kw = {k.arg for k in node.value.keywords}
            if fn.endswith("basicConfig") and kw & {"filename", "handlers", "stream"}:
                return False, f"module-level {fn}(filename/handlers) at line {node.lineno} opens a log file"
            if _SAFE_TOPLEVEL_CALLS.match(fn):
                continue
            return False, f"module-level call {fn}() at line {node.lineno}"
        return False, f"module-level {node.__class__.__name__} at line {node.lineno}"
    if not has_main_guard:
        return False, "no __main__ guard"
    return True, "argparse + main guard + no module-level side effects"


def bwrap_argv(cwd: str, scratch: str, python: str = "") -> list[str]:
    """Read-only root, private writable /tmp, no network, no access to the user runtime dir (env, sockets).
    A venv that itself lives under /tmp (a measurement build) is re-bound read-only after the /tmp tmpfs."""
    argv = [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        f"/run/user/{os.getuid()}",
        "--bind",
        scratch,
        scratch,
    ]
    venv = str(Path(python).parent.parent) if python else ""
    if venv.startswith("/tmp/"):
        argv += ["--ro-bind", venv, venv]
    if cwd.startswith("/tmp/"):
        argv += ["--ro-bind", cwd, cwd]
    return argv + ["--unshare-net", "--unshare-ipc", "--die-with-parent", "--new-session", "--chdir", cwd]


def verify_job(
    job: dict[str, Any],
    cfg: Config,
    python: str,
    scratch: str,
    *,
    sandbox: str = "bwrap",
    timeout: int = 25,
    runner=subprocess.run,
) -> dict[str, Any]:
    lay = cfg.layout
    tgt = job["target"]
    res: dict[str, Any] = {"lineno": job["lineno"], "kind": tgt["kind"], "path": tgt["path"]}
    if tgt["kind"] in ("inline", "other") or not tgt["path"]:
        res.update(result="skip", reason=f"{tgt['kind']} command: no single script to dry-run")
        return res
    path = Path(tgt["path"].replace(lay.current, os.path.realpath(lay.current), 1))
    if not path.is_file():
        res.update(result="fail", reason=f"script missing in CURRENT: {tgt['path']}")
        return res
    if tgt["kind"] == "shell":
        r = runner(["bash", "-n", str(path)], capture_output=True, text=True, timeout=timeout)
        w = job.get("wrapper") or scan_wrapper(path, lay)
        if r.returncode != 0:
            res.update(result="fail", reason=f"bash -n: {r.stderr.strip()[:200]}")
        elif w["verdict"] == "pins_dev":
            res.update(result="fail", reason="wrapper hard-codes the dev tree: " + "; ".join(w["hard"][:2]))
        else:
            res.update(result="pass", reason=f"bash -n ok; wrapper {w['verdict']}")
        return res
    safe, why = help_safety(path)
    cwd = os.path.realpath(tgt.get("cwd") or lay.current)
    if not safe:
        # The script is never executed. Its imports are resolved (find_spec on top-level names only, which
        # does not run them) inside the same sandbox: proves the release venv + CURRENT supply every module.
        return _verify_imports(
            res, path, cwd, python, scratch, why, sandbox=sandbox, timeout=timeout, runner=runner, layout=lay
        )
    argv = [python, str(path), "--help"]
    if sandbox == "bwrap":
        argv = bwrap_argv(cwd, scratch, python) + argv
    env = {
        "HOME": HOME,
        "PATH": f"{os.path.dirname(python)}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TRADEAI_VENV_PYTHON": python,
        CODE_ROOT_VAR: lay.current,
        "TRADEAI_RUN_FROM_RELEASE_VERIFY": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": "/tmp",
    }
    try:
        r = runner(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired:
        res.update(result="fail", reason=f"--help timed out after {timeout}s (ran work, or blocked on I/O)")
        return res
    text = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 and re.search(r"usage:|Usage:|--help", text):
        res.update(result="pass", reason="--help exit 0 from CURRENT with the release venv")
    else:
        last = [ln for ln in text.strip().splitlines() if ln.strip()][-1:] or [""]
        res.update(result="fail", reason=f"--help rc={r.returncode}: {last[0][:200]}")
    return res


_FIND_SPEC_PROBE = (
    "import importlib.util, json, sys\n"
    "sys.path[:0] = sys.argv[2].split(':')\n"
    "missing = [m for m in json.loads(sys.argv[1]) if importlib.util.find_spec(m) is None]\n"
    "print(json.dumps(missing))\n"
    "sys.exit(3 if missing else 0)\n"
)


def top_level_imports(script: Path) -> list[str]:
    """Absolute top-level module names a script imports anywhere (function bodies included)."""
    try:
        tree = _parse(script.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    optional: set[int] = set()
    for node in ast.walk(tree):
        # `try: import x / except ImportError:` (or a bare except) is an optional dependency, not a requirement.
        if isinstance(node, ast.Try):
            for sub in node.body:
                for inner in ast.walk(sub):
                    if isinstance(inner, (ast.Import, ast.ImportFrom)):
                        optional.add(id(inner))
    names: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in optional:
            continue
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    names.discard("__future__")
    return sorted(names)


def _verify_imports(
    res: dict[str, Any],
    path: Path,
    cwd: str,
    python: str,
    scratch: str,
    why: str,
    *,
    sandbox: str,
    timeout: int,
    runner,
    layout: Layout,
) -> dict[str, Any]:
    mods = top_level_imports(path)
    if not mods:
        res.update(result="skip", reason=f"--help not provably safe ({why}); no imports to resolve")
        return res
    real = os.path.realpath(layout.current)
    search = ":".join([str(path.parent), real, f"{real}/scripts", f"{real}/scripts/lib"])
    argv = [python, "-I", "-c", _FIND_SPEC_PROBE, json.dumps(mods), search]
    if sandbox == "bwrap":
        argv = bwrap_argv(cwd, scratch, python) + argv
    env = {"HOME": HOME, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        r = runner(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired:
        res.update(result="fail", reason="import probe timed out")
        return res
    if r.returncode == 0:
        res.update(
            result="pass_imports",
            reason=f"not executed ({why}); all {len(mods)} imports resolve from CURRENT + release venv",
        )
    elif r.returncode == 3:
        res.update(result="fail", reason=f"imports missing from CURRENT/release venv: {r.stdout.strip()[:200]}")
    else:
        res.update(result="fail", reason=f"import probe rc={r.returncode}: {(r.stderr or '').strip()[-200:]}")
    return res


# --------------------------------------------------------------------------- write-path scan

WRITE_ATTRS = {
    "write_text",
    "write_bytes",
    "mkdir",
    "touch",
    "unlink",
    "rename",
    "replace",
    "symlink_to",
    "to_csv",
    "to_json",
    "to_parquet",
    "to_excel",
    "rmdir",
}
WRITE_FUNCS = {
    "os.makedirs",
    "os.mkdir",
    "os.replace",
    "os.rename",
    "os.remove",
    "os.unlink",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "shutil.move",
    "shutil.rmtree",
    "shutil.copytree",
    "logging.FileHandler",
    "FileHandler",
    "RotatingFileHandler",
    "TimedRotatingFileHandler",
    "logging.handlers.RotatingFileHandler",
    "sqlite3.connect",
}
WRITE_NAME_RX = re.compile(r"(write|save|dump|append|persist|atomic|store|emit_receipt|record)", re.IGNORECASE)


class _PathEval:
    """Tiny evaluator for paths derived from __file__ inside one script."""

    def __init__(self, script: Path, repo: Path):
        self.script = script
        self.repo = repo
        self.names: dict[str, Path] = {}

    def ev(self, node: ast.AST) -> Optional[Path]:
        if isinstance(node, ast.Name):
            if node.id == "__file__":
                return self.script
            return self.names.get(node.id)
        if isinstance(node, ast.Call):
            fn = ast.unparse(node.func)
            if fn in ("Path", "pathlib.Path") and node.args:
                base = self.ev(node.args[0])
                if base is None:
                    return None
                for a in node.args[1:]:
                    seg = self._seg(a)
                    if seg is None:
                        return None
                    base = base / seg
                return base
            if fn.endswith("get_live_project_root") or fn.endswith("live_project_root"):
                return self.repo
            if fn in ("os.path.dirname",) and node.args:
                b = self.ev(node.args[0])
                return b.parent if b is not None else None
            if fn in ("os.path.abspath", "os.path.realpath", "os.path.normpath", "str", "os.fspath") and node.args:
                return self.ev(node.args[0])
            if fn == "os.path.join" and node.args:
                b = self.ev(node.args[0])
                if b is None:
                    return None
                for a in node.args[1:]:
                    seg = self._seg(a)
                    if seg is None:
                        return None
                    b = b / seg
                return b
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("resolve", "absolute", "expanduser"):
                return self.ev(node.func.value)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
                b = self.ev(node.func.value)
                if b is None:
                    return None
                for a in node.args:
                    seg = self._seg(a)
                    if seg is None:
                        return None
                    b = b / seg
                return b
            return None
        if isinstance(node, ast.Attribute):
            if node.attr == "parent":
                b = self.ev(node.value)
                return b.parent if b is not None else None
            return None
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
            b = self.ev(node.value.value)
            idx = node.slice
            if b is not None and isinstance(idx, ast.Constant) and isinstance(idx.value, int):
                try:
                    return b.parents[idx.value]
                except IndexError:
                    return None
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            b = self.ev(node.left)
            seg = self._seg(node.right)
            if b is not None and seg is not None:
                return b / seg
            return None
        return None

    @staticmethod
    def _seg(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                parts.append(v.value if isinstance(v, ast.Constant) else "{*}")
            return "".join(parts)
        return None


def scan_write_paths(script: Path, repo: Path) -> list[dict[str, Any]]:
    try:
        tree = _parse(script.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    pe = _PathEval(script.resolve(), repo.resolve())
    # Two passes so module constants defined after a function body still resolve.
    for _ in range(2):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                p = pe.ev(node.value)
                if p is not None:
                    pe.names[node.targets[0].id] = p
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                p = pe.ev(node.value)
                if p is not None:
                    pe.names[node.target.id] = p
    hits: list[dict[str, Any]] = []

    def rel(p: Path) -> Optional[str]:
        try:
            return str(p.relative_to(pe.repo))
        except ValueError:
            return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = ast.unparse(node.func)
        target: Optional[Path] = None
        op = ""
        if isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_ATTRS:
            target, op = pe.ev(node.func.value), node.func.attr
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            mode = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "mode"), None)
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and re.search(r"[wax+]", mode.value):
                target, op = pe.ev(node.func.value), f"open({mode.value})"
        elif fn == "open" and node.args:
            mode = (
                node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
            )
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and re.search(r"[wax+]", mode.value):
                target, op = pe.ev(node.args[0]), f"open({mode.value})"
        elif fn in WRITE_FUNCS and node.args:
            idx = (
                1
                if fn.startswith(("shutil.copy", "shutil.move", "os.replace", "os.rename")) and len(node.args) > 1
                else 0
            )
            target, op = pe.ev(node.args[idx]), fn
        elif WRITE_NAME_RX.search(fn.rsplit(".", 1)[-1]) and not fn.startswith(("print", "log")):
            for a in list(node.args[:2]) + [k.value for k in node.keywords if k.arg in ("path", "dest", "out")]:
                t = pe.ev(a)
                if t is not None:
                    target, op = t, f"{fn}()"
                    break
        if target is None:
            continue
        r = rel(target)
        if r is None or r in ("", "."):
            continue
        r = os.path.normpath(r)
        if r.startswith(".."):
            continue
        hits.append({"script": str(script.relative_to(repo)), "line": node.lineno, "op": op, "path": r})
    return hits


def release_status(rel_path: str, release: Path) -> str:
    """linked:<target> when a component under the release is a symlink (checked top-down, so a linked parent
    wins); release-local when the whole path exists as real entries inside the release; absent otherwise."""
    cur = release
    for part in Path(rel_path.replace("{*}", "_")).parts:
        cur = cur / part
        if cur.is_symlink():
            return f"linked:{os.readlink(cur)}"
        if not cur.exists():
            return "absent"
    return "release-local"


def write_status(rel_path: str, release: Path) -> str:
    """Where a WRITE to <release>/<rel_path> lands. linked:<target> when a component is a symlink (the write
    reaches a store outside the release); otherwise release-local: the bytes stay in this release dir and the
    next promote's rsync-from-PREV copy forks them (WS6-08). A missing component is still release-local: the
    job would create it inside the release."""
    cur = release
    for part in Path(rel_path.replace("{*}", "_")).parts:
        cur = cur / part
        if cur.is_symlink():
            return f"linked:{os.readlink(cur)}"
        if not cur.exists():
            return "release-local"
    return "release-local"


def _prefix(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if len(parts) <= 1:
        return parts[0] if parts else ""
    if parts[0] in ("data", "state", "docs") and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0] if len(parts) == 2 else "/".join(parts[:2])


def scan_repo_write_paths(repo: Path, release: Optional[Path]) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    for sub in ("scripts", "agents", "linux_launchers"):
        base = repo / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if any(part in {"__pycache__", "node_modules", "tests"} for part in p.parts):
                continue
            hits.extend(scan_write_paths(p, repo))
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for h in hits:
        h["status"] = write_status(h["path"], release) if release else "unknown"
        kind = "linked" if h["status"].startswith("linked:") else h["status"]
        key = (_prefix(h["path"]), kind)
        row = by_key.setdefault(key, {"prefix": key[0], "status": kind, "writes": 0, "scripts": set(), "examples": []})
        row["writes"] += 1
        row["scripts"].add(h["script"])
        if len(row["examples"]) < 3 and h["path"] not in row["examples"]:
            row["examples"].append(h["path"])
    rows = sorted(by_key.values(), key=lambda r: (-r["writes"], r["prefix"]))
    for row in rows:
        row["scripts"] = sorted(row["scripts"])
    local = [r for r in rows if r["status"] == "release-local"]
    return {
        "write_sites": len(hits),
        "scripts_writing": len({h["script"] for h in hits}),
        "write_sites_release_local": sum(r["writes"] for r in local),
        "write_sites_linked": sum(r["writes"] for r in rows if r["status"] == "linked"),
        "prefixes": rows,
        "release_local": local,
        "hits": hits,
    }


def dev_root_code_refs(repo: Path, layout: Layout) -> dict[str, Any]:
    """Python and shell files that name the dev tree literally (they reach back into it from any release)."""
    py, sh = [], []
    for p in sorted((repo / "scripts").rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix not in (".py", ".sh"):
            continue
        try:
            t = normalize(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if layout.dev_root in t:
            (py if p.suffix == ".py" else sh).append(str(p.relative_to(repo)))
    return {"python_files": len(py), "shell_files": len(sh), "python": py, "shell": sh}


# --------------------------------------------------------------------------- forced-run script


def forced_run_script(candidate: str, cohort: str) -> str:
    """A bash script that replays each cohort line exactly as cron would (cron's env: SHELL, HOME, LOGNAME,
    PATH=/usr/bin:/bin plus the crontab's own assignments above the line) — PROBE ONLY unless RUN=1.

    The probe prints the PY / TRADEAI_VENV_PYTHON the line will see and refuses when $RPY is not executable,
    so the first forced run cannot silently fall back to the dev venv."""
    lines = parse_crontab(candidate)
    envs = cron_env_at(lines)
    out = [
        "#!/usr/bin/env bash",
        f"# forced run of cohort {cohort} — generated by scripts/run_from_release.py forced-run. PROBE ONLY by default.",
        "# RUN=1 executes each line once, in cron's environment. LINE=<n> limits it to one line.",
        "set -u",
        'RUN="${RUN:-0}"; ONLY="${LINE:-}"; rc_all=0',
    ]
    n = 0
    for ln, env in zip(lines, envs):
        if ln.kind != "job":
            continue
        m = PREFIX_RX.match(ln.command)
        if not m or m.group("cohort") != cohort:
            continue
        if re.search(r"(?<!\\)%", ln.command):
            out.append(f"echo 'line {ln.lineno}: unescaped % (cron would truncate it) — refusing'; rc_all=1")
            continue
        command = ln.command.replace("\\%", "%")
        cron_env = {
            "SHELL": env.get("SHELL", "/bin/sh"),
            "HOME": HOME,
            "LOGNAME": os.environ.get("USER", "johnclaw"),
            "PATH": env.get("PATH", "/usr/bin:/bin"),
        }
        cron_env.update({k: v for k, v in env.items() if k not in cron_env})
        env_args = " ".join(shlex.quote(f"{k}={v}") for k, v in cron_env.items())
        shell = shlex.quote(cron_env["SHELL"])
        probe = (
            command[: m.end()]
            + 'test -x "$RPY" || { echo "RPY not executable: $RPY"; exit 97; }; '
            + 'printf "probe PY=%s TRADEAI_VENV_PYTHON=%s\\n" "$PY" "$TRADEAI_VENV_PYTHON"'
        )
        n += 1
        out += [
            "",
            f"# line {ln.lineno}: {ln.schedule}",
            f'if [[ -z "$ONLY" || "$ONLY" == "{ln.lineno}" ]]; then',
            f"  echo '== line {ln.lineno}'",
            f"  env -i {env_args} {shell} -c {shlex.quote(probe)} || {{ rc_all=1; echo 'probe FAILED line {ln.lineno}'; }}",
            '  if [[ "$RUN" == "1" ]]; then',
            f"    ( cd {shlex.quote(HOME)} && env -i {env_args} {shell} -c {shlex.quote(command)} ); rc=$?",
            f'    echo "line {ln.lineno} exit=$rc"; [[ $rc -eq 0 ]] || rc_all=1',
            "  fi",
            "fi",
        ]
    out += ["", f"echo 'cohort {cohort}: {n} line(s); RUN='\"$RUN\"", "exit $rc_all", ""]
    return "\n".join(out)


# --------------------------------------------------------------------------- inventory


def inventory(crontab_text: str, cfg: Config, unit_cats: dict[str, str], states: dict[str, str]) -> dict[str, Any]:
    lines = parse_crontab(crontab_text)
    envs = cron_env_at(lines)
    cache: dict[str, dict] = {}
    jobs = [classify_job(ln, env, cfg, cache) for ln, env in zip(lines, envs) if ln.kind == "job"]
    units = [classify_unit(u, t, cfg, states.get(u, "")) for u, t in sorted(unit_cats.items())]

    def count(rows: list[dict], key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    wrappers = list(cache.values())
    header = {ln.name: ln.value for ln in lines if ln.kind == "env"}
    return {
        "schema": "RunFromReleaseInventory@v1",
        "crontab": {
            "lines_total": len(lines),
            "jobs_active": len(jobs),
            "env_header": {k: v for k, v in header.items() if k in ("PY", "PROJ", "TRADEAI_ENV", "RPY", CODE_ROOT_VAR)},
            "by_root": count(jobs, "root"),
            "by_interpreter": count(jobs, "interpreter"),
            "executes_dev": sum(1 for j in jobs if j["executes_dev"]),
            "trade_ai_jobs": sum(1 for j in jobs if j["trade_ai"]),
            "broker_adjacent": sum(1 for j in jobs if j["broker_adjacent"]),
            "wrappers": {
                "distinct": len(wrappers),
                "pins_dev": sum(1 for w in wrappers if w["verdict"] == "pins_dev"),
                "dev_default": sum(1 for w in wrappers if w["verdict"] == "dev_default"),
                "clean": sum(1 for w in wrappers if w["verdict"] == "clean"),
                "missing": sum(1 for w in wrappers if w["verdict"] == "missing"),
            },
            "jobs_via_pins_dev_wrapper": sum(1 for j in jobs if j["wrapper"] and j["wrapper"]["verdict"] == "pins_dev"),
        },
        "units": {
            "services_total": len(units),
            "by_root": count(units, "root"),
            "by_interpreter": count(units, "interpreter"),
            "by_state": count(units, "state"),
            "by_unit_cohort": count([u for u in units if u["root"] == "dev"], "unit_cohort"),
            "daemons_on_dev": sum(1 for u in units if u["root"] == "dev" and u["daemon"]),
        },
        "jobs": jobs,
        "unit_rows": [{k: v for k, v in u.items() if k != "_eff"} for u in units],
        "wrapper_rows": wrappers,
    }


# --------------------------------------------------------------------------- CLI


def _read_crontab(path: Optional[str]) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30).stdout


def _collect_units(unit_dir: Path, cat_dir: Optional[str]) -> tuple[dict[str, str], dict[str, str]]:
    if cat_dir:
        cats = {p.name[: -len(".cat")]: p.read_text(encoding="utf-8") for p in sorted(Path(cat_dir).glob("*.cat"))}
        return cats, {}
    names = list_user_services(unit_dir)
    return {n: systemctl_cat(n) for n in names}, unit_states()


def _write(out: Path, name: str, text: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = out / name
    p.write_text(text, encoding="utf-8")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_inv = sub.add_parser("inventory", help="classify crontab lines and user services (read-only)")
    p_inv.add_argument("--crontab-file")
    p_inv.add_argument("--unit-dir", default=str(Path.home() / ".config/systemd/user"))
    p_inv.add_argument("--unit-cat-dir", help="directory of <unit>.cat files instead of systemctl (tests)")
    p_inv.add_argument("--json")

    p_cr = sub.add_parser("crontab", help="write a candidate crontab + diff (never installs)")
    p_cr.add_argument("--crontab-file")
    p_cr.add_argument("--cohorts", default="")
    p_cr.add_argument("--revert", default="")
    p_cr.add_argument("--final", action="store_true")
    p_cr.add_argument("--out", required=True)
    p_cr.add_argument("--no-lane-gate", action="store_true")

    p_dr = sub.add_parser("dropins", help="write candidate unit drop-ins (never installs)")
    p_dr.add_argument("--unit-dir", default=str(Path.home() / ".config/systemd/user"))
    p_dr.add_argument("--unit-cat-dir")
    p_dr.add_argument("--units", default="u1,u2,u3", help="unit cohorts to emit")
    p_dr.add_argument("--out", required=True)

    p_ve = sub.add_parser("verify", help="dry-run rewritten lines from CURRENT (sandboxed --help / bash -n)")
    p_ve.add_argument("--crontab-file", required=True)
    p_ve.add_argument("--cohorts", default="")
    p_ve.add_argument("--all", action="store_true", help="every trade-ai job, migrated or not")
    p_ve.add_argument("--python", required=True, help="the release venv interpreter to test with")
    p_ve.add_argument("--sandbox", choices=("bwrap", "none"), default="bwrap")
    p_ve.add_argument("--scratch", default=os.environ.get("TMPDIR", "/tmp"))
    p_ve.add_argument("--json")

    p_fr = sub.add_parser("forced-run", help="emit a probe/forced-run script for one cohort of a candidate")
    p_fr.add_argument("--crontab-file", required=True)
    p_fr.add_argument("--cohort", required=True)
    p_fr.add_argument("--out", required=True)

    p_wp = sub.add_parser("write-paths", help="paths code writes relative to its own root (WS6-08)")
    p_wp.add_argument("--repo", default=str(REPO))
    p_wp.add_argument("--release", default="")
    p_wp.add_argument("--json")

    a = ap.parse_args(argv)
    cfg = load_config(Path(a.config))

    if a.cmd == "inventory":
        cats, states = _collect_units(Path(a.unit_dir), a.unit_cat_dir)
        inv = inventory(_read_crontab(a.crontab_file), cfg, cats, states)
        if a.json:
            _write(Path(a.json).parent, Path(a.json).name, json.dumps(inv, indent=2, default=str))
        print(json.dumps({"crontab": inv["crontab"], "units": inv["units"]}, indent=2))
        return 0

    if a.cmd == "crontab":
        live = _read_crontab(a.crontab_file)
        res = generate_crontab(
            live,
            cfg,
            cohorts=[c for c in a.cohorts.split(",") if c],
            revert=[c for c in a.revert.split(",") if c],
            final=a.final,
            keep_declared=None if a.no_lane_gate else lane_declared_checker(),
        )
        out = Path(a.out)
        _write(out, "crontab.live", live)
        _write(out, "crontab.candidate", res.text)
        _write(out, "crontab.diff", res.diff)
        gate = {"skipped": True} if a.no_lane_gate else lane_gate(live, res.text)
        summary = dict(res.summary, lane_gate=gate, changed=res.changed)
        _write(out, "crontab.summary.json", json.dumps(summary, indent=2))
        print(json.dumps({k: v for k, v in summary.items() if k != "changed"}, indent=2))
        print(f"candidate → {out / 'crontab.candidate'} (NOT installed)")
        return 0 if gate.get("ok", True) else 2

    if a.cmd == "dropins":
        cats, states = _collect_units(Path(a.unit_dir), a.unit_cat_dir)
        want = {c for c in a.units.split(",") if c}
        out = Path(a.out)
        rows = []
        for u, t in sorted(cats.items()):
            info = classify_unit(u, t, cfg, states.get(u, ""))
            if info["root"] != "dev" and not info["dev_refs"]:
                continue
            text = render_dropin(info, cfg, cfg.exclude_units) if info["unit_cohort"] in want else None
            if text:
                _write(out / f"{u}.d", DROPIN_NAME, text)
            rows.append(
                {
                    "unit": u,
                    "unit_cohort": info["unit_cohort"],
                    "daemon": info["daemon"],
                    "broker_adjacent": info["broker_adjacent"],
                    "state": info["state"],
                    "emitted": bool(text),
                    "excluded": u in cfg.exclude_units,
                    "blockers": info.get("blockers", []),
                }
            )
        _write(out, "dropins.summary.json", json.dumps(rows, indent=2))
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["unit_cohort"]] = counts.get(r["unit_cohort"], 0) + 1
        print(
            json.dumps(
                {
                    "dev_units": len(rows),
                    "emitted": sum(r["emitted"] for r in rows),
                    "emitted_ready": sum(1 for r in rows if r["emitted"] and not r["blockers"]),
                    "emitted_blocked": sum(1 for r in rows if r["emitted"] and r["blockers"]),
                    "excluded": [r["unit"] for r in rows if r["excluded"]],
                    "by_cohort": counts,
                },
                indent=2,
            )
        )
        print(f"drop-ins → {out} (NOT installed)")
        return 0

    if a.cmd == "verify":
        if a.sandbox == "bwrap" and not shutil.which("bwrap"):
            print("bwrap missing: refusing to run --help outside a sandbox (pass --sandbox none to accept)")
            return 2
        text = Path(a.crontab_file).read_text(encoding="utf-8")
        lines = parse_crontab(text)
        envs = cron_env_at(lines)
        cache: dict[str, dict] = {}
        wanted = {c for c in a.cohorts.split(",") if c}
        results = []
        for ln, env in zip(lines, envs):
            if ln.kind != "job":
                continue
            job = classify_job(ln, env, cfg, cache)
            if not job["trade_ai"]:
                continue
            if not a.all and (job["migrated_cohort"] is None or (wanted and job["migrated_cohort"] not in wanted)):
                continue
            r = verify_job(job, cfg, a.python, a.scratch, sandbox=a.sandbox)
            r["cohort"] = job["migrated_cohort"] or assign_cohort(job, cfg)
            r["broker_adjacent"] = bool(job["broker_adjacent"])
            results.append(r)
        tally: dict[str, int] = {}
        for r in results:
            tally[r["result"]] = tally.get(r["result"], 0) + 1
        report = {
            "schema": "RunFromReleaseVerify@v1",
            "python": a.python,
            "sandbox": a.sandbox,
            "lines": len(results),
            "tally": tally,
            "results": results,
        }
        if a.json:
            _write(Path(a.json).parent, Path(a.json).name, json.dumps(report, indent=2))
        print(json.dumps({"lines": len(results), "tally": tally}, indent=2))
        return 0 if not tally.get("fail") else 1

    if a.cmd == "forced-run":
        text = forced_run_script(Path(a.crontab_file).read_text(encoding="utf-8"), a.cohort)
        p = _write(Path(a.out).parent, Path(a.out).name, text)
        p.chmod(0o700)
        print(f"forced-run script → {p} (probe only unless RUN=1)")
        return 0

    if a.cmd == "write-paths":
        repo = Path(a.repo)
        release = Path(a.release) if a.release else Path(os.path.realpath(cfg.layout.current))
        rep = scan_repo_write_paths(repo, release if release.is_dir() else None)
        rep["dev_root_code_refs"] = dev_root_code_refs(repo, cfg.layout)
        if a.json:
            _write(Path(a.json).parent, Path(a.json).name, json.dumps(rep, indent=2))
        print(
            json.dumps(
                {
                    "write_sites": rep["write_sites"],
                    "scripts_writing": rep["scripts_writing"],
                    "write_sites_release_local": rep["write_sites_release_local"],
                    "write_sites_linked": rep["write_sites_linked"],
                    "release_local_prefixes": [
                        (r["prefix"], r["writes"], len(r["scripts"])) for r in rep["release_local"]
                    ],
                    "dev_root_code_refs": {k: v for k, v in rep["dev_root_code_refs"].items() if k.endswith("_files")},
                },
                indent=2,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
