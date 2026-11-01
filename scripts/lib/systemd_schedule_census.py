"""Read-only systemd timer census for the Jobs projection (2026-11-01).

`config/lane_registry.json` names a systemd lane by its unit (``scheduler.expression``), not by a
cron expression, so the Jobs projection could not measure 121 ACTIVE lanes: every one read
"Schedule is not measured" and could never be counted as due, succeeded or missed.

This module records what the host itself says. It is a writer plus a pure parser:

* :func:`write_census` runs ``systemctl --user show`` (and ``systemctl show`` for the few
  ``scheduler.scope == "system"`` rows), reads ``NextElapseUSecRealtime``, ``TimersCalendar``,
  ``TimersMonotonic`` and ``LastTriggerUSec``, and writes one small artifact under the state root.
* :func:`parse_instant`, :func:`parse_duration` and :func:`next_elapse` are pure and tested.

The caller is the already-installed hourly ``expected-services-audit`` unit, so no new schedule,
cron line or operator grant is introduced. The Jobs projection only READS the artifact; it never
runs systemctl itself. Nothing here touches a broker, a credential, an order or durable business
state: it observes the scheduler and writes one observation file.

``MBI_BEHAVIOR = 0``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = "SystemdScheduleCensus@v1"
REL = "data/runtime/systemd_schedule_census.json"
PROPS = ("Id", "ActiveState", "SubState", "UnitFileState",
         "NextElapseUSecRealtime", "LastTriggerUSec", "TimersCalendar", "TimersMonotonic")
DEFAULT_TZ = "America/New_York"

_ABSOLUTE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(us|ms|s|min|h|d|w|month|y)\b")
_SECONDS = {"us": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0,
            "d": 86400.0, "w": 604800.0, "month": 2592000.0, "y": 31536000.0}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_instant(value: object, tz: str = DEFAULT_TZ) -> datetime | None:
    """An absolute systemd stamp ('Sun 2026-11-01 18:30:00 EST') as an aware UTC datetime.

    systemd prints the zone abbreviation, which ``strptime`` cannot resolve; the lane's declared
    timezone is the right one to attach, because it is the zone the timer was scheduled in.
    """
    if not isinstance(value, str):
        return None
    match = _ABSOLUTE.search(value)
    if not match:
        return None
    try:
        naive = datetime.strptime(match.group(0), "%Y-%m-%d %H:%M:%S")
        return naive.replace(tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)
    except (ValueError, KeyError):
        return None


def parse_duration(value: object) -> timedelta | None:
    """'2min' / '1month 2w 5d 8h 11min 50s' as a timedelta; None when it names no duration."""
    if not isinstance(value, str):
        return None
    parts = _DURATION.findall(value)
    if not parts:
        return None
    seconds = sum(float(number) * _SECONDS[unit] for number, unit in parts)
    return timedelta(seconds=seconds) if seconds > 0 else None


def next_elapse(props: dict, *, now: datetime, tz: str = DEFAULT_TZ) -> datetime | None:
    """The next fire the host reports, from the realtime field or the embedded next_elapse=."""
    realtime = parse_instant(props.get("NextElapseUSecRealtime"), tz)
    if realtime:
        return realtime
    for key in ("TimersCalendar", "TimersMonotonic"):
        text = props.get(key)
        if not isinstance(text, str):
            continue
        for raw in re.findall(r"next_elapse=([^;}]*)", text):
            raw = raw.strip()
            absolute = parse_instant(raw, tz)
            if absolute:
                return absolute
            delta = parse_duration(raw)
            if delta:
                return now + delta
    return None


def _props(block: str) -> dict:
    return dict(line.split("=", 1) for line in block.splitlines() if "=" in line)


def _systemctl(scope: str, names: list[str]) -> str:
    env = dict(os.environ)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    command = ["systemctl"] + (["--user"] if scope != "system" else []) + [
        "show", *names, "--property=" + ",".join(PROPS)]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=60, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def collect(units, *, now: datetime | None = None, runner=_systemctl) -> dict:
    """{unit: observation} for (name, scope, tz) triples. A missing unit is simply absent."""
    now = now or datetime.now(timezone.utc)
    grouped: dict[str, list[tuple[str, str]]] = {}
    for name, scope, tz in units:
        grouped.setdefault(scope or "user", []).append((name, tz or DEFAULT_TZ))
    out: dict[str, dict] = {}
    for scope, rows in grouped.items():
        stdout = runner(scope, [name for name, _ in rows])
        zones = {name: tz for name, tz in rows}
        for block in stdout.split("\n\n"):
            props = _props(block)
            unit = props.get("Id")
            if not unit:
                continue
            tz = zones.get(unit, DEFAULT_TZ)
            near = next_elapse(props, now=now, tz=tz)
            last = parse_instant(props.get("LastTriggerUSec"), tz)
            out[unit] = {"scope": scope, "active_state": props.get("ActiveState"),
                         "sub_state": props.get("SubState"), "unit_file_state": props.get("UnitFileState"),
                         "next_elapse": _iso(near) if near else None,
                         "last_trigger": _iso(last) if last else None}
    return out


def units_from_registry(root: Path) -> list[tuple[str, str, str]]:
    """(unit, scope, timezone) for every systemd lane, in registry order, without duplicates."""
    try:
        registry = json.loads((Path(root) / "config/lane_registry.json").read_text())
    except (OSError, ValueError):
        return []
    seen, out = set(), []
    for lane in registry.get("lanes") or []:
        scheduler = lane.get("scheduler") or {}
        if scheduler.get("kind") != "systemd" or not scheduler.get("expression"):
            continue
        unit = str(scheduler["expression"])
        if unit in seen:
            continue
        seen.add(unit)
        out.append((unit, str(scheduler.get("scope") or "user"),
                    str(scheduler.get("timezone") or DEFAULT_TZ)))
    return out


def _out_path(root: Path, out: Path | None) -> Path:
    if out is not None:
        return Path(out)
    # An explicit test or host override wins, so a test that runs the audit cannot write the
    # live state root.
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env) / REL
    try:
        from persistent_state_root import resolve_durable_dir  # type: ignore
        return resolve_durable_dir("data/runtime", Path(root)) / Path(REL).name
    except Exception:
        return Path.home() / "trade-ai-releases/persistent-state" / REL


def write_census(root: Path, *, out: Path | None = None, now: datetime | None = None,
                 runner=_systemctl) -> Path | None:
    """Observe the host and write one artifact. Never raises; returns None on failure."""
    try:
        now = now or datetime.now(timezone.utc)
        root = Path(root)
        units = units_from_registry(root)
        observed = collect(units, now=now, runner=runner)
        coverage = ("UNMEASURED" if not observed
                    else "COMPLETE" if len(observed) == len(units) else "PARTIAL")
        target = _out_path(root, out)
        document = {"schema": SCHEMA, "observed_at": _iso(now), "coverage": coverage,
                    "units": observed}
        try:
            from scripts.lib.atomic_json_store import atomic_write_json
        except ImportError:
            from atomic_json_store import atomic_write_json  # type: ignore
        atomic_write_json(target, document, indent=1)
        return target
    except Exception as exc:  # noqa: BLE001 -- an observation failure must never break the caller
        print(f"[systemd-schedule-census] write failed: {type(exc).__name__}", file=sys.stderr)
        return None
