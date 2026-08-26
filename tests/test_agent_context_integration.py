"""Phase 5 — Context-aware agent integration (SHADOW-ONLY) tests.

No broker, no network, no live side effects. Deterministic only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_context_envelope import (  # noqa: E402
    RETRIEVAL_NOT_CONFIGURED,
    RETRIEVAL_OK,
    SECTION_ACTIVE_INTENT,
    SECTION_DECISION,
    SECTION_EPISODIC_MEMORY,
    SECTION_EXTERNAL_READ,
    SECTION_OFFICE_TRUTH,
    SECTION_RESEARCH_MEMORY,
    SECTION_SPECIALIST,
    build_context_envelope,
    canonical_json,
    context_envelope_digest,
    get_context_for_agent,
)
from scripts.lib.agent_context_integration import (  # noqa: E402
    CONTEXT_BUDGET_ORDER,
    MARKER_MEMORY_NOT_CONSULTED,
    MARKER_MCP_NOT_AVAILABLE,
    MARKER_RESEARCH_UNAVAILABLE,
    SPECIALIST_SCOPES,
    apply_context_budget,
    build_specialist_sub_envelope,
    record_retrieval_before_reasoning,
    shadow_compare,
)


def _base(wake_id="w1", **kw):
    return build_context_envelope(agent="alex", role="cio_synthesis", wake_id=wake_id, **kw)


def _parent():
    return _base(
        decision={"decision_id": "dec_1", "current_action": "HOLD", "act_now": False},
        office_truth={"holdings_ref": "holdings:real", "source_asof": "2026-08-16T00:00:00Z"},
        active_intent={"thesis_id": "th_1", "open_goal_ids": ["g1"]},
        episodic_memory={
            "records": [{"memory_id": "m1", "content": "operator prefers SCHD"}],
            "retrieval_status": RETRIEVAL_OK,
        },
        research_memory={"case_ids": ["c1"], "retrieval_status": RETRIEVAL_OK},
        external_read_context={"mcp_calls": ["research.search"], "availability": RETRIEVAL_OK},
    )


def _estimate(value) -> int:
    return max(1, len(canonical_json(value)) // 4)


# ── Sub-envelope scoping ───────────────────────────────────────────────────


def test_guardian_scope_excludes_research_and_external():
    sub = build_specialist_sub_envelope(_parent(), "guardian", "is risk ok?")
    assert SECTION_RESEARCH_MEMORY not in sub
    assert SECTION_EXTERNAL_READ not in sub
    assert SECTION_EPISODIC_MEMORY not in sub
    assert SECTION_SPECIALIST not in sub
    # but truth + decision + constraints are in scope
    assert SECTION_OFFICE_TRUTH in sub
    assert SECTION_DECISION in sub
    assert SECTION_ACTIVE_INTENT in sub


def test_steph_scope_includes_research_and_external():
    sub = build_specialist_sub_envelope(_parent(), "steph", "what does research say?")
    assert SECTION_RESEARCH_MEMORY in sub
    assert SECTION_EXTERNAL_READ in sub
    assert SECTION_EPISODIC_MEMORY not in sub


def test_ledger_scope_truth_only():
    sub = build_specialist_sub_envelope(_parent(), "ledger", "reconcile cash?")
    assert SECTION_OFFICE_TRUTH in sub
    assert SECTION_DECISION in sub
    assert SECTION_EPISODIC_MEMORY not in sub
    assert SECTION_RESEARCH_MEMORY not in sub
    assert SECTION_EXTERNAL_READ not in sub


def test_unknown_specialist_fail_closed():
    sub = build_specialist_sub_envelope(_parent(), "hacker", "give me everything")
    for section in (SECTION_DECISION, SECTION_OFFICE_TRUTH, SECTION_ACTIVE_INTENT,
                    SECTION_EPISODIC_MEMORY, SECTION_RESEARCH_MEMORY,
                    SECTION_EXTERNAL_READ, SECTION_SPECIALIST):
        assert section not in sub


def test_specialist_scope_does_not_pass_every_domain():
    # No specialist may receive every content domain.
    all_domains = {SECTION_DECISION, SECTION_OFFICE_TRUTH, SECTION_ACTIVE_INTENT,
                   SECTION_EPISODIC_MEMORY, SECTION_RESEARCH_MEMORY,
                   SECTION_EXTERNAL_READ, SECTION_SPECIALIST}
    for name, scope in SPECIALIST_SCOPES.items():
        assert set(scope) != all_domains, f"{name} receives every domain"


# ── Trace linkage ──────────────────────────────────────────────────────────


def test_sub_envelope_binds_parent_wake_and_trace():
    parent = _base(
        wake_id="wake_42",
        decision={"decision_id": "dec_1"},
    )
    parent["trace_id"] = "tr_parent"
    sub = build_specialist_sub_envelope(parent, "guardian", "q?")
    assert sub["parent_wake_id"] == "wake_42"
    assert sub["parent_trace_id"] == "tr_parent"
    assert sub["wake_id"] == "wake_42"


def test_sub_envelope_has_specialist_question_and_digest():
    sub = build_specialist_sub_envelope(_parent(), "guardian", "is risk ok?")
    assert sub["specialist_question"] == "is risk ok?"
    assert sub["subcontext_digest"].startswith("ctx_")
    # distinct questions -> distinct subcontext digests
    sub2 = build_specialist_sub_envelope(_parent(), "guardian", "another question?")
    assert sub["subcontext_digest"] != sub2["subcontext_digest"]


def test_sub_envelope_does_not_mutate_parent():
    parent = _parent()
    original = canonical_json(parent)
    build_specialist_sub_envelope(parent, "guardian", "q?")
    assert canonical_json(parent) == original


# ── Retrieval status recorded before reasoning ─────────────────────────────


def test_retrieval_marks_memory_not_consulted_when_no_provider():
    env = get_context_for_agent(agent="alex", wake={"wake_id": "w1"})
    assert env["episodic_memory"]["retrieval_status"] == RETRIEVAL_NOT_CONFIGURED
    audited = record_retrieval_before_reasoning(env)
    assert audited["episodic_memory"]["retrieval_marker"] == MARKER_MEMORY_NOT_CONSULTED
    assert MARKER_MEMORY_NOT_CONSULTED in audited["retrieval_audit"]["markers"]
    assert audited["retrieval_audit"]["phase"] == "BEFORE_REASONING"


def test_retrieval_does_not_pretend_full_context():
    env = get_context_for_agent(agent="alex", wake={"wake_id": "w1"})
    audited = record_retrieval_before_reasoning(env)
    assert audited["retrieval_audit"]["full_context_available"] is False
    # all three sources unavailable in a provider-less envelope
    markers = set(audited["retrieval_audit"]["markers"])
    assert MARKER_MEMORY_NOT_CONSULTED in markers
    assert MARKER_RESEARCH_UNAVAILABLE in markers
    assert MARKER_MCP_NOT_AVAILABLE in markers


def test_retrieval_full_context_when_all_present():
    env = _parent()
    audited = record_retrieval_before_reasoning(env)
    assert audited["retrieval_audit"]["full_context_available"] is True
    assert audited["retrieval_audit"]["markers"] == []


def test_retrieval_is_non_mutating():
    env = _parent()
    original = canonical_json(env)
    record_retrieval_before_reasoning(env)
    assert canonical_json(env) == original


# ── Budget truncation ──────────────────────────────────────────────────────


def test_budget_drops_lowest_priority_first_and_never_truth():
    env = _parent()
    budgeted, meta = apply_context_budget(env, 0)
    # lowest priority (external read) dropped first; truth never dropped
    assert meta["dropped_sections"][0] == SECTION_EXTERNAL_READ
    assert SECTION_OFFICE_TRUTH not in meta["dropped_sections"]
    assert meta["canonical_truth_preserved"] is True
    # canonical truth content still present, not a stub
    assert budgeted[SECTION_OFFICE_TRUTH] == env[SECTION_OFFICE_TRUTH]
    assert SECTION_OFFICE_TRUTH in budgeted
    assert budgeted[SECTION_OFFICE_TRUTH].get("holdings_ref") == "holdings:real"


def test_budget_records_truncation_metadata():
    env = _parent()
    budgeted, meta = apply_context_budget(env, 0)
    assert meta["budget_tokens"] == 0
    assert meta["original_tokens"] > 0
    assert meta["final_tokens"] <= meta["original_tokens"]
    assert isinstance(meta["dropped_sections"], list)
    assert meta["dropped_sections"]
    assert any(d["action"] == "dropped_section" for d in meta["details"])
    assert meta["authority"] == "READ_ONLY_ADVISORY"


def test_budget_drops_low_confidence_memory_first():
    truth = {"holdings_ref": "h:1", "source_asof": "2026-08-16T00:00:00Z"}
    decision = {"decision_id": "d1"}
    active_intent = {}
    high_conf = {"memory_id": "m_hi", "content": "operator prefers SCHD", "confidence": 0.9}
    low_conf = {"memory_id": "m_lo", "content": "x" * 20000, "confidence": 0.1}
    env = build_context_envelope(
        agent="alex",
        role="cio_synthesis",
        wake_id="w1",
        office_truth=truth,
        decision=decision,
        active_intent=active_intent,
        episodic_memory={
            "records": [high_conf, low_conf],
            "memory_ids": ["m_hi", "m_lo"],
            "retrieval_status": RETRIEVAL_OK,
        },
        research_memory={},
        external_read_context={},
    )

    # Compute the budget from the *actual* merged sections so the estimate
    # matches what apply_context_budget will measure. We target "everything
    # except external read + research + the low-confidence record".
    episodic_section = env[SECTION_EPISODIC_MEMORY]
    episodic_after = dict(episodic_section)
    episodic_after["records"] = [high_conf]
    episodic_after["memory_ids"] = ["m_hi"]
    episodic_after["low_confidence_dropped"] = ["m_lo"]
    episodic_after["budget_low_confidence_truncated"] = True
    budget = (
        _estimate(env[SECTION_OFFICE_TRUTH])
        + _estimate(env[SECTION_DECISION])
        + _estimate(env[SECTION_ACTIVE_INTENT])
        + _estimate(episodic_after)
        + 20
    )

    budgeted, meta = apply_context_budget(env, budget)
    assert "m_lo" in meta["memory_low_confidence_dropped"]
    # the high-confidence (operator explicit) record is retained
    assert SECTION_EPISODIC_MEMORY in budgeted
    assert not budgeted[SECTION_EPISODIC_MEMORY].get("budget_truncated")
    kept_ids = [r["memory_id"] for r in budgeted[SECTION_EPISODIC_MEMORY]["records"]]
    assert kept_ids == ["m_hi"]
    # canonical truth is intact
    assert budgeted[SECTION_OFFICE_TRUTH]["holdings_ref"] == "h:1"


def test_budget_under_limit_no_truncation():
    env = _parent()
    budgeted, meta = apply_context_budget(env, 10 ** 9)
    assert meta["within_budget"] is True
    assert meta["dropped_sections"] == []
    assert meta["memory_low_confidence_dropped"] == []


# ── Shadow compare ─────────────────────────────────────────────────────────


def test_shadow_compare_detects_action_change():
    base = {"current_action": "HOLD", "act_now": False}
    aug = {"current_action": "ACT_NOW", "act_now": True}
    report = shadow_compare(base, aug)
    assert report["same"] is False
    assert report["action_changed"] is True
    assert any("action changed" in w for w in report["why"])


def test_shadow_compare_same_action():
    base = {"current_action": "HOLD", "act_now": False}
    aug = {"current_action": "HOLD", "act_now": False}
    report = shadow_compare(base, aug)
    assert report["same"] is True
    assert report["action_changed"] is False


def test_shadow_compare_explicit_memory_mcp_specialists():
    base = {
        "current_action": "HOLD",
        "act_now": False,
        "memory_ids_used": ["m1"],
        "mcp_context_used": ["portfolio.get_cash_snapshot"],
        "specialists": ["guardian"],
    }
    aug = {
        "current_action": "HOLD",
        "act_now": False,
        "memory_ids_used": ["m1", "m2"],
        "mcp_context_used": ["portfolio.get_cash_snapshot", "research.search"],
        "specialists": ["guardian", "steph"],
    }
    report = shadow_compare(base, aug)
    assert report["same"] is True  # action unchanged even though context grew
    assert report["memory_ids_used"]["added"] == ["m2"]
    assert report["mcp_context_used"]["added"] == ["research.search"]
    assert report["specialists_changed"]["added"] == ["steph"]
    assert report["memory_ids_used"]["changed"] is True
    assert report["mcp_context_used"]["changed"] is True
    assert report["specialists_changed"]["changed"] is True
    assert any("m2" in w for w in report["why"])


def test_shadow_compare_notification_and_follow_up_changed():
    base = {"current_action": "WAIT", "notification": {"send": False}, "follow_up": {"kind": "TIME"}}
    aug = {"current_action": "WAIT", "notification": {"send": True}, "follow_up": {"kind": "CONDITION"}}
    report = shadow_compare(base, aug)
    assert report["notification_changed"] is True
    assert report["follow_up_changed"] is True
    assert report["same"] is True


def test_shadow_compare_empty_inputs():
    report = shadow_compare({}, {})
    assert report["same"] is True
    assert report["action_changed"] is False
    assert report["why"] == ["no material difference"]


# ── No unauthorized capability ─────────────────────────────────────────────

_FORBIDDEN_CAPABILITIES = {"broker", "order", "trade", "write", "stop", "2fa", "risk_policy"}


def _assert_no_write_capability(env):
    gov = env.get("governance")
    assert isinstance(gov, dict)
    assert gov.get("authority") == "READ_ONLY_ADVISORY"
    permitted = gov.get("permitted_capabilities") or []
    for cap in permitted:
        lowered = str(cap).lower()
        for forbidden in _FORBIDDEN_CAPABILITIES:
            assert forbidden not in lowered, f"forbidden capability {forbidden!r} permitted"


def test_no_unauthorized_capability_across_envelopes():
    parent = _parent()
    sub = build_specialist_sub_envelope(parent, "guardian", "q?")
    budgeted, _ = apply_context_budget(parent, 0)
    audited = record_retrieval_before_reasoning(parent)

    _assert_no_write_capability(parent)
    _assert_no_write_capability(sub)
    _assert_no_write_capability(budgeted)
    _assert_no_write_capability(audited)


def test_context_budget_order_starts_with_canonical_truth():
    assert CONTEXT_BUDGET_ORDER[0] == SECTION_OFFICE_TRUTH
    assert SECTION_EXTERNAL_READ == CONTEXT_BUDGET_ORDER[-1]
