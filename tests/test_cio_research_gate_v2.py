"""ResearchNeedDecision@v2 — the routing gate, cadence, corpus and templates.

The gate is the only place allowed to authorise a paid call, so every branch is
pinned here. The ordering matters as much as the branches: a cost cap must be
read before materiality escalation, and execution language must fail closed
before any escalation at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_corpus_index as corpus
from scripts.lib.cio_research_gate import (
    PAID_DECISIONS, TTL_HOURS, decide, schedule_surface, ttl_for,
)
from scripts.lib.cio_research_templates import GATES, build, forbidden_clause

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def d(**kw):
    base = {"material": True, "kind": "held_core_thesis"}
    base.update(kw)
    return decide(base, now=NOW)


# ---------------------------------------------------------------- gate matrix

def test_not_material_skips():
    assert d(material=False)["decision"] == "skip"
    assert d(material=False)["reason"] == "not_material"


def test_watch_block_never_reaches_a_model():
    """watch BLOCK gets no LLM at any materiality."""
    r = d(kind="watch_block", material=True)
    assert r["decision"] == "skip"
    assert r["reason"] == "kind_never_uses_llm"


def test_cost_cap_is_a_budget_stop_not_a_failure():
    r = d(cost_cap_hit=True)
    assert r["decision"] == "skip"
    assert r["reason"] == "cost_cap"
    assert r["next_eligible_at"], "a capped job must say when it may retry"


def test_cost_cap_outranks_escalation():
    """A capped day must not still escalate to a more expensive gate."""
    r = d(cost_cap_hit=True, prior_outcome="PARTIAL")
    assert r["decision"] == "skip"


def test_execution_language_fails_closed():
    r = d(prior_outcome="execution_language")
    assert r["decision"] == "skip"
    assert r["reason"] == "execution_language_fail_closed"
    assert r["next_eligible_at"] is None, "fail closed means no scheduled retry"


def test_execution_language_never_escalates_to_a_paid_gate():
    """The whole point: a tainted artifact does not buy a bigger model."""
    for prior in ("PARTIAL", "FAIL", "truncated"):
        r = d(prior_outcome="execution_language", pro_attempted=True,
              unreviewed_paid_artifact=True)
        assert r["decision"] not in PAID_DECISIONS, prior


def test_execution_language_detected_in_prior_text():
    """Detected via the one shared matcher, not a second word list."""
    r = d(prior_text="Sell half the position now.")
    assert r["decision"] == "skip"
    assert r["reason"] == "execution_language_fail_closed"


def test_past_tense_is_not_execution_language():
    """Decision 1: do not ban the words, ban the instruction."""
    r = d(prior_text="We trimmed the position in March and it lagged since.")
    assert r["decision"] != "skip" or r["reason"] != "execution_language_fail_closed"


def test_reuse_when_valid_row_inside_ttl():
    r = d(last_valid_at=(NOW - timedelta(hours=2)).isoformat())
    assert r["decision"] == "reuse"
    assert r["prior_outcome"] == "VALID"
    assert "hermes_research_results" in r["free_sources_tried"]


def test_stale_valid_row_does_not_reuse():
    r = d(last_valid_at=(NOW - timedelta(days=30)).isoformat())
    assert r["decision"] != "reuse"


def test_corpus_hit_spends_nothing():
    r = d(corpus={"closes": True, "reason": "corpus_fact_reproduced",
                  "source_refs": [{"source_id": "sta_x"}], "max_influence_pct": 10.0})
    assert r["decision"] == "corpus_hit"
    assert r["source_refs"]
    assert r["standalone_sell"] is False
    assert r["creates_trim"] is False


def test_first_pass_goes_to_flash():
    r = d()
    assert r["decision"] == "flash"


def test_flash_partial_escalates_to_pro():
    assert d(prior_outcome="PARTIAL")["decision"] == "pro"
    assert d(prior_outcome="truncated")["decision"] == "pro"


def test_pro_unresolved_escalates_to_openai():
    r = d(prior_outcome="FAIL", pro_attempted=True)
    assert r["decision"] == "openai"


def test_fail_without_pro_does_not_jump_to_openai():
    """No skipping the ladder: Flash failure alone never buys OpenAI."""
    assert d(prior_outcome="FAIL")["decision"] != "openai"


def test_paid_artifact_is_critiqued_before_attach():
    r = d(unreviewed_paid_artifact=True)
    assert r["decision"] == "grok_critique"


def test_valid_artifact_awaits_critique():
    r = d(prior_outcome="VALID", last_valid_at=(NOW - timedelta(days=30)).isoformat())
    assert r["decision"] == "grok_critique"


def test_grok_never_runs_first_pass():
    """Grok critiques; it never grinds a cold question."""
    r = d()
    assert r["decision"] != "grok_critique"


# -------------------------------------------------------------------- cadence

def test_cadence_not_due_skips():
    r = d(next_eligible_at=(NOW + timedelta(hours=5)).isoformat())
    assert r["decision"] == "skip"
    assert r["reason"] == "cadence_not_due"


def test_same_plan_twice_inside_ttl_second_is_skipped():
    """The core cadence claim: run it, then it stops running."""
    first = d()
    assert first["decision"] == "flash"
    second = decide({"material": True, "kind": "held_core_thesis",
                     "next_eligible_at": first["next_eligible_at"]},
                    now=NOW + timedelta(hours=1))
    assert second["decision"] == "skip"
    assert second["reason"] == "cadence_not_due"


def test_ttl_expiry_makes_it_eligible_again():
    first = d()
    later = NOW + timedelta(hours=TTL_HOURS["held_core_thesis"] + 1)
    again = decide({"material": True, "kind": "held_core_thesis",
                    "next_eligible_at": first["next_eligible_at"]}, now=later)
    assert again["decision"] == "flash"


def test_event_driven_kind_idles_without_an_event():
    assert d(kind="s6_concentration")["decision"] == "skip"
    assert d(kind="s6_concentration")["reason"] == "event_driven_kind_no_event"


def test_event_driven_kind_fires_on_its_event():
    assert d(kind="s6_concentration", event_fired=True)["decision"] == "flash"


def test_earnings_proximity_forces_eligibility():
    r = d(kind="earnings_calendar", days_to_event=2)
    assert r["decision"] == "flash"


def test_distant_earnings_does_not():
    r = d(kind="earnings_calendar", days_to_event=40)
    assert r["decision"] == "skip"


def test_event_overrides_a_fresh_reuse_row():
    """A material event beats a warm cache — that is what makes it an event."""
    r = d(kind="earnings_calendar", days_to_event=1,
          last_valid_at=(NOW - timedelta(hours=1)).isoformat())
    assert r["decision"] != "reuse"


def test_ttl_overrides_are_honoured():
    assert ttl_for("held_core_thesis") == 24 * 7
    assert ttl_for("held_core_thesis", {"held_core_thesis": 1}) == 1


# --------------------------------------------------------------------- corpus

def test_corpus_closes_only_reproduced_grades():
    """A/B may close. C and D are context only; D 'must not be treated as a fact'."""
    r = corpus.consult("seasonality")
    assert r["closes"] is True
    assert all(x["evidence_grade"] in {"A", "B"} for x in r["source_refs"])


def test_corpus_refuses_entity_specific_dimensions():
    """No almanac fact closes a bear case for a single name."""
    for dim in ("bear_case", "structural_drivers", "what_is_priced_in"):
        assert corpus.consult(dim)["closes"] is False


def test_context_only_grades_do_not_close_but_are_recorded():
    r = corpus.consult("macro")
    assert r["closes"] is False
    assert r["reason"].startswith("corpus_fact_context_only_grade_")
    assert r["source_refs"], "refs are still recorded when they fail to close"


def test_corpus_hit_carries_an_influence_ceiling():
    r = corpus.consult("seasonality")
    assert r["max_influence_pct"] == 10.0
    assert r["standalone_sell"] is False


def test_corpus_coverage_reports_the_thin_families():
    cov = corpus.coverage()
    assert cov["total_facts"] == 11
    assert cov["families"]["seasonality"] == 5


# ------------------------------------------------------------------ templates

@pytest.mark.parametrize("gate", GATES)
def test_every_template_forbids_execution_language(gate):
    t = build(gate, symbol="NOC")
    for verb in ("buy", "sell", "trim", "flatten", "liquidate", "place",
                 "submit", "execute"):
        assert verb in t["system"], f"{gate} must name {verb} as forbidden"
    assert "notification" in t["system"] or "notify" in t["system"]


@pytest.mark.parametrize("gate", GATES)
def test_every_template_declares_a_schema(gate):
    assert build(gate)["output_schema"]


def test_flash_asks_and_does_not_answer():
    s = build("flash")["system"]
    assert "Do NOT answer" in s
    assert "recommendation" in s


def test_critique_does_not_perform_research():
    s = build("grok_critique")["system"]
    assert "do not perform the research yourself" in s.lower()


def test_carry_forward_is_preserved_across_gates():
    t = build("pro", question_ids=["q1", "q2"], research_id="r9",
              artifact_id="a1", prior_outcome="PARTIAL",
              corpus_refs=[{"source_id": "sta_x", "evidence_grade": "B"}])
    assert t["carry"]["question_ids"] == ["q1", "q2"]
    assert t["carry"]["research_id"] == "r9"
    assert t["carry"]["prior_outcome"] == "PARTIAL"
    assert "sta_x" in t["user"]


def test_corpus_refs_travel_with_their_grade():
    """So a grade-D citation cannot be read as a settled fact."""
    t = build("pro", corpus_refs=[{"source_id": "pub_x", "evidence_grade": "D"}])
    assert "evidence_grade" in t["user"]
    assert "context/risk-modifier only" in t["user"]


def test_unknown_gate_raises():
    with pytest.raises(ValueError):
        build("claude")


def test_forbidden_clause_is_shared_not_duplicated():
    clause = forbidden_clause()
    for gate in GATES:
        assert clause in build(gate)["system"]


# ------------------------------------------------------------ ops surface

def test_schedule_surface_counts_and_caps():
    rows = [d(), d(material=False), d(cost_cap_hit=True),
            d(kind="watch_block")]
    s = schedule_surface(rows, cap=2, now=NOW)
    assert s["considered"] == 4
    assert s["skipped_by_reason"]["not_material"] == 1
    assert s["skipped_by_reason"]["cost_cap"] == 1
    assert len(s["next_eligible"]) <= 2


def test_schedule_surface_is_advisory_and_silent():
    s = schedule_surface([d()], now=NOW)
    assert s["authority"] == "READ_ONLY_ADVISORY"
    assert s["financial_action"] is False
    assert "telegram" not in str(s).lower()


def test_empty_eligible_is_healthy_not_an_error():
    s = schedule_surface([d(material=False)], now=NOW)
    assert s["next_eligible"] == []
    assert "healthy" in s["note"]


# ------------------------------------------------------------------- rails

def test_gate_is_advisory_and_takes_no_financial_action():
    for r in (d(), d(material=False), d(prior_outcome="PARTIAL")):
        assert r["authority"] == "READ_ONLY_ADVISORY"
        assert r["financial_action"] is False


def test_gate_is_deterministic():
    assert decide({"material": True, "kind": "held_core_thesis"}, now=NOW) == \
           decide({"material": True, "kind": "held_core_thesis"}, now=NOW)


def test_corpus_map_doc_is_committed():
    root = Path(__file__).resolve().parents[1]
    doc = root / "docs" / "ops" / "CIO_INSTITUTIONAL_CORPUS_MAP_2026-08-29.md"
    assert doc.exists()
    assert "CORPUS_UNLOCATED" in doc.read_text(encoding="utf-8")


# ------------------------------------------- delegation to the existing gate

def test_freshness_is_delegated_not_reimplemented():
    """There must be exactly one freshness law.

    `research_source_index.decide()` already owns "is this source stale or
    unchanged", with class SLAs in `freshness_days_for`. v2 asks it rather than
    keeping a second TTL opinion, because two laws over one question drift and
    the drift stays invisible until someone diffs them by hand.
    """
    import inspect

    from scripts.lib import cio_research_gate as gate

    src = inspect.getsource(gate)
    assert "research_source_index" in src, (
        "v2 must consult the existing source-hash gate")


def test_source_index_skip_becomes_reuse(monkeypatch):
    import scripts.lib.research_source_index as rsi

    monkeypatch.setattr(rsi, "decide", lambda *a, **k: "SKIP_UNCHANGED")
    r = decide({"material": True, "kind": "held_core_thesis",
                "source_id": "src_x", "content_hash": "h"}, now=NOW)
    assert r["decision"] == "reuse"
    assert r["source_index_verdict"] == "SKIP_UNCHANGED"
    assert "research_source_index" in r["free_sources_tried"]


def test_source_index_execute_falls_through_to_the_ladder(monkeypatch):
    import scripts.lib.research_source_index as rsi

    monkeypatch.setattr(rsi, "decide", lambda *a, **k: "RESEARCH_EXECUTED")
    r = decide({"material": True, "kind": "held_core_thesis",
                "source_id": "src_x", "content_hash": "h"}, now=NOW)
    assert r["decision"] == "flash"


def test_an_event_overrides_a_source_index_skip():
    """A triggered event must not be swallowed by an unchanged hash."""
    r = decide({"material": True, "kind": "held_core_thesis",
                "source_id": "src_x", "content_hash": "h",
                "event_fired": True}, now=NOW)
    assert r["decision"] != "reuse"


def test_missing_source_id_falls_back_to_local_ttl():
    r = decide({"material": True, "kind": "held_core_thesis",
                "last_valid_at": (NOW - timedelta(hours=2)).isoformat()}, now=NOW)
    assert r["decision"] == "reuse"
    assert r["reason"] == "valid_on_disk_within_ttl"
