"""Which user units resolved the release ``CURRENT`` symlink at start, which may a promote restart, and did it work?

A unit with ``WorkingDirectory=.../portfolio-server/CURRENT`` resolves the symlink once, at start, and keeps the
concrete release directory for its whole life. Every promote strands it on the old release until something restarts
it. 2026-10-31 (live read-back): tradeai-ops-applier on 10-22 code (refusing newer Ops Controls kinds as
KIND_UNKNOWN), grok-/chatgpt-oauth-proxy and heartbeat-receiver on 10-11/10-13 code, tradeai-active-trader-motion on
10-30 code.

The rule (AGENTS.md 28.1.0 §25.10), FAIL-CLOSED by construction:

* **Restart** only units that are (a) on ``HISTORICAL_DEFAULTS`` — the deploy's long-standing list, which 28.1.0
  only narrows — or (b) on ``ADDITIONAL_RESTART_SAFE``, the three daemons named in the 28.1.0 text; AND whose
  WorkingDirectory is ``CURRENT`` (the only binding verify can read back from ``/proc/<pid>/cwd``); AND which are
  installed units (FragmentPath under ``~/.config/systemd/user``, ``Transient=no``). Discovery never adds a unit.
* **Never restart, page only:**
  - ``PAGE_ONLY_NAMED`` (tradeai-ops-applier: writes guard grants, engages the kill switch, clears STOP, no SIGTERM
    handler; portfolio-server: the deploy's own path).
  - ``MARKET_HOURS_PAGE_ONLY`` (tradeai-telegram-callback-poller: /ptapprove, /stop, guard /approve, Schwab OAuth
    exchange) while any US equity session is open (04:00–20:00 ET on a trading day).
  - Any unit whose name, ExecStart argv, WorkingDirectory or environment trips ``HARD_NEVER`` (broker, order,
    §24.10 ``active_trader/`` and ``brokers/`` paths, …) — applied to EVERY candidate, defaults and operator
    override included.
  - Units outside the two lists, or on ``ADDITIONAL_RESTART_SAFE`` but tripping the ``lane_dispatch`` forbidden-token
    matcher (AGENTS.md §23.14) on their argv.
  - Units bound only through ExecStart, the environment, or a cwd inside a release.
* At most ``MAX_RESTARTS`` restarts per promote (circuit breaker); the rest are paged.

Read-only: nothing here restarts anything. The restart stays in ``scripts/cio_phase2_exact_main_deploy.sh`` after
``health_check`` passed; ``scripts/current_bound_units.py verify`` is the single judge afterwards.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

RELEASES_BASE = Path(os.environ.get("TRADEAI_RELEASES_BASE") or Path.home() / "trade-ai-releases" / "portfolio-server")
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
ET = ZoneInfo("America/New_York")
MAX_RESTARTS = 12

# The deploy's long-standing bound list (the restart_root_frozen_units default literal). 28.1.0 only narrows it.
HISTORICAL_DEFAULTS: tuple[str, ...] = (
    "tradeai-health-agent.service",
    "cio-governed-bridge.service",
    "tradeai-cio-telegram.service",
    "tradeai-telegram-callback-poller.service",
    "tradeai-n8n-coordination-gateway.service",
    "tradeai-n8n-run-relay.service",
    "tradeai-n8n-run-executor.service",
    "tradeai-phone-status.service",
)
# Named in the AGENTS.md 28.1.0 text; ratification is the operator decision config/release_pin_daemons.json reserves.
ADDITIONAL_RESTART_SAFE: tuple[str, ...] = (
    "grok-oauth-proxy.service",
    "chatgpt-oauth-proxy.service",
    "heartbeat-receiver.service",
)
PAGE_ONLY_NAMED: dict[str, str] = {
    "tradeai-ops-applier.service": "ops_applier_writes_grants_killswitch_stop",
    "portfolio-server.service": "separately_handled",
}
MARKET_HOURS_PAGE_ONLY: dict[str, str] = {
    "tradeai-telegram-callback-poller.service": "approval_and_oauth_handler_market_open",
}
# Applied to every candidate, whatever list it came from. Word tokens match whole words/path segments; tokens with
# a "/" or "-" match as substrings of the argv/path text.
HARD_NEVER: tuple[str, ...] = (
    "broker",
    "brokers/",
    "brokerage",
    "order",
    "orders",
    "place_order",
    "active_trader/",
    "active-trader",
    "active_trader",
    "activetrader",
    "schwab",
    "alpaca",
    "moomoo",
    "snaptrade",
    "mbi",
    "2fa",
    "totp",
    "two_factor",
    "bws",
    "bitwarden",
    "render_env",
    "render-env",
    "secret",
    "secrets/",
    "kill_switch",
    "kill-switch",
    "killswitch",
    "sizing",
    "stoploss",
    "stop_loss",
    "gain_guardian",
    "gain-guardian",
    "holding_protection",
    "holding-protection",
    "scalp_live",
    "scalp-live",
    "scalplive",
    "paper_exec",
    "paper-exec",
    "deploy",
    "guard",
    "dof",
)
# AGENTS.md §23.14 word classes. Matched as whole words / path components of the unit NAME, argv and
# WorkingDirectory only (so `trade-ai-releases` never hits, and an environment variable NAME such as
# COMMS_INBOUND_SENDER_ALLOWLIST does not turn a reader into a "sender").
WORD_NEVER_23_14: tuple[str, ...] = (
    "stop",
    "position",
    "account",
    "sender",
    "execution",
    "retention",
    "agent-loop",
    "agent_loop",
)

Runner = Callable[[list[str]], str]


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _hit(text: str, tokens: Iterable[str]) -> str | None:
    t = text.lower()
    for tok in tokens:
        tok = tok.lower()
        if re.fullmatch(r"[a-z0-9]+", tok):
            if re.search(rf"(^|[^a-z0-9]){re.escape(tok)}s?([^a-z0-9]|$)", t):
                return tok
        elif tok in t:
            return tok
    return None


def _dispatch_hit(name: str, argv: str) -> str | None:
    try:
        from scripts.lib import lane_dispatch as ld  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — fail closed: an unloadable matcher refuses every additional unit
        return "lane_dispatch_unavailable"
    hits = ld.forbidden_hits({"lane_id": name, "exec_start": argv})
    return hits[0][0] if hits else None


def extra_never_tokens() -> list[str]:
    raw = os.environ.get("TRADEAI_CURRENT_BOUND_EXTRA_NEVER", "")
    return [t for t in raw.replace(",", " ").split() if t]


def market_open(now: datetime | None = None, *, trading_day: Callable[[datetime], bool] | None = None) -> bool:
    """Any US equity session (pre, regular, after: 04:00–20:00 ET) on a trading day."""
    now = (now or datetime.now(ET)).astimezone(ET)
    if trading_day is None:
        try:
            from market_session import is_trading_day  # noqa: PLC0415

            trading_day = is_trading_day
        except Exception:  # noqa: BLE001 — unknown calendar: treat weekdays as trading days (fail closed)

            def trading_day(d):
                return d.weekday() < 5

    if not trading_day(now):
        return False
    return 4 <= now.hour < 20


def path_names_current(text: str, current_link: str) -> bool:
    """Full-path match: ``CURRENT`` as a whole path component, so ``CURRENT-foo`` never matches."""
    return re.search(rf"(^|[\s=:;'\"]){re.escape(current_link)}(/|$|[\s;'\"])", text) is not None


def in_release(cwd: str, current_dir: str) -> bool:
    """The one rule bash and Python share: cwd is the release dir or inside it."""
    cur = str(current_dir).rstrip("/")
    return bool(cwd) and (cwd == cur or cwd.startswith(cur + "/"))


def decide(
    name: str,
    *,
    argv: str,
    wd: str,
    env: str,
    installed: bool,
    current_link: str,
    is_market_open: bool,
    extra_never: Iterable[str] = (),
) -> tuple[bool, str]:
    """Fail-closed decision for one unit: (restart, reason)."""
    if name in PAGE_ONLY_NAMED:
        return False, PAGE_ONLY_NAMED[name]
    hard = _hit(f"{name} {argv} {wd} {env}", (*HARD_NEVER, *extra_never)) or _hit(
        f"{name} {argv} {wd}", WORD_NEVER_23_14
    )
    if hard:
        return False, f"never:{hard}"
    if is_market_open and name in MARKET_HOURS_PAGE_ONLY:
        return False, MARKET_HOURS_PAGE_ONLY[name]
    if not installed:
        return False, "transient_or_not_user_unit"
    if not path_names_current(wd, current_link):
        return False, "not_working_directory_bound"
    if name in HISTORICAL_DEFAULTS:
        return True, "historical_default"
    if name in ADDITIONAL_RESTART_SAFE:
        d = _dispatch_hit(name, argv)
        if d:
            return False, f"lane_dispatch:{d}"
        return True, "named_in_28_1_0"
    return False, "not_on_restart_safe_list"


@dataclass
class Unit:
    name: str
    working_directory: str
    argv: str
    main_pid: int
    cwd: str
    stale: bool
    action: str  # restart | page_only
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


PROPS = ("WorkingDirectory", "ExecStart", "MainPID", "Environment", "EnvironmentFiles", "FragmentPath", "Transient")


def _show(run: Runner, unit: str) -> dict[str, str]:
    cmd = ["systemctl", "--user", "show"]
    for p in PROPS:
        cmd += ["-p", p]
    props: dict[str, str] = {}
    for ln in run(cmd + [unit]).splitlines():
        key, _, val = ln.partition("=")
        props[key] = val
    return props


def _argv(exec_start: str) -> str:
    m = re.search(r"argv\[\]=([^;]*)", exec_start)
    return (m.group(1) if m else exec_start).strip()


def _installed(props: dict[str, str]) -> bool:
    frag = props.get("FragmentPath", "")
    return props.get("Transient", "no") != "yes" and bool(frag) and frag.startswith(str(USER_UNIT_DIR) + "/")


def _cwd(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def _decide_for(name: str, props: dict[str, str], current_link: str, is_open: bool, extra_never) -> tuple[bool, str]:
    return decide(
        name,
        argv=_argv(props.get("ExecStart", "")),
        wd=props.get("WorkingDirectory", ""),
        env=f"{props.get('Environment', '')} {props.get('EnvironmentFiles', '')}",
        installed=_installed(props),
        current_link=current_link,
        is_market_open=is_open,
        extra_never=extra_never,
    )


def plan(
    current_dir: str | Path,
    *,
    releases_base: str | Path = RELEASES_BASE,
    extra_never: Iterable[str] | None = None,
    run: Runner = _run,
    cwd_of: Callable[[int], str] = _cwd,
    now: datetime | None = None,
    is_open: bool | None = None,
) -> Plan:
    """Derive the CURRENT-bound running units and decide restart (fail-closed) vs page-only. Read-only."""
    base = str(Path(releases_base))
    current_link = f"{base}/CURRENT"
    cur = str(current_dir)
    extra = list(extra_never) if extra_never is not None else extra_never_tokens()
    is_open = market_open(now) if is_open is None else is_open
    p = Plan(current=cur)
    for name in _running_services(run):
        props = _show(run, name)
        wd, ex = props.get("WorkingDirectory", ""), props.get("ExecStart", "")
        env = f"{props.get('Environment', '')} {props.get('EnvironmentFiles', '')}"
        try:
            pid = int(props.get("MainPID") or 0)
        except ValueError:
            pid = 0
        cwd = cwd_of(pid)
        bound = (
            path_names_current(wd, current_link)
            or path_names_current(ex, current_link)
            or path_names_current(env, current_link)
            or cwd.startswith(base + "/")
        )
        if not bound:
            continue
        stale = not in_release(cwd, cur)
        ok, reason = _decide_for(name, props, current_link, is_open, extra)
        if ok and len(p.restart) >= MAX_RESTARTS:
            ok, reason = False, "restart_cap_reached"
        (p.restart if ok else p.page_only).append(name)
        p.units.append(Unit(name, wd, _argv(ex)[:200], pid, cwd, stale, "restart" if ok else "page_only", reason))
    return p


def filter_units(
    names: Iterable[str],
    *,
    releases_base: str | Path = RELEASES_BASE,
    extra_never: Iterable[str] | None = None,
    run: Runner = _run,
    now: datetime | None = None,
    is_open: bool | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Apply the same fail-closed rule to ANY candidate list (defaults, derived or operator override)."""
    current_link = f"{Path(releases_base)}/CURRENT"
    extra = list(extra_never) if extra_never is not None else extra_never_tokens()
    is_open = market_open(now) if is_open is None else is_open
    keep: list[str] = []
    refused: dict[str, str] = {}
    for name in dict.fromkeys(n for n in names if n):
        ok, reason = _decide_for(name, _show(run, name), current_link, is_open, extra)
        if ok and len(keep) >= MAX_RESTARTS:
            ok, reason = False, "restart_cap_reached"
        if ok:
            keep.append(name)
        else:
            refused[name] = reason
    return keep, refused


def verify(
    current_dir: str | Path,
    units: Iterable[str],
    *,
    run: Runner = _run,
    cwd_of: Callable[[int], str] = _cwd,
) -> dict[str, dict]:
    """Read back each unit's live cwd. ``ok`` only when it resolves inside ``current_dir``."""
    out: dict[str, dict] = {}
    for name in units:
        props = _show(run, name)
        try:
            pid = int(props.get("MainPID") or 0)
        except ValueError:
            pid = 0
        cwd = cwd_of(pid)
        out[name] = {"pid": pid, "cwd": cwd, "ok": in_release(cwd, current_dir)}
    return out
