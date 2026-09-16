"""A validator that has never disagreed is not a control — prove it, per mechanism.

Measured 2026-09-16, before this change: ``independent_critic`` 31/31 accept with zero
disagreements; ``agent_view_v1.critic_pass`` 346/346 True with ``critique_id`` None and
``critic_notes`` ``[]``; ``research_quality.critique()`` 608 completions with zero FAILED
and both passing verdicts accepted, so the gate had never blocked anything;
``StructuralGoldenJudge`` returning literals on most of its rubric. Four validators, none
of which had ever contested anything, all reported as working.

Each test below fails if its guarantee is removed. Every one also carries a positive
control where the shape permits, because a detector that cannot be seen to fire is
indistinguishable from a detector that never fires — the same premise as the repo's
``alarm_capture`` negative controls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.validator_calibration import (  # noqa: E402
    BLIND,
    CALIBRATED,
    DOWNGRADE_STATE,
    MIN_SAMPLE,
    NOT_YET_MEASURED,
    UNCALIBRATED,
    Observation,
    SeededKnownBad,
    assess,
    day_one_calibration,
    downgrade_verdict,
    load_known_bad_probes,
    observations_from_counts,
    observe_known_bad,
    seeded_probe_due,
    verdict_is_passing,
    zero_variance_axes,
)

# No COVERS: this module sends nothing. It is a pure calculation over observations, and
# claiming an alarm site here would inflate the firing-coverage number without testing one.
COVERS = []

VALIDATOR = "lane_under_test"


def _live_window(n: int = 40, disagreements: int = 8, **kwargs) -> list[Observation]:
    """A window that WOULD calibrate: enough samples, and it argues sometimes."""
    return list(observations_from_counts(VALIDATOR, total=n, disagreements=disagreements, **kwargs))


# --------------------------------------------------------------- mechanism (ii)


def test_a_validator_that_passes_a_seeded_known_bad_is_blind_and_its_window_is_voided():
    probe = SeededKnownBad(probe_id="shadow-bad-001", payload={"defect": "quarantine_case"})
    window = _live_window()
    window.append(observe_known_bad(VALIDATOR, probe, "PASS"))

    verdict = assess(VALIDATOR, window)

    assert verdict.state == BLIND
    assert verdict.window_voided is True
    assert verdict.seeded_known_bads_passed == 1
    assert verdict.permits_certification is False
    assert any("PASSED_SEEDED_KNOWN_BAD" in r for r in verdict.reasons)
    # The 40 real observations either side of the miss prove nothing: the instrument was
    # not measuring while it produced them.
    assert "shadow-bad-001" in verdict.evidence["missed_known_bad_ids"]


def test_positive_control_a_validator_that_catches_the_known_bad_keeps_its_window():
    """Without this, BLIND could be unreachable-in-practice and the test above vacuous."""
    probe = SeededKnownBad(probe_id="shadow-bad-002", payload={"defect": "quarantine_case"})
    window = _live_window()
    window.append(observe_known_bad(VALIDATOR, probe, "REJECT"))

    verdict = assess(VALIDATOR, window)

    assert verdict.state == CALIBRATED
    assert verdict.window_voided is False
    assert verdict.seeded_known_bads == 1
    assert verdict.seeded_known_bads_passed == 0


def test_the_seeded_probe_is_due_one_in_twenty():
    assert [n for n in range(1, 61) if seeded_probe_due(n)] == [20, 40, 60]
    with pytest.raises(ValueError):
        seeded_probe_due(20, every=0)


def test_the_known_bad_corpus_the_repo_already_ships_is_what_gets_seeded():
    """Reuses tests/fixtures/shadow_acceptance/known_bad.json — no second scheme."""
    probes = load_known_bad_probes()
    assert len(probes) >= 20, "packet D requires 20 known-bad fixtures; this reuses them"
    probe = probes[0]
    assert probe.judge("PASS") is True  # passing a known-bad is the blindness signal
    assert probe.judge("REJECT") is False


# ---------------------------------------------------------------- mechanism (i)


def test_the_day_one_baselines_are_all_uncalibrated_by_their_own_numbers():
    """No new measurement convicts them — their own counts do."""
    verdicts = day_one_calibration()

    assert set(verdicts) == {
        "independent_critic",
        "agent_view_critic_pass",
        "research_quality_critique",
    }
    for name, expected_n in (
        ("independent_critic", 31),  # 31/31 accept
        ("agent_view_critic_pass", 346),  # 346/346 True
        ("research_quality_critique", 608),  # 608 completions, zero FAILED
    ):
        verdict = verdicts[name]
        assert verdict.state == UNCALIBRATED, (name, verdict.state)
        assert verdict.n == expected_n
        assert verdict.disagreements == 0
        assert verdict.disagreement_rate == 0.0
        assert verdict.permits_certification is False
        assert any("NO_DISAGREEMENT_IN_WINDOW" in r for r in verdict.reasons)
        assert verdict.evidence["corpus"]


def test_zero_disagreements_only_convicts_once_the_sample_is_large_enough():
    short = assess(VALIDATOR, _live_window(n=MIN_SAMPLE - 1, disagreements=0))
    assert short.state == NOT_YET_MEASURED  # not a pass, and not yet a conviction
    assert short.permits_certification is False

    at_floor = assess(VALIDATOR, _live_window(n=MIN_SAMPLE, disagreements=0))
    assert at_floor.state == UNCALIBRATED


def test_an_empty_window_is_not_a_pass():
    verdict = assess(VALIDATOR, [])
    assert verdict.state == NOT_YET_MEASURED
    assert verdict.permits_certification is False
    assert verdict.disagreement_rate is None  # never a fabricated 0.0


def test_an_uncalibrated_validator_may_only_say_it_does_not_know():
    uncalibrated = assess(VALIDATOR, _live_window(disagreements=0))
    verdict, reasons = downgrade_verdict("PASS", uncalibrated)
    assert verdict == DOWNGRADE_STATE
    assert reasons and "UNCALIBRATED" in reasons[0]

    # It may not say REJECT either: an instrument that cannot be trusted to agree cannot
    # be trusted to refuse.
    assert downgrade_verdict("REJECT", uncalibrated)[0] == DOWNGRADE_STATE

    calibrated = assess(VALIDATOR, _live_window())
    assert downgrade_verdict("PASS", calibrated) == ("PASS", ())


# -------------------------------------------------------------- mechanism (iii)


def test_a_constant_score_axis_is_not_a_measurement():
    """The StructuralGoldenJudge shape: grounding always 4, calibration always 3."""
    window = [
        Observation(
            VALIDATOR,
            "PASS",
            disagreed=(i % 5 == 0),
            scores={
                "coverage": float(1 + (i % 5)),  # moves
                "grounding": 4.0,  # hardcoded literal
                "calibration": 3.0,  # hardcoded literal
            },
        )
        for i in range(MIN_SAMPLE + 5)
    ]

    assert zero_variance_axes(window) == ("calibration", "grounding")

    verdict = assess(VALIDATOR, window)
    assert verdict.state == UNCALIBRATED  # despite disagreeing often enough
    assert verdict.constant_axes == ("calibration", "grounding")
    assert any("ZERO_SCORE_VARIANCE" in r for r in verdict.reasons)


def test_positive_control_axes_that_move_are_not_flagged():
    window = [
        Observation(
            VALIDATOR,
            "PASS",
            disagreed=(i % 5 == 0),
            scores={
                "coverage": float(1 + (i % 5)),
                "grounding": float(1 + (i % 3)),
            },
        )
        for i in range(MIN_SAMPLE + 5)
    ]
    assert zero_variance_axes(window) == ()
    assert assess(VALIDATOR, window).state == CALIBRATED


def test_one_score_vector_cannot_show_variance_and_is_not_convicted_of_lacking_it():
    assert zero_variance_axes([Observation(VALIDATOR, "PASS", scores={"coverage": 3.0})]) == ()


def test_each_validators_own_pass_vocabulary_is_understood():
    # The four live validators speak four different languages for "let it through".
    assert verdict_is_passing(True) is True  # agent_view_v1.critic_pass
    assert verdict_is_passing("accept") is True  # independent_critic
    assert verdict_is_passing("VALID") is True  # research_quality
    assert verdict_is_passing("PARTIAL") is True  # research_quality: also accepted
    assert verdict_is_passing("PASS") is True  # CriticPanel
    assert verdict_is_passing(False) is False
    assert verdict_is_passing("REJECT") is False
    assert verdict_is_passing("FAILED") is False
    assert verdict_is_passing("INSUFFICIENT_EVIDENCE") is False


def test_a_known_bad_result_cannot_be_recorded_as_an_ordinary_observation():
    with pytest.raises(ValueError):
        Observation(VALIDATOR, "PASS", known_bad_passed=True)  # not marked seeded
    with pytest.raises(ValueError):
        Observation("", "PASS")
