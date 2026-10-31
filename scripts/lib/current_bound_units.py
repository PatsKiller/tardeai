"""Which user units resolved the release ``CURRENT`` symlink at start, and do they now run the new release?

A unit with ``WorkingDirectory=.../portfolio-server/CURRENT`` (or an ``ExecStart`` naming that path) resolves the
symlink once, when it starts, and keeps the concrete release directory for its whole life. Every promote therefore
strands it on the old release until something restarts it. ``restart_root_frozen_units`` in
``scripts/cio_phase2_exact_main_deploy.sh`` restarted a fixed list; units outside that list stayed stale for weeks.
2026-10-31 (live read-back): tradeai-ops-applier on 99bfa4abc and before that on 10-22 code (it refused every newer
Ops Controls kind as KIND_UNKNOWN), grok-oauth-proxy and heartbeat-receiver on 10-11 code, chatgpt-oauth-proxy on
10-13 code, tradeai-active-trader-motion on 10-30 code.

This module DERIVES the bound set from the running units instead of trusting a hand list:

* ``plan(current_dir)`` lists running user services whose WorkingDirectory or ExecStart references the releases'
  ``CURRENT`` path, or whose live process cwd sits in a release directory. It splits them into ``restart`` (safe to
  restart after the health check) and ``page_only`` (never restarted by the deploy: the AGENTS.md §23.14 never-list —
  broker, order, execution, scalp, sender, guard, secret, stop, position, account, paper, deploy/release,
  retention, agent-loop, DOF — plus Active Trader, a held class, and portfolio-server, which the deploy restarts on
  its own path). The never-list is a code constant; config can only ADD names (``extra_never``), never remove.
* ``verify(current_dir, units)`` reads each unit's ``/proc/<MainPID>/cwd`` back. Activeness proves nothing — a stale
  unit stays active — so the read-back is the only check that counts.

The CLI (``scripts/current_bound_units.py``) prints the plan (dry run, the default), verifies, writes a receipt and
pages P1 when a unit is still stale after the restart. Restarting itself stays in the deploy script, after
``health_check`` passed. Read-only here: this module never restarts anything.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

RELEASES_BASE = Path(os.environ.get("TRADEAI_RELEASES_BASE") or Path.home() / "trade-ai-releases" / "portfolio-server")

# AGENTS.md §23.14 never-list, matched case-insensitively as whole words or word parts of the unit name.
# Code constant: config may extend it (extra_never) but cannot shrink it.
NEVER_TOKENS: tuple[str, ...] = (
    "broker",
    "order",
    "execution",
    "exec-live",
    "scalp",
    "sender",
    "guard",
    "secret",
    "stop",
    "position",
    "account",
    "paper",
    "deploy",
    "release",
    "retention",
    "agent-loop",
    "dof",
    "schwab",
    "alpaca",
    "moomoo",
    "active-trader",  # Active Trader / MBI is a held class (config/merge_hold_paths.json)
)
# Restarted by the deploy's own promote/health path; never by this list.
SEPARATELY_HANDLED: frozenset[str] = frozenset({"portfolio-server.service"})

Runner = Callable[[list[str]], str]


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False).stdout


def never_reason(unit: str, extra_never: Iterable[str] = ()) -> str | None:
    """Return the matching never-token for ``unit`` or None. Case-insensitive; tokens match as name parts."""
    name = unit.lower()
    if name in SEPARATELY_HANDLED:
        return "separately_handled"
    for tok in (*NEVER_TOKENS, *(t.lower() for t in extra_never)):
        if re.search(rf"(^|[^a-z0-9]){re.escape(tok)}s?([^a-z0-9]|$)", name):
            return tok
    return None


@dataclass
class Unit:
    name: str
    working_directory: str
    exec_start: str
    main_pid: int
    cwd: str
    bound: bool
    stale: bool
    action: str  # restart | page_only | skip
    reason: str = ""


@dataclass
class Plan:
    current: str
    restart: list[str] = field(default_factory=list)
    page_only: list[str] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "current": self.current,
            "restart": self.restart,
            "page_only": self.page_only,
            "units": [asdict(u) for u in self.units],
        }


def _running_services(run: Runner) -> list[str]:
    out = run(["systemctl", "--user", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"])
    return [ln.split()[0] for ln in out.splitlines() if ln.split()]


def _show(run: Runner, unit: str) -> dict[str, str]:
    out = run(["systemctl", "--user", "show", "-p", "WorkingDirectory", "-p", "ExecStart", "-p", "MainPID", unit])
    props: dict[str, str] = {}
    for ln in out.splitlines():
        key, _, val = ln.partition("=")
        props[key] = val
    return props


def _cwd(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def plan(
    current_dir: str | Path,
    *,
    releases_base: str | Path = RELEASES_BASE,
    extra_never: Iterable[str] = (),
    run: Runner = _run,
    cwd_of: Callable[[int], str] = _cwd,
) -> Plan:
    """Derive the CURRENT-bound running units and decide restart vs page-only. Read-only."""
    base = str(Path(releases_base))
    current_link = f"{base}/CURRENT"
    cur = str(current_dir)
    p = Plan(current=cur)
    for name in _running_services(run):
        props = _show(run, name)
        wd = props.get("WorkingDirectory", "")
        ex = props.get("ExecStart", "")
        try:
            pid = int(props.get("MainPID") or 0)
        except ValueError:
            pid = 0
        cwd = cwd_of(pid)
        in_release = cwd.startswith(base + "/") and cwd != current_link
        bound = (current_link in wd) or (current_link in ex) or in_release
        if not bound:
            continue
        stale = bool(cwd) and not (cwd == cur or cwd.startswith(cur + "/"))
        reason = never_reason(name, extra_never)
        if reason:
            action = "page_only"
            p.page_only.append(name)
        else:
            action = "restart"
            p.restart.append(name)
        p.units.append(Unit(name, wd, ex[:200], pid, cwd, bound, stale, action, reason or ""))
    return p


def verify(
    current_dir: str | Path,
    units: Iterable[str],
    *,
    run: Runner = _run,
    cwd_of: Callable[[int], str] = _cwd,
) -> dict[str, dict]:
    """Read back each unit's live cwd. ``ok`` only when it resolves inside ``current_dir``."""
    cur = str(current_dir)
    out: dict[str, dict] = {}
    for name in units:
        props = _show(run, name)
        try:
            pid = int(props.get("MainPID") or 0)
        except ValueError:
            pid = 0
        cwd = cwd_of(pid)
        ok = bool(cwd) and (cwd == cur or cwd.startswith(cur + "/"))
        out[name] = {"pid": pid, "cwd": cwd, "ok": ok}
    return out
