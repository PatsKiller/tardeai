"""Stage 5 harness — safe one-shot scheduler RENDERER + live authorization marker.

This module PLANS a later user-level transient timer and PROVES the live executable refuses
to run without an owner-issued authorization marker. It NEVER calls systemd-run/systemctl/at/
cron, never starts a process, never writes a unit. `--execute-schedule` returns
NOT_AUTHORIZED_BY_BUILD_TRANSACTION; live verification without a marker returns
BLOCKED_OWNER_AUTHORIZATION_REQUIRED. No secret bypass env var exists.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from active_trader import market_calendar as _cal

MARKET_TZ = "America/New_York"
_TZ = ZoneInfo(MARKET_TZ)

NOT_AUTHORIZED = "NOT_AUTHORIZED_BY_BUILD_TRANSACTION"
BLOCKED_OWNER = "BLOCKED_OWNER_AUTHORIZATION_REQUIRED"

# Environment NAME allowlist for the future transient unit (names only — never values).
ENV_NAME_ALLOWLIST = ("XDG_RUNTIME_DIR", "HOME", "PATH", "TZ", "LANG")
DEFAULT_TIMEOUT_START_SEC = 4 * 3600      # bounded runtime (06:55 -> ~10:05 + margin)


# ---- schedule planning -----------------------------------------------------

def schedule_plan(now: _dt.datetime, calendar: Optional[_cal.ExchangeCalendar] = None) -> dict:
    """Compute disposition + the next qualifying observation session. Read-only."""
    calendar = calendar or _cal.NyseCalendar()
    now = now.astimezone(_TZ)
    today = now.date()
    preflight = _dt.datetime.combine(today, _cal.PREFLIGHT, _TZ)
    cutoff = _dt.datetime.combine(today, _dt.time(7, 10), _TZ)

    try:
        today_sess = calendar.session_for_date(today)
        today_qualifies = today_sess.qualifies_for_observation()
    except _cal.CalendarError:
        today_qualifies = False

    if today_qualifies and preflight <= now <= cutoff:
        disposition, target = "START_NOW", today_sess
    elif today_qualifies and now < preflight:
        disposition, target = "SCHEDULE_TODAY", today_sess
    else:
        disposition, target = "SCHEDULE_NEXT_TRADING_DAY", calendar.next_observation_session(now)

    return {
        "disposition": disposition,
        "target_trading_date": target.local_date,
        "target_preflight_et": _cal.PREFLIGHT.strftime("%H:%M:%S"),
        "target_capture_start_et": _cal.CAPTURE_START.strftime("%H:%M:%S"),
        "target_capture_end_et": _cal.REQUIRED_RTH_COMPLETION.strftime("%H:%M:%S"),
        "timezone": MARKET_TZ,
        "is_early_close": target.is_early_close,
        "calendar_source": target.source,
        "calendar_version": target.calendar_version,
        "late_start_cutoff_et": "07:10:00",
    }


# ---- transient-unit RENDERER (text only; nothing executed) -----------------

def render_transient_unit(*, now: _dt.datetime, launcher_path: str, worktree: str,
                          state_dir: str, log_dir: str, session_number: int,
                          marker_path: Optional[str] = None,
                          calendar: Optional[_cal.ExchangeCalendar] = None) -> dict:
    plan = schedule_plan(now, calendar)
    target_date = plan["target_trading_date"]
    preflight_ts = f'{target_date}T{plan["target_preflight_et"]}'
    argv = [launcher_path, "--mode", "live", "--session-index", str(session_number)]
    if marker_path:
        argv += ["--authorization-marker", marker_path]     # a path, never a secret value
    unit_properties = {
        "Type": "oneshot",
        "RemainAfterExit": "no",
        "WorkingDirectory": worktree,
        "ExecStart": " ".join(argv),
        "TimeoutStartSec": DEFAULT_TIMEOUT_START_SEC,
        "KillMode": "mixed",
        "KillSignal": "SIGTERM",
        "StandardOutput": f"append:{log_dir}/observation_session_{session_number:02d}.log",
        "StandardError": f"append:{log_dir}/observation_session_{session_number:02d}.log",
        "Environment (names only)": list(ENV_NAME_ALLOWLIST),
    }
    # dry-run shell REPRESENTATION (documentation; NOT executed here)
    dry_run_shell = (
        "systemd-run --user --unit=at-observation-{sn:02d} --timer-property=AccuracySec=1s "
        "--on-calendar='{ts}' --property=Type=oneshot --property=RemainAfterExit=no "
        "--property=WorkingDirectory={wt} --property=TimeoutStartSec={to} "
        "--property=KillMode=mixed -- {argv}"
    ).format(sn=session_number, ts=preflight_ts, wt=worktree,
             to=DEFAULT_TIMEOUT_START_SEC, argv=" ".join(argv))
    return {
        "target_trading_date": target_date,
        "target_preflight_timestamp": preflight_ts,
        "argv": argv,
        "argv_contains_secret": False,
        "environment_name_allowlist": list(ENV_NAME_ALLOWLIST),
        "unit_properties": unit_properties,
        "user_level": True, "transient": True, "one_shot": True,
        "linger_change": False, "boot_persistence": False,
        "cleanup_plan": [
            f"systemctl --user stop at-observation-{session_number:02d}.service (after run)",
            f"systemctl --user reset-failed at-observation-{session_number:02d}.service",
            "no linger enabled; transient units vanish on completion",
        ],
        "dry_run_shell": dry_run_shell,
        "logs_path": log_dir, "state_path": state_dir,
        "note": "RENDER ONLY — nothing was scheduled or executed by this build transaction.",
    }


def execute_schedule(marker: Optional["ObservationAuthorizationMarker"] = None, **_) -> dict:
    """--execute-schedule entry point. This build transaction NEVER schedules."""
    return {
        "status": NOT_AUTHORIZED,
        "reason": ("scheduling requires a later owner-issued observation prompt supplying a typed "
                   "authorization marker; this build transaction does not schedule"),
        "systemd_run_called": False,
        "marker_supplied": marker is not None,
    }


# ---- live authorization marker (controller §18) ----------------------------

@dataclass(frozen=True)
class ObservationAuthorizationMarker:
    run_id: str
    session_number: int
    expected_git_sha: str
    target_market_date: str
    target_window: str
    symbols_policy: str
    created_at: str
    expires_at: str
    owner_authorization_version: str

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ObservationAuthorizationMarker":
        fields = cls.__dataclass_fields__
        missing = [k for k in fields if k not in d]
        if missing:
            raise ValueError(f"authorization marker missing fields: {missing}")
        # markers must never carry secrets
        blob = " ".join(str(v).lower() for v in d.values())
        for bad in ("password", "token", "secret", "sms", "unlock", "pin"):
            if bad in blob:
                raise ValueError(f"authorization marker must contain no secret-like field ({bad})")
        return cls(**{k: d[k] for k in fields})


@dataclass
class LiveAuthorizationCheck:
    authorized: bool
    status: str
    failures: list = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def verify_live_authorization(marker: Optional[ObservationAuthorizationMarker], *,
                              current_git_sha: str, worktree_clean: bool, session_number: int,
                              now: _dt.datetime, calendar: Optional[_cal.ExchangeCalendar] = None,
                              smoke_pass: bool, credential_green: bool,
                              trade_scan_pass: bool) -> LiveAuthorizationCheck:
    """The live executable calls this. Without a marker -> BLOCKED_OWNER_AUTHORIZATION_REQUIRED."""
    if marker is None:
        return LiveAuthorizationCheck(False, BLOCKED_OWNER, ["no owner authorization marker supplied"])
    calendar = calendar or _cal.NyseCalendar()
    fails = []
    if marker.expected_git_sha != current_git_sha:
        fails.append("git SHA does not match marker")
    if not worktree_clean:
        fails.append("worktree not clean and no approved runtime package hash")
    if int(marker.session_number) != int(session_number):
        fails.append("session number mismatch")
    now_et = now.astimezone(_TZ)
    if marker.target_market_date != now_et.date().isoformat():
        fails.append("calendar date does not match marker target")
    try:
        if not calendar.session_for_date(now_et.date()).qualifies_for_observation():
            fails.append("target date is not a qualifying observation session")
    except _cal.CalendarError as e:
        fails.append(f"calendar: {e}")
    try:
        if now_et > _dt.datetime.fromisoformat(marker.expires_at).astimezone(_TZ):
            fails.append("authorization marker expired")
    except Exception:
        fails.append("marker expires_at unparseable")
    if not smoke_pass:
        fails.append("Stage 5 data-smoke PASS evidence missing")
    if not credential_green:
        fails.append("credential readiness marker not GREEN")
    if not trade_scan_pass:
        fails.append("trade API scan did not pass")
    if fails:
        return LiveAuthorizationCheck(False, BLOCKED_OWNER, fails)
    return LiveAuthorizationCheck(True, "AUTHORIZED", [])
