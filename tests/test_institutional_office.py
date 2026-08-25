"""Institutional CIO office — shadow only. Activation OFF. No full-text theater."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.advisory_office import compose_brief
from scripts.lib.canon_reasoning import reason_with_canon
from scripts.lib.cio_forward_program import ACTIVATION, MBI, OFFICE_TRUTH
from scripts.lib.cio_office_synthesizer import (
    run_office_cycle_from_manifest,
    unattended_week_capability,
)
from scripts.lib.historical_regime_lab import compare, register_episode
from scripts.lib.institutional_knowledge_fabric import retrieve
from scripts.lib.investment_theory_engine import competing_theories, list_theories, propose_theory, transition
from scripts.lib.reference_brain_audit import audit_reference_brain
from scripts.lib.sector_research_desk import build_sector_theses, inherit_sector_context
from scripts.lib.transferson_universe import build_universe

REPO = Path(__file__).resolve().parents[1]


def _manifest():
    return build_universe(sources={
        "holdings": ["NOC"],
        "symbol_profiles": [
            {"symbol": "NOC", "sector": "Industrials", "industry": "Aerospace", "company": "Northrop",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "RTX", "sector": "Industrials", "industry": "Aerospace", "company": "RTX",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
        ],
        "trs": [{"symbol": "NOC", "security_guid": "sec-noc"}],
        "screener_active": [],
        "discovery_validated": [],
    })


def test_office_activation_off() -> None:
    assert ACTIVATION["OFFICE"] is False
    assert all(v is False for v in ACTIVATION.values())
    assert MBI == 0


def test_reference_brain_does_not_claim_full_text() -> None:
    audit = audit_reference_brain(REPO, drive_titles=["book knowledge inventory"])
    assert audit["catalog_n"] == 34
    assert audit["SOURCE_IDENTIFIED_n"] == 34
    assert audit["SOURCE_AVAILABLE_n"] == 0
    assert audit["NOT_AVAILABLE_n"] == 34
    assert audit["catalog_is_not_a_corpus"] is True
    graham = next(s for s in audit["sources"] if s["source_id"] == "graham_zweig_intelligent_investor")
    assert graham["SOURCE_IDENTIFIED"] is True
    assert graham["SOURCE_AVAILABLE"] is False
    assert graham["DERIVED_KNOWLEDGE_AVAILABLE"] is True
    assert graham["EMBEDDED"] is False
    assert "Intelligent Investor" not in (audit.get("drive_titles_searched") or [])
    assert any(d["knowledge_class"] == "operator_derived_doctrine" for d in audit["derived_register"])
    assert any(d["knowledge_class"] == "implemented_mechanic" for d in audit["derived_register"])


def test_fabric_retrieves_doctrine_and_operator_memory_without_mutating_truth() -> None:
    CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
    out = retrieve(CURRENT, query="attractive valuation", symbol="NOC", limit=20)
    assert out["mutated_office_truth"] is False
    assert out["memory_behavior_influence"] == 0
    assert any(h["knowledge_class"] == "operator_derived_doctrine" for h in out["hits"])
    assert out["used_knowledge_ids"]


def test_canon_is_not_a_gate() -> None:
    out = reason_with_canon(REPO, question="Is NOC attractive?", symbol="NOC")
    assert out["deterministic_reject"] is False
    stances = {v["stance"] for v in out["views"]}
    assert "SOURCE_UNAVAILABLE" in stances
    assert out["disagreement_visible"] is True


def test_competing_theories_required_and_not_overwritten(tmp_path) -> None:
    miss = competing_theories(
        tmp_path, question="x", authoring_agent="test", evidence_class="UNIT_TEST",
        statements={"base": {"statement": "b", "falsification_conditions": ["f"]}},
    )
    assert miss["ok"] is False
    assert miss["reason"] == "competing_theories_required"
    ok = competing_theories(
        tmp_path, question="x", authoring_agent="test", evidence_class="UNIT_TEST",
        affected_entities=["NOC"],
        statements={
            "base": {"statement": "base", "falsification_conditions": ["base wrong if edge proven"]},
            "bull": {"statement": "bull", "falsification_conditions": ["bull wrong if drivers reverse"]},
            "bear": {"statement": "bear", "falsification_conditions": ["bear wrong if cycle improves"]},
            "alternative": {"statement": "alt", "scope": "theme", "falsification_conditions": ["alt wrong if no related name"]},
        },
    )
    assert ok["ok"] is True
    tid = ok["theories"]["base"]["theory_id"]
    t2 = transition(tmp_path, tid, "UNDER_RESEARCH", reason="hermes searching disconfirming evidence")
    assert t2["silently_overwritten"] is False
    assert t2["theory"]["version"] == 2
    assert t2["theory"]["prior_status"] == "PROPOSED"
    versions = [r["version"] for r in list_theories(tmp_path) if r["theory_id"] == tid]
    # list_theories returns latest only
    assert versions == [2]
    # raw file keeps both
    raw = (tmp_path / "data/cio/office/investment_theories.jsonl").read_text()
    assert raw.count("\n") >= 5  # 4 propose + 1 transition


def test_theory_requires_falsification(tmp_path) -> None:
    out = propose_theory(
        tmp_path, statement="s", mechanism="m", scope="security",
        authoring_agent="t", evidence_class="UNIT_TEST",
    )
    assert out["ok"] is False
    assert out["reason"] == "falsification_required"


def test_regime_analogue_requires_differences(tmp_path) -> None:
    register_episode(
        tmp_path, label="1970s inflation",
        statement="high inflation, rising rates",
        axes={"inflation": "high", "rates": "rising", "valuation": "compressed"},
        differences=["today's market structure and indexation differ"],
    )
    cmp = compare(tmp_path, {"inflation": "high", "rates": "rising", "valuation": "rich"})
    assert cmp["historical_similarity_is_not_destiny"] is True
    assert cmp["n"] == 1
    assert cmp["analogues"][0]["similar_axes"]
    assert cmp["analogues"][0]["differences"]


def test_sector_desk_inherits_and_discovers() -> None:
    m = _manifest()
    desk = build_sector_theses("/tmp", m, persist=False, focus_symbol="NOC")
    assert desk["n"] >= 1
    inh = inherit_sector_context(m, "NOC", desk)
    assert inh["sector"] == "Industrials"
    assert "RTX" in inh["discovered_related_tickers"]


def test_cio_cycle_is_not_a_scanner_and_does_not_trade(tmp_path) -> None:
    m = _manifest()
    cycle = run_office_cycle_from_manifest(
        tmp_path, m,
        change={"symbol": "NOC", "question": "Is NOC attractive?", "materiality": 0.9},
        evidence_class="UNIT_TEST",
        persist=True,
        deterministic_setup={"recommendation": "BUY"},
    )
    assert cycle["activated"] is False
    assert cycle["autonomous_trading"] is False
    assert cycle["mutated_office_truth"] is False
    assert cycle["office_truth"]["lane"] == OFFICE_TRUTH
    assert cycle["office_truth"]["cognition_may_not_override"] is True
    assert "cio_synthesis" in cycle["lineage"]
    assert cycle["synthesis"]["recommendation"] in cycle["synthesis"]["allowed_set"]
    assert cycle["theories"]["ok"] is True
    assert set(cycle["theories"]["roles"]) == {"base", "bull", "bear", "alternative"}
    assert cycle["influence_trace"]["memory_used"] is not None
    brief = compose_brief(cycle)
    assert brief["advisory_only"] is True
    assert brief["influence_trace"] == cycle["influence_trace"]
    # restart persistence
    again = list_theories(tmp_path)
    assert len(again) >= 4


def test_week_acceptance_is_honestly_no() -> None:
    cap = unattended_week_capability()
    assert cap["answer"] == "NO"
    assert cap["activated"] is False
    assert any("R17" in r for r in cap["reasons"])
