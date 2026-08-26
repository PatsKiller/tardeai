"""PR C: curation version rule, Librarian epistemic, gaps, events, zero paid."""
from __future__ import annotations

from scripts.lib.artifact_embed import embed_artifact
from scripts.lib.curation_cycle import curate_security
from scripts.lib.event_identity import build_event, event_guid, supersede_scheduled
from scripts.lib.evidence_freshness_policy import POLICY_CLASSES, classify_evidence_class, freshness_state
from scripts.lib.evidence_refresh_job import dispatch_paid_provider, reset_paid_dispatch_probe
from scripts.lib.free_first_circulation import circulate_symbol, project_hermes_rows
from scripts.lib.hermes_research_context import build_context
from scripts.lib.librarian_assessment import assess_artifact
from scripts.lib.research_gap import should_create_gap
from scripts.lib.security_identity import attach_identity_v2
from scripts.lib.ticker_knowledge_graph import build_profile, retrieve_context, seed_profiles

import pytest


def _profile(sym="NOC"):
    return attach_identity_v2(build_profile(sym, metadata={"company": "Northrop", "sector": "Industrials"}))


def _hermes():
    return {
        "research": [{
            "id": 11, "topic": "defense", "summary": "backlog intact", "thesis": "HOLD durability",
            "status": "promoted", "research_type": "web",
            "source_urls_json": ["https://sec.gov/Archives/noc"],
            "created_at": "2026-08-20T00:00:00+00:00",
        }],
        "external": [{
            "id": 22, "lane": "deepseek", "recommendation": "HOLD / DO NOT ADD",
            "created_at": "2026-08-22T00:00:00+00:00",
        }],
    }


def _empty_rag(_sym):
    return {"ok": True, "supporting": [], "contradictory": []}


def test_context_asks_what_changed():
    ctx = build_context(identity={"symbol": "NOC"}, curation=None, state=None)
    assert ctx["question"] == "WHAT_CHANGED"
    assert ctx["forbidden_default"] == "tell_me_about_symbol"
    assert ctx["llm_eligible"] is False


def test_no_new_info_does_not_version_curation(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "NG", "sector": "Industrials"}])
    r1 = circulate_symbol(tmp_path, _profile(), hermes_rows=_hermes(), rag_fn=_empty_rag, allow_searx=False)
    r2 = circulate_symbol(tmp_path, _profile(), hermes_rows=_hermes(), rag_fn=_empty_rag, allow_searx=False)
    assert r1["decision"] == "NO_NEW_INFO"
    assert r1["curation_wrote"] is True
    assert r1["curation_reason"] == "BASELINE_PROJECTION"
    assert r2["state_wrote"] is False
    assert r2["curation_wrote"] is False
    assert r2["paid_dispatch_entered"] == 0


def test_gap_not_created_when_hermes_resolved():
    assert should_create_gap(hermes_resolved=True, material_stale=False, contradiction_open=False, need_data=False) is False
    assert should_create_gap(hermes_resolved=False, material_stale=False, contradiction_open=False, need_data=True) is True


def test_event_guid_is_period_specific():
    a = event_guid(issuer_guid="iss", event_type="EARNINGS", period="2026_Q3")
    b = event_guid(issuer_guid="iss", event_type="EARNINGS", period="2026_Q4")
    assert a and b and a != b
    scheduled = build_event(issuer_guid="iss", security_guid="sec", event_type="EARNINGS", period="2026_Q3", status="SCHEDULED")
    hist = supersede_scheduled(scheduled, occurred_as_of="2026-08-20")
    assert hist["status"] == "SUPERSEDED"


def test_freshness_policy_has_required_classes():
    required = {
        "intraday_technical", "price_market_state", "breaking_news", "catalyst",
        "analyst_action", "earnings_scheduled", "earnings_result", "company_guidance",
        "sec_filing", "economic_release", "fed_event", "sector_classification",
        "industry_classification", "structural_relationship", "supply_chain_relationship",
        "methodology_canon",
    }
    assert required.issubset(set(POLICY_CLASSES))
    assert classify_evidence_class({"source_type": "8-k"}) == "sec_filing"
    assert freshness_state(None, evidence_class="sec_filing") == "STALE"


def test_librarian_duplicate_decision():
    a = assess_artifact({"title": "t", "summary": "s", "source_url": "https://sec.gov/x", "source_id": "1"})
    b = assess_artifact({"title": "t", "summary": "s", "source_url": "https://sec.gov/x", "source_id": "1"}, prior_hashes={a["content_hash"]})
    assert b["duplicate"] is True
    assert b["decision"] == "IGNORE_DUPLICATE"
    assert b["primary_source"] is True


def test_embed_deferred_is_semantic_pending_not_no_evidence():
    rec = embed_artifact("/tmp", {"research_artifact_guid": "g1", "title": "t"})
    assert rec.get("rag_semantic") == "RAG_SEMANTIC_PENDING"
    assert rec["status"] in ("ACQUIRED", "ACQUIRED_EMBED_PENDING", "EMBEDDED")


def test_curation_cycle_zero_paid(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "NG"}])
    project_hermes_rows(tmp_path, "NOC", rows=_hermes())
    out = curate_security(tmp_path, _profile(), {"symbol": "NOC", "decision": "NO_NEW_INFO", "hermes_resolved": True, "searx_accepted": 0, "path": ["NO_NEW_INFO"]})
    assert out["paid_dispatch"] == 0
    assert out["context_question"] == "WHAT_CHANGED"
    reset_paid_dispatch_probe()
    with pytest.raises(RuntimeError, match="PAID_DISPATCH_FORBIDDEN"):
        dispatch_paid_provider(state="PLANNED", mode="FREE_FIRST_ONLY")
