"""LQ-20261107-1808 item 2 — one route per process.

`hermes_external_research` declared `lane_policy: "deepseek_only"` AND `anthropic_first: true`. The
promotional router (`lib/anthropic_routing.eligible`) reads the flag with `is True`, so the "deepseek"
research lane executed on `claude-haiku-5-5`: 219 of the last 24 h failed
`ANTHROPIC_INPUT_LIMIT_EXCEEDED` while every stored row said `deepseek-flash`.

The checker fails on that pair for any process. The real registry still holds the 2026-10-25
Anthropic-first promotion cohort, whose removal is an operator decision; the test pins the cohort
exactly, so a NEW contradictory row fails CI while a decommissioned one must be removed from the pin
in the same change (Constitution Rule 7: a declaration naming two routes is the defect).
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import check_llm_process_registry as chk

REGISTRY = Path(__file__).resolve().parents[1] / "config" / "llm_process_registry.json"

#: The 2026-10-25 Anthropic-first promotion cohort as of 2026-11-10 (docs/ops/ANTHROPIC_FIRST_20261025.md).
#: Operator-only to decommission; pinned so it cannot grow unnoticed.
KNOWN_20261025_COHORT = {
    "advisory_desk_opinion",
    "advisory_desk_synthesis",
    "alex_cio_escalation",
    "alex_cio_synthesis",
    "cio_hermes_research",
    "cio_operator_reply",
    "cio_overnight_brief",
    "cio_plan_enrichment",
    "cio_policy_field_advisor",
    "cio_prompt_judge",
    "contradiction_adjudicator",
    "guardian_risk_critique",
    "hermes_cloud_json",
    "hermes_golden_judge",
    "hermes_usefulness_score",
    "l3_judgment_author",
    "ledger_tax_critique",
    "local_llm_compat",
    "morgan_wealth_synthesis",
    "options_thesis_cio_review",
    "prospectus_accuracy_review",
    "prospectus_cio_news_note",
    "prospectus_fact_check",
    "prospectus_news_classify",
    "prospectus_writer",
    "prospectus_writer_premium",
    "reflective_critic_flash",
    "research_circle_analyzer",
    "steph_allocation_review",
    "watchlist_agent_debate_flash",
    "watchlist_agent_flash_extract",
    "watchlist_maria_flash_narrative",
    "watchlist_risk_flash_narrative",
    "watchlist_steph_flash_narrative",
}


def _row(pid, policy="deepseek_only", **extra):
    return {"id": pid, "lane_policy": policy, **extra}


# ── synthetic fixtures: the checker itself ────────────────────────────────────────────────────────


def test_synthetic_contradiction_is_reported():
    doc = {"processes": [_row("synthetic_both", anthropic_first=True)]}

    rec = chk.report(doc)

    assert rec["ok"] is False
    assert [v["id"] for v in rec["violations"]] == ["synthetic_both"]


def test_synthetic_clean_registry_passes():
    doc = {"processes": [
        _row("synthetic_deepseek"),
        _row("synthetic_anthropic", policy="anthropic_only", anthropic_first=True),
    ]}

    rec = chk.report(doc)

    assert rec["ok"] is True
    assert rec["violations"] == []
    assert rec["processes"] == 2


def test_only_the_literal_boolean_true_counts():
    """The router reads `is True`; a string or 1 must not be accepted as a flagged route either."""
    doc = {"processes": [
        _row("synthetic_string", anthropic_first="true"),
        _row("synthetic_int", anthropic_first=1),
        _row("synthetic_false", anthropic_first=False),
    ]}

    assert chk.route_contradictions(doc) == []


def test_other_lane_policies_are_not_violations():
    doc = {"processes": [_row("synthetic_flex", policy="deepseek_first", anthropic_first=True)]}

    assert chk.route_contradictions(doc) == []


def test_cli_fails_on_violation_and_passes_when_clean(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"processes": [_row("synthetic_both", anthropic_first=True)]}))
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"processes": [_row("synthetic_deepseek")]}))

    assert chk.main(["--registry", str(bad), "--fail-on-violation"]) == 1
    assert chk.main(["--registry", str(good), "--fail-on-violation"]) == 0


def test_cli_refuses_to_pass_on_an_unreadable_registry(tmp_path):
    """A checker that cannot read is not a pass (Constitution Rules 8 and 11)."""
    assert chk.main(["--registry", str(tmp_path / "missing.json"), "--fail-on-violation"]) == 2


# ── the real registry ───────────────────────────────────────────────────────────────────────────


def test_hermes_external_research_names_one_route():
    doc = chk.load_registry(REGISTRY)
    rows = [r for r in chk._rows(doc) if r.get("id") == "hermes_external_research"]

    assert len(rows) == 1, "one process, one row"
    row = rows[0]
    assert row["lane_policy"] == "deepseek_only"
    assert "anthropic_first" not in row, (
        "the deepseek research lane must not also be admitted to Anthropic first (LQ-1808)"
    )


def test_real_registry_violations_are_exactly_the_known_promotion_cohort():
    rec = chk.report(chk.load_registry(REGISTRY))
    found = {v["id"] for v in rec["violations"]}

    assert found == KNOWN_20261025_COHORT, (
        "A new deepseek_only+anthropic_first row is a new two-route declaration and fails this test. "
        "If a cohort row was decommissioned, remove it here in the same change.\n"
        f"  new: {sorted(found - KNOWN_20261025_COHORT)}\n"
        f"  gone: {sorted(KNOWN_20261025_COHORT - found)}"
    )
