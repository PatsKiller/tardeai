#!/usr/bin/env python3
"""effective_truth.py — declared is not effective.

Three surfaces in the Command Center report a configured intention and let the
operator read it as a running fact:

  * feature flags     a config file says a capability is on. The loader may coerce
                      it off for safety and record an audit note. The surface that
                      shows the file value is showing the wrong number.
  * schedulers        a timer exists, therefore the job runs. A disabled unit, a
                      failed last activation and an overdue timer all look the same
                      from a list of unit names.
  * the Finviz store  "no data" has three distinct causes — never cached, cached and
                      stale, or present but unreadable — and only one of them is a
                      problem with the provider.

Each contract here reports DECLARED and EFFECTIVE side by side and names the
delta. A surface can then say which one it is showing.

AUTHORITY: READ_ONLY_ADVISORY. Reads config, stats files, and queries systemd /
crontab for their own state. It never enables, disables, starts, stops, installs
or edits a unit, a cron entry, a flag or a cache.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "EffectiveTruth@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
CALCULATION_VERSION = "1.0.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ── 1. feature flags: declared vs effective ──────────────────────────────────


def feature_flag_truth(root: Path | str | None = None) -> dict[str, Any]:
    """Config-file value vs the value the loader actually returns.

    ``active_trader_live_session_enabled`` is hard-locked off: a config setting it
    true is coerced to False with an audit note. A surface rendering the file
    value would tell the operator a live session is enabled when it is not — the
    most dangerous direction for this particular flag to be wrong in.
    """
    r = Path(root) if root else ROOT
    import sys

    scripts = str(r / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)

    try:
        from active_trader.feature_flags import (  # type: ignore
            FLAG_NAMES,
            LIVE_LOCKED,
            MANDATE_DEFAULTS,
            load_flags,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "FeatureFlagTruth@v1",
            "status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {exc}",
            "authority": AUTHORITY,
        }

    cfg_path = os.environ.get("ACTIVE_TRADER_FLAGS") or str(r / "config" / "active_trader_flags.json")
    declared: dict[str, Any] = {}
    cfg_present = Path(cfg_path).is_file()
    if cfg_present:
        try:
            declared = (json.loads(Path(cfg_path).read_text()) or {}).get("flags") or {}
        except Exception:  # noqa: BLE001
            declared = {}

    try:
        flags = load_flags()
        effective = {name: bool(getattr(flags, name, MANDATE_DEFAULTS.get(name, False))) for name in FLAG_NAMES}
        notes = list(getattr(flags, "notes", []) or [])
        source = getattr(flags, "source", None)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "FeatureFlagTruth@v1",
            "status": "UNAVAILABLE",
            "reason": f"load_flags failed: {type(exc).__name__}: {exc}",
            "authority": AUTHORITY,
        }

    rows = []
    for name in FLAG_NAMES:
        d = declared.get(name, MANDATE_DEFAULTS.get(name))
        e = effective[name]
        locked = name in LIVE_LOCKED
        rows.append(
            {
                "flag": name,
                "declared": d,
                "declared_source": "config" if name in declared else "mandate_default",
                "effective": e,
                "agrees": bool(d) == bool(e),
                "hard_locked_off": locked,
                "delta_reason": (
                    "hard-locked off in this build; a config value of true is coerced to false"
                    if locked and bool(d) and not e
                    else ("" if bool(d) == bool(e) else "the loader overrode the declared value")
                ),
            }
        )

    deltas = [x for x in rows if not x["agrees"]]
    return {
        "schema": "FeatureFlagTruth@v1",
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _iso(_now()),
        "config_path": cfg_path,
        "config_present": cfg_present,
        "loader_source": str(source) if source else None,
        "flag_count": len(rows),
        "delta_count": len(deltas),
        "coercion_notes": notes,
        "flags": rows,
        "rule": "A surface must render the EFFECTIVE value and name any delta; the file value alone is a claim.",
    }


# ── 2. schedulers: declared, disabled, missed ────────────────────────────────


def _systemctl(*args: str) -> str:
    try:
        return subprocess.run(
            ["systemctl", "--user", "--no-pager", *args],
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout
    except Exception:  # noqa: BLE001
        return ""


def _show(units: list[str], props: list[str]) -> dict[str, dict[str, str]]:
    """``systemctl show`` for many units at once, keyed by unit name.

    The ``list-timers`` table is column-aligned prose whose fields contain spaces;
    parsing it is fragile and silently yields zero rows when the format shifts.
    ``show`` is the machine interface, so it is the one used.
    """
    if not units:
        return {}
    out: dict[str, dict[str, str]] = {}
    chunk = 40
    for i in range(0, len(units), chunk):
        batch = units[i : i + chunk]
        raw = _systemctl("show", "--property=Id," + ",".join(props), *batch)
        cur: dict[str, str] = {}
        for line in raw.splitlines():
            if not line.strip():
                if cur.get("Id"):
                    out[cur["Id"]] = cur
                cur = {}
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                cur[k] = v
        if cur.get("Id"):
            out[cur["Id"]] = cur
    return out


def scheduler_truth() -> dict[str, Any]:
    """Every user timer with its enablement, last result and overdue state.

    "A unit exists" is not "the job ran". A disabled timer, a timer whose service
    last exited non-zero, and a timer with no next elapse are three different
    failures that a list of unit names renders identically.
    """
    units_raw = _systemctl("list-unit-files", "--type=timer", "--plain")
    declared: dict[str, str] = {}
    for line in units_raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(".timer"):
            declared[parts[0]] = parts[1]

    timer_names = sorted(declared)
    timer_props = _show(
        timer_names,
        [
            "ActiveState",
            "UnitFileState",
            # A monotonic timer (OnUnitActiveSec) publishes only the monotonic field;
            # reading the realtime one alone reports a live timer as having no next
            # elapse. Both are read and either counts.
            "NextElapseUSecRealtime",
            "NextElapseUSecMonotonic",
            "LastTriggerUSec",
            "Unit",
        ],
    )
    services = sorted({v.get("Unit", "") for v in timer_props.values() if v.get("Unit")})
    svc_props = _show(services, ["ActiveState", "Result", "ExecMainStatus", "ExecMainExitTimestamp"])

    rows = []
    for name in timer_names:
        t = timer_props.get(name, {})
        svc = t.get("Unit") or name.replace(".timer", ".service")
        sp = svc_props.get(svc, {})
        nxt_real = t.get("NextElapseUSecRealtime", "")
        nxt_mono = t.get("NextElapseUSecMonotonic", "")
        nxt = nxt_real or nxt_mono
        last = t.get("LastTriggerUSec", "")
        result = sp.get("Result")
        rows.append(
            {
                "timer": name,
                "activates": svc,
                "declared_state": declared.get(name, "unknown"),
                "unit_file_state": t.get("UnitFileState"),
                "enabled": declared.get(name) in ("enabled", "enabled-runtime", "static"),
                "timer_active_state": t.get("ActiveState"),
                "next_elapse_realtime": nxt_real or None,
                "next_elapse_monotonic": nxt_mono or None,
                "last_trigger": last or None,
                "next_is_absent": nxt_real in ("", "n/a", "0") and nxt_mono in ("", "n/a", "0"),
                "never_triggered": last in ("", "n/a", "0"),
                "service_active_state": sp.get("ActiveState"),
                "service_result": result,
                "last_exit_status": sp.get("ExecMainStatus"),
                "last_run_failed": bool(result) and result != "success",
            }
        )

    disabled = [u for u, st in declared.items() if st == "disabled"]
    failed = [r["timer"] for r in rows if r["last_run_failed"]]
    no_next = [r["timer"] for r in rows if r["next_is_absent"] and r["enabled"]]
    never = [r["timer"] for r in rows if r["never_triggered"] and r["enabled"]]

    cron_lines: list[str] = []
    try:
        cron_lines = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=60).stdout.splitlines()
    except Exception:  # noqa: BLE001
        cron_lines = []
    cron_active = [ln for ln in cron_lines if ln.strip() and not ln.lstrip().startswith("#")]
    cron_commented_jobs = [
        ln
        for ln in cron_lines
        if ln.lstrip().startswith("#") and re.search(r"#\s*[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s", ln)
    ]

    return {
        "schema": "SchedulerTruth@v1",
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _iso(_now()),
        "timer_unit_files": len(declared),
        "timers_inspected": len(rows),
        "disabled_timers": disabled,
        "enabled_timers_with_no_next_elapse": no_next,
        "enabled_timers_never_triggered": never,
        "timers_with_failed_last_run": failed,
        "cron_active_entries": len(cron_active),
        "cron_commented_out_jobs": len(cron_commented_jobs),
        "timers": rows,
        "rule": (
            "A scheduler surface must distinguish enabled-and-running from disabled, "
            "from failed-last-run, from enabled-but-never-triggered. Presence of a unit "
            "proves none of them."
        ),
    }


# ── 3. Finviz store: cached / uncached / broken ──────────────────────────────

CACHED_FRESH = "CACHED_FRESH"
CACHED_STALE = "CACHED_STALE"
UNCACHED = "UNCACHED"
BROKEN_STORE = "BROKEN_STORE"
UNREADABLE = "UNREADABLE"

DEFAULT_FINVIZ_STORE = "data/portfolios/state/finviz_quote_cache.json"


def served_state_root() -> Path:
    """The root the running service reads.

    Defaulting to the checkout would report UNCACHED for a store the deployed
    service serves — the producer/served fork again, this time dressed as a
    provider outage.
    """
    for key in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        v = os.environ.get(key)
        if v:
            return Path(v)
    return Path.home() / "trade-ai-releases" / "persistent-state"


#: The repo writes market stamps as ``2026-09-03 15:30:02 ET`` as well as ISO-8601.
#: A parser that only accepts ISO reports a healthy, four-minute-old store as
#: BROKEN — a manufactured defect, which is the opposite of the point.
_ET = timezone(timedelta(hours=-4))
_ZONE_SUFFIX = {
    "ET": _ET,
    "EDT": _ET,
    "EST": timezone(timedelta(hours=-5)),
    "UTC": timezone.utc,
    "Z": timezone.utc,
}


def _parse_stamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 or ``<naive> <ZONE>`` timestamp. None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    tail = text.rsplit(" ", 1)[-1].upper() if " " in text else ""
    tz = _ZONE_SUFFIX.get(tail)
    if tz is not None:
        text = text.rsplit(" ", 1)[0].strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz or timezone.utc)
    return dt


def finviz_store_health(
    store: Path | str | None = None,
    *,
    stale_after_hours: float = 6.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Why the Finviz surface has no number, stated exactly.

    "No data" has three unrelated causes and one of them is not a provider problem:

      UNCACHED       the store has never been written; nothing failed yet
      CACHED_FRESH   present and within the freshness window
      CACHED_STALE   present, parseable, and older than the window
      BROKEN_STORE   present but not parseable, or parseable with no ``_meta``
      UNREADABLE     present but the process cannot read it

    Collapsing these to an empty render is how a permissions problem was read as a
    provider outage.
    """
    p = Path(store) if store else (served_state_root() / DEFAULT_FINVIZ_STORE)
    n = now or _now()

    if not p.exists():
        return {
            "schema": "FinvizStoreHealth@v1",
            "authority": AUTHORITY,
            "as_of": _iso(n),
            "store": str(p),
            "state": UNCACHED,
            "reason": "the store has never been written; this is not a provider failure",
            "symbol_count": 0,
            "last_updated": None,
            "age_hours": None,
        }

    try:
        raw = p.read_text()
    except OSError as exc:
        return {
            "schema": "FinvizStoreHealth@v1",
            "authority": AUTHORITY,
            "as_of": _iso(n),
            "store": str(p),
            "state": UNREADABLE,
            "reason": f"the store exists but cannot be read: {type(exc).__name__}",
            "symbol_count": None,
            "last_updated": None,
            "age_hours": None,
        }

    try:
        doc = json.loads(raw)
    except ValueError as exc:
        return {
            "schema": "FinvizStoreHealth@v1",
            "authority": AUTHORITY,
            "as_of": _iso(n),
            "store": str(p),
            "state": BROKEN_STORE,
            "reason": f"the store exists but does not parse: {exc}",
            "bytes": len(raw),
            "symbol_count": None,
            "last_updated": None,
            "age_hours": None,
        }

    if not isinstance(doc, dict):
        return {
            "schema": "FinvizStoreHealth@v1",
            "authority": AUTHORITY,
            "as_of": _iso(n),
            "store": str(p),
            "state": BROKEN_STORE,
            "reason": f"the store parsed to {type(doc).__name__}, not an object",
            "symbol_count": None,
            "last_updated": None,
            "age_hours": None,
        }

    meta = doc.get("_meta") or {}
    symbols = [k for k in doc if not k.startswith("_")]
    last = meta.get("last_updated") or meta.get("updated_at")
    if not last:
        return {
            "schema": "FinvizStoreHealth@v1",
            "authority": AUTHORITY,
            "as_of": _iso(n),
            "store": str(p),
            "state": BROKEN_STORE,
            "reason": "the store parsed but carries no _meta.last_updated, so its age is unknowable",
            "symbol_count": len(symbols),
            "last_updated": None,
            "age_hours": None,
        }

    dt = _parse_stamp(last)
    if dt is not None:
        age = (n - dt.astimezone(timezone.utc)).total_seconds() / 3600.0
    else:
        return {
            "schema": "FinvizStoreHealth@v1",
            "authority": AUTHORITY,
            "as_of": _iso(n),
            "store": str(p),
            "state": BROKEN_STORE,
            "reason": f"_meta.last_updated is not a parseable timestamp: {last!r}",
            "symbol_count": len(symbols),
            "last_updated": str(last),
            "age_hours": None,
        }

    stale = age >= stale_after_hours
    return {
        "schema": "FinvizStoreHealth@v1",
        "authority": AUTHORITY,
        "as_of": _iso(n),
        "store": str(p),
        "state": CACHED_STALE if stale else CACHED_FRESH,
        "reason": (
            f"cached {age:.1f}h ago, older than the {stale_after_hours:.0f}h window"
            if stale
            else f"cached {age:.1f}h ago, within the {stale_after_hours:.0f}h window"
        ),
        "symbol_count": len(symbols),
        "last_updated": str(last),
        "age_hours": round(age, 2),
        "stale_after_hours": stale_after_hours,
    }
