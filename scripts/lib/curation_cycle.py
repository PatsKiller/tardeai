"""Deterministic curation after free-first. Zero paid. Version only on material delta."""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.lib.contradiction_graph import build_contradiction, upsert_contradiction
from scripts.lib.hermes_curation_summary import build_summary, load_latest, upsert_summary
from scripts.lib.hermes_research_context import build_context
from scripts.lib.librarian_assessment import assess_artifact
from scripts.lib.research_gap import build_gap, should_create_gap, upsert_gap
from scripts.lib.ticker_knowledge_graph import retrieve_context

AUTHORITY = "READ_ONLY_ADVISORY"


def _arts(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in (ctx["linear"] + ctx["lateral"] + ctx["vertical"] + ctx["macro"] + ctx["calendar"]) if r.get("research_artifact_guid")]


def curate_security(root: Path | str, profile: dict[str, Any], circulate_row: dict[str, Any]) -> dict[str, Any]:
    """Apply Librarian + curation version rule. Never calls a provider."""
    sym = circulate_row.get("symbol") or profile.get("symbol")
    ctx = retrieve_context(root, sym, limit=400)
    arts = _arts(ctx)
    prior_hashes = {str(a.get("content_hash")) for a in arts if a.get("content_hash")}
    assessments = [assess_artifact(a, prior_hashes=prior_hashes - {str(a.get("content_hash"))}) for a in arts]
    mix = Counter(a.get("evidence_class") for a in assessments)
    freshness_counts = Counter(a.get("freshness_state") for a in assessments)
    watermark = str(sorted(a.get("research_artifact_guid") for a in arts))
    prev = load_latest(root, security_guid=profile.get("security_guid"), symbol=sym)
    material = circulate_row.get("decision") not in ("NO_NEW_INFO",) or bool(circulate_row.get("searx_accepted"))
    if prev is None:
        material = False
        what = "BASELINE_PROJECTION"
    elif prev.get("evidence_watermark") == watermark:
        material = False
        what = "NO_NEW_INFO"
    else:
        what = "watermark_changed" if material else "NO_NEW_INFO"
    support = [a.get("research_artifact_guid") for a in ctx["linear"][:8]]
    counter = [a.get("research_artifact_guid") for a in ctx["lateral"][:4]]
    summary = build_summary(
        security_guid=profile.get("security_guid"),
        issuer_guid=profile.get("issuer_guid"),
        listing_guid=profile.get("listing_guid"),
        symbol=sym,
        evidence_watermark=watermark,
        previous=prev,
        support_guids=support,
        counter_guids=counter,
        catalyst_guids=profile.get("catalyst_guids") or [],
        calendar_guids=profile.get("calendar_event_guids") or [],
        sector_guid=profile.get("sector_guid"),
        industry_guid=profile.get("industry_guid"),
        theme_guids=profile.get("theme_guids") or [],
        peer_guids=profile.get("peer_guids") or [],
        open_gap_ids=[],
        contradictions=[],
        freshness_summary=",".join(f"{k}:{v}" for k, v in sorted(freshness_counts.items())),
        source_mix=dict(mix),
        source_sha=str(os.getenv("FREE_FIRST_SOURCE_SHA") or ""),
        what_changed=what,
        next_review=str(circulate_row.get("path", ["FRESH_NO_CHANGE"])[-1] if circulate_row.get("path") else "FRESH_NO_CHANGE"),
        material=material,
        conclusion=str(circulate_row.get("decision") or "NO_NEW_INFO"),
    )
    wrote = upsert_summary(root, summary, material=material)
    gap_needed = should_create_gap(
        hermes_resolved=bool(circulate_row.get("hermes_resolved")),
        material_stale=freshness_counts.get("STALE", 0) == len(assessments) and assessments,
        contradiction_open=False,
        need_data=circulate_row.get("decision") == "LLM_ELIGIBLE_NOT_AUTHORIZED",
    )
    gap_res = {"wrote": False}
    if gap_needed:
        gap = build_gap(
            security_guid=profile.get("security_guid"),
            symbol=sym,
            reason="unresolved_after_free" if not circulate_row.get("hermes_resolved") else "all_stale",
            question="material evidence missing or stale",
            materiality="high" if not circulate_row.get("hermes_resolved") else "low",
            status="LLM_ELIGIBLE_NOT_AUTHORIZED" if circulate_row.get("decision") == "LLM_ELIGIBLE_NOT_AUTHORIZED" else "OPEN",
        )
        gap_res = upsert_gap(root, gap)
    contra_res = {"wrote": False}
    if support and counter and not circulate_row.get("hermes_resolved"):
        contra_res = upsert_contradiction(root, build_contradiction(
            security_guid=profile.get("security_guid"), symbol=sym, topic="support_vs_counter",
            support_guids=support, counter_guids=counter,
        ))
    context = build_context(identity=profile, curation=wrote.get("summary") or prev, state=None)
    return {
        "symbol": sym,
        "curation_wrote": wrote.get("wrote"),
        "curation_reason": wrote.get("reason"),
        "curation_version": (wrote.get("summary") or {}).get("version"),
        "gap_wrote": gap_res.get("wrote"),
        "contradiction_wrote": contra_res.get("wrote"),
        "assessments": len(assessments),
        "freshness": dict(freshness_counts),
        "primary": sum(1 for a in assessments if a.get("primary_source")),
        "duplicate": sum(1 for a in assessments if a.get("duplicate")),
        "context_question": context["question"],
        "authority": AUTHORITY,
        "paid_dispatch": 0,
    }
