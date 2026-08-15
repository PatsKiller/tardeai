"""Research governance — enums + models + protocol immutability tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance.enums import (  # noqa: E402
    EvidenceGrade,
    EvidenceType,
    GateState,
    ResearchStatus,
    TERMINAL_STATUSES,
)
from scripts.lib.research_governance.models import (  # noqa: E402
    ResearchHypothesis,
    TrialRecord,
)


def test_three_dimensions_are_distinct():
    assert EvidenceType.SEASONALITY.value != ResearchStatus.OOS_SUPPORTED.value
    assert ResearchStatus.OOS_SUPPORTED.value != EvidenceGrade.B.value
    assert EvidenceGrade.B.value != EvidenceType.SEASONALITY.value


def test_gate_state_has_both_not_applicable_and_not_in_scope():
    assert GateState.NOT_APPLICABLE.value == "NOT_APPLICABLE"
    assert GateState.NOT_IN_SCOPE.value == "NOT_IN_SCOPE"
    assert GateState.NOT_APPLICABLE.value != GateState.PASS.value


def test_terminal_statuses_include_all_dispositions():
    assert TERMINAL_STATUSES >= {"COMPLETED", "INVALID", "CANCELED_WITH_REASON", "FAILED"}


def test_trial_record_is_frozen_dataclass():
    rec = TrialRecord(trial_id="t", config_hash="c", result_hash="r", terminal_status="COMPLETED")
    with pytest.raises(Exception):
        rec.result_hash = "changed"  # frozen dataclass => FrozenInstanceError


def test_compute_protocol_hash_does_not_mutate():
    h = ResearchHypothesis(hypothesis_id="h1", signal_definition="sig")
    before = h.protocol_hash
    assert before is None
    h.compute_protocol_hash()
    # compute_protocol_hash is a pure function; it must not set protocol_hash.
    assert h.protocol_hash is None


def test_frozen_snapshot_immutable_and_binds_hash():
    h = ResearchHypothesis(hypothesis_id="h1", signal_definition="sig", universe="SPX")
    snap = h.freeze()
    assert snap.protocol_hash
    h.universe = "NDX"  # mutate the ORIGINAL after freezing
    snap2 = h.freeze()
    assert snap.protocol_hash != snap2.protocol_hash  # mutation changes hash
    # The first snapshot is immutable and unchanged.
    assert snap.universe == "SPX"
