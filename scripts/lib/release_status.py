"""Release status gate (QA-GOLDEN-RULES E15): DEPLOYED / LIVE / VERIFIED, computed from /proc, never declared.

  DEPLOYED  the activation finished (CURRENT points at the target) but one or more intended services still run
            another release, or their release cannot be read. Deploy success is not release success.
  LIVE      every intended service runs the target release (``/proc/<pid>/cwd`` resolves inside it).
  VERIFIED  LIVE and every acceptance probe passed. A probe that was skipped or could not run is NOT a pass
            (unknown beats wrong), so the release stays LIVE.

Intended services: every running ``tradeai-*`` and ``portfolio-server`` user unit bound to a release. The binding
and the page-only / never-restart lists are ``lib.current_bound_units``'s, reused, not copied: this module adds no
list of its own. Units the activation skips by design (ops-applier, active-trader-motion, the callback poller
during market hours) therefore hold the release at DEPLOYED until their restart is confirmed. One-shot units that
timers start resolve ``CURRENT`` afresh on every start and are not long-lived, so they are not intended services.

Read-only: nothing here restarts anything. It prints the exact ``systemctl --user restart <unit>`` line for each
lagging unit and leaves the act to whoever may do it. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

try:
    from lib import current_bound_units as cbu
except ImportError:  # imported as scripts.lib.release_status
    from scripts.lib import current_bound_units as cbu  # type: ignore[no-redef]

ET = cbu.ET
SCHEMA = "ReleaseStatus@v1"
DEPLOYED, LIVE, VERIFIED, UNDETERMINED = "DEPLOYED", "LIVE", "VERIFIED", "UNDETERMINED"
PASS, FAIL, SKIPPED = "PASS", "FAIL", "SKIPPED"
HEALTH_URL = os.environ.get("HEALTH_URL", "http://localhost:7777/api/v2/health")

# AGENTS.md section 28.8: no request to the portfolio server 04:00-16:15 ET on a market day.
LOOPBACK_BLOCK_START = (4, 0)
LOOPBACK_BLOCK_END = (16, 15)

NOTES: dict[str, str] = {
    "tradeai-telegram-callback-poller.service": (
        "MARKET-HOURS CAUTION: this poller handles /ptapprove, /stop, guard /approve and the Schwab OAuth exchange. "
        "Do not restart it while any US equity session is open (04:00-20:00 ET on a trading day); restart after 20:00 ET."
    ),
    "tradeai-ops-applier.service": (
        "Page-only by design: it writes guard grants, engages the kill switch and clears STOP and has no SIGTERM "
        "handler. Restart only as a deliberate operator act, with the Ops Controls queue empty."
    ),
    "tradeai-active-trader-motion.service": (
        "Execution-adjacent (AGENTS.md 24.10): agents never restart it without an operator execution-ops grant "
        "naming the unit, and only while markets are closed."
    ),
}


@dataclass
class UnitStatus:
    name: str
    pid: int
    cwd: str
    release: str  # basename of the release dir the process runs from ("" when unreadable)
    on_target: Optional[bool]  # None = could not be read (unknown, never assumed fine)
    action: str  # restart | page_only: what the activation's own rule does with it
    reason: str
    restart_command: str = ""
    note: str = ""
    # LQ-20261107-2082 (E21): "" = genuinely stale (pages); otherwise the standing policy refusal that keeps it on
    # the old release on purpose (page_only_named | hard_never | market_hours).
    deferred: str = ""


@dataclass
class Probe:
    name: str
    status: str  # PASS | FAIL | SKIPPED
    detail: str = ""


@dataclass
class ReleaseStatus:
    schema: str = SCHEMA
    status: str = UNDETERMINED
    target: str = ""
    target_name: str = ""
    checked_at: str = ""
    units: list[UnitStatus] = field(default_factory=list)
    lagging: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    probes: list[Probe] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_intended(name: str) -> bool:
    return name.startswith("tradeai-") or name == "portfolio-server.service"


def loopback_allowed(now: Optional[datetime] = None, *, trading_day: Optional[Callable[[datetime], bool]] = None) -> bool:
    """False 04:00-16:15 ET on a weekday (AGENTS.md 28.8). Unknown calendar: weekdays count as market days."""
    now = (now or datetime.now(ET)).astimezone(ET)
    day = trading_day(now) if trading_day else now.weekday() < 5
    if not day:
        return True
    hm = (now.hour, now.minute)
    return not (LOOPBACK_BLOCK_START <= hm < LOOPBACK_BLOCK_END)


def resolve_target(releases_base: Path) -> str:
    link = Path(releases_base) / "CURRENT"
    try:
        real = os.path.realpath(link)
    except OSError:
        return ""
    return real if os.path.isdir(real) and os.path.islink(link) else ""


def _release_of(cwd: str, base: str) -> str:
    prefix = base.rstrip("/") + "/"
    if cwd.startswith(prefix):
        return cwd[len(prefix):].split("/", 1)[0]
    return ""


def restart_line(name: str) -> str:
    return f"systemctl --user restart {name}"


def build_units(plan: "cbu.Plan", target: str, base: str, *, is_market_open: bool) -> list[UnitStatus]:
    out: list[UnitStatus] = []
    for u in plan.units:
        if not is_intended(u.name):
            continue
        if not u.cwd:
            on_target: Optional[bool] = None
        else:
            on_target = cbu.in_release(u.cwd, target)
        lag = on_target is not True
        out.append(
            UnitStatus(
                name=u.name,
                pid=u.main_pid,
                cwd=u.cwd,
                release=_release_of(u.cwd, base),
                on_target=on_target,
                action=u.action,
                reason=u.reason,
                restart_command=restart_line(u.name) if lag else "",
                note=NOTES.get(u.name, "") if lag else "",
                deferred=(cbu.deferral_category(u.reason, is_market_open=is_market_open) or "") if lag else "",
            )
        )
    return out


# ----------------------------------------------------------------------------------------------- acceptance probes
Fetch = Callable[[str], Any]


def _fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 - fixed loopback URL
        return json.loads(resp.read().decode("utf-8"))


def probe_build_stamp(target: str) -> Probe:
    p = Path(target) / "BUILD_SHA"
    try:
        sha = p.read_text().strip()
    except OSError:
        return Probe("build_sha_stamped", FAIL, f"{p} unreadable")
    if not sha:
        return Probe("build_sha_stamped", FAIL, "BUILD_SHA is empty")
    lead = Path(target).name.split("-", 1)[0]
    if lead and all(c in "0123456789abcdef" for c in lead) and not sha.startswith(lead):
        return Probe("build_sha_stamped", FAIL, f"BUILD_SHA {sha[:12]} does not match the release name prefix {lead}")
    return Probe("build_sha_stamped", PASS, sha[:12])


def probe_expected_pin(target: str, releases_base: Path) -> Probe:
    p = Path(releases_base) / "EXPECTED_RELEASE"
    try:
        pinned = p.read_text().strip()
    except OSError:
        return Probe("expected_release_pin", FAIL, f"{p} unreadable")
    if os.path.realpath(pinned) == os.path.realpath(target):
        return Probe("expected_release_pin", PASS, Path(target).name)
    return Probe("expected_release_pin", FAIL, f"pin names {Path(pinned).name}, CURRENT is {Path(target).name}")


def probe_health(now: Optional[datetime], fetch: Fetch, url: str = HEALTH_URL) -> Probe:
    if not loopback_allowed(now):
        return Probe("portfolio_health", SKIPPED, "no loopback request 04:00-16:15 ET on a market day (AGENTS.md 28.8)")
    try:
        body = fetch(url)
    except Exception as exc:  # noqa: BLE001 - an unreachable endpoint is the verdict
        return Probe("portfolio_health", FAIL, f"{type(exc).__name__}")
    ok = isinstance(body, dict) and bool(body.get("ok"))
    return Probe("portfolio_health", PASS if ok else FAIL, "ok" if ok else "health body not ok")


def default_probes(target: str, releases_base: Path, now: Optional[datetime], fetch: Fetch) -> list[Probe]:
    return [probe_build_stamp(target), probe_expected_pin(target, releases_base), probe_health(now, fetch)]


# ---------------------------------------------------------------------------------------------------- the verdict
def compute(
    *,
    releases_base: str | Path = cbu.RELEASES_BASE,
    run: cbu.Runner = cbu._run,
    cwd_of: Callable[[int], str] = cbu._cwd,
    now: Optional[datetime] = None,
    is_open: Optional[bool] = None,
    fetch: Fetch = _fetch_json,
    probes: Optional[Callable[[str], Iterable[Probe]]] = None,
    run_probes: bool = True,
) -> ReleaseStatus:
    base = Path(releases_base)
    now_et = (now or datetime.now(ET)).astimezone(ET)
    rs = ReleaseStatus(checked_at=now_et.isoformat(timespec="seconds"))
    target = resolve_target(base)
    if not target:
        rs.reason = f"{base}/CURRENT is not a symlink to a release directory"
        return rs
    rs.target, rs.target_name = target, Path(target).name
    open_now = cbu.market_open(now_et) if is_open is None else is_open
    plan = cbu.plan(target, releases_base=base, run=run, cwd_of=cwd_of, now=now_et, is_open=open_now)
    rs.units = build_units(plan, target, str(base), is_market_open=open_now)
    if not rs.units:
        rs.reason = "no running tradeai-* / portfolio-server unit is bound to a release: nothing to compare"
        return rs
    rs.lagging = [u.name for u in rs.units if u.on_target is False]
    rs.unknown = [u.name for u in rs.units if u.on_target is None]
    if rs.lagging or rs.unknown:
        rs.status = DEPLOYED
        rs.reason = (
            f"{len(rs.lagging)} unit(s) run another release"
            + (f", {len(rs.unknown)} could not be read" if rs.unknown else "")
        )
        return rs
    rs.status = LIVE
    rs.reason = f"all {len(rs.units)} intended units run {rs.target_name}"
    if run_probes:
        found = probes(target) if probes else default_probes(target, base, now_et, fetch)
        rs.probes = list(found)
        if rs.probes and all(p.status == PASS for p in rs.probes):
            rs.status = VERIFIED
            rs.reason += "; all acceptance probes passed"
        else:
            pending = [f"{p.name}={p.status}" for p in rs.probes if p.status != PASS]
            rs.reason += "; acceptance incomplete: " + (", ".join(pending) or "no probes ran")
    return rs


# ---------------------------------------------------------------------------------------------------- the output
def human(rs: ReleaseStatus) -> str:
    lines = [f"RELEASE STATUS: {rs.status}  target={rs.target_name or '?'}  checked {rs.checked_at}", f"  {rs.reason}"]
    for u in rs.units:
        mark = {True: "ok ", False: "LAG", None: "?? "}[u.on_target]
        # LQ-20261107-2082 (E21): the LAG line itself says why the unit is expected to lag, so a reader never has to
        # cross-reference the activation log. The verdict stays DEPLOYED: deferred is not live.
        why = f"  [intentionally deferred: {u.deferred}; {u.reason}]" if u.deferred else ""
        lines.append(f"  [{mark}] {u.name:<46} pid={u.pid:<8} release={u.release or '(unreadable)'}{why}")
    for p in rs.probes:
        lines.append(f"  probe {p.name}: {p.status} {p.detail}".rstrip())
    laggards = [u for u in rs.units if u.on_target is not True]
    if laggards:
        lines.append("")
        lines.append("To bring the release to LIVE, restart each lagging unit (run by whoever holds the authority):")
        for u in laggards:
            lines.append(f"  {u.restart_command}")
            if u.deferred:
                lines.append(f"      intentionally deferred by the activation policy ({u.deferred}: {u.reason}); "
                             "operator action, not the deploy")
            if u.note:
                lines.append(f"      {u.note}")
    return "\n".join(lines)


def alert_text(rs: ReleaseStatus) -> str:
    head = (
        f"[release-status] {rs.target_name}: {rs.status}, not LIVE. {rs.reason}. "
        "Deploy success is not release success (E15). Restart lines:"
    )
    body = []
    for u in rs.units:
        if u.on_target is not True:
            deferred = f" | intentionally deferred: {u.reason}" if u.deferred else ""
            body.append(
                f"{u.restart_command}  # runs {u.release or 'unreadable cwd'}{deferred}"
                + (f" | {u.note}" if u.note else "")
            )
    return head + "\n" + "\n".join(body)
