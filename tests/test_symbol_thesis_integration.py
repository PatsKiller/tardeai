"""Integration tests for symbol-thesis → CIO books / review / research / CC.

No live broker writes. Fixtures only where possible; live-root tests are opt-in.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def thesis_store(tmp_path):
    from scripts.lib.cio_theses import CIOThesisStore
    return CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "proj.json",
    )


def test_cusip_bucket_sorts_unresolved_last():
    from scripts.lib.symbol_thesis_cc import _is_cusip, _membership_bucket, _BUCKET_PRIORITY
    assert _is_cusip("12507E201")
    assert _is_cusip("543354104")
    assert not _is_cusip("MSFT")
    assert not _is_cusip("SCHD")
    assert _membership_bucket({"symbol": "12507E201", "memberships": ["HELD"]}) == "BONDS_UNRESOLVED"
    assert _membership_bucket({"symbol": "MSFT", "memberships": ["HELD"]}) == "HELD"
    assert _membership_bucket({"symbol": "AMC", "memberships": ["FORMER_HOLDING", "REENTRY"]}) == "REENTRY"
    assert _membership_bucket({"symbol": "PLTR", "memberships": ["WATCHLIST"]}) == "WATCH"
    # BONDS_UNRESOLVED must sort after every real membership.
    assert _BUCKET_PRIORITY["BONDS_UNRESOLVED"] > _BUCKET_PRIORITY["HELD"]
    assert _BUCKET_PRIORITY["BONDS_UNRESOLVED"] > _BUCKET_PRIORITY["REENTRY"]
    assert _BUCKET_PRIORITY["BONDS_UNRESOLVED"] > _BUCKET_PRIORITY["WATCH"]



def test_reconcile_no_churn_on_identical(thesis_store, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis

    publish_symbol_thesis(
        "SCHG",
        summary="SCHG is the primary large-cap growth sleeve for the book with clear invalidation.",
        stance="hold",
        portfolio_role="GROWTH",
        why_owned_or_watched="Growth exposure",
        store=thesis_store,
        notify=False,
    )
    r1 = reconcile_symbol_thesis(
        "SCHG",
        trigger="test",
        evidence={
            "summary": "SCHG is the primary large-cap growth sleeve for the book with clear invalidation.",
            "stance": "hold",
            "why_owned_or_watched": "Growth exposure",
            "portfolio_role": "GROWTH",
        },
        store=thesis_store,
        root=tmp_path,
        publish=True,
        notify=False,
    )
    assert r1["classification"] == "NO_MATERIAL_CHANGE"
    assert r1["version_published"] is False

    # Replay identical → still no churn
    r2 = reconcile_symbol_thesis(
        "SCHG",
        trigger="test_replay",
        evidence={
            "summary": "SCHG is the primary large-cap growth sleeve for the book with clear invalidation.",
            "stance": "hold",
            "why_owned_or_watched": "Growth exposure",
            "portfolio_role": "GROWTH",
        },
        store=thesis_store,
        root=tmp_path,
        publish=True,
        notify=False,
    )
    assert r2["classification"] == "NO_MATERIAL_CHANGE"
    assert r2["version_published"] is False


def test_reconcile_material_strengthen_and_broken(thesis_store, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis

    publish_symbol_thesis(
        "CSCO",
        summary="CSCO was a prior holding for networking exposure; thesis intact pending confirmation.",
        stance="watch",
        portfolio_role="CORE",
        why_exited="DATA_UNAVAILABLE",
        store=thesis_store,
        notify=False,
    )
    r = reconcile_symbol_thesis(
        "CSCO",
        trigger="research_completion",
        evidence={
            "summary": "CSCO thesis strengthened: durable cash flows and AI networking demand support re-entry study.",
            "stance": "add",
            "evidence_for": ["research:r1: AI networking demand"],
            "why_exited": "Trimmed for concentration; thesis not broken",
            "portfolio_role": "CORE",
        },
        store=thesis_store,
        root=tmp_path,
        notify=False,
    )
    assert r["classification"] == "THESIS_STRENGTHENED"
    assert r["version_published"] is True

    r2 = reconcile_symbol_thesis(
        "CSCO",
        trigger="contradiction",
        evidence={
            "summary": "CSCO thesis broken — competitive displacement invalidated prior networking thesis.",
            "stance": "avoid",
            "counter_evidence": ["competitive displacement"],
            "portfolio_role": "CORE",
        },
        store=thesis_store,
        root=tmp_path,
        notify=False,
    )
    assert r2["classification"] == "THESIS_BROKEN"
    assert r2["version_published"] is True


def test_specific_research_gap_not_vague(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_research import build_research_request

    fields = {
        "symbol_thesis_id": "symbol_schg",
        "symbol_thesis_version": None,
        "thesis_state": "RESEARCH_REQUIRED",
        "portfolio_role": "GROWTH",
        "memberships": ["HELD", "WATCHLIST"],
        "thesis_stance": None,
        "counter_evidence": [],
    }
    req = build_research_request(
        "SCHG",
        gap="Create living symbol thesis (role, why owned/exited, invalidation, research gaps)",
        thesis_fields=fields,
    )
    q = req["specific_question"].lower()
    assert "schg" in q
    assert q.strip() != "research schg."
    assert "research schg" != q.strip()
    assert req["priority"] == "P1"  # held gap
    assert req["enqueue"] is False
    assert "why is schg still held" in q or "still held" in q


def test_discovery_not_flooded(monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_research import propose_prioritized_research

    # Live read is OK for this gate — must not enqueue; must skip mass discovery
    prop = propose_prioritized_research(root=ROOT, limit=40, max_p3=5)
    assert prop["enqueued"] is False
    assert prop["counts"]["proposed"] <= 40
    # Must not propose thousands
    assert prop["counts"]["proposed"] < 500
    # Discovery skip should be recorded when universe is large
    if (prop.get("coverage_counts") or {}).get("rows", 0) > 1000:
        assert prop["counts"]["skipped_discovery_or_capped"] > 0


def test_opportunity_actionability_research_required():
    from scripts.lib.symbol_thesis_attach import opportunity_actionability
    row = {
        "thesis_state": "RESEARCH_REQUIRED",
        "status": "NEAR",
        "verdict": "ADD",
        "research_gap_count": 2,
    }
    assert opportunity_actionability(row) == "RESEARCH_REQUIRED"


def test_adjudicate_reentry_data_unavailable(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    from scripts.lib.cio_investment_product import adjudicate_reentry
    from scripts.lib.symbol_thesis_attach import clear_cache

    clear_cache()
    # Point product root at empty thesis store via _product_root
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/portfolios/state").mkdir(parents=True)
    (tmp_path / "data/portfolios/state/holdings.json").write_text(
        json.dumps({"accounts": []}), encoding="utf-8"
    )
    row = {
        "symbol": "ANET",
        "reentry_signal": "NEAR ENTRY",
        "pct_above_exit": 5,
        "reentry_zone_low": 100,
        "reentry_zone_high": 110,
        "last_exit_price": 105,
        "_product_root": str(ROOT),  # use real roles; thesis still missing for ANET typically
    }
    rec = adjudicate_reentry(
        row, qitems=[], lessons={}, fs_ok=False, infl={"lesson_enhanced": False}
    )
    assert "DATA_UNAVAILABLE" in str(rec.get("why_previously_owned") or "") or rec.get("why_previously_owned")
    assert rec.get("thesis_state") in {
        "RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE", "CONFLICTED", "CURRENT"
    }
    assert rec.get("governed_verdict") != "RE_ENTER"  # no queue RE_ENTER
    assert rec.get("status") in {"NEAR", "WAIT", "AVOID"}


def test_cc_symbol_card_schg_operator_role(monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_cc import build_symbol_thesis_card

    card = build_symbol_thesis_card("SCHG", root=ROOT)
    assert card["symbol"] == "SCHG"
    assert card["portfolio_role"] == "GROWTH"
    assert "operator" in str(card.get("portfolio_role_source") or "")
    assert card["thesis_state"] in {
        "RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE", "CONFLICTED", "CURRENT", "RETIRED"
    }
    assert card["authority"] == "READ_ONLY_ADVISORY"
    assert isinstance(card.get("thesis_history"), list)


def test_ask_cio_context_transparent(monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_cc import ask_cio_symbol_context

    ctx = ask_cio_symbol_context("SCHG", root=ROOT)
    assert ctx["trading_execution_authority"] is False
    assert ctx["portfolio_role"] == "GROWTH"
    if ctx.get("transparent_if_missing"):
        assert ctx["current_symbol_thesis"]["state"] in {
            "RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE", "CONFLICTED"
        }


def test_reassessment_hooks_thesis_review(tmp_path, monkeypatch):
    """research completion → thesis review → at most one material version (idempotent)."""
    monkeypatch.chdir(ROOT)
    from scripts.lib.cio_theses import CIOThesisStore
    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis

    store = CIOThesisStore(
        event_path=tmp_path / "t.jsonl",
        projection_path=tmp_path / "p.json",
    )
    evidence = {
        "summary": "ANET remains a high-quality networking compounder; watch for valuation stretch.",
        "stance": "watch",
        "evidence_for": ["research:r99: quality compounder"],
        "research_result_id": "r99",
    }
    a = reconcile_symbol_thesis(
        "ANET", trigger="research_completion", evidence=evidence,
        store=store, root=tmp_path, notify=False,
    )
    b = reconcile_symbol_thesis(
        "ANET", trigger="research_completion", evidence=evidence,
        store=store, root=tmp_path, notify=False,
    )
    assert a["version_published"] is True
    assert b["classification"] == "NO_MATERIAL_CHANGE"
    assert b["version_published"] is False


def test_api_helpers_importable():
    import api_v3_cio as cio
    assert callable(cio.get_universe_theses)
    assert callable(cio.get_agent_research_ops)
    assert callable(cio.get_symbol_thesis_card)
    assert callable(cio.get_thesis_research_proposal)
    assert callable(cio.get_ask_thesis_context)
    assert callable(cio.get_thesis_ri_pipeline)


def test_research_request_not_hermes_as_source():
    from scripts.lib.symbol_thesis_research import build_research_request
    fields = {
        "symbol_thesis_id": "symbol_schg",
        "thesis_state": "RESEARCH_REQUIRED",
        "portfolio_role": "GROWTH",
        "memberships": ["HELD"],
        "counter_evidence": [],
    }
    req = build_research_request(
        "SCHG",
        gap="Create living symbol thesis (role, why owned/exited, invalidation, research gaps)",
        thesis_fields=fields,
    )
    assert req["hermes_is_acquisition_source"] is False
    assert req["hermes_role"] == "synthesis_and_challenge_only"
    assert req["acquisition_plane"] == "research_intelligence_multi_source"
    assert "rag_retrieve_supporting_and_contradictory" in req["pipeline"]
    assert "searxng_metasearch" in req["required_evidence_domains"]
    assert "hermes" not in req["required_evidence_domains"]


def test_acquisition_plan_skips_when_sufficient():
    from scripts.lib.symbol_thesis_acquisition import build_acquisition_plan
    catalog = {
        "sufficiency": {
            "sufficient_for_synthesis": True,
            "remaining_evidence_gaps": [],
        }
    }
    plan = build_acquisition_plan(
        "SCHG", question="Why held?", evidence_catalog=catalog, priority="P1"
    )
    assert plan["status"] == "SKIP_ACQUISITION"
    assert plan["hermes_is_acquisition_source"] is False
    assert plan["steps"] == []


def test_acquisition_plan_budgeted_and_multi_source():
    from scripts.lib.symbol_thesis_acquisition import build_acquisition_plan, SOURCE_FAMILIES
    catalog = {
        "sufficiency": {
            "sufficient_for_synthesis": False,
            "remaining_evidence_gaps": [
                "insufficient_supporting_rag",
                "insufficient_contradictory_rag",
                "no_approved_primary_or_news",
            ],
        }
    }
    plan = build_acquisition_plan(
        "CSCO",
        question="Build living exit/re-entry thesis for CSCO",
        evidence_catalog=catalog,
        priority="P1",
    )
    assert plan["status"] == "ACQUISITION_PLANNED"
    families = {s["family"] for s in plan["steps"]}
    assert "searxng_metasearch" in families
    assert "sec_filings" in families
    assert "deterministic_structured" in families
    # Hermes must not appear as an acquisition step
    assert "hermes" not in families
    assert "deepseek_flash" not in families
    for s in plan["steps"]:
        assert s["family"] in SOURCE_FAMILIES or s["family"] == "rag_existing"
        assert len(s["targets"]) <= s["cap"]
    assert plan["curation_gate"]["no_second_vector_store"] is True
    assert plan["synthesis_gate"]["not_acquisition_source"] is True


def test_synthesis_packet_blocked_without_evidence():
    from scripts.lib.symbol_thesis_synthesis import build_synthesis_packet
    packet = build_synthesis_packet(
        "ANET",
        question="thesis?",
        evidence_catalog={
            "supporting": [],
            "contradictory": [],
            "structured": [],
            "sufficiency": {"sufficient_for_synthesis": False},
        },
        acquisition_plan={"status": "ACQUISITION_PLANNED", "plan_id": "x"},
    )
    assert packet["gate"] == "BLOCKED_PENDING_ACQUISITION_AND_CURATION"
    assert packet["llm_lanes"]["acquisition_source"] is False
    assert packet["call_llm"] is False


def test_curate_blocks_low_quality():
    from scripts.lib.symbol_thesis_acquisition import curate_candidate_for_embed
    bad = curate_candidate_for_embed({"rag_status": "blocked", "quality": "SECONDARY_RESEARCH"})
    assert bad["admit"] is False
    good = curate_candidate_for_embed({
        "rag_status": "approved", "quality": "APPROVED_NEWS", "fact": "ok"
    })
    assert good["admit"] is True
    assert good["embed_ready"] is True


def test_r71_dependency_versioned():
    from scripts.lib.r71_cursor_fabric_map import fabric_map_report, load_dependency
    dep = load_dependency()
    assert dep.get("cursor_remediation_versioned") is True
    assert dep.get("cursor_head", "").startswith("6e429619")
    assert dep.get("cursor_pr") == 398
    assert dep.get("dependency_strategy") == "DECLARE_SHA_CONSUME_DATA_PLANE_NO_WHOLESALE_MERGE"
    report = fabric_map_report()
    assert report["hold_on_unversioned"] is False
    assert "DO_NOT_IMPORT" in report["by_class"]
    assert any("candidate_discovery" in c for c in report["by_class"]["CONSUME_DIRECTLY"])


def test_materiality_membership_not_evidence():
    from scripts.lib.symbol_thesis_materiality import classify_materiality
    m = classify_materiality(
        memberships=["WATCHLIST"],
        source_tier="candidate",
        origin_system="hermes_research+social",
        provenance_complete=True,
        social_score=95,
    )
    assert m["membership_is_not_evidence"] is True
    assert m["social_score_is_derived_only"] is True
    assert m["auto_apply_is_not_research_confidence"] is True
    assert m["materiality_tier"] == "T3_DISCOVERY"
    assert m["expensive_thesis_work_allowed"] is False

    held = classify_materiality(memberships=["HELD", "WATCHLIST"], held=True)
    assert held["materiality_tier"] == "T0_CURRENT_HOLDING"
    assert held["expensive_thesis_work_allowed"] is True


def test_legacy_unattributed_trust():
    from scripts.lib.symbol_thesis_materiality import classify_materiality
    m = classify_materiality(
        memberships=["REENTRY", "WATCHLIST"],
        reentry_state="NEAR ENTRY",
        origin_system=None,
        provenance_complete=False,
    )
    assert m["evidence_trust"] == "LEGACY_UNATTRIBUTED"
    # near reentry without provenance demoted from expensive (except holdings)
    assert m["expensive_thesis_work_allowed"] is False


def test_wake_dedupe_no_auto_thesis_version(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_event_wake import plan_wake_from_discovery, execute_wake_checks
    # use tmp root for dedupe file via monkeypatch of parents — pass root
    p1 = plan_wake_from_discovery(symbol="SCHG", event_id="evt-test-1", root=tmp_path)
    assert p1["duplicate"] is False
    assert "auto_thesis_version" in p1["actions_forbidden"]
    assert p1["cio_event_type"] == "watch.new_signal"
    # mark seen
    from scripts.lib.symbol_thesis_event_wake import execute_wake_checks as _
    # manually persist by calling execute with persist
    # (execute builds full context — may be slow; just re-plan after fake save)
    from scripts.lib.symbol_thesis_event_wake import _save_seen
    _save_seen(tmp_path, {"seen": {p1["wake_id"]: {"as_of": "x"}}, "updated_at": "x"})
    p2 = plan_wake_from_discovery(symbol="SCHG", event_id="evt-test-1", root=tmp_path)
    assert p2["duplicate"] is True
    assert p2["action"] == "SUPPRESS"


def test_shared_searx_client_importable():
    from scripts.lib.searxng_client import searx_search, DEFAULT_SEARXNG
    assert "8080" in DEFAULT_SEARXNG or "SEARXNG" in DEFAULT_SEARXNG or "http" in DEFAULT_SEARXNG
    assert callable(searx_search)
