"""PersistentWakeScheduleContract@v1 — define cadence/health without activating cron.

This module is schedule-READY, not schedule-ACTIVE. It never writes crontab,
systemd units, or timers. Integration wires invocation later.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from scripts.lib.persistent_wake_interfaces import (
    SCHEDULE_SCHEMA,
    SCHEDULE_STATES,
    ns_schedule_slot,
)
import uuid

AUTHORITY = "READ_ONLY_ADVISORY"
FEATURE_FLAG = "PERSISTENT_WAKE_SCHEDULE_ENABLED"  # default OFF


@dataclass(frozen=True)
class ScheduleContract:
    agent_id: str
    wake_reason: str
    cadence_minutes: int = 60
    staleness_tolerance_minutes: int = 180
    catch_up_policy: str = "skip_missed"  # skip_missed | catch_up_bounded
    catch_up_max_slots: int = 0
    schema_version: str = SCHEDULE_SCHEMA

    def slot_for(self, when: datetime) -> str:
        """Deterministic UTC slot id for `when`."""
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(timezone.utc)
        # Floor to cadence boundary
        epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
        minutes = int((when - epoch).total_seconds() // 60)
        floored = minutes - (minutes % self.cadence_minutes)
        slot_dt = epoch + timedelta(minutes=floored)
        return slot_dt.strftime("%Y-%m-%dT%H:%MZ")

    def slot_uuid(self, slot: str, subject_guid: str) -> str:
        return str(uuid.uuid5(ns_schedule_slot, f"{self.agent_id}|{self.wake_reason}|{slot}|{subject_guid}"))


@dataclass
class ScheduleHealth:
    agent_id: str
    state: str
    last_successful_slot: str | None = None
    last_successful_wake_id: str | None = None
    missed_slots: list[str] | None = None
    stale: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["missed_slots"] = list(self.missed_slots or [])
        return d


def evaluate_health(
    contract: ScheduleContract,
    *,
    now: datetime,
    completed_slots: Iterable[str],
    running_slots: Iterable[str] = (),
    failed_slots: Iterable[str] = (),
    replay_suppressed_slots: Iterable[str] = (),
    dependency_stale: bool = False,
    memory_relevant: bool | None = None,
    never_scheduled: bool = False,
) -> ScheduleHealth:
    """Pure health evaluation. Never activates anything."""
    if never_scheduled:
        return ScheduleHealth(contract.agent_id, "never_scheduled", detail="no schedule installed")
    if dependency_stale:
        return ScheduleHealth(contract.agent_id, "stale_dependency", stale=True, detail="dependency older than tolerance")
    if memory_relevant is False:
        return ScheduleHealth(contract.agent_id, "no_relevant_memory", detail="subject memory empty/irrelevant")

    completed = set(completed_slots)
    running = set(running_slots)
    failed = set(failed_slots)
    suppressed = set(replay_suppressed_slots)
    current = contract.slot_for(now)

    if current in suppressed:
        return ScheduleHealth(contract.agent_id, "replay_suppressed", last_successful_slot=max(completed) if completed else None)
    if current in running:
        return ScheduleHealth(contract.agent_id, "running", detail=f"slot {current}")
    if current in failed:
        return ScheduleHealth(contract.agent_id, "failed", detail=f"slot {current}")
    if current in completed:
        return ScheduleHealth(contract.agent_id, "completed", last_successful_slot=current)

    # Due if current slot not completed
    # Missed = prior slots within staleness window not completed
    missed = []
    if contract.staleness_tolerance_minutes > 0:
        n = max(1, contract.staleness_tolerance_minutes // contract.cadence_minutes)
        for i in range(1, n + 1):
            past = contract.slot_for(now - timedelta(minutes=i * contract.cadence_minutes))
            if past not in completed and past not in suppressed:
                missed.append(past)

    if missed and contract.catch_up_policy == "skip_missed":
        # still due for current; missed recorded
        return ScheduleHealth(
            contract.agent_id, "due", missed_slots=missed,
            last_successful_slot=max(completed) if completed else None,
            detail=f"current={current}",
        )
    if missed and len(missed) > contract.catch_up_max_slots:
        return ScheduleHealth(contract.agent_id, "partial", missed_slots=missed, detail="catch-up bound exceeded")
    return ScheduleHealth(
        contract.agent_id, "due", missed_slots=missed,
        last_successful_slot=max(completed) if completed else None,
        detail=f"current={current}",
    )


def assert_schedule_states_complete() -> None:
    required = set(SCHEDULE_STATES)
    assert required == {
        "never_scheduled", "due", "running", "completed", "partial", "failed",
        "replay_suppressed", "stale_dependency", "no_relevant_memory",
    }
