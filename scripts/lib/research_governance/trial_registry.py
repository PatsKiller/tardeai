"""Research governance — trial registry (PR-R1).

The foundation of the statistical-governance layer. DSR, PBO, and Reality Check
are meaningless if the system quietly forgets unsuccessful variants and keeps
only the winner.

Invariant (enforced):

    NO CONFIRMATORY RESULT WITHOUT A FROZEN HYPOTHESIS FAMILY
    NO FROZEN FAMILY WITHOUT A COMPLETE TRIAL REGISTRY
    NO COMPLETE TRIAL REGISTRY THAT RECORDS ONLY SELECTED/WINNING VARIANTS

Anti-gaming properties enforced by this registry:

  * freeze binds a PREDETERMINED universe of planned trial ids + config hashes,
    a protocol hash, and a family definition hash. After freeze:
      - no unplanned trial ids may be recorded,
      - a trial's config hash must match its frozen planned config hash.
  * trial records are IMMUTABLE: same trial_id + identical payload is idempotent,
    same trial_id + changed payload is a hard error.
  * selection is a separate append-only event, so a loser cannot be rewritten
    into a winner.
  * result_hash hashes the ACTUAL result payload; there is no parameter-hash
    fallback.
  * a family is COMPLETE only when every planned trial has an explicit terminal
    disposition (COMPLETED / INVALID / CANCELED_WITH_REASON / FAILED) and a
    protocol hash is present.
  * OOS consumption is terminal: the first `oos_consumed_at` is immutable and a
    consumed window can never be reported as untouched OOS evidence.

Pure, in-memory, injectable. No I/O here — persistence is the caller's concern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .enums import TERMINAL_STATUSES
from .models import OOSWindow, SelectionEvent, TrialRecord, _stable_hash


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TrialFamily:
    family_id: str
    hypothesis_id: str
    protocol_hash: str
    frozen_at: str
    planned_trial_ids: list[str]
    planned_config_hashes: dict[str, str]
    family_definition_hash: Optional[str] = None
    frozen: bool = True
    trials: dict[str, TrialRecord] = field(default_factory=dict)
    selection_events: list[SelectionEvent] = field(default_factory=list)
    oos_windows: dict[str, OOSWindow] = field(default_factory=dict)

    @property
    def trial_count(self) -> int:
        return len(self.trials)

    @property
    def selected_count(self) -> int:
        return sum(1 for e in self.selection_events if e.selected)

    @property
    def losing_count(self) -> int:
        return sum(1 for e in self.selection_events if not e.selected)


def _normalize_planned_trials(planned_trials: Iterable[Any]) -> tuple[list[str], dict[str, str]]:
    """Accept either [(trial_id, config_hash), ...] or [{'trial_id':..., 'config_hash':...}, ...]."""
    ids: list[str] = []
    hashes: dict[str, str] = {}
    for item in planned_trials:
        if isinstance(item, (tuple, list)):
            tid, chash = item[0], item[1]
        elif isinstance(item, dict):
            tid, chash = item["trial_id"], item["config_hash"]
        else:
            raise ValueError(f"invalid planned trial spec: {item!r}")
        if tid in hashes:
            raise ValueError(f"duplicate planned trial id: {tid}")
        ids.append(tid)
        hashes[tid] = chash
    return ids, hashes


class TrialRegistry:
    """Records every attempted variant for every hypothesis family."""

    def __init__(self) -> None:
        self._families: dict[str, TrialFamily] = {}

    # -- family lifecycle -------------------------------------------------
    def freeze_family(
        self,
        family_id: str,
        hypothesis_id: str,
        protocol_hash: str,
        planned_trials: Iterable[Any],
        family_definition_hash: Optional[str] = None,
    ) -> TrialFamily:
        """Freeze a family BEFORE confirmatory testing, binding the variant universe."""
        if not protocol_hash or not protocol_hash.strip():
            raise ValueError("protocol_hash is required to freeze a family")
        ids, hashes = _normalize_planned_trials(planned_trials)
        if not ids:
            raise ValueError("planned_trials must be non-empty")
        if family_id in self._families:
            raise ValueError(f"family {family_id} already frozen")

        fam = TrialFamily(
            family_id=family_id,
            hypothesis_id=hypothesis_id,
            protocol_hash=protocol_hash,
            frozen_at=_now_iso(),
            planned_trial_ids=ids,
            planned_config_hashes=hashes,
            family_definition_hash=family_definition_hash,
        )
        self._families[family_id] = fam
        return fam

    def is_frozen(self, family_id: str) -> bool:
        fam = self._families.get(family_id)
        return bool(fam and fam.frozen)

    def get_family(self, family_id: str) -> Optional[TrialFamily]:
        return self._families.get(family_id)

    # -- trial recording --------------------------------------------------
    def record_trial(
        self,
        family_id: str,
        trial_id: str,
        *,
        config_hash: str,
        result_hash: Optional[str] = None,
        result_payload: Optional[dict[str, Any]] = None,
        code_sha: Optional[str] = None,
        dataset_hash: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        terminal_status: str = "COMPLETED",
    ) -> TrialRecord:
        """Record (immutably) a trial. Only preregistered ids/configs are allowed."""
        fam = self._families.get(family_id)
        if fam is None or not fam.frozen:
            raise ValueError(f"family {family_id} not frozen")
        if trial_id not in fam.planned_config_hashes:
            raise ValueError(
                f"unplanned trial {trial_id} for family {family_id}; "
                f"planned={fam.planned_trial_ids}")
        if config_hash != fam.planned_config_hashes[trial_id]:
            raise ValueError(
                f"config_hash mismatch for {trial_id}: "
                f"frozen={fam.planned_config_hashes[trial_id]!r} got={config_hash!r}")
        if terminal_status not in TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal_status {terminal_status!r}")
        if result_hash is None:
            if result_payload is None:
                raise ValueError(
                    "result_hash (or result_payload to hash) is required; "
                    "parameter hashing is NOT a result hash")
            result_hash = _stable_hash(result_payload)

        rec = TrialRecord(
            trial_id=trial_id,
            config_hash=config_hash,
            result_hash=result_hash,
            terminal_status=terminal_status,
            started_at=started_at,
            completed_at=completed_at,
            code_sha=code_sha,
            dataset_hash=dataset_hash,
        )

        existing = fam.trials.get(trial_id)
        if existing is not None:
            if existing == rec:
                return existing  # idempotent: exact same payload
            raise ValueError(
                f"trial {trial_id} already recorded with different content; "
                "trial records are immutable")
        fam.trials[trial_id] = rec
        return rec

    def record_selection(
        self,
        family_id: str,
        trial_id: str,
        selected: bool,
        *,
        reason: Optional[str] = None,
        selection_event_id: Optional[str] = None,
    ) -> SelectionEvent:
        """Append a selection disposition. Does NOT mutate the trial record."""
        fam = self._families.get(family_id)
        if fam is None:
            raise ValueError(f"unknown family {family_id}")
        if trial_id not in fam.planned_config_hashes:
            raise ValueError(f"unknown trial {trial_id} in family {family_id}")
        event = SelectionEvent(
            selection_event_id=selection_event_id
            or f"{family_id}:{trial_id}:{len(fam.selection_events)}",
            trial_id=trial_id,
            selected=selected,
            reason=reason,
            timestamp=_now_iso(),
        )
        fam.selection_events.append(event)
        return event

    # -- completeness -----------------------------------------------------
    def completeness_report(self, family_id: str) -> dict[str, Any]:
        """A family is complete only when frozen, has a protocol hash, and every
        planned trial has an explicit terminal disposition."""
        fam = self._families.get(family_id)
        if fam is None:
            return {"family_id": family_id, "frozen": False, "complete": False,
                    "reason": "family not found"}

        problems: list[str] = []
        if not fam.frozen:
            problems.append("family not frozen")
        if not fam.protocol_hash:
            problems.append("protocol_hash absent")
        for tid in fam.planned_trial_ids:
            rec = fam.trials.get(tid)
            if rec is None:
                problems.append(f"planned trial {tid} has no recorded outcome")
            elif rec.terminal_status not in TERMINAL_STATUSES:
                problems.append(f"planned trial {tid} lacks a terminal disposition")

        # Anti-gaming: a complete family must account for ALL planned variants,
        # not merely contain at least one losing variant.
        return {
            "family_id": family_id,
            "frozen": fam.frozen,
            "protocol_hash_present": bool(fam.protocol_hash),
            "planned_trial_count": len(fam.planned_trial_ids),
            "recorded_trial_count": fam.trial_count,
            "selected_count": fam.selected_count,
            "losing_count": fam.losing_count,
            "complete": len(problems) == 0,
            "problems": problems,
        }

    # -- OOS consumption --------------------------------------------------
    def register_oos_window(
        self,
        family_id: str,
        oos_window_id: str,
        oos_generation: int,
        segment_start: Optional[str] = None,
        segment_end: Optional[str] = None,
    ) -> OOSWindow:
        fam = self._families.get(family_id)
        if fam is None or not fam.frozen:
            raise ValueError(f"OOS window requires a frozen family: {family_id}")
        existing = fam.oos_windows.get(oos_window_id)
        if existing is not None:
            return existing  # idempotent; never resets consumed timestamp
        win = OOSWindow(
            oos_window_id=oos_window_id,
            oos_generation=oos_generation,
            segment_start=segment_start,
            segment_end=segment_end,
        )
        fam.oos_windows[oos_window_id] = win
        return win

    def consume_oos_window(
        self, family_id: str, oos_window_id: str, at: Optional[str] = None
    ) -> OOSWindow:
        """Mark an OOS segment consumed. The first timestamp is immutable."""
        fam = self._families.get(family_id)
        if fam is None or oos_window_id not in fam.oos_windows:
            raise KeyError(f"unknown OOS window {family_id}/{oos_window_id}")
        win = fam.oos_windows[oos_window_id]
        if win.oos_consumed_at is None:
            win.oos_consumed_at = at or _now_iso()
        return win

    def oos_is_untouched(self, family_id: str, oos_window_id: str) -> bool:
        fam = self._families.get(family_id)
        if fam is None or oos_window_id not in fam.oos_windows:
            return False
        return fam.oos_windows[oos_window_id].oos_consumed_at is None
