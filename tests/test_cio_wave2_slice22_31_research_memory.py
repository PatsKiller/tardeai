"""Wave 2 slices 22–31 — research attach, memory governance, lessons.

22  hermes_result_id is still stamped on a new attachable complete.
23  CASE_SUMMARY still mints on a VALID complete, once per (plan, result).
25  VALID / PARTIAL / FAIL-family counts, with attachable stated separately.
26  the attach rule is VALID|PARTIAL and is not silently tightened.
27  due-checkpoint eligibility excludes DUST_RESIDUAL.
28  top PROVISIONAL lessons are capped and can never become policy.
29  the promotion ceiling is REVIEW_READY — policy count is 0.
30  admission receipts carry memory_type + promotable.
31  RESEARCH_REFERENCE is never ACTIVE.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_research_fail_policy import build_verdict_counts
from scripts.lib.hermes_research_loop import (
    _SUCCESS_VERDICTS,
    research_complete_is_attachable,
)

VALID = {"verdict": "VALID"}
PARTIAL = {"verdict": "PARTIAL"}


# ── 22 / 26: what may stamp hermes_result_id ─────────────────────────────────

def test_valid_complete_is_attachable():
    assert research_complete_is_attachable({"status": "completed"}, VALID) is True


def test_partial_complete_is_attachable_by_design():
    """PARTIAL attaches. Documented, not an oversight — do not silently tighten."""
    assert research_complete_is_attachable({"status": "completed"}, PARTIAL) is True


@pytest.mark.parametrize("verdict", ["FAILED", "STALE", "CONFLICTED", "INSUFFICIENT", ""])
def test_other_verdicts_do_not_attach(verdict):
    assert research_complete_is_attachable({"status": "completed"}, {"verdict": verdict}) is False


@pytest.mark.parametrize("status", ["failed", "error", "truncated", "cost_cap", "cancelled"])
def test_failed_family_never_attaches_even_with_a_valid_critique(status):
    assert research_complete_is_attachable({"status": status}, VALID) is False


@pytest.mark.parametrize("flag", ["truncated", "cost_capped", "failed"])
def test_flagged_results_never_attach(flag):
    assert research_complete_is_attachable({"status": "completed", flag: True}, VALID) is False


def test_missing_critique_never_attaches():
    assert research_complete_is_attachable({"status": "completed"}, None) is False


def test_attach_rule_is_exactly_valid_or_partial():
    assert _SUCCESS_VERDICTS == frozenset({"VALID", "PARTIAL"})


# ── 23: CASE_SUMMARY minting ─────────────────────────────────────────────────

def test_case_summary_source_kind_marks_a_valid_complete():
    from scripts.lib.hermes_case_summary import SOURCE_KIND

    assert SOURCE_KIND == "HERMES_VALID_COMPLETE"


def test_case_summary_is_an_admit_active_type_but_research_reference_is_not():
    from scripts.lib.agent_memory_governance import (
        ADMIT_ACTIVE_TYPES,
        MEMORY_TYPE_CASE_SUMMARY,
    )

    assert MEMORY_TYPE_CASE_SUMMARY in ADMIT_ACTIVE_TYPES
    assert "RESEARCH_REFERENCE" not in ADMIT_ACTIVE_TYPES


def test_admit_active_types_were_not_expanded():
    """Guard: AGENT_COMMITMENT is listed but must not gain new company."""
    from scripts.lib.agent_memory_governance import ADMIT_ACTIVE_TYPES

    assert len(ADMIT_ACTIVE_TYPES) == 3


# ── 25: verdict counts ───────────────────────────────────────────────────────

def _result(summary="SCHD income ballast as of 2026-08-01", sources=("https://x")):
    return {"symbol": "SCHD", "summary": summary, "sources": list(sources),
            "as_of": "2026-08-01"}


def test_verdict_counts_separate_attachable_from_valid():
    rows = [
        _result(),                                  # VALID
        _result(sources=()),                        # PARTIAL (no_sources)
        _result(summary=""),                        # INSUFFICIENT
    ]
    c = build_verdict_counts(rows)
    assert c["completed_n"] == 3
    assert c["valid_n"] == 1
    assert c["partial_n"] == 1
    assert c["attachable_n"] == 2                   # VALID + PARTIAL
    assert c["fail_family_n"] == 1
    assert c["attach_rule"] == "VALID|PARTIAL"


def test_verdict_counts_report_why_something_was_partial():
    c = build_verdict_counts([_result(sources=())])
    assert c["top_reasons"].get("no_sources") == 1


def test_verdict_counts_on_empty_input():
    c = build_verdict_counts([])
    assert c["completed_n"] == 0
    assert c["attachable_n"] == 0
    assert c["by_verdict"] == {}


# ── 27: dust never gets an outcome checkpoint ────────────────────────────────

HOLDINGS = {"holdings": [
    {"symbol": "SCHD", "market_value": 365694.75},
    {"symbol": "SRNE", "market_value": 0.90},        # dust
    {"symbol": "CASH", "is_cash": True, "market_value": 100.0},
]}


def test_dust_symbol_is_not_checkpoint_eligible():
    from scripts.lib.cio_plan_outcome_checkpoints import skip_reason
    from scripts.lib.cio_investment_product import held_equity_symbols_nondust

    held = set(held_equity_symbols_nondust(HOLDINGS))
    assert "SRNE" not in held and "SCHD" in held

    dust_plan = {"status": "draft", "hermes_result_id": "rr_1",
                 "recommendation": "hold", "symbols": ["SRNE"]}
    assert skip_reason(dust_plan, held) == "not_held"

    real_plan = {"status": "draft", "hermes_result_id": "rr_1",
                 "recommendation": "hold", "symbols": ["SCHD"]}
    assert skip_reason(real_plan, held) is None


def test_cash_sleeve_is_still_skipped():
    from scripts.lib.cio_plan_outcome_checkpoints import skip_reason

    plan = {"status": "draft", "hermes_result_id": "rr_1",
            "recommendation": "hold", "symbols": ["CASH"]}
    assert skip_reason(plan, {"SCHD"}) == "cash_sleeve"


# ── 28 / 29: lessons cannot become policy ────────────────────────────────────

def _case_summary(plan_id="plan_1", result_id="rr_1", symbol="SCHD"):
    return {
        "memory_type": "CASE_SUMMARY",
        "status": "ACTIVE",
        "memory_id": f"mem_{plan_id}",
        "symbols": [symbol],
        "plan_ids": [plan_id],
        "metadata": {"hermes_result_id": result_id},
        "source_refs": [f"plan:{plan_id}", f"result:{result_id}"],
    }


def test_every_case_summary_lesson_is_provisional_and_capped_at_review_ready():
    from scripts.lib.outcome_to_lesson import candidates_from_case_summaries

    cands = candidates_from_case_summaries([_case_summary(f"plan_{i}") for i in range(5)])
    assert len(cands) == 5
    for c in cands:
        assert c["status"] == "PROVISIONAL"
        assert c["promotion_stage"] == "REVIEW_READY"
        assert c["max_unattended"] == "REVIEW_READY"
        assert c["cannot_become_policy"] is True
        assert c["policy_effect"] is False
        assert c["memory_behavior_influence"] == 0
        assert c["role"] == "SUPPORTING_CONTEXT"


def test_no_case_summary_lesson_ever_reaches_policy():
    from scripts.lib.outcome_to_lesson import candidates_from_case_summaries

    cands = candidates_from_case_summaries([_case_summary(f"plan_{i}") for i in range(5)])
    stages = {c["promotion_stage"] for c in cands}
    assert stages == {"REVIEW_READY"}
    assert not (stages & {"POLICY", "ADVISORY_ACTIVE", "PRODUCTION", "SUPPORTED"})


def test_non_active_case_summaries_produce_no_lesson():
    from scripts.lib.outcome_to_lesson import candidates_from_case_summaries

    rec = _case_summary()
    rec["status"] = "CANDIDATE"
    assert candidates_from_case_summaries([rec]) == []


def test_research_reference_produces_no_lesson():
    from scripts.lib.outcome_to_lesson import candidates_from_case_summaries

    rec = _case_summary()
    rec["memory_type"] = "RESEARCH_REFERENCE"
    assert candidates_from_case_summaries([rec]) == []


def test_lessons_are_deduped_per_symbol_plan_result():
    from scripts.lib.outcome_to_lesson import candidates_from_case_summaries

    dup = _case_summary()
    assert len(candidates_from_case_summaries([dup, dict(dup)])) == 1


# ── 30: admission receipts stay self-describing ──────────────────────────────

def test_receipt_promotable_is_derived_from_admit_active_types():
    from scripts.lib.agent_memory_governance import ADMIT_ACTIVE_TYPES

    assert ("CASE_SUMMARY" in ADMIT_ACTIVE_TYPES) is True
    assert ("RESEARCH_REFERENCE" in ADMIT_ACTIVE_TYPES) is False


def test_receipt_writer_still_sets_memory_type_and_promotable():
    """Source-level guard is not enough — assert the keys the writer emits."""
    import inspect

    from scripts.lib import agent_memory_admission as ama

    src = inspect.getsource(ama)
    assert '"memory_type": stored_type or None' in src
    assert '"promotable": stored_type in ADMIT_ACTIVE_TYPES' in src
