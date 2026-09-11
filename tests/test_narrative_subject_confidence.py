#!/usr/bin/env python3
"""Two enums were being written into one column.

`narrative_subjects.confidence` accepts {CONFIRMED, CANDIDATE, UNKNOWN_LEGACY}.
The identity registry reports identity_status in {CONFIRMED,
UNRESOLVED_WITH_REASON, ...}. `subject_ref` assigned one straight into the
other.

They overlap on exactly one value — CONFIRMED — which is why this survived
review and a merge: every confirmed identity wrote fine. Measured 2026-09-11,
material_change_detector crashed on every 30-minute run for ~15 hours with

    CheckViolation: new row for relation "narrative_subjects" violates check
    constraint "narrative_subjects_confidence_ck"
    DETAIL: ... IMNM, mentioned, UNRESOLVED_WITH_REASON, cio, ...

and node 2 (materiality) produced nothing in that window: material_changes sat
at 178 rows, newest 12:30 ET, while the detector ran 30 more times.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_narrative_subjects import (  # noqa: E402
    CONFIDENCE_CANDIDATE,
    CONFIDENCE_CONFIRMED,
    CONFIDENCE_LEGACY,
    _confidence_from_identity_status,
)

# The exact vocabulary the migration's CHECK constraint allows.
ALLOWED = {"CONFIRMED", "CANDIDATE", "UNKNOWN_LEGACY"}


def test_the_value_that_actually_broke_production():
    """UNRESOLVED_WITH_REASON is the literal value from the failing row."""
    assert _confidence_from_identity_status("UNRESOLVED_WITH_REASON") == CONFIDENCE_CANDIDATE


def test_every_identity_status_maps_into_the_allowed_vocabulary():
    """No identity status, present or future, may escape the CHECK constraint.

    This is the control that would have caught the original defect: it asserts
    against the constraint's vocabulary rather than against a list of statuses
    someone remembered to enumerate.
    """
    statuses = [
        "CONFIRMED", "UNRESOLVED_WITH_REASON", "UNKNOWN_LEGACY", "UNKNOWN",
        "PENDING", "REJECTED", "", None, "  confirmed  ", "some_future_status",
    ]
    for s in statuses:
        got = _confidence_from_identity_status(s)
        assert got in ALLOWED, f"identity_status {s!r} produced {got!r}, outside {ALLOWED}"


def test_confirmed_survives_round_trip():
    """The one overlapping value must not be downgraded by the mapping."""
    assert _confidence_from_identity_status("CONFIRMED") == CONFIDENCE_CONFIRMED
    assert _confidence_from_identity_status("confirmed") == CONFIDENCE_CONFIRMED


def test_legacy_is_preserved_and_not_flattened_to_candidate():
    assert _confidence_from_identity_status("UNKNOWN_LEGACY") == CONFIDENCE_LEGACY


def test_missing_status_is_a_candidate_not_a_confirmation():
    """Absence of evidence must never present as confirmed identity."""
    assert _confidence_from_identity_status(None) == CONFIDENCE_CANDIDATE
    assert _confidence_from_identity_status("") == CONFIDENCE_CANDIDATE
