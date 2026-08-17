"""Phase 6 — durable follow-up binding + proactive advisory message tests.

No broker, no network. Deterministic only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_followup import (  # noqa: E402
    build_durable_next_review,
    compose_advisory_message,
    reopen_after_reject,
    validate_durable_next_review,
)
from scripts.lib.agent_notification_intelligence import (  # noqa: E402
    NEXT_REVIEW_UNAVAILABLE,
)


# ── Notification policy: unchanged replay suppression + reject re-open ─────


def test_unchanged_hold_cash_replay_suppressed():
    # HOLD_CASH replay: identical identity + evidence, prior operator REJECT.
    assert reopen_after_reject("REJECT", same_identity=True, same_evidence=True) == "SUPPRESS"


def test_unchanged_reentry_wait_suppressed():
    # REENTRY WAIT replay: identical identity + evidence, prior operator ACK.
    assert reopen_after_reject("ACK", same_identity=True, same_evidence=True) == "SUPPRESS"


def test_unchanged_rejected_schd_generation_suppressed():
    # Rejected SCHD generation replayed unchanged (REJECT and DONE both suppress).
    assert reopen_after_reject("REJECT", same_identity=True, same_evidence=True) == "SUPPRESS"
    assert reopen_after_reject("DONE", same_identity=True, same_evidence=True) == "SUPPRESS"


def test_all_suppressing_dispositions_suppress_unchanged():
    for disp in ("REJECT", "ACK", "DONE"):
        assert reopen_after_reject(disp, True, True) == "SUPPRESS"


def test_new_schd_evidence_reopens():
    # Same SCHD decision but a changed evidence digest reopens a prior REJECT.
    assert (
        reopen_after_reject("REJECT", same_identity=True, same_evidence=False)
        == "WHAT CHANGED SINCE YOUR REJECT"
    )


def test_no_prior_reject_allows():
    assert reopen_after_reject(None, True, True) == "ALLOW"
    # New identity (different recommendation) is not a replay.
    assert reopen_after_reject("REJECT", False, True) == "ALLOW"


def test_new_identity_with_changed_evidence_allows():
    # Regression: a NEW recommendation identity with changed evidence must be
    # ALLOW, never "WHAT CHANGED SINCE YOUR REJECT" — that label is reserved
    # for the SAME recommendation whose evidence changed.
    assert reopen_after_reject("REJECT", same_identity=False, same_evidence=False) == "ALLOW"


# ── Durable next review ────────────────────────────────────────────────────


def test_durable_next_review_time_valid():
    nr = build_durable_next_review(
        "WAIT",
        kind="TIME",
        due_at="2026-08-18T00:00:00Z",
        revisit_id="rv_1",
    )
    ok, reason = validate_durable_next_review(nr)
    assert ok, reason
    assert nr["kind"] == "TIME"
    assert nr["due_at"] == "2026-08-18T00:00:00Z"


def test_durable_next_review_condition_valid():
    nr = build_durable_next_review(
        "DEFER",
        kind="CONDITION",
        condition="cash_band_rebalanced",
        lineage="ln_1",
    )
    ok, reason = validate_durable_next_review(nr)
    assert ok, reason


def test_durable_next_review_auto_revisit_id():
    nr = build_durable_next_review("RESEARCH", kind="EVENT", condition="earnings_reported")
    ok, reason = validate_durable_next_review(nr)
    assert ok, reason
    assert nr["revisit_id"].startswith("rv_")


def test_bare_next_review_rejected():
    ok, reason = validate_durable_next_review({})
    assert not ok
    assert "kind missing" in reason


def test_non_dict_next_review_rejected():
    ok, reason = validate_durable_next_review("NEXT REVIEW")
    assert not ok


def test_next_review_unavailable_with_reason_valid():
    nr = {"kind": NEXT_REVIEW_UNAVAILABLE, "reason": "no reliable schedule source"}
    ok, reason = validate_durable_next_review(nr)
    assert ok, reason


def test_next_review_unavailable_without_reason_rejected():
    ok, reason = validate_durable_next_review({"kind": NEXT_REVIEW_UNAVAILABLE})
    assert not ok


def test_time_without_due_at_rejected():
    ok, reason = validate_durable_next_review({"kind": "TIME", "revisit_id": "rv_1"})
    assert not ok
    assert "due_at" in reason


def test_condition_without_descriptor_rejected():
    ok, reason = validate_durable_next_review({"kind": "CONDITION", "revisit_id": "rv_1"})
    assert not ok


def test_bound_without_revisit_id_or_lineage_rejected():
    ok, reason = validate_durable_next_review({"kind": "TIME", "due_at": "2026-08-18T00:00:00Z"})
    assert not ok


def test_unknown_kind_rejected():
    ok, reason = validate_durable_next_review({"kind": "SOMEDAY", "revisit_id": "rv_1"})
    assert not ok


def test_build_non_action_rejects_bare_kind():
    with pytest.raises(ValueError):
        build_durable_next_review("WAIT", kind=None)


def test_build_non_action_rejects_wrong_kind():
    with pytest.raises(ValueError):
        build_durable_next_review("REVALIDATE", kind="SOMEDAY")


def test_build_unavailable_requires_reason():
    with pytest.raises(ValueError):
        build_durable_next_review("WAIT", kind=NEXT_REVIEW_UNAVAILABLE)


def test_build_unavailable_with_reason():
    nr = build_durable_next_review(
        "DATA_UNAVAILABLE",
        kind=NEXT_REVIEW_UNAVAILABLE,
        unavailable_reason="feed offline",
    )
    assert nr["kind"] == NEXT_REVIEW_UNAVAILABLE
    ok, reason = validate_durable_next_review(nr)
    assert ok, reason


# ── Proactive advisory message ─────────────────────────────────────────────


def test_advisory_message_required_sections():
    msg = compose_advisory_message(
        what_changed="cash band moved",
        current_action="WAIT",
        why="waiting for rebalance",
    )
    assert "WHAT CHANGED" in msg
    assert "MY CURRENT ACTION" in msg
    assert "WHY" in msg


def test_advisory_message_includes_memory_only_when_provided():
    with_memory = compose_advisory_message(
        what_changed="cash band moved",
        current_action="WAIT",
        why="waiting for rebalance",
        memory_view="operator prefers SCHD as income anchor",
    )
    assert "MEMORY-PRIOR-OPERATOR-VIEW" in with_memory
    assert "operator prefers SCHD" in with_memory

    without_memory = compose_advisory_message(
        what_changed="cash band moved",
        current_action="WAIT",
        why="waiting for rebalance",
    )
    assert "MEMORY-PRIOR-OPERATOR-VIEW" not in without_memory
    assert "MEMORY" not in without_memory


def test_advisory_message_empty_memory_omitted():
    msg = compose_advisory_message(
        what_changed="cash band moved",
        current_action="WAIT",
        why="waiting for rebalance",
        memory_view="",
    )
    assert "MEMORY-PRIOR-OPERATOR-VIEW" not in msg
    assert "MEMORY" not in msg


def test_advisory_message_optional_sections():
    msg = compose_advisory_message(
        what_changed="cash band moved",
        current_action="WAIT",
        why="waiting for rebalance",
        counter_thesis="rebalance may not trigger this cycle",
        changes_my_mind="cash returns to target band",
        next_review={"kind": "TIME", "due_at": "2026-08-18T00:00:00Z", "revisit_id": "rv_1"},
    )
    assert "COUNTER-THESIS" in msg
    assert "WHAT CHANGES MY MIND" in msg
    assert "NEXT REVIEW" in msg
