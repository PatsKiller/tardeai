"""Phase 6 — wake trigger taxonomy + autonomous action classification tests.

No broker, no network. Deterministic only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_wake_taxonomy import (  # noqa: E402
    AUTONOMOUS_ALLOWED_ACTIONS,
    AUTONOMOUS_DENIED_ACTIONS,
    WAKE_TRIGGERS,
    allowed_autonomous_action,
    canonicalize_wake_trigger,
    is_followup_wake,
    is_material_wake,
)


# ── Canonical trigger set ──────────────────────────────────────────────────


def test_wake_triggers_exact_set():
    expected = {
        "POSITION_OPENED",
        "POSITION_CLOSED",
        "POSITION_SIZE_CHANGED_MATERIAL",
        "CASH_BAND_CHANGED",
        "CASH_USE_BECAME_ELIGIBLE",
        "REENTRY_STATE_CHANGED",
        "REENTRY_ELIGIBILITY_CHANGED",
        "RISK_STATE_CHANGED",
        "RESEARCH_DECISION_USE_CHANGED",
        "FRESHNESS_CHANGED",
        "DEFER_DUE",
        "FOLLOW_UP_DUE",
        "OPERATOR_CHALLENGE_OPENED",
        "OPERATOR_CHALLENGE_REVIEWABLE",
        "OUTCOME_MATURED",
        "LESSON_CANDIDATE_CREATED",
    }
    assert set(WAKE_TRIGGERS) == expected
    assert len(WAKE_TRIGGERS) == 16


def test_every_canonical_trigger_self():
    for t in WAKE_TRIGGERS:
        assert canonicalize_wake_trigger(t) == t


# ── Alias normalization ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("position_opened", "POSITION_OPENED"),
        ("Position Opened", "POSITION_OPENED"),
        ("position-opened", "POSITION_OPENED"),
        ("POSITION OPENED", "POSITION_OPENED"),
        ("positionopened", "POSITION_OPENED"),
        ("cash band changed", "CASH_BAND_CHANGED"),
        ("cash_band_crossed", "CASH_BAND_CHANGED"),
        ("follow-up due", "FOLLOW_UP_DUE"),
        ("followup_due", "FOLLOW_UP_DUE"),
        ("risk-state-changed", "RISK_STATE_CHANGED"),
        ("operator challenge opened", "OPERATOR_CHALLENGE_OPENED"),
    ],
)
def test_alias_normalization(raw, expected):
    assert canonicalize_wake_trigger(raw) == expected


# ── Unknown triggers ───────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["", "NOT_A_TRIGGER", "TRADE_NOW", "bogus", None])
def test_unknown_trigger_none(raw):
    assert canonicalize_wake_trigger(raw) is None


# ── Material vs follow-up wakes ────────────────────────────────────────────


def test_followup_wakes():
    assert is_followup_wake("FOLLOW_UP_DUE")
    assert is_followup_wake("DEFER_DUE")
    assert is_followup_wake("defer_due")
    assert not is_followup_wake("POSITION_OPENED")


def test_material_wakes():
    assert is_material_wake("POSITION_OPENED")
    assert is_material_wake("RISK_STATE_CHANGED")
    assert is_material_wake("cash_band_changed")
    assert not is_material_wake("FOLLOW_UP_DUE")
    assert not is_material_wake("DEFER_DUE")
    assert not is_material_wake("bogus")


# ── Autonomous action classification ───────────────────────────────────────


def test_action_sets_disjoint():
    assert not (set(AUTONOMOUS_ALLOWED_ACTIONS) & set(AUTONOMOUS_DENIED_ACTIONS))


def test_allowed_actions():
    for a in [
        "LOAD_VERIFIED_TRUTH",
        "load truth",
        "load-truth",
        "SEARCH_INTERNAL_RESEARCH",
        "retrieve memory",
        "retrieve-memory",
        "USE_READ_ONLY_MCP",
        "read-only-mcp",
        "use read only mcp",
        "delegate",
        "delegate bounded specialist question",
        "CREATE_UPDATE_ADVISORY_CASE",
        "create advisory case",
        "schedule revisit",
        "schedule-revisit",
        "PREPARE_NOTIFICATION",
        "prepare notification",
    ]:
        ok, reason = allowed_autonomous_action(a)
        assert ok, (a, reason)


def test_denied_actions():
    for a in [
        "TRADE",
        "trade",
        "MODIFY_RISK_POLICY",
        "risk policy",
        "risk-policy",
        "MUTATE_BROKER_AUTH",
        "broker-auth",
        "PROMOTE_LEARNED_RULES",
        "promote rules",
        "promote-rules",
        "EDIT_EXTERNAL_DOCS_CALENDAR",
        "edit external docs",
        "SEND_ARBITRARY_EMAIL",
        "send arbitrary email",
    ]:
        ok, reason = allowed_autonomous_action(a)
        assert not ok, (a, reason)


def test_unknown_action_fail_closed():
    ok, reason = allowed_autonomous_action("hack the mainframe")
    assert not ok
    assert "unrecognized" in reason


def test_none_action_fail_closed():
    ok, reason = allowed_autonomous_action(None)  # type: ignore[arg-type]
    assert not ok
