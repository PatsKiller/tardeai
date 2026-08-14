"""Research governance — trial registry (PR-R1).

The foundation of the statistical-governance layer. DSR, PBO, and Reality Check
are meaningless if the system quietly forgets the unsuccessful parameter
variations and keeps only the winner.

Invariant (enforced here):

    NO CONFIRMATORY RESULT WITHOUT A FROZEN HYPOTHESIS FAMILY
    NO FROZEN FAMILY WITHOUT A COMPLETE TRIAL REGISTRY
    NO COMPLETE TRIAL REGISTRY THAT RECORDS ONLY SELECTED/WINNING VARIANTS

OOS consumption: once a confirmatory OOS segment has been examined and then used
to alter parameters, that segment is consumed (`oos_consumed_at`). It can no
longer be reported as untouched OOS evidence; a subsequent iteration needs a new
untouched segment or must be labelled POST_OOS_TUNED rather than OOS_SUPPORTED.

Pure, in-memory, injectable. No I/O here — persistence is the caller's concern.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .models import OOSWindow, TrialRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_params(params: dict[str, Any]) -> str:
    import json
    canonical = json.dumps(params, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class TrialFamily:
    family_id: str
    hypothesis_id: str
    protocol_hash: Optional[str] = None
    frozen: bool = False
    frozen_at: Optional[str] = None
    trials: dict[str, TrialRecord] = field(default_factory=dict)
    oos_windows: dict[str, OOSWindow] = field(default_factory=dict)

    @property
    def trial_count(self) -> int:
        return len(self.trials)

    @property
    def selected_count(self) -> int:
        return sum(1 for t in self.trials.values() if t.selected_for_followup)

    @property
    def losing_count(self) -> int:
        return sum(1 for t in self.trials.values() if not t.selected_for_followup)


class TrialRegistry:
    """Records every attempted variant for every hypothesis family."""

    def __init__(self) -> None:
        self._families: dict[str, TrialFamily] = {}

    # -- family lifecycle -------------------------------------------------
    def freeze_family(
        self,
        family_id: str,
        hypothesis_id: str,
        protocol_hash: Optional[str] = None,
    ) -> TrialFamily:
        """Freeze a hypothesis family BEFORE any confirmatory testing."""
        fam = self._families.setdefault(
            family_id, TrialFamily(family_id=family_id, hypothesis_id=hypothesis_id)
        )
        if fam.frozen:
            raise ValueError(f"family {family_id} already frozen")
        fam.protocol_hash = protocol_hash
        fam.frozen = True
        fam.frozen_at = _now_iso()
        return fam

    def is_frozen(self, family_id: str) -> bool:
        fam = self._families.get(family_id)
        return bool(fam and fam.frozen)

    # -- trial recording --------------------------------------------------
    def record_trial(
        self,
        family_id: str,
        trial_id: str,
        parameters: dict[str, Any],
        *,
        hypothesis_id: Optional[str] = None,
        code_sha: Optional[str] = None,
        dataset_hash: Optional[str] = None,
        result_hash: Optional[str] = None,
        selected_for_followup: bool = False,
        selection_reason: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> TrialRecord:
        fam = self._families.get(family_id)
        if fam is None:
            fam = TrialFamily(
                family_id=family_id,
                hypothesis_id=hypothesis_id or family_id,
            )
            self._families[family_id] = fam

        rec = TrialRecord(
            trial_id=trial_id,
            family_id=family_id,
            hypothesis_id=hypothesis_id or fam.hypothesis_id,
            parameters=parameters,
            started_at=started_at or _now_iso(),
            completed_at=completed_at,
            code_sha=code_sha,
            dataset_hash=dataset_hash,
            result_hash=result_hash or _hash_params(parameters),
            selected_for_followup=selected_for_followup,
            selection_reason=selection_reason,
        )
        fam.trials[trial_id] = rec
        return rec

    def record_losing_trial(
        self, family_id: str, trial_id: str, parameters: dict[str, Any], **kwargs: Any
    ) -> TrialRecord:
        """Convenience: register a losing/non-selected variant (kept, not dropped)."""
        kwargs["selected_for_followup"] = False
        return self.record_trial(family_id, trial_id, parameters, **kwargs)

    def get_family(self, family_id: str) -> Optional[TrialFamily]:
        return self._families.get(family_id)

    # -- invariants -------------------------------------------------------
    def completeness_report(self, family_id: str) -> dict[str, Any]:
        """Report whether the family satisfies the trial-accounting invariant."""
        fam = self._families.get(family_id)
        if fam is None:
            return {"family_id": family_id, "frozen": False, "complete": False,
                    "reason": "family not found"}

        problems: list[str] = []
        if not fam.frozen:
            problems.append("family not frozen")
        if fam.trial_count == 0:
            problems.append("no trials recorded")
        # A complete registry must record losing variants, not only winners.
        if fam.trial_count > 0 and fam.selected_count == fam.trial_count and fam.trial_count == 1:
            problems.append("only one trial and it is selected — no losing variants recorded")
        if fam.trial_count > 1 and fam.losing_count == 0:
            problems.append("only winning/selected variants recorded")

        return {
            "family_id": family_id,
            "frozen": fam.frozen,
            "trial_count": fam.trial_count,
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
        fam = self._families.setdefault(
            family_id, TrialFamily(family_id=family_id, hypothesis_id=family_id)
        )
        # Idempotent: re-registering an existing window never resets its consumed
        # timestamp — OOS consumption is terminal.
        existing = fam.oos_windows.get(oos_window_id)
        if existing is not None:
            return existing
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
        """Mark an OOS segment consumed (it can no longer be treated as untouched)."""
        fam = self._families.get(family_id)
        if fam is None or oos_window_id not in fam.oos_windows:
            raise KeyError(f"unknown OOS window {family_id}/{oos_window_id}")
        win = fam.oos_windows[oos_window_id]
        win.oos_consumed_at = at or _now_iso()
        return win

    def oos_is_untouched(self, family_id: str, oos_window_id: str) -> bool:
        fam = self._families.get(family_id)
        if fam is None or oos_window_id not in fam.oos_windows:
            return False
        return fam.oos_windows[oos_window_id].oos_consumed_at is None
