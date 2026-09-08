#!/usr/bin/env python3
"""run_persistent_wake.py — cron-callable CLI for PersistentAgentWake@v2.

Thin runner around ``run_scheduled_wake``. Does NOT install or activate any
crontab, systemd unit, or timer (AGENTS.md §17). Activation stays operator-only.

Fail-closed: BOTH env flags must be on, otherwise exit 0 with no side effects:
  PERSISTENT_WAKE_ENABLED
  PERSISTENT_WAKE_SCHEDULE_ENABLED

Idempotent per schedule slot. Missed slots are skipped (catch_up_policy=skip_missed).
Exit 0 for ok / disabled / nothing-due; exit 1 for hard errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from scripts.lib.persistent_agent_wake import (  # noqa: E402
    FEATURE_FLAG as WAKE_FLAG,
    feature_enabled as wake_feature_enabled,
    run_scheduled_wake,
)
from scripts.lib.persistent_wake_schedule import (  # noqa: E402
    FEATURE_FLAG as SCHEDULE_FLAG,
    ScheduleContract,
)
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402

WAKE_REASON = "scheduled_persistent_review"
DEFAULT_STATE_ENV = "TRADEAI_PERSISTENT_WAKE_STATE_ROOT"
DEFAULT_MEMORY_ENV = "TRADEAI_PERSISTENT_WAKE_MEMORY_PATH"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def schedule_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return _truthy(e.get(SCHEDULE_FLAG))


def both_flags_on(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return wake_feature_enabled(e) and schedule_enabled(e)


def _emit(line: dict[str, Any]) -> None:
    """One structured, cron/journald-readable line."""
    print(json.dumps(line, sort_keys=True, default=str), flush=True)


def _default_state_root(env: dict) -> Path:
    raw = env.get(DEFAULT_STATE_ENV) or ""
    if raw:
        return Path(raw)
    # Disposable-by-default under repo-local state; never the production DB.
    return _PROJECT / "data" / "persistent_wake" / "state"


def _completed_slots(store: JsonlStore, *, agent_id: str, wake_reason: str, subject_guid: str) -> set[str]:
    out: set[str] = set()
    for row in store.iter("wakes"):
        if row.get("agent_id") != agent_id:
            continue
        if row.get("wake_reason") != wake_reason:
            continue
        if str(row.get("subject_guid")) != str(subject_guid):
            continue
        if row.get("lifecycle_state") in {"SETTLED", "ABANDONED", "STALE", "MEMORY_UNAVAILABLE", "MEMORY_MALFORMED"}:
            slot = row.get("schedule_slot_utc")
            if slot:
                out.add(str(slot))
    return out


def run_once(
    *,
    agent_id: str,
    subject_guid: str | None,
    dry_run: bool = False,
    env: dict | None = None,
    when: datetime | None = None,
    state_root: Path | str | None = None,
    memory_backend: Any = None,
) -> int:
    """Execute at most one wake for the current schedule slot. Return process exit code."""
    env = dict(env if env is not None else os.environ)
    when = when or _now()
    contract = ScheduleContract(agent_id=agent_id, wake_reason=WAKE_REASON)
    slot = contract.slot_for(when)

    base = {
        "script": "run_persistent_wake",
        "agent_id": agent_id,
        "subject_guid": subject_guid,
        "slot": slot,
        "wake_flag": WAKE_FLAG,
        "schedule_flag": SCHEDULE_FLAG,
    }

    if not both_flags_on(env):
        _emit({
            **base,
            "outcome": "disabled",
            "wake_id": "none",
            "detail": (
                f"{WAKE_FLAG}={'on' if wake_feature_enabled(env) else 'off'} "
                f"{SCHEDULE_FLAG}={'on' if schedule_enabled(env) else 'off'}; "
                "both must be on"
            ),
        })
        return 0

    if not subject_guid:
        _emit({**base, "outcome": "nothing_due", "wake_id": "none", "detail": "no --subject-guid"})
        return 0

    root = Path(state_root) if state_root is not None else _default_state_root(env)
    if memory_backend is None:
        mem_path = env.get(DEFAULT_MEMORY_ENV) or ""
        memory_backend = Path(mem_path) if mem_path else None

    store = JsonlStore(root)
    completed = _completed_slots(
        store, agent_id=agent_id, wake_reason=WAKE_REASON, subject_guid=subject_guid,
    )

    # skip_missed: never catch up prior slots; only consider the current slot.
    if slot in completed:
        missed = []
        n = max(1, contract.staleness_tolerance_minutes // contract.cadence_minutes)
        for i in range(1, n + 1):
            past = contract.slot_for(when - timedelta(minutes=i * contract.cadence_minutes))
            if past not in completed:
                missed.append(past)
        _emit({
            **base,
            "outcome": "nothing_due",
            "wake_id": "none",
            "detail": "current slot already complete; missed slots skipped",
            "missed_skipped": missed,
        })
        return 0

    if dry_run:
        _emit({
            **base,
            "outcome": "dry_run",
            "wake_id": "none",
            "detail": "would invoke run_scheduled_wake; no writes",
        })
        return 0

    try:
        result = run_scheduled_wake(
            agent_id=agent_id,
            subject_guid=subject_guid,
            wake_reason=WAKE_REASON,
            state_root=root,
            memory_backend=memory_backend,
            when=when,
            contract=contract,
            env=env,
        )
    except Exception as exc:
        _emit({
            **base,
            "outcome": "error",
            "wake_id": "none",
            "detail": f"{type(exc).__name__}: {exc}",
        })
        return 1

    if result.get("skipped"):
        _emit({
            **base,
            "outcome": "disabled",
            "wake_id": "none",
            "detail": result.get("reason") or "feature_flag_off",
        })
        return 0

    wake = result.get("wake") or {}
    wake_id = wake.get("wake_id") or "none"
    state = wake.get("lifecycle_state") or result.get("state") or "unknown"

    if result.get("replay_suppressed"):
        outcome = "nothing_due"
        detail = "idempotent collision; slot already settled"
    elif state in {"MEMORY_MALFORMED", "STALE", "MEMORY_UNAVAILABLE"}:
        # Refuse to act; exit 0 so cron does not page.
        outcome = "refused"
        detail = f"memory_state={state}"
    elif result.get("memory_empty") and state == "LOADED":
        outcome = "refused"
        detail = "no_relevant_memory"
    elif result.get("ok"):
        outcome = "ok"
        detail = f"lifecycle_state={state}"
    else:
        outcome = "refused"
        detail = f"lifecycle_state={state}"

    # Report missed slots skipped (never caught up).
    missed = []
    n = max(1, contract.staleness_tolerance_minutes // contract.cadence_minutes)
    for i in range(1, n + 1):
        past = contract.slot_for(when - timedelta(minutes=i * contract.cadence_minutes))
        if past not in completed and past != slot:
            missed.append(past)

    _emit({
        **base,
        "outcome": outcome,
        "wake_id": wake_id,
        "detail": detail,
        "missed_skipped": missed,
        "inserted": bool(result.get("inserted")),
    })
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Cron-callable persistent wake runner (schedule-READY; not schedule-ACTIVE)",
    )
    p.add_argument("--agent-id", required=True, help="Agent id (e.g. cio)")
    p.add_argument("--subject-guid", default=None, help="Subject GUID to wake on")
    p.add_argument("--dry-run", action="store_true", help="Report what would run; write nothing")
    p.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Process a single slot/subject and exit (default)",
    )
    p.add_argument("--state-root", default=None, help="Disposable/state JSONL root (tests/ops)")
    p.add_argument("--memory-path", default=None, help="Optional memory JSONL path")
    p.add_argument("--when-utc", default=None, help="Override clock ISO-8601 UTC (tests only)")
    args = p.parse_args(argv)

    when = _now()
    if args.when_utc:
        when = datetime.fromisoformat(args.when_utc.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)

    env = dict(os.environ)
    mem = Path(args.memory_path) if args.memory_path else None
    return run_once(
        agent_id=args.agent_id,
        subject_guid=args.subject_guid,
        dry_run=args.dry_run,
        env=env,
        when=when,
        state_root=args.state_root,
        memory_backend=mem,
    )


if __name__ == "__main__":
    raise SystemExit(main())
