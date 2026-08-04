"""Canonical P0 containment for process_watchlist_agent_jobs (issue #283 / PR #284).

Single source of truth. FAIL-CLOSED for any uncertainty.

Activate by either:
  - env AGENT_JOBS_P0_CONTAINED=1|true|yes|on
  - flag file (default: ~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED)

Deactivate only by explicit env false/0/off AND absence of flag (or flag removed).

All callers of the worker command MUST use guard_agent_jobs_execution().
Import / state-read / evaluation failures BLOCK worker execution.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("tradeai.agent_jobs_containment")

# Canonical flag — one path, one env name
ENV_NAME = "AGENT_JOBS_P0_CONTAINED"
DEFAULT_FLAG = Path.home() / ".local" / "state" / "tradeai" / "AGENT_JOBS_P0_CONTAINED"
FLAG_PATH = Path(os.environ.get("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(DEFAULT_FLAG)))

WORKER_SCRIPT_MARKERS = (
    "process_watchlist_agent_jobs.py",
    "process_watchlist_agent_jobs",
)

STATUS_ACTIVE = "ACTIVE"
STATUS_INACTIVE = "INACTIVE"
STATUS_INVALID = "INVALID"

CONTAINED_CODE = "CONTAINED"
CHECK_FAILED_CODE = "CONTAINMENT_CHECK_FAILED"

CONTAINED_MESSAGE = (
    "CONTAINED: process_watchlist_agent_jobs is under P0 containment "
    "(issue #283). Remediation will not invoke the worker. "
    "Clear flag only after governed deploy + explicit re-enable approval."
)
CHECK_FAILED_MESSAGE = (
    "CONTAINMENT_CHECK_FAILED: cannot prove process_watchlist_agent_jobs "
    "containment is inactive; worker invocation blocked (fail-closed)."
)

# Exit code for worker entry when blocked
WORKER_BLOCKED_EXIT = 78

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off", ""})


class ContainmentStateError(RuntimeError):
    """Containment state unavailable or invalid — fail closed."""


def command_invokes_worker(cmd: str | None) -> bool:
    c = (cmd or "").lower()
    return any(m in c for m in WORKER_SCRIPT_MARKERS)


def evaluate_containment_state() -> dict[str, Any]:
    """Return containment state; raises ContainmentStateError if unreadable/invalid.

    status:
      ACTIVE   — containment on (block worker)
      INACTIVE — proven off (allow worker)
      (INVALID never returned; raises instead)
    """
    raw = (os.environ.get(ENV_NAME) if ENV_NAME in os.environ else None)
    if raw is not None:
        val = str(raw).strip().lower()
        if val in _TRUE:
            return {"status": STATUS_ACTIVE, "source": "env", "detail": f"{ENV_NAME}=on"}
        if val in _FALSE:
            # env explicitly inactive — still require flag absence
            pass
        elif val:
            # unknown env value is invalid
            raise ContainmentStateError(f"malformed env {ENV_NAME}={raw!r}")

    try:
        exists = FLAG_PATH.exists()
    except Exception as e:
        raise ContainmentStateError(f"flag exists() failed: {type(e).__name__}") from e

    if not exists:
        return {"status": STATUS_INACTIVE, "source": "no_flag", "detail": str(FLAG_PATH)}

    # Flag present — must be readable with non-empty content
    try:
        text = FLAG_PATH.read_text(encoding="utf-8")
    except Exception as e:
        raise ContainmentStateError(f"flag read failed: {type(e).__name__}") from e

    if text is None or not str(text).strip():
        raise ContainmentStateError("malformed flag: empty content")

    # Any non-empty flag content means ACTIVE (including "active reason=...")
    return {
        "status": STATUS_ACTIVE,
        "source": "flag",
        "detail": f"flag present ({len(text.strip())} chars)",
    }


def is_contained() -> bool:
    """True when containment is ACTIVE.

    Raises ContainmentStateError if state cannot be determined (fail-closed callers
    must treat raise as block). Does NOT return False on I/O errors.
    """
    st = evaluate_containment_state()
    return st["status"] == STATUS_ACTIVE


def activate(reason: str = "p0") -> Path:
    """Create the flag file (host-side containment). Idempotent."""
    FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLAG_PATH.write_text(f"active reason={reason}\n", encoding="utf-8")
    return FLAG_PATH


def report_contained(*, source: str = "unknown") -> dict[str, Any]:
    return {
        "status": CONTAINED_CODE,
        "remediation_status": CONTAINED_CODE,
        "contained": True,
        "blocked": True,
        "allowed": False,
        "fixable": False,
        "retry_cmd": None,
        "cmd": None,
        "source": source,
        "message": CONTAINED_MESSAGE,
        "flag_path": str(FLAG_PATH),
        "env": ENV_NAME,
        "worker_invoked": False,
    }


def report_check_failed(*, source: str = "unknown", error: str = "") -> dict[str, Any]:
    msg = CHECK_FAILED_MESSAGE
    if error:
        # sanitized: type/short message only, no secrets
        msg = f"{CHECK_FAILED_MESSAGE} detail={error[:120]}"
    return {
        "status": CHECK_FAILED_CODE,
        "remediation_status": CHECK_FAILED_CODE,
        "contained": True,  # treat as blocked
        "blocked": True,
        "allowed": False,
        "fixable": False,
        "retry_cmd": None,
        "cmd": None,
        "source": source,
        "message": msg,
        "error": (error or "")[:200],
        "flag_path": str(FLAG_PATH),
        "env": ENV_NAME,
        "worker_invoked": False,
    }


def guard_agent_jobs_execution(
    command: str | None,
    *,
    source: str = "unknown",
) -> dict[str, Any]:
    """Shared fail-closed guard for any process_watchlist_agent_jobs invocation.

    Contract:
      - unrelated command → allowed (blocked=false)
      - containment ACTIVE → blocked / CONTAINED
      - containment INACTIVE and state valid → allowed
      - state unavailable/invalid → blocked / CONTAINMENT_CHECK_FAILED
      - any unexpected exception → blocked / CONTAINMENT_CHECK_FAILED

    Never raises for control flow of remediation callers.
    """
    try:
        if not command_invokes_worker(command):
            return {
                "blocked": False,
                "allowed": True,
                "cmd": command,
                "retry_cmd": command,
                "fixable": True,
                "remediation_status": None,
                "status": "ALLOWED_UNRELATED",
                "source": source,
                "worker_invoked": False,
            }

        try:
            st = evaluate_containment_state()
        except ContainmentStateError as e:
            log.warning(
                "agent_jobs containment check failed source=%s err=%s",
                source, type(e).__name__,
            )
            r = report_check_failed(source=source, error=f"{type(e).__name__}: {e}")
            r["original_cmd"] = command
            return r
        except Exception as e:
            log.warning(
                "agent_jobs containment unexpected error source=%s err=%s",
                source, type(e).__name__,
            )
            r = report_check_failed(source=source, error=f"{type(e).__name__}")
            r["original_cmd"] = command
            return r

        if st["status"] == STATUS_ACTIVE:
            r = report_contained(source=source)
            r["original_cmd"] = command
            r["state"] = st
            return r

        # INACTIVE — proven off
        return {
            "blocked": False,
            "allowed": True,
            "cmd": command,
            "retry_cmd": command,
            "fixable": True,
            "remediation_status": None,
            "status": "ALLOWED",
            "source": source,
            "state": st,
            "worker_invoked": False,
        }
    except Exception as e:
        # Absolute last resort — still fail closed for worker-related uncertainty
        log.warning(
            "agent_jobs guard outer failure source=%s err=%s",
            source, type(e).__name__,
        )
        if command_invokes_worker(command):
            r = report_check_failed(source=source, error=f"outer:{type(e).__name__}")
            r["original_cmd"] = command
            return r
        # unrelated command — allow
        return {
            "blocked": False,
            "allowed": True,
            "cmd": command,
            "source": source,
            "status": "ALLOWED_UNRELATED_AFTER_ERROR",
        }


# Backward-compatible aliases
def guard_remediation_command(cmd: str | None, *, source: str = "health_agent") -> dict[str, Any]:
    return guard_agent_jobs_execution(cmd, source=source)


def exit_if_contained_worker_entry() -> int | None:
    """Worker entry: block if contained or if containment cannot be proven inactive.

    Returns exit code to terminate with, or None to continue.
    On any error → block (exit 78). Never proceeds on uncertainty.
    """
    try:
        g = guard_agent_jobs_execution(
            "scripts/process_watchlist_agent_jobs.py",
            source="worker_entry",
        )
    except Exception as e:
        print(CHECK_FAILED_MESSAGE + f" ({type(e).__name__})")
        return WORKER_BLOCKED_EXIT

    if g.get("blocked"):
        print(g.get("message") or CHECK_FAILED_MESSAGE)
        return WORKER_BLOCKED_EXIT
    return None
