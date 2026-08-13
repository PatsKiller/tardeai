"""
CIO Event Detector — Deterministic wake job creation for material CIO work.

This is a LAB service (P-1.6). Reads P-1.3 (action ledger), P-1.4 (handoff queue),
P-1.5 (health boundary) and schedule definitions. Creates ONE wake job per
material event. No model calls. No Telegram. No scheduling activation.

Legacy schedule definitions are derived from the actual crontab discovered
during P-1.6 inventory (2026-08-08). See LEGACY_ALEX_SCHEDULE_INVENTORY.md.

All times are America/New_York (ET), matching legacy crontab.
"""
from datetime import datetime, timezone, time, timedelta, date
from typing import List, Dict, Any, Optional, Set, Tuple
import hashlib, json, os, uuid
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# Legacy schedule definitions (discovered from actual crontab, 2026-08-08)
# ═══════════════════════════════════════════════════════════════════════════════

LEGACY_SCHEDULES = [
    {
        "schedule_id": "alex_daily",
        "schedule_type": "daily",
        "time_slot": "05:00",
        "timezone": "America/New_York",
        "weekdays": [0, 1, 2, 3, 4],  # Mon-Fri (Python weekday: 0=Mon)
        "domains": ["portfolio", "holdings", "performance", "risk"],
        "legacy_cron": "0 5 * * 1-5",
        "legacy_script": "scripts/run_alex_daily.py --daily",
        "enabled": True,
    },
    {
        "schedule_id": "alex_weekly",
        "schedule_type": "weekly",
        "weekday": 6,  # Sunday (Python weekday: 6=Sun)
        "time_slot": "08:00",
        "timezone": "America/New_York",
        "domains": ["portfolio", "allocation", "retirement"],
        "legacy_cron": "0 8 * * 0",
        "legacy_script": "scripts/run_alex_daily.py --weekly",
        "enabled": True,
    },
    {
        "schedule_id": "alex_monthly",
        "schedule_type": "monthly",
        "day_of_month": 1,
        "time_slot": "09:00",
        "timezone": "America/New_York",
        "domains": ["tax", "retirement", "allocation", "medicaid"],
        "legacy_cron": "0 9 1 * *",
        "legacy_script": "scripts/run_alex_daily.py --monthly",
        "enabled": True,
    },
    {
        "schedule_id": "alex_hygiene",
        "schedule_type": "daily",
        "time_slot": "07:15",
        "timezone": "America/New_York",
        "weekdays": [0, 1, 2, 3, 4],  # Mon-Fri
        "domains": ["governance", "decisions"],
        "legacy_cron": "15 7 * * 1-5",
        "legacy_script": "scripts/alex_hygiene.py",
        "enabled": True,
    },
    {
        "schedule_id": "alex_gov_research",
        "schedule_type": "weekly",
        "weekday": 0,  # Monday
        "time_slot": "06:00",
        "timezone": "America/New_York",
        "domains": ["tax", "retirement", "regulatory"],
        "legacy_cron": "0 6 * * 1",
        "legacy_script": "scripts/alex_gov_research.py --refresh",
        "enabled": True,
    },
]

# Derived defaults for the detector
from scripts.lib.cio_wake_jobs import (
    PRIORITY_MAP,
    WAKE_REASON_CODES,
    TRIGGER_TYPES,
)


class CIOEventDetector:
    """Deterministic detector that creates wake jobs for material CIO work.

    Reads P-1.3 (action ledger), P-1.4 (handoff queue), P-1.5 (health boundary)
    and schedule definitions. Creates ONE wake job per material event.
    No model calls. No Telegram. No scheduling activation.
    """

    POLICY_VERSION = "1.0.0"
    LOOKBACK_HOURS = 24
    CATCHUP_MAX_SLOTS = 7

    def __init__(
        self,
        schedules=None,
        wake_store=None,
        action_ledger=None,
        handoff_queue=None,
        health_boundary=None,
    ):
        self.schedules = schedules or LEGACY_SCHEDULES
        self._wake_store = wake_store
        self._action_ledger = action_ledger
        self._handoff_queue = handoff_queue
        self._health_boundary = health_boundary
        self._now = None
        self._timezone = None

    def set_clock(self, dt: datetime):
        """Inject clock for deterministic testing."""
        self._now = dt
        self._timezone = dt.tzinfo if dt.tzinfo else timezone.utc

    def _now_dt(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    def run_once(self) -> Dict[str, Any]:
        """Run one detection cycle. Returns summary of wakes created."""
        now = self._now_dt()
        wakes: List[dict] = []

        # A. Check schedules
        schedule_wakes = self._check_schedules(now)
        wakes.extend(schedule_wakes)

        # B. Check action follow-ups
        if self._action_ledger:
            followup_wakes = self._check_action_followups(now)
            wakes.extend(followup_wakes)

        # C. Health transitions — FUTURE: requires health boundary transition
        # event export. For P-1.6, documented but not wired to live boundary.

        # D. Check handoff completions
        if self._handoff_queue:
            handoff_wakes = self._check_handoff_completions(now)
            wakes.extend(handoff_wakes)

        return {
            "run_at": now.isoformat(),
            "wakes_created": len(wakes),
            "wake_ids": [w["stream_id"] for w in wakes],
            "detector_version": self.POLICY_VERSION,
        }

    def _check_schedules(self, now: datetime) -> List[dict]:
        """Check which schedule slots are due and create wake jobs."""
        wakes: List[dict] = []
        for sched in self.schedules:
            if not sched.get("enabled", True):
                continue

            due_slots = self._compute_due_slots(sched, now)

            for slot in due_slots:
                schedule_id = sched["schedule_id"]
                slot_key = slot.strftime("%Y-%m-%d-%H%M")
                idem_key = hashlib.sha256(
                    f"{schedule_id}|{slot_key}|{self.POLICY_VERSION}".encode()
                ).hexdigest()[:32]

                if self._wake_store and self._wake_idempotent_exists(idem_key):
                    continue

                wake_id = f"wake-scheduled-{schedule_id}-{slot.strftime('%Y%m%d-%H%M')}"

                wake = self._create_wake(
                    wake_id=wake_id,
                    trigger_type="SCHEDULE_DUE",
                    trigger_ref=schedule_id,
                    trigger_hash=hashlib.sha256(slot_key.encode()).hexdigest(),
                    scheduled_slot=slot.isoformat(),
                    reason_codes=["SCHEDULE_DUE"],
                    required_domains=sched.get("domains", []),
                    idempotency_key=idem_key,
                )
                if wake:
                    wakes.append(wake)

        return wakes

    def _compute_due_slots(self, sched: dict, now: datetime) -> List[datetime]:
        """Compute schedule slots that are due but haven't been woken.

        Uses bounded lookback for restart recovery.
        """
        schedule_type = sched["schedule_type"]
        time_slot = sched.get("time_slot", "00:00")
        tz_name = sched.get("timezone", "America/New_York")

        hour, minute = map(int, time_slot.split(":"))

        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
        except Exception:
            from datetime import timezone as _utc
            tz = _utc.utc

        lookback = now - timedelta(hours=self.LOOKBACK_HOURS)

        if schedule_type == "daily":
            due_slots: List[datetime] = []
            now_tz = now.astimezone(tz)
            current_date = now_tz.date()
            weekdays = sched.get("weekdays")

            for days_back in range(min(self.CATCHUP_MAX_SLOTS, 7)):
                check_date = current_date - timedelta(days=days_back)

                if weekdays is not None and check_date.weekday() not in weekdays:
                    continue

                slot_dt = datetime.combine(check_date, time(hour, minute), tzinfo=tz)
                slot_utc = slot_dt.astimezone(timezone.utc)

                if lookback <= slot_utc <= now:
                    due_slots.append(slot_utc)

            return due_slots

        elif schedule_type == "weekly":
            weekday = sched.get("weekday", 6)
            now_tz = now.astimezone(tz)

            # Check if the target weekday slot has passed this week
            current_weekday = now_tz.weekday()
            if current_weekday == weekday:
                slot_dt = datetime.combine(now_tz.date(), time(hour, minute), tzinfo=tz)
                slot_utc = slot_dt.astimezone(timezone.utc)
                if slot_utc <= now and slot_utc >= lookback:
                    return [slot_utc]
            elif weekday < current_weekday:
                # Target weekday already passed this week
                days_since = current_weekday - weekday
                target_date = now_tz.date() - timedelta(days=days_since)
                slot_dt = datetime.combine(target_date, time(hour, minute), tzinfo=tz)
                slot_utc = slot_dt.astimezone(timezone.utc)
                if slot_utc >= lookback:
                    return [slot_utc]

            # Also check last week
            days_back = 7 + weekday - current_weekday
            if days_back >= 7:
                days_back -= 7
            last_week_date = now_tz.date() - timedelta(days=days_back + 7)
            last_slot = datetime.combine(last_week_date, time(hour, minute), tzinfo=tz)
            last_slot_utc = last_slot.astimezone(timezone.utc)
            if lookback <= last_slot_utc <= now:
                days_since_slot = (now - last_slot_utc).total_seconds() / 3600
                if days_since_slot <= 48:  # Catch up within 2 days
                    return [last_slot_utc]

            return []

        elif schedule_type == "monthly":
            day_of_month = sched.get("day_of_month", 1)
            now_tz = now.astimezone(tz)
            current_day = now_tz.day

            if current_day == day_of_month:
                slot_dt = datetime.combine(now_tz.date(), time(hour, minute), tzinfo=tz)
                slot_utc = slot_dt.astimezone(timezone.utc)
                if slot_utc <= now:
                    return [slot_utc]

            # Check if the monthly slot passed earlier today or yesterday (bounded)
            if current_day > day_of_month and current_day - day_of_month <= 2:
                target_date = now_tz.date().replace(day=day_of_month)
                slot_dt = datetime.combine(target_date, time(hour, minute), tzinfo=tz)
                slot_utc = slot_dt.astimezone(timezone.utc)
                if lookback <= slot_utc <= now:
                    return [slot_utc]

            return []

        return []

    def _check_action_followups(self, now: datetime) -> List[dict]:
        """Check P-1.3 action ledger for due follow-ups."""
        wakes: List[dict] = []
        try:
            actions = self._action_ledger.list_actions()
        except Exception:
            return wakes

        for action in actions:
            status = action.get("current_status")
            if status in ("DONE", "EXPIRED", "SUPERSEDED", "CANCELLED", "BLOCKED"):
                continue

            next_check = action.get("next_check_at")
            if not next_check:
                continue

            try:
                next_dt = datetime.fromisoformat(next_check)
                if next_dt.tzinfo is None:
                    next_dt = next_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if next_dt > now:
                continue

            action_id = action["cio_action_id"]
            last_event_hash = action.get("last_event_hash", "")

            idem_key = hashlib.sha256(
                f"{action_id}|{next_check}|{last_event_hash}|{self.POLICY_VERSION}".encode()
            ).hexdigest()[:32]

            if self._wake_store and self._wake_idempotent_exists(idem_key):
                continue

            reason_codes = ["ACTION_FOLLOWUP_DUE"]
            if action.get("deadline"):
                try:
                    deadline_dt = datetime.fromisoformat(action["deadline"])
                    if deadline_dt.tzinfo is None:
                        deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
                    hours_to_deadline = (deadline_dt - now).total_seconds() / 3600
                    if hours_to_deadline <= 24:
                        reason_codes.append("ACTION_DEADLINE_NEAR")
                except (ValueError, TypeError):
                    pass

            wake_id = f"wake-action-{action_id[:16]}"

            wake = self._create_wake(
                wake_id=wake_id,
                trigger_type="ACTION_FOLLOWUP_DUE",
                trigger_ref=action_id,
                trigger_hash=last_event_hash,
                parent_cio_action_id=action_id,
                reason_codes=reason_codes,
                required_domains=[action.get("domain", "GENERAL")],
                idempotency_key=idem_key,
            )
            if wake:
                wakes.append(wake)

        return wakes

    def _check_handoff_completions(self, now: datetime) -> List[dict]:
        """Check P-1.4 for newly completed handoffs that need CIO attention."""
        wakes: List[dict] = []
        try:
            handoffs = self._handoff_queue.list_handoffs(status="COMPLETED")
        except Exception:
            return wakes

        lookback = now - timedelta(hours=self.LOOKBACK_HOURS)

        for handoff in handoffs:
            updated_at = handoff.get("updated_at")
            if not updated_at:
                continue

            try:
                ut_dt = datetime.fromisoformat(updated_at)
                if ut_dt.tzinfo is None:
                    ut_dt = ut_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if ut_dt < lookback:
                continue

            handoff_id = handoff["handoff_id"]
            artifact_hash = handoff.get("artifact_hash", "")
            parent_run_id = handoff.get("parent_run_id", "")

            idem_key = hashlib.sha256(
                f"{handoff_id}|completed|{artifact_hash}|{self.POLICY_VERSION}".encode()
            ).hexdigest()[:32]

            if self._wake_store and self._wake_idempotent_exists(idem_key):
                continue

            wake_id = f"wake-handoff-{handoff_id[:16]}"

            # A completed specialist handoff must RE-OPEN its parent CIO run so the
            # committee can convene from real specialist output. Use RESUME_RUN when
            # the parent run is known; fall back to NEW_RUN (SPECIALIST_COMPLETION)
            # for orphaned handoffs.
            wake = self._create_wake(
                wake_id=wake_id,
                trigger_type="HANDOFF_COMPLETED",
                trigger_ref=handoff_id,
                trigger_hash=artifact_hash,
                parent_handoff_id=handoff_id,
                parent_cio_action_id=handoff.get("parent_cio_action_id"),
                reason_codes=["HANDOFF_COMPLETED"],
                required_domains=[],
                idempotency_key=idem_key,
                wake_intent=("RESUME_RUN" if parent_run_id else "NEW_RUN"),
                target_run_id=(parent_run_id or None),
            )
            if wake:
                wakes.append(wake)

        return wakes

    def _wake_idempotent_exists(self, idempotency_key: str) -> bool:
        """Check if a wake with this idempotency key already exists."""
        if not self._wake_store:
            return False
        wakes = self._wake_store.list_wakes()
        for wake in wakes:
            events = self._wake_store.list_events(wake.get("wake_job_id", ""))
            for e in events:
                if e.get("payload", {}).get("idempotency_key") == idempotency_key:
                    return True
        return False

    def _create_wake(
        self,
        wake_id,
        trigger_type,
        trigger_ref,
        trigger_hash,
        reason_codes,
        required_domains,
        idempotency_key,
        scheduled_slot=None,
        parent_cio_action_id=None,
        parent_handoff_id=None,
        health_decision_id=None,
        source_snapshot_id=None,
        wake_intent=None,
        target_run_id=None,
    ) -> Optional[dict]:
        """Create a wake job if store is available."""
        if not self._wake_store:
            return None

        now = self._now_dt()
        priority = PRIORITY_MAP.get(trigger_type, "normal")

        # Boost priority if ACTION_DEADLINE_NEAR is in reason codes
        if "ACTION_DEADLINE_NEAR" in reason_codes:
            priority = "high"

        payload = {
            "wake_job_id": wake_id,
            "trigger_type": trigger_type,
            "trigger_ref": trigger_ref,
            "trigger_hash": trigger_hash,
            "scheduled_slot": scheduled_slot or now.isoformat(),
            "created_at": now.isoformat(),
            "due_at": now.isoformat(),
            "priority": priority,
            "reason_codes": list(reason_codes),
            "required_domains": list(required_domains),
            "parent_cio_action_id": parent_cio_action_id,
            "parent_handoff_id": parent_handoff_id,
            "health_decision_id": health_decision_id,
            "source_snapshot_id": source_snapshot_id,
            "wake_intent": wake_intent or "NEW_RUN",
            "target_run_id": target_run_id,
            "idempotency_key": idempotency_key,
        }

        try:
            return self._wake_store.enqueue(payload)
        except ValueError as e:
            if "already exists" in str(e):
                return None
            return None


def run_cio_event_detector_once(wake_store_path=None, action_ledger_path=None, handoff_queue_path=None):
    """CLI entrypoint for one detection cycle."""
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    from scripts.lib.cio_action_ledger import CIOActionLedger
    from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue

    store_path = Path(wake_store_path) if wake_store_path else None
    ledger_path = Path(action_ledger_path) if action_ledger_path else None
    queue_path = Path(handoff_queue_path) if handoff_queue_path else None

    wake_store = CIOWakeJobStore(event_store_path=store_path) if store_path else CIOWakeJobStore()
    action_ledger = CIOActionLedger(event_store_path=ledger_path) if ledger_path else CIOActionLedger()
    handoff_queue = AgentHandoffQueue(event_store_path=queue_path) if queue_path else AgentHandoffQueue()

    detector = CIOEventDetector(
        wake_store=wake_store,
        action_ledger=action_ledger,
        handoff_queue=handoff_queue,
    )

    result = detector.run_once()
    return result
