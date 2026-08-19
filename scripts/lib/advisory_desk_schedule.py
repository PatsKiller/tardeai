"""Advisory Desk schedule + operator run-now (READ_ONLY_ADVISORY).

Scheduled path: systemd timer tradeai-advisory-shadow-session.timer
  OnCalendar=Mon..Fri *-*-* 09:15:00  (host local / America/New_York)

Run-now rebuilds the deterministic desk then Flash opinions + Pro synthesis.
Does not mutate broker / orders / stops / risk / 2FA.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
WEEKDAY_HOUR = 9
WEEKDAY_MINUTE = 15
TIMER_UNIT = "tradeai-advisory-shadow-session.timer"
STATUS_FILE = Path(
    os.environ.get(
        "TRADEAI_ADVISORY_RUN_STATUS",
        str(Path(__file__).resolve().parents[2] / "data" / "runtime" / "advisory_run_now.json"),
    )
)
LOCK_FILE = Path(
    os.environ.get(
        "TRADEAI_ADVISORY_RUN_LOCK",
        str(STATUS_FILE.with_suffix(".lock")),
    )
)
_STATE_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_SYSTEMD_CACHE: dict[str, Any] = {"at": 0.0, "iso": None}


def _now_et() -> datetime:
    return datetime.now(ET)


def next_weekday_0915_et(now: datetime | None = None) -> datetime:
    """Next Mon–Fri 09:15 America/New_York (09:15 today is next only if still future)."""
    cur = (now or _now_et()).astimezone(ET)
    candidate = cur.replace(hour=WEEKDAY_HOUR, minute=WEEKDAY_MINUTE, second=0, microsecond=0)
    if cur >= candidate:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:  # Sat=5 Sun=6
        candidate += timedelta(days=1)
    return candidate


def _systemd_next_iso() -> str | None:
    now = time.monotonic()
    if now - float(_SYSTEMD_CACHE.get("at") or 0) < 60:
        iso = _SYSTEMD_CACHE.get("iso")
        return str(iso) if iso else None
    try:
        out = subprocess.check_output(
            [
                "systemctl",
                "--user",
                "show",
                TIMER_UNIT,
                "-p",
                "NextElapseUSecRealtime",
                "--value",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        ).strip()
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        _SYSTEMD_CACHE["at"] = now
        _SYSTEMD_CACHE["iso"] = None
        return None
    iso = None
    if out and out not in ("0", "n/a", "N/A"):
        try:
            usec = int(out)
            if usec > 0:
                iso = datetime.fromtimestamp(usec / 1_000_000, tz=timezone.utc).isoformat()
        except ValueError:
            iso = None
    _SYSTEMD_CACHE["at"] = now
    _SYSTEMD_CACHE["iso"] = iso
    return iso


def schedule_payload(now: datetime | None = None) -> dict[str, Any]:
    computed = next_weekday_0915_et(now)
    systemd_iso = _systemd_next_iso()
    next_iso = systemd_iso or computed.isoformat()
    try:
        next_dt = datetime.fromisoformat(next_iso.replace("Z", "+00:00")).astimezone(ET)
    except ValueError:
        next_dt = computed
    return {
        "cadence": "weekdays 09:15 America/New_York",
        "timer_unit": TIMER_UNIT,
        "source": "systemd" if systemd_iso else "calendar",
        "next_run_at": next_dt.isoformat(),
        "next_run_et": next_dt.strftime("%a %Y-%m-%d %H:%M %Z"),
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }


def _read_status() -> dict[str, Any]:
    try:
        if STATUS_FILE.exists():
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"state": "idle"}


def _write_status(payload: dict[str, Any]) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(STATUS_FILE)


def run_status() -> dict[str, Any]:
    st = _read_status()
    st.setdefault("state", "idle")
    st["schedule"] = schedule_payload()
    st["authority"] = "READ_ONLY_ADVISORY"
    st["financial_action"] = False
    st["broker_write_authority"] = "NONE"
    return st


def _try_lock() -> TextIO | None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK_FILE, "a+", encoding="utf-8")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        return None
    return fd


def _unlock(fd: TextIO | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        fd.close()
    except OSError:
        pass


def _execute_run(*, live_llm: bool, lock_fd: TextIO) -> None:
    from lib.data_broker.advisory_desk import (
        build_advisory_desk,
        enrich_advisory_with_opinions,
    )

    started = datetime.now(timezone.utc).isoformat()
    try:
        if live_llm:
            os.environ["ADVISORY_DESK_V1"] = "true"
        desk = build_advisory_desk(force=True, max_age_s=0)
        enrich_advisory_with_opinions(
            desk,
            dry_run=not live_llm,
            include_synthesis=True,
            force=True,
        )
        with _STATE_LOCK:
            _write_status(
                {
                    "state": "ok",
                    "started_at": started,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "live_llm": live_llm,
                    "authority": "READ_ONLY_ADVISORY",
                    "financial_action": False,
                    "broker_write_authority": "NONE",
                }
            )
    except Exception as exc:
        with _STATE_LOCK:
            _write_status(
                {
                    "state": "error",
                    "started_at": started,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "error": f"{type(exc).__name__}: {exc}"[:400],
                    "live_llm": live_llm,
                    "authority": "READ_ONLY_ADVISORY",
                    "financial_action": False,
                    "broker_write_authority": "NONE",
                }
            )
    finally:
        _unlock(lock_fd)


def start_run_now(*, live_llm: bool = True) -> dict[str, Any]:
    """Kick a background desk rebuild. Returns immediately."""
    global _THREAD
    lock_fd = _try_lock()
    if lock_fd is None:
        out = run_status()
        out["ok"] = False
        out["accepted"] = False
        out["reason"] = "already_running"
        out["state"] = "running"
        return out

    started = datetime.now(timezone.utc).isoformat()
    with _STATE_LOCK:
        _write_status(
            {
                "state": "running",
                "started_at": started,
                "live_llm": live_llm,
                "authority": "READ_ONLY_ADVISORY",
                "financial_action": False,
                "broker_write_authority": "NONE",
            }
        )
        t = threading.Thread(
            target=_execute_run,
            kwargs={"live_llm": live_llm, "lock_fd": lock_fd},
            name="advisory-desk-run-now",
            daemon=True,
        )
        _THREAD = t
        t.start()
    return {
        "ok": True,
        "accepted": True,
        "state": "running",
        "started_at": started,
        "live_llm": live_llm,
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "broker_write_authority": "NONE",
        "schedule": schedule_payload(),
        "message": (
            "Rebuilding desk facts, Flash opinions, and Pro synthesis. "
            "Paid path. Advisory only."
        ),
    }
