"""Thesis-gap → Research Intelligence multi-source plane (NOT Hermes-as-source).

Pipeline (gap-driven, budgeted — never crawl all 5,135 symbols):

  1. Specific unanswered investment question (from coverage gap)
  2. RAG-first retrieval — supporting AND contradictory
     (existing content_embeddings via rag_retrieval)
  3. Structured / primary pulls already in corpus (approved news, SEC, YT, FS)
  4. If insufficient → source-aware acquisition plan:
       SearXNG/metasearch, SEC/filings, RSS/news, YouTube/transcripts,
       Financial Senses, deterministic (Alpaca/Finviz/yfinance/FRED)
  5. Catalog evidence (source/freshness/quality/provenance)
  6. Curate via rag_status + research_sources governance
  7. Embed approved content into EXISTING content_embeddings (rag_indexer)
  8. ONLY THEN Hermes / DeepSeek Flash for synthesis + challenge
     → reconcile_symbol_thesis

Symbol thesis = structured versioned belief object.
RAG = its evidence retrieval layer.
No second ingestion system. No second vector store.

Default: DRY (plan + retrieve only). apply_acquire / apply_embed / call_llm
require explicit opt-in. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.research_need_decision import decide as decide_research_need
from scripts.lib.symbol_thesis_acquisition import (
    build_acquisition_plan,
    plan_embed_into_existing_rag,
)
from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol, watchlist_materiality
from scripts.lib.symbol_thesis_coverage import (
    build_coverage_report,
    research_gap_triggers,
    symbol_thesis_id,
)
from scripts.lib.symbol_thesis_evidence import build_evidence_catalog
from scripts.lib.symbol_thesis_synthesis import build_synthesis_packet

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolThesisResearchRequest@v1"
PIPELINE_SCHEMA = "SymbolThesisRIPipeline@v1"

PRIORITY_ORDER = ("P0", "P1", "P2", "P3")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _specific_question(symbol: str, gap: str, *, memberships: list[str], role: str, thesis_state: str) -> str:
    """Turn a coverage gap string into a concrete unanswered investment question."""
    g = (gap or "").lower()
    memb = set(memberships or [])
    if "conflict" in g or thesis_state == "CONFLICTED":
        return (
            f"Why is {symbol} currently held while thesis stance conflicts? "
            f"What evidence resolves hold vs avoid for role={role}?"
        )
    if "stale" in g or thesis_state == "STALE":
        return (
            f"What material facts changed for {symbol} since last thesis review? "
            f"Does the living thesis still justify current memberships={sorted(memb)}?"
        )
    if "re-entry" in g or "reentry" in g or ("REENTRY" in memb and "missing" in g):
        return (
            f"For former holding {symbol}: why was it owned, why exited, is the thesis intact, "
            f"and what specific evidence would move NEAR→RE_ENTER without bypassing gates?"
        )
    if "role" in g and "unknown" in g:
        return (
            f"What portfolio role should {symbol} occupy (CORE/GROWTH/INCOME/SATELLITE/HEDGE) "
            f"and what operator/historical evidence supports it?"
        )
    if (
        "why owned" in g or "why exit" in g or "living thesis" in g
        or "missing" in g or g.startswith("create ")
    ):
        if "HELD" in memb:
            return (
                f"Why is {symbol} still held (role={role})? State positive case, counter-thesis, "
                f"and what would justify ADD vs TRIM vs EXIT."
            )
        if "REENTRY" in memb or "FORMER_HOLDING" in memb:
            return (
                f"Build living exit/re-entry thesis for {symbol}: why previously owned, why exited, "
                f"what changed since exit, market/sector fit, and research gaps."
            )
        if "OPPORTUNITY" in memb:
            return (
                f"What specific thesis would make {symbol} actionable vs WATCH? "
                f"List unresolved evidence domains blocking ADD/REENTER."
            )
        return (
            f"Create a living symbol thesis for {symbol}: memberships={sorted(memb)}, "
            f"role={role}, stance, invalidation, counter-thesis, research gaps."
        )
    if "invalidation" in g or "what changes" in g:
        return (
            f"What explicit invalidation conditions and 'what changes my mind' criteria "
            f"should govern {symbol} for role={role}?"
        )
    return (
        f"For {symbol} (state={thesis_state}, role={role}): resolve gap — {gap[:160]}"
    )


def _priority_band(
    *,
    memberships: list[str],
    thesis_state: str,
    reentry_state: str | None,
    opportunity_rank: Any,
    materiality: str,
) -> str:
    m = set(memberships or [])
    if "HELD" in m and thesis_state == "CONFLICTED":
        return "P0"
    if "HELD" in m and thesis_state in {"RESEARCH_REQUIRED", "STALE", "INSUFFICIENT_DATA"}:
        return "P1"
    rs = str(reentry_state or "").upper()
    if ("REENTRY" in m or "FORMER_HOLDING" in m) and any(
        x in rs for x in ("NEAR", "READY", "IN_ZONE", "REENTER")
    ):
        return "P1"
    try:
        rank = int(opportunity_rank) if opportunity_rank is not None else 999
    except (TypeError, ValueError):
        rank = 999
    if "OPPORTUNITY" in m and rank <= 20 and thesis_state in {
        "RESEARCH_REQUIRED", "STALE", "CONFLICTED", "INSUFFICIENT_DATA"
    }:
        return "P1"
    if materiality in {"ACTIVE_MATERIAL", "ACTIVE_LOW_PRIORITY"} and "WATCHLIST" in m:
        return "P2"
    return "P3"


def _domains_for_gap(gap: str, memberships: list[str]) -> list[str]:
    """Evidence domains map to RI acquisition families — not 'ask Hermes'."""
    g = (gap or "").lower()
    domains = [
        "rag_existing",
        "searxng_metasearch",
        "sec_filings",
        "rss_news",
        "deterministic_structured",
    ]
    if "re-entry" in g or "reentry" in g or "REENTRY" in memberships:
        domains.extend(["youtube_transcripts", "financial_senses"])
    if "conflict" in g or "counter" in g:
        domains.append("financial_senses")
    if "HELD" in memberships:
        domains.append("financial_senses")
    seen = set()
    out = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def build_research_request(
    symbol: str,
    *,
    gap: str,
    thesis_fields: dict[str, Any],
    coverage_row: Optional[dict[str, Any]] = None,
    parent_run: str | None = None,
    parent_product: str | None = None,
    budget_revisit_hours: int = 72,
) -> dict[str, Any]:
    """One specific research request — RI plane, never vague 'research SCHG'."""
    cov = coverage_row or {}
    memberships = list(thesis_fields.get("memberships") or cov.get("memberships") or [])
    role = str(thesis_fields.get("portfolio_role") or "UNKNOWN")
    thesis_state = str(thesis_fields.get("thesis_state") or cov.get("coverage_state") or "INSUFFICIENT_DATA")
    materiality = watchlist_materiality(
        memberships,
        thesis_state=thesis_state,
        opp_rank=cov.get("opportunity_rank") or thesis_fields.get("opportunity_rank"),
    )
    priority = _priority_band(
        memberships=memberships,
        thesis_state=thesis_state,
        reentry_state=cov.get("reentry_state") or thesis_fields.get("reentry_state"),
        opportunity_rank=cov.get("opportunity_rank"),
        materiality=materiality,
    )
    question = _specific_question(
        symbol, gap, memberships=memberships, role=role, thesis_state=thesis_state
    )
    need = decide_research_need({
        "symbol": symbol,
        "held": "HELD" in memberships,
        "material": materiality == "ACTIVE_MATERIAL",
        "contradictions": thesis_state == "CONFLICTED",
        "research_complete": False,
        "questions": [{"dim": "thesis_gap", "q": question}],
    })
    req_id = "str_" + _digest(symbol, gap, thesis_fields.get("symbol_thesis_version"), question)
    return {
        "schema": SCHEMA,
        "request_id": req_id,
        "symbol": symbol.upper(),
        "thesis_id": thesis_fields.get("symbol_thesis_id") or symbol_thesis_id(symbol),
        "thesis_version": thesis_fields.get("symbol_thesis_version"),
        "research_gap": gap,
        "specific_question": question,
        "why_needed": (
            f"thesis_state={thesis_state}; memberships={sorted(set(memberships))}; "
            f"role={role}; materiality={materiality}"
        ),
        "priority": priority,
        "required_evidence_domains": _domains_for_gap(gap, memberships),
        "acquisition_plane": "research_intelligence_multi_source",
        "hermes_role": "synthesis_and_challenge_only",
        "hermes_is_acquisition_source": False,
        "pipeline": [
            "rag_retrieve_supporting_and_contradictory",
            "structured_corpus_read",
            "if_insufficient: budgeted_multi_source_acquire",
            "catalog_provenance",
            "curate_rag_status_research_sources",
            "embed_existing_content_embeddings",
            "hermes_or_flash_synthesize_challenge",
            "reconcile_symbol_thesis",
        ],
        "current_stance": thesis_fields.get("thesis_stance"),
        "counter_thesis": thesis_fields.get("counter_evidence") or [],
        "requested_at": _now(),
        "parent_run": parent_run,
        "parent_product": parent_product,
        "budget_revisit_hours": budget_revisit_hours if priority != "P0" else 24,
        "research_need_decision": need.get("decision"),
        "materiality": materiality,
        "enqueue": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def run_ri_pipeline_for_gap(
    symbol: str,
    *,
    gap: str | None = None,
    question: str | None = None,
    root: Path | str | None = None,
    retrieve: bool = True,
    apply_acquire: bool = False,
    apply_embed: bool = False,
    call_llm: bool = False,
) -> dict[str, Any]:
    """Execute (or dry-run) the full RI pipeline for one symbol thesis gap.

    Defaults are safe: retrieve + plan only. No universe crawl. No LLM call.
    apply_acquire / apply_embed / call_llm must be explicitly enabled.
    """
    root = _root(root)
    fields = thesis_fields_for_symbol(symbol, root=root)
    memberships = list(fields.get("memberships") or [])
    role = str(fields.get("portfolio_role") or "UNKNOWN")
    thesis_state = str(fields.get("thesis_state") or "INSUFFICIENT_DATA")
    gap = gap or (
        (fields.get("research_gaps") or ["Create living symbol thesis"])[0]
    )
    question = question or _specific_question(
        symbol, gap, memberships=memberships, role=role, thesis_state=thesis_state
    )

    catalog = None
    if retrieve:
        catalog = build_evidence_catalog(
            symbol, question=question, role=role, limit_each=8
        )
    else:
        catalog = {
            "supporting": [], "contradictory": [], "structured": [],
            "sufficiency": {"sufficient_for_synthesis": False,
                           "remaining_evidence_gaps": ["retrieve_skipped"]},
        }

    plan = build_acquisition_plan(
        symbol,
        question=question,
        evidence_catalog=catalog,
        priority=_priority_band(
            memberships=memberships,
            thesis_state=thesis_state,
            reentry_state=fields.get("reentry_state"),
            opportunity_rank=None,
            materiality=watchlist_materiality(memberships, thesis_state=thesis_state),
        ),
    )

    # Opt-in acquire: only SearXNG dry probe today (other families stay planned)
    acquired_items: list[dict[str, Any]] = []
    if apply_acquire and plan.get("status") == "ACQUISITION_PLANNED":
        from scripts.lib.symbol_thesis_acquisition import dry_run_searx_step
        for step in plan.get("steps") or []:
            if step.get("family") == "searxng_metasearch":
                acquired_items.extend(dry_run_searx_step(step.get("targets") or []))
                step["status"] = "DRY_EXECUTED"
        plan["acquire"] = True

    embed_plan = plan_embed_into_existing_rag(
        acquired_items,
        max_embeds=int((plan.get("budget") or {}).get("max_new_embeds") or 20),
    )
    if apply_embed:
        # Explicitly do NOT auto-write production embeddings in this PR boundary
        # unless operator later enables a governed path. Keep plan only.
        embed_plan["apply"] = False
        embed_plan["note"] = (
            "apply_embed requested but production embed remains gated — "
            "use scripts/rag_indexer.py under existing curation after rag_status=approved"
        )

    packet = build_synthesis_packet(
        symbol,
        question=question,
        evidence_catalog=catalog,
        acquisition_plan=plan,
        thesis_fields=fields,
        portfolio_role=role,
    )
    packet["call_llm"] = bool(call_llm) and packet.get("gate") == "READY_FOR_SYNTHESIS"

    return {
        "schema": PIPELINE_SCHEMA,
        "as_of": _now(),
        "symbol": symbol.upper(),
        "gap": gap,
        "specific_question": question,
        "evidence_catalog": {
            "sufficiency": catalog.get("sufficiency"),
            "supporting_n": len(catalog.get("supporting") or []),
            "contradictory_n": len(catalog.get("contradictory") or []),
            "structured_n": len(catalog.get("structured") or []),
            "support_query": catalog.get("support_query"),
            "counter_query": catalog.get("counter_query"),
            # keep slim samples for audit
            "supporting_sample": (catalog.get("supporting") or [])[:3],
            "contradictory_sample": (catalog.get("contradictory") or [])[:3],
        },
        "acquisition_plan": plan,
        "acquired_items_n": len(acquired_items),
        "embed_plan": embed_plan,
        "synthesis_packet": {
            "packet_id": packet.get("packet_id"),
            "gate": packet.get("gate"),
            "llm_lanes": packet.get("llm_lanes"),
            "call_llm": packet.get("call_llm"),
            "instructions_role": (packet.get("instructions") or {}).get("role"),
        },
        "full_synthesis_packet": packet if call_llm else None,
        "hermes_is_acquisition_source": False,
        "second_vector_store": False,
        "universe_crawl": False,
        "authority": AUTHORITY,
        "financial_action": False,
        "flags": {
            "retrieve": retrieve,
            "apply_acquire": apply_acquire,
            "apply_embed": apply_embed,
            "call_llm": call_llm,
        },
    }


def propose_prioritized_research(
    *,
    root: Path | str | None = None,
    material_only: bool = True,
    max_p3: int = 5,
    limit: int = 40,
    parent_run: str | None = None,
    parent_product: str | None = None,
    run_pipeline_preview: int = 3,
) -> dict[str, Any]:
    """DRY prioritized thesis-gap set with RI pipeline previews for top N.

    Does not enqueue Hermes jobs as acquisition. Does not crawl 5,010 discovery rows.
    """
    root = _root(root)
    report = build_coverage_report(root=root, material_only=False)
    triggers = research_gap_triggers(report, limit=500)

    requests: list[dict[str, Any]] = []
    skipped_discovery = 0
    p3_count = 0
    by_sym = {r["symbol"]: r for r in (report.get("rows") or [])}

    for t in triggers:
        sym = t["symbol"]
        cov = by_sym.get(sym) or {}
        memberships = list(cov.get("memberships") or [])
        thesis_state = str(cov.get("coverage_state") or "")
        materiality = watchlist_materiality(
            memberships,
            thesis_state=thesis_state,
            opp_rank=cov.get("opportunity_rank"),
        )
        if materiality == "DISCOVERY_ONLY" and thesis_state == "INSUFFICIENT_DATA":
            skipped_discovery += 1
            continue
        if material_only and materiality not in {
            "ACTIVE_MATERIAL", "ACTIVE_LOW_PRIORITY", "RESEARCH_REQUIRED"
        }:
            if not cov.get("material"):
                skipped_discovery += 1
                continue

        fields = thesis_fields_for_symbol(sym, root=root)
        gaps = list(t.get("research_gaps") or fields.get("research_gaps") or [])
        if not gaps:
            gaps = ["Create living symbol thesis with invalidation and counter-thesis"]

        req = build_research_request(
            sym,
            gap=gaps[0],
            thesis_fields=fields,
            coverage_row=cov,
            parent_run=parent_run,
            parent_product=parent_product,
        )
        if req["priority"] == "P3":
            if p3_count >= max_p3:
                skipped_discovery += 1
                continue
            p3_count += 1
        requests.append(req)
        if len(requests) >= limit:
            break

    rank = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    requests.sort(key=lambda r: (rank.get(r["priority"], 9), r["symbol"]))

    by_pri: dict[str, int] = {p: 0 for p in PRIORITY_ORDER}
    for r in requests:
        by_pri[r["priority"]] = by_pri.get(r["priority"], 0) + 1

    # Pipeline preview for top N (RAG retrieve — may hit DB/Ollama; fail-soft)
    previews = []
    for r in requests[: max(0, int(run_pipeline_preview))]:
        try:
            previews.append(run_ri_pipeline_for_gap(
                r["symbol"],
                gap=r["research_gap"],
                question=r["specific_question"],
                root=root,
                retrieve=True,
                apply_acquire=False,
                apply_embed=False,
                call_llm=False,
            ))
        except Exception as exc:
            previews.append({
                "symbol": r["symbol"],
                "error": f"{type(exc).__name__}:{exc}",
                "hermes_is_acquisition_source": False,
            })

    return {
        "schema": "SymbolThesisResearchProposal@v1",
        "as_of": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
        "enqueued": False,
        "acquisition_plane": "research_intelligence_multi_source",
        "hermes_is_acquisition_source": False,
        "note": (
            "DRY proposal. RAG-first then budgeted multi-source plan. "
            "Hermes/Flash = synthesis/challenge only after curated embed. "
            "Discovery-only INSUFFICIENT_DATA rows are not auto-queued."
        ),
        "counts": {
            "proposed": len(requests),
            "skipped_discovery_or_capped": skipped_discovery,
            "by_priority": by_pri,
            "universe_rows": (report.get("coverage_counts") or {}).get("rows"),
            "research_required_material": (report.get("coverage_counts") or {}).get("RESEARCH_REQUIRED"),
            "pipeline_previews": len(previews),
        },
        "requests": requests,
        "pipeline_previews": previews,
        "coverage_counts": report.get("coverage_counts"),
    }


def research_requests_for_symbol(
    symbol: str,
    *,
    root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """All specific gaps for one symbol (dry request objects)."""
    root = _root(root)
    fields = thesis_fields_for_symbol(symbol, root=root)
    gaps = list(fields.get("research_gaps") or [])
    if not gaps and fields.get("thesis_state") in {
        "RESEARCH_REQUIRED", "STALE", "CONFLICTED", "INSUFFICIENT_DATA"
    }:
        gaps = [f"Living thesis incomplete ({fields.get('thesis_state')})"]
    return [
        build_research_request(symbol, gap=g, thesis_fields=fields)
        for g in gaps
    ]
