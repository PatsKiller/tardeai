"""A calibration tier is earned on outcomes that can be right or wrong — never on `hold`.

LQ-20261107-48, 2026-11-07. ``agent_calibration_windows`` for maria read, on 2026-11-01:

    recommendations 653 | resolved 506 | correct 0 | incorrect 0 | neutral 506
    accuracy 0.0 | sample_size_status proposal_allowed

``aggregate_windows`` counted every outcome except ``unresolved``/``relist_neutral`` as
``resolved``, including ``neutral``. A neutral is not a claim that can be scored: it is a
``hold`` recommendation, or a proposal that was rejected. maria emitted ``hold`` 4560 times
in 30 days and the engine graded almost all of it ``neutral`` — so 506 "resolved", 0
graded, and a promotion to ``proposal_allowed`` (the tier that says the agent's record is
large enough to act on) with no accuracy evidence at all.

The tier and the accuracy denominator now use ``graded = correct + incorrect +
partially_correct``. ``resolved`` stays as the count of outcomes whose end state is known.

Hermetic: pure function, no DB, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_calibration_engine as ace   # noqa: E402


def _event(outcome, agent="maria", score=None):
    return {"agent_name": agent, "actual_outcome": outcome, "predicted_confidence": 0.6,
            "outcome_score": score, "calibration_error": None, "overconfidence": None,
            "underconfidence": None, "r_multiple": None}


def _window(events, agent="maria"):
    windows = ace.aggregate_windows(events, window_days=90)
    rows = [w for w in windows if w["agent_name"] == agent]
    assert len(rows) == 1
    return rows[0]


def test_a_neutral_flood_does_not_earn_a_tier():
    """506 neutral outcomes: the exact maria window — insight_only, accuracy unknown."""
    w = _window([_event("neutral") for _ in range(506)])
    assert w["resolved"] == 506 and w["neutral"] == 506 and w["graded"] == 0
    assert w["sample_size_status"] == "insight_only"
    assert w["accuracy"] is None, "0 correct of 0 graded is not an accuracy of 0.0"


def test_neutral_does_not_count_towards_the_promotion_threshold():
    # 99 graded + 1500 neutral: still below the shadow threshold on evidence.
    events = [_event("correct") for _ in range(99)] + [_event("neutral") for _ in range(1500)]
    w = _window(events)
    assert w["resolved"] == 1599 and w["graded"] == 99
    assert w["sample_size_status"] == "shadow_only"


def test_graded_outcomes_earn_the_tier():
    events = [_event("correct") for _ in range(120)]
    w = _window(events)
    assert w["graded"] == 120 and w["sample_size_status"] == "proposal_allowed"
    assert w["accuracy"] == 1.0


def test_accuracy_denominator_is_graded_not_resolved():
    events = [_event("correct") for _ in range(10)] + [_event("neutral") for _ in range(10)]
    w = _window(events)
    assert w["accuracy"] == 1.0, "10 of 10 graded outcomes were correct"


def test_incorrect_and_partial_both_count_as_graded():
    events = (_event("correct") for _ in range(8))
    events = list(events) + [_event("incorrect") for _ in range(2)] \
        + [_event("partially_correct") for _ in range(2)]
    w = _window(events)
    assert w["graded"] == 12
    assert w["accuracy"] == round(8 / 12, 4)


def test_unresolved_and_relist_neutral_stay_out_of_every_count():
    events = [_event("correct") for _ in range(30)] + [_event("unresolved") for _ in range(5)] \
        + [_event("relist_neutral") for _ in range(5)]
    w = _window(events)
    assert w["graded"] == 30 and w["resolved"] == 30 and w["unresolved"] == 5
    assert w["sample_size_status"] == "shadow_only"
