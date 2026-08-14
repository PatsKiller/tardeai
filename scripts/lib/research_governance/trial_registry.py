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
    a protocol hash, and (for confirmatory families) a family definition hash.
    After freeze: no unplanned ids, no config-hash mutation.
  * trial records are IMMUTABLE: same id + identical payload is idempotent,
    same id + changed payload is a hard error.
  * result lineage is VERIFIABLE: inline payloads are hashed by the registry;
    external artifacts require ref + size + sha256 and an injectable verifier,
    and the verification result is RETAINED on the record. A confirmatory
    COMPLETED trial must be VERIFIED.
  * terminal dispositions INVALID / FAILED / CANCELED_WITH_REASON require a
    terminal_reason (and optionally failure_stage); a family cannot be
    "completed" by cheaply invalidating inconvenient variants.
  * selection is a separate append-only event pointing at a RECORDED trial; a
    merely-planned trial cannot be selected. Conflicting dispositions are
    surfaced explicitly, never silently resolved.
  * a family is COMPLETE only when frozen, has a protocol hash (and, for
    confirmatory families, a family definition hash), every planned trial has an
    explicit terminal disposition, and every non-COMPLETED trial has a reason.
  * OOS windows are immutable; identity = economic segment (dataset identity +
    segment + protocol family). Dataset snapshot lineage (`dataset_hash`) is
    stored but a consumed economic segment cannot become fresh by changing the
    snapshot; corrected data is classified CORRECTED_DATA_RERUN, never fresh OOS.

Persistence scope: this registry is an IN-MEMORY, INJECTABLE, IMMUTABLE
in-process contract. Durable append-only persistence is DEFERRED to a later PR.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .enums import (
    REASON_REQUIRED_STATUSES,
    TERMINAL_STATUSES,
    ResultStorage,
    VerificationStatus,
)
from .models import (
    ArtifactVerification,
    ArtifactVerifier,
    OOSWindow,
    SelectionEvent,
    TrialRecord,
    _stable_hash,
)


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
    confirmatory: bool = False
    frozen: bool = True
    trials: dict[str, TrialRecord] = field(default_factory=dict)
    selection_events: list[SelectionEvent] = field(default_factory=list)
    selection_event_ids: set = field(default_factory=set)
    oos_windows: dict[str, OOSWindow] = field(default_factory=dict)
    oos_economic_segments: dict[str, str] = field(default_factory=dict)

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
        if not chash or not str(chash).strip():
            raise ValueError(f"empty config hash for planned trial: {tid}")
        ids.append(tid)
        hashes[tid] = chash
    return ids, hashes


def _oos_economic_identity(family_id: str, protocol_hash: str, dataset_id: Optional[str],
                           segment_start: Optional[str], segment_end: Optional[str],
                           oos_generation: int) -> str:
    """Economic/time segment identity — NOT dataset snapshot hash.

    Changing the dataset snapshot hash must NOT produce a fresh OOS identity;
    the same economic period stays the same segment. Snapshot lineage is stored
    separately (`dataset_hash`) so corrected data is a rerun, not a new segment.
    """
    return _stable_hash({
        "family_id": family_id,
        "protocol_hash": protocol_hash,
        "dataset_id": dataset_id,
        "segment_start": segment_start,
        "segment_end": segment_end,
        "oos_generation": oos_generation,
    })


class TrialRegistry:
    """Records every attempted variant for every hypothesis family."""

    def __init__(self, verifier: Optional[ArtifactVerifier] = None) -> None:
        self._families: dict[str, TrialFamily] = {}
        self._verifier = verifier

    # -- family lifecycle -------------------------------------------------
    def freeze_family(
        self,
        family_id: str,
        hypothesis_id: str,
        protocol_hash: str,
        planned_trials: Iterable[Any],
        family_definition_hash: Optional[str] = None,
        confirmatory: bool = False,
    ) -> TrialFamily:
        if not protocol_hash or not protocol_hash.strip():
            raise ValueError("protocol_hash is required to freeze a family")
        if not hypothesis_id or not hypothesis_id.strip():
            raise ValueError("hypothesis_id is required to freeze a family")
        if confirmatory and (not family_definition_hash or not family_definition_hash.strip()):
            raise ValueError("family_definition_hash is required for a confirmatory family")
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
            confirmatory=confirmatory,
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
        result_artifact_ref: Optional[str] = None,
        result_artifact_size: Optional[int] = None,
        hash_algorithm: str = "sha256",
        code_sha: Optional[str] = None,
        dataset_hash: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        terminal_status: str = "COMPLETED",
        terminal_reason: Optional[str] = None,
        failure_stage: Optional[str] = None,
    ) -> TrialRecord:
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
        if terminal_status in REASON_REQUIRED_STATUSES and not (terminal_reason or "").strip():
            raise ValueError(
                f"terminal_status {terminal_status!r} requires a terminal_reason "
                f"(cannot dispose a trial cheaply)")

        # -- result lineage -------------------------------------------------
        result_storage: str
        result_verified_at: Optional[str] = None
        result_verification_status: Optional[str] = None
        if result_payload is not None:
            computed = _stable_hash(result_payload)
            if result_hash is not None and result_hash != computed:
                raise ValueError("supplied result_hash does not match result_payload")
            result_hash = computed
            result_storage = ResultStorage.INLINE_PAYLOAD_HASH.value
            result_verification_status = VerificationStatus.VERIFIED.value
            result_artifact_ref = None
            result_artifact_size = None
        elif result_hash is not None:
            if hash_algorithm != "sha256":
                raise ValueError("only sha256 result hashes are supported")
            if not result_artifact_ref or result_artifact_size is None:
                raise ValueError(
                    "caller-supplied result_hash requires result_artifact_ref + "
                    "result_artifact_size (no opaque hash as a completed result)")
            result_storage = ResultStorage.EXTERNAL_ARTIFACT.value
            if self._verifier is not None:
                av: ArtifactVerification = self._verifier.verify(
                    result_artifact_ref, result_artifact_size, result_hash)
                if not av.verified:
                    raise ValueError(f"external artifact verification failed: {av.error}")
                result_verified_at = av.verified_at
                result_verification_status = VerificationStatus.VERIFIED.value
            else:
                result_verified_at = None
                result_verification_status = VerificationStatus.UNVERIFIED.value
        else:
            raise ValueError(
                "result_payload or a verifiable result_hash+artifact reference is required")

        # -- confirmatory execution lineage ----------------------------------
        if fam.confirmatory and terminal_status == "COMPLETED":
            missing = []
            if not code_sha:
                missing.append("code_sha")
            if not dataset_hash:
                missing.append("dataset_hash")
            if not started_at:
                missing.append("started_at")
            if not completed_at:
                missing.append("completed_at")
            if result_verification_status != VerificationStatus.VERIFIED.value:
                missing.append("verified result (verification_status != VERIFIED)")
            if missing:
                raise ValueError(
                    f"confirmatory COMPLETED trial {trial_id} missing execution lineage: {missing}")

        rec = TrialRecord(
            trial_id=trial_id,
            config_hash=config_hash,
            result_hash=result_hash,
            terminal_status=terminal_status,
            result_storage=result_storage,
            result_artifact_ref=result_artifact_ref,
            result_artifact_size=result_artifact_size,
            hash_algorithm=hash_algorithm,
            result_verified_at=result_verified_at,
            result_verification_status=result_verification_status,
            terminal_reason=terminal_reason,
            failure_stage=failure_stage,
            started_at=started_at,
            completed_at=completed_at,
            code_sha=code_sha,
            dataset_hash=dataset_hash,
        )

        existing = fam.trials.get(trial_id)
        if existing is not None:
            if existing == rec:
                return existing
            raise ValueError(
                f"trial {trial_id} already recorded with different content; "
                "trial records are immutable")
        fam.trials[trial_id] = rec
        return rec

    # -- selection ---------------------------------------------------------
    def record_selection(
        self,
        family_id: str,
        trial_id: str,
        selected: bool,
        *,
        reason: Optional[str] = None,
        selection_event_id: Optional[str] = None,
    ) -> SelectionEvent:
        """Append a selection disposition for a RECORDED (terminal) trial."""
        fam = self._families.get(family_id)
        if fam is None:
            raise ValueError(f"unknown family {family_id}")
        if trial_id not in fam.planned_config_hashes:
            raise ValueError(f"unknown trial {trial_id} in family {family_id}")
        if trial_id not in fam.trials:
            raise ValueError(
                f"trial {trial_id} has no recorded terminal result; selection must "
                "point to an executed trial")
        eid = selection_event_id or f"{family_id}:{trial_id}:{len(fam.selection_events)}"
        if eid in fam.selection_event_ids:
            raise ValueError(f"duplicate selection_event_id: {eid}")
        event = SelectionEvent(
            selection_event_id=eid,
            trial_id=trial_id,
            selected=selected,
            reason=reason,
            timestamp=_now_iso(),
        )
        fam.selection_event_ids.add(eid)
        fam.selection_events.append(event)
        return event

    def selection_disposition(self, family_id: str, trial_id: str) -> dict:
        """Expose the current disposition and any conflict explicitly.

        Consumers must NOT infer "selected" by finding any selected=true event;
        contradictory events are reported as a conflict.
        """
        fam = self._families.get(family_id)
        events = [e for e in fam.selection_events if e.trial_id == trial_id] if fam else []
        if not events:
            return {"trial_id": trial_id, "selected": None, "conflict": False, "events": []}
        selected_vals = {e.selected for e in events}
        conflict = len(selected_vals) > 1
        # Last event wins only when there is no conflict.
        current = events[-1].selected if not conflict else None
        return {
            "trial_id": trial_id,
            "selected": current,
            "conflict": conflict,
            "events": [{"id": e.selection_event_id, "selected": e.selected,
                        "timestamp": e.timestamp} for e in events],
        }

    # -- completeness -----------------------------------------------------
    def completeness_report(self, family_id: str) -> dict[str, Any]:
        fam = self._families.get(family_id)
        if fam is None:
            return {"family_id": family_id, "frozen": False, "complete": False,
                    "reason": "family not found"}

        problems: list[str] = []
        if not fam.frozen:
            problems.append("family not frozen")
        if not fam.protocol_hash:
            problems.append("protocol_hash absent")
        if fam.confirmatory and not fam.family_definition_hash:
            problems.append("confirmatory family missing family_definition_hash")

        terminal_counts: dict[str, int] = {}
        for tid in fam.planned_trial_ids:
            rec = fam.trials.get(tid)
            if rec is None:
                problems.append(f"planned trial {tid} has no recorded outcome")
                continue
            terminal_counts[rec.terminal_status] = terminal_counts.get(rec.terminal_status, 0) + 1
            if rec.terminal_status not in TERMINAL_STATUSES:
                problems.append(f"planned trial {tid} lacks a terminal disposition")
            if rec.terminal_status in REASON_REQUIRED_STATUSES and not rec.terminal_reason:
                problems.append(f"planned trial {tid} disposed as {rec.terminal_status} without terminal_reason")
            if fam.confirmatory and rec.terminal_status == "COMPLETED" \
                    and rec.result_verification_status != VerificationStatus.VERIFIED.value:
                problems.append(f"confirmatory COMPLETED trial {tid} has unverified result lineage")

        return {
            "family_id": family_id,
            "frozen": fam.frozen,
            "confirmatory": fam.confirmatory,
            "protocol_hash_present": bool(fam.protocol_hash),
            "family_definition_hash_present": bool(fam.family_definition_hash),
            "planned_trial_count": len(fam.planned_trial_ids),
            "recorded_trial_count": fam.trial_count,
            "selected_count": fam.selected_count,
            "losing_count": fam.losing_count,
            "terminal_counts": terminal_counts,
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
        dataset_id: Optional[str] = None,
        dataset_hash: Optional[str] = None,
    ) -> OOSWindow:
        """Register an OOS segment. Same id + changed payload => hard error.

        Economic segment identity is (dataset_id + segment + protocol family).
        A consumed economic segment cannot become fresh by changing `dataset_hash`;
        corrected data is classified CORRECTED_DATA_RERUN.
        """
        fam = self._families.get(family_id)
        if fam is None or not fam.frozen:
            raise ValueError(f"OOS window requires a frozen family: {family_id}")

        existing = fam.oos_windows.get(oos_window_id)
        if existing is not None:
            same_payload = (
                existing.oos_generation == oos_generation
                and existing.segment_start == segment_start
                and existing.segment_end == segment_end
                and existing.dataset_id == dataset_id
                and existing.dataset_hash == dataset_hash
            )
            if same_payload:
                return existing
            raise ValueError(
                f"OOS window {oos_window_id} already registered with different payload; "
                "OOS windows are immutable")

        economic_fp = _oos_economic_identity(
            family_id, fam.protocol_hash, dataset_id,
            segment_start, segment_end, oos_generation)

        rerun_classification: Optional[str] = None
        if economic_fp in fam.oos_economic_segments:
            prev_ds = fam.oos_economic_segments[economic_fp]
            if dataset_hash == prev_ds:
                raise ValueError(
                    "OOS economic segment already registered (same identity + dataset "
                    "snapshot) under another id; consumed segment cannot be re-registered "
                    "as fresh OOS")
            # Same economic segment, different dataset snapshot => corrected rerun.
            rerun_classification = "CORRECTED_DATA_RERUN"

        fam.oos_economic_segments[economic_fp] = dataset_hash

        win = OOSWindow(
            oos_window_id=oos_window_id,
            oos_generation=oos_generation,
            segment_start=segment_start,
            segment_end=segment_end,
            dataset_id=dataset_id,
            dataset_hash=dataset_hash,
            protocol_hash=fam.protocol_hash,
            family_definition_hash=fam.family_definition_hash,
            registered_at=_now_iso(),
            oos_consumed_at=None,
            rerun_classification=rerun_classification,
        )
        fam.oos_windows[oos_window_id] = win
        return win

    def consume_oos_window(
        self, family_id: str, oos_window_id: str, at: Optional[str] = None
    ) -> OOSWindow:
        """Mark an OOS segment consumed. The first timestamp is immutable.

        OOSWindow is frozen, so consumption REPLACES the record with a new one
        carrying the immutable first-consumption timestamp.
        """
        fam = self._families.get(family_id)
        if fam is None or oos_window_id not in fam.oos_windows:
            raise KeyError(f"unknown OOS window {family_id}/{oos_window_id}")
        win = fam.oos_windows[oos_window_id]
        if win.oos_consumed_at is None:
            consumed = replace(win, oos_consumed_at=at or _now_iso())
            fam.oos_windows[oos_window_id] = consumed
            return consumed
        return win

    def oos_is_untouched(self, family_id: str, oos_window_id: str) -> bool:
        """Fresh untouched OOS only when not consumed and not a corrected rerun."""
        fam = self._families.get(family_id)
        if fam is None or oos_window_id not in fam.oos_windows:
            return False
        win = fam.oos_windows[oos_window_id]
        return win.oos_consumed_at is None and win.rerun_classification is None
