"""Isolated eight-stage NOC advisory-loop acceptance.

This fixture exercises the real source contracts against a temporary root. It
does not call an LLM, send a notification, or touch broker/runtime state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.api_v3_advisory import build_symbol_thesis_context
from scripts.lib.agent_decision_payload import emit_reentry_operator_payloads
from scripts.lib.cio_operator_ticker_feedback import append_feedback
from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.research_prompt_context import build_research_prompt_context
from scripts.lib.research_thesis_delta import accept_research_result
from scripts.lib.symbol_thesis_attach import clear_cache
from scripts.lib.symbol_thesis_cc import ask_cio_symbol_context, build_symbol_thesis_card
from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
from scripts.lib.thesis_decision_gate import apply_thesis_decision_gate

AUTHORITY = "READ_ONLY_ADVISORY"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(value, sort_keys=True) + "\n")


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _seed(root: Path) -> CIOThesisStore:
    _write_json(
        root / "data/portfolios/state/holdings.json",
        {"as_of": "2026-08-22T12:00:00+00:00", "holdings": [
            {"symbol": "NOC", "quantity": 12, "is_cash": False, "account": "acceptance"}
        ]},
    )
    _write_json(root / "data/runtime/reentry_decision_desk_latest.json", {"rows": []})
    store = CIOThesisStore(
        event_path=root / "data/cio/cio_theses.jsonl",
        projection_path=root / "data/cio/cio_theses_projection.json",
    )
    standing = (
        "NOC is held as a defensive-growth aerospace and defense position. "
        "Its funded backlog provides multi-year demand visibility across named programs. "
        "Program execution and margin conversion remain the primary operating tests. "
        "Government budget durability supports the role but does not remove appropriation risk. "
        "B-21 execution is a material catalyst and concentration risk. "
        "Free-cash-flow conversion must corroborate reported revenue growth. "
        "The position remains a HOLD while valuation and portfolio gates remain unchanged. "
        "A material program cancellation or withdrawn guidance would invalidate the thesis. "
        "No part of this thesis grants trading or broker authority."
    )
    publish_symbol_thesis(
        "NOC",
        summary=standing,
        stance="HOLD",
        portfolio_role="DEFENSIVE_GROWTH",
        universe_memberships=["HELD", "T0"],
        why_owned_or_watched="Defense backlog and program visibility diversify cyclical exposure.",
        evidence_for=["prior_filing_backlog"],
        counter_evidence=["prior_cash_conversion"],
        invalidation_conditions=["material program cancellation", "guidance withdrawn"],
        research_gaps=["quantify next-quarter cash conversion"],
        what_changes_my_mind=["sustained program losses", "appropriation reversal"],
        change_note="Acceptance seed standing thesis",
        store=store,
        notify=False,
        actor_id="noc_golden_fixture",
        provenance={
            "writer": "noc_golden_fixture",
            "writer_version": "NocGoldenLoop@v1",
            "trigger": "ISOLATED_ACCEPTANCE_SEED",
            "run_id": "run_noc_seed",
            "source_sha": "acceptance-fixture",
            "reason_for_change": "Establish governed standing thesis before delta review",
        },
    )
    clear_cache()
    return store


def _research_result() -> dict[str, Any]:
    return {
        "recommendation": (
            "NOC remains a HOLD in the defensive-growth role after the latest evidence review. "
            "Revenue increased 6.7% as funded backlog supported visible multi-year demand. "
            "The B-21 program remains the most important named catalyst for future sales and margin mix. "
            "Management guidance supports continued growth but does not justify an independent ADD decision. "
            "Cash conversion is the strongest counterpoint and requires confirmation in the next filing. "
            "The standing thesis is strengthened because program funding and execution evidence improved. "
            "Material program cancellation or withdrawn guidance remains the explicit invalidation condition. "
            "NOC should therefore remain held while deterministic portfolio gates retain decision authority. "
            "This delta improves evidence completeness and grants no trading or broker authority."
        ),
        "dissent": "Free-cash-flow conversion could weaken while reported revenue and backlog rise.",
        "confidence": 0.82,
        "classification": "STRENGTHENS",
        "evidence_as_of": "2026-08-22T20:00:00+00:00",
        "evidence": [
            {"evidence_id": "sec_noc_10q_2026q2", "provenance_class": "FACTUAL", "text": "Revenue increased 6.7%."},
            {"evidence_id": "noc_guidance_2026", "provenance_class": "FACTUAL", "text": "Guidance retained its growth range."},
        ],
        "contradictory_evidence": [
            {"evidence_id": "noc_cash_conversion", "provenance_class": "FACTUAL", "text": "Cash conversion weakened."}
        ],
        "reason_summary": "Fresh primary evidence strengthens completeness without promoting action.",
        "what_changed": ["revenue evidence", "backlog evidence"],
        "what_did_not_change": ["HOLD stance", "invalidation conditions"],
        "research_gaps_remaining": ["next-quarter cash conversion"],
        "source_quality": {"grade": "PRIMARY", "verified": True},
        "freshness": {"state": "CURRENT", "as_of": "2026-08-22T20:00:00+00:00"},
        "source_refs": ["sec:noc:10-q:2026q2", "company:noc:guidance:2026q2"],
        "thesis_stance": "HOLD",
        "provider": "governed_cloud",
        "model": "acceptance-model",
    }


def _prompt(root: Path, *, previous: dict[str, Any]) -> dict[str, Any]:
    return build_research_prompt_context(
        "NOC",
        question="What changed in the standing NOC thesis?",
        root=root,
        rag_catalog={
            "supporting": [{"evidence_id": "rag_noc_backlog", "text": "Funded backlog expanded."}],
            "contradictory": [{"evidence_id": "rag_noc_cash", "text": "Cash conversion weakened."}],
            "sufficiency": {"sufficient_for_synthesis": True, "fresh": True},
        },
        deterministic_current={
            "company": "Northrop Grumman",
            "sector": "Industrials",
            "industry": "Aerospace & Defense",
            "price": 590.0,
            "atr": 12.4,
            "rvol": 1.1,
            "trend": "UP",
        },
        previous_research=previous,
        memory_context={
            "authority": "NON_AUTHORITATIVE_CONTEXT",
            "memory_behavior_influence": "0",
            "supporting": [{"memory_id": "mem_noc_1", "subject": "Prefer primary filings"}],
            "counter": [],
            "conflicts": [],
        },
        ratified_lessons=[{"lesson_id": "lesson_primary_sources", "lifecycle": "RATIFIED_CONTEXT"}],
        financial_senses_receipts=[{
            "receipt_id": "fs_noc_1",
            "provider": "financial_senses",
            "status": "CURRENT",
            "evidence_refs": ["market_regime_20260822"],
        }],
    )


def run_noc_golden_loop(root: Path | str) -> dict[str, Any]:
    """Run the golden loop twice and return a machine-verifiable evidence record."""
    root_p = Path(root)
    store = _seed(root_p)
    result = _research_result()
    prompt1 = _prompt(
        root_p,
        previous={
            "research_id": "research_noc_prior",
            "conclusion": "Maintain HOLD pending cash-conversion evidence.",
            "as_of": "2026-08-18T12:00:00+00:00",
        },
    )
    research_record = {
        "schema": "GoldenResearchRecord@v1",
        "research_id": "research_noc_golden_1",
        "symbol": "NOC",
        "status": "CURRENT",
        "recommendation": result["recommendation"],
        "dissent": result["dissent"],
        "evidence": result["evidence"],
        "contradictory_evidence": result["contradictory_evidence"],
        "source_refs": result["source_refs"],
        "provider": result["provider"],
        "model": result["model"],
        "raw_response_provenance": {
            "sha256": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
            "stored_fields": sorted(result),
            "raw_chain_of_thought": False,
        },
        "prompt_context_hash": prompt1["prompt_context_hash"],
        "authority": AUTHORITY,
    }
    research_path = root_p / "data/cio/golden_research_records.jsonl"
    _append_jsonl(research_path, research_record)

    first = accept_research_result(
        "NOC",
        result,
        prompt_context=prompt1,
        research_id=research_record["research_id"],
        root=root_p,
        provider=result["provider"],
        model=result["model"],
        trigger="research_completion",
        run_id="run_noc_golden_1",
        source_sha="golden-source-sha",
    )
    clear_cache()
    current = store.get_current("symbol_noc")
    if current is None or first.get("new_version") != "symbol_noc@v2":
        raise AssertionError("automatic thesis reconciliation did not publish symbol_noc@v2")

    gate = apply_thesis_decision_gate(
        current_action="READY",
        governed_verdict="HOLD",
        thesis_state="CURRENT",
        thesis_stance=current.get("stance"),
        delta=first["delta"],
    )
    decision_id = "dec_noc_golden_v2"
    trace_path = root_p / "data/cio/agent_run_traces.jsonl"
    fingerprint_path = root_p / "data/cio/reentry_payload_fingerprints.json"
    decision_row = {
        "symbol": "NOC",
        "decision_id": decision_id,
        "previous_action": "READY",
        "confidence": 0.82,
        "intel": {"state": "READY TO REVIEW", "action": "Review only"},
        "advisory": {"action": gate["effective_action"]},
        "thesis_gate": gate,
        "symbol_thesis_id": "symbol_noc",
        "symbol_thesis_version": first["new_version"],
        "research_delta": first["delta"],
        "truth_inputs": {"price": 590.0, "source": "acceptance_fixture"},
        "source_freshness": {"state": "CURRENT", "as_of": result["evidence_as_of"]},
        "notification_outcome": {"sent": False, "reason": "acceptance_no_transport"},
    }
    emitted1 = emit_reentry_operator_payloads(
        [decision_row],
        flags={"AGENT_DECISION_PAYLOAD": 1},
        path=trace_path,
        fingerprint_path=fingerprint_path,
        wake_id="wake_noc_golden_1",
    )
    _write_json(root_p / "data/cio/cio_investment_brief.json", {
        "action_book": {"WATCH_CLOSELY": [{
            "symbol": "NOC",
            "action": gate["effective_action"],
            "decision_id": decision_id,
            "previous_action": "READY",
            "reason_codes": gate["reason_codes"],
            "research_delta": first["delta"],
            "thesis_version": first["new_version"],
            "source_freshness": decision_row["source_freshness"],
        }]},
        "authority": AUTHORITY,
    })
    card = build_symbol_thesis_card("NOC", root=root_p, research_rows=[])
    cio = ask_cio_symbol_context("NOC", root=root_p)
    advisory = build_symbol_thesis_context("NOC", root=root_p)

    feedback = append_feedback({
        "symbol": "NOC",
        "intent": "DISAGREE",
        "free_text": "Cash conversion needs one more filing before confidence rises.",
        "decision_id": decision_id,
        "thesis_id": "symbol_noc",
        "thesis_version": first["new_version"],
        "operator_identity_class": "ACCEPTANCE_OPERATOR",
        "source_surface": "command_center_symbol_card",
        "status": "ACTIVE",
    }, root=root_p)

    prompt2 = _prompt(root_p, previous={
        "research_id": research_record["research_id"],
        "conclusion": result["recommendation"],
        "as_of": result["evidence_as_of"],
    })
    replay = accept_research_result(
        "NOC",
        result,
        prompt_context=prompt2,
        research_id="research_noc_golden_2",
        root=root_p,
        provider=result["provider"],
        model=result["model"],
        trigger="research_completion",
        run_id="run_noc_golden_2",
        source_sha="golden-source-sha",
    )
    emitted2 = emit_reentry_operator_payloads(
        [decision_row],
        flags={"AGENT_DECISION_PAYLOAD": 1},
        path=trace_path,
        fingerprint_path=fingerprint_path,
        wake_id="wake_noc_golden_2",
    )
    final_store = CIOThesisStore(
        event_path=root_p / "data/cio/cio_theses.jsonl",
        projection_path=root_p / "data/cio/cio_theses_projection.json",
    )
    final = final_store.get_current("symbol_noc") or {}

    return {
        "schema": "NocAutonomousAdvisoryGoldenLoop@v1",
        "mode": "ISOLATED_SOURCE_ACCEPTANCE",
        "live_proven": False,
        "symbol": "NOC",
        "stages": {
            "research": research_record,
            "automatic_reconciliation": first,
            "published_thesis_version": first.get("new_version"),
            "advisory": advisory,
            "cio": cio,
            "symbol_card": card,
            "decision_gate": gate,
            "decision_emit": emitted1,
            "feedback": feedback,
            "next_prompt": prompt2,
        },
        "replay": {
            "delta_classification": replay["delta"]["classification"],
            "version_published": replay["version_published"],
            "final_thesis_version": final.get("thesis_version"),
            "thesis_change_cards": _line_count(root_p / "data/cio/thesis_change_cards.jsonl"),
            "decision_traces": _line_count(trace_path),
            "second_decision_emit": emitted2,
            "research_requests_created": 0,
            "notifications_sent": 0,
            "telegram_messages_sent": 0,
        },
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "financial_writes": 0,
    }
