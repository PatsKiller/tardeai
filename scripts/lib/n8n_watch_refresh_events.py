"""watch_refresh_lifecycle/v1 — coordination events around Watch decision refresh (Wave B).

Events-only: workers stay systemd-run / PG jobs. n8n never replaces the workers and never
sends. Lane ``watch-refresh`` must be on TRADEAI_N8N_GATEWAY_EXTRA_LANES for accept_event
to stick; until then emit stays fail-soft (shadow sidecar + typed refusal).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

LANE = "watch-refresh"
SCHEMA = "watch_refresh_lifecycle/v1"
SIDECAR_REL = "n8n_cc_wave_b/watch_refresh"  # under <state root>/data/runtime
PHASES = frozenset({"started", "terminal"})
TERMINAL_STATES = frozenset({"COMPLETE", "FAILED", "PARTIAL", "CANCELLED"})
class WatchRefreshEventError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def reason(self) -> str:
        return f"typed_refusal:{self.code}"


def utc_day(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def idempotency_key(run_id: int | str, phase: str, *, terminal_state: str = "", now: datetime | None = None) -> str:
    day = utc_day(now)
    raw = f"{run_id}|{phase}|{terminal_state}|{day}"
    return "wr-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def validate(run_id: int | str, phase: str, *, terminal_state: str = "") -> None:
    if phase not in PHASES:
        raise WatchRefreshEventError("bad_phase")
    try:
        rid = int(run_id)
    except (TypeError, ValueError) as exc:
        raise WatchRefreshEventError("bad_run_id") from exc
    if rid <= 0:
        raise WatchRefreshEventError("bad_run_id")
    if phase == "terminal":
        st = str(terminal_state or "").upper()
        if st not in TERMINAL_STATES:
            raise WatchRefreshEventError("bad_terminal_state")


def subject_key(run_id: int | str, phase: str, *, terminal_state: str = "") -> str:
    validate(run_id, phase, terminal_state=terminal_state)
    if phase == "started":
        return f"phase=started;run_id={int(run_id)}"
    return f"phase=terminal;run_id={int(run_id)};state={str(terminal_state).upper()}"


def sidecar_rel(key: str) -> str:
    return f"{SIDECAR_REL}/{key}.json"


def build_event(
    *,
    run_id: int | str,
    phase: str,
    origin_sha: str,
    symbols: list[str] | None = None,
    terminal_state: str = "",
    requested_by: str = "operator",
    reason: str = "",
    now: datetime | None = None,
    deadline_hours: float = 24.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(gateway event, sidecar). Validates first; sidecar carries free text + symbols."""
    validate(run_id, phase, terminal_state=terminal_state)
    now = now or datetime.now(timezone.utc)
    rid = int(run_id)
    key = idempotency_key(rid, phase, terminal_state=terminal_state, now=now)
    syms = [str(s).upper().strip() for s in (symbols or []) if str(s).strip()][:40]
    subj = subject_key(rid, phase, terminal_state=terminal_state)
    event = {
        "event_id": f"evt-{LANE}-{key}",
        "source_project": "trade-ai",
        "lane_id": LANE,
        "schema_version": "event-reference/v0",
        "origin_sha": origin_sha,
        "subject_key": subj,
        "source_timestamp": now.isoformat(),
        "deadline": (now + timedelta(hours=deadline_hours)).isoformat(),
        "artifact_ref": f"data/runtime:{sidecar_rel(key)}",
        "authority_class": "coordination_read",
        "correlation_id": f"corr-{key}",
        "idempotency_key": key,
    }
    sidecar = {
        "schema": SCHEMA,
        "idempotency_key": key,
        "lane_id": LANE,
        "run_id": rid,
        "phase": phase,
        "terminal_state": str(terminal_state or "").upper() or None,
        "symbols": syms,
        "requested_by": str(requested_by or "operator")[:60],
        "reason": str(reason or "")[:400],
        "recorded_at": now.isoformat(),
        "origin_sha": origin_sha,
        "note": "events-only; workers remain systemd-run / PG jobs",
    }
    return event, sidecar
