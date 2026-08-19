"""Gap-driven, budgeted multi-source acquisition plan for symbol theses.

Uses the EXISTING Research Intelligence acquisition plane:
  SearXNG/metasearch, SEC/filings, RSS/news, YouTube/transcripts,
  Financial Senses, deterministic structured data (Alpaca/Finviz/yfinance/FRED).

Does NOT crawl all 5,135 symbols.
Does NOT create a second ingestion system or vector store.
Hermes/DeepSeek Flash are NOT listed as acquisition sources.

Default: plan-only (dry). apply_acquire / apply_embed require explicit flags.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolThesisAcquisitionPlan@v1"

# Acquisition source families (NOT Hermes/Flash)
SOURCE_FAMILIES = (
    "rag_existing",          # already retrieved — never re-crawl
    "searxng_metasearch",
    "sec_filings",
    "rss_news",
    "youtube_transcripts",
    "financial_senses",
    "deterministic_structured",  # alpaca / finviz / yfinance / fred
)

# Per-gap budgets (hard caps)
DEFAULT_BUDGET = {
    "max_searx_queries": 3,
    "max_sec_pulls": 2,
    "max_news_refresh": 1,
    "max_youtube_discover": 2,
    "max_fs_providers": 3,
    "max_structured_reads": 4,
    "max_new_embeds": 20,
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _gap_driven_queries(symbol: str, question: str, evidence_gaps: list[str]) -> dict[str, list[str]]:
    """Concrete queries per source family — gap-driven, not generic crawl."""
    sym = symbol.upper()
    q = (question or "").strip()
    gaps = set(evidence_gaps or [])
    searx: list[str] = []
    sec: list[str] = []
    news: list[str] = []
    yt: list[str] = []
    fs: list[str] = []
    structured: list[str] = []

    # Always: one bull + one bear web probe when RAG insufficient
    if "insufficient_supporting_rag" in gaps or not gaps:
        searx.append(f"{sym} investment thesis catalysts 2025 2026")
    if "insufficient_contradictory_rag" in gaps or not gaps:
        searx.append(f"{sym} risks bear case valuation competition")
    if "no_approved_primary_or_news" in gaps:
        searx.append(f"{sym} SEC 10-K 10-Q earnings filing")
        sec.append("submissions_recent")
        sec.append("companyfacts_key_metrics")
        news.append("refresh_symbol_rss")
        fs.append("sec_edgar")
        fs.append("macro")  # regime context only

    # Question-shaped extras (budgeted)
    ql = q.lower()
    if "re-entry" in ql or "reenter" in ql or "exited" in ql:
        searx.append(f"{sym} why sold why exited institutional ownership change")
        structured.append("finviz_snapshot")
        structured.append("yfinance_fundamentals")
    if "still held" in ql or "trim" in ql or "exit" in ql:
        structured.append("alpaca_bars_or_quote")
        structured.append("finviz_snapshot")
        fs.append("factor_exposure")
    if "role" in ql:
        structured.append("finviz_snapshot")
        yt.append(f"{sym} portfolio role ETF holdings analysis")

    # Dedup preserve order + hard caps applied by caller
    def _dedup(xs: list[str]) -> list[str]:
        seen = set()
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {
        "searxng_metasearch": _dedup(searx),
        "sec_filings": _dedup(sec),
        "rss_news": _dedup(news),
        "youtube_transcripts": _dedup(yt),
        "financial_senses": _dedup(fs),
        "deterministic_structured": _dedup(structured),
    }


def build_acquisition_plan(
    symbol: str,
    *,
    question: str,
    evidence_catalog: dict[str, Any],
    priority: str = "P1",
    budget: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    """Build a source-aware plan ONLY when RAG sufficiency failed.

    If catalog is already sufficient → plan.status = SKIP_ACQUISITION.
    """
    budget = {**DEFAULT_BUDGET, **(budget or {})}
    sufficiency = (evidence_catalog or {}).get("sufficiency") or {}
    gaps = list(sufficiency.get("remaining_evidence_gaps") or [])

    if sufficiency.get("sufficient_for_synthesis"):
        return {
            "schema": SCHEMA,
            "plan_id": "tap_" + _digest(symbol, question, "skip"),
            "symbol": symbol.upper(),
            "question": question,
            "priority": priority,
            "status": "SKIP_ACQUISITION",
            "reason": "existing_rag_and_structured_evidence_sufficient",
            "steps": [],
            "budget": budget,
            "authority": AUTHORITY,
            "financial_action": False,
            "acquire": False,
            "embed": False,
            "hermes_is_acquisition_source": False,
            "as_of": _now(),
        }

    queries = _gap_driven_queries(symbol, question, gaps)
    steps: list[dict[str, Any]] = []

    def _add(family: str, action: str, targets: list[str], cap: int, module_hint: str) -> None:
        targets = targets[:cap]
        if not targets:
            return
        steps.append({
            "family": family,
            "action": action,
            "targets": targets,
            "cap": cap,
            "module_hint": module_hint,
            "status": "PLANNED",
            # Hermes/Flash never appear here
        })

    _add(
        "searxng_metasearch", "metasearch_query",
        queries["searxng_metasearch"], int(budget["max_searx_queries"]),
        "think_tank_signal_miner.mine_web_searx / hermes_youtube_discovery.searx_youtube",
    )
    _add(
        "sec_filings", "sec_edgar_read",
        queries["sec_filings"], int(budget["max_sec_pulls"]),
        "financial_senses.sec_provider.SecEdgarProvider / sec_companyfacts_reader",
    )
    _add(
        "rss_news", "news_refresh_symbol",
        queries["rss_news"], int(budget["max_news_refresh"]),
        "existing news ingestion → news_articles (rag_status=pending until curated)",
    )
    _add(
        "youtube_transcripts", "youtube_discover",
        queries["youtube_transcripts"], int(budget["max_youtube_discover"]),
        "hermes_youtube_discovery (SearXNG youtube category) → youtube_transcripts",
    )
    _add(
        "financial_senses", "fs_provider_read",
        queries["financial_senses"], int(budget["max_fs_providers"]),
        "financial_senses providers (sec_edgar, macro, factor_exposure) — receipts only",
    )
    _add(
        "deterministic_structured", "structured_snapshot",
        queries["deterministic_structured"], int(budget["max_structured_reads"]),
        "finviz_snapshot / yfinance / alpaca quote / FRED series — deterministic only",
    )

    return {
        "schema": SCHEMA,
        "plan_id": "tap_" + _digest(symbol, question, json.dumps(gaps, sort_keys=True)),
        "symbol": symbol.upper(),
        "question": question,
        "priority": priority,
        "status": "ACQUISITION_PLANNED",
        "reason": "rag_insufficient:" + ",".join(gaps) if gaps else "rag_insufficient",
        "evidence_gaps": gaps,
        "steps": steps,
        "budget": budget,
        "curation_gate": {
            "require_rag_status_approved_before_embed": True,
            "require_research_sources_active_or_candidate": True,
            "blocked_statuses": ["blocked", "low_quality"],
            "indexer": "scripts/rag_indexer.py → content_embeddings",
            "no_second_vector_store": True,
        },
        "synthesis_gate": {
            "hermes_flash_role": "synthesis_and_challenge_only",
            "not_acquisition_source": True,
            "requires_cataloged_evidence": True,
            "requires_supporting_and_contradictory": True,
        },
        "authority": AUTHORITY,
        "financial_action": False,
        "acquire": False,  # dry default
        "embed": False,
        "hermes_is_acquisition_source": False,
        "as_of": _now(),
        "note": (
            "Gap-driven and budgeted. Do not crawl the full universe. "
            "Returned evidence must be cataloged (source/freshness/quality/provenance), "
            "curated via rag_status + research_sources, embedded into existing "
            "content_embeddings, THEN Hermes/Flash may synthesize."
        ),
    }


def curate_candidate_for_embed(item: dict[str, Any]) -> dict[str, Any]:
    """Apply existing governance rules before embedding into content_embeddings.

    Mirrors topic_curator / research_sources gates — does not invent a new store.
    """
    status = str(item.get("rag_status") or "pending").lower()
    quality = str(item.get("quality") or "").upper()
    if status in {"blocked", "low_quality"}:
        return {"admit": False, "reason": f"rag_status={status}", "item": item}
    if quality in {"ERROR"}:
        return {"admit": False, "reason": "quality_error", "item": item}
    if item.get("research_source_active") is False:
        return {"admit": False, "reason": "research_source_inactive", "item": item}
    # pending is allowed into indexer queue but flagged
    return {
        "admit": True,
        "reason": "approved" if status == "approved" else "pending_awaiting_curation",
        "embed_ready": status == "approved" or quality in {
            "PRIMARY_REGULATORY", "APPROVED_NEWS", "RAG_HIT"
        },
        "item": item,
    }


def plan_embed_into_existing_rag(
    cataloged_new_items: list[dict[str, Any]],
    *,
    max_embeds: int = 20,
) -> dict[str, Any]:
    """Describe which cataloged items would be indexed via rag_indexer.

    Default dry — does not call rag_indexer. No second vector store.
    """
    admitted = []
    rejected = []
    for it in cataloged_new_items:
        decision = curate_candidate_for_embed(it)
        if decision.get("admit") and decision.get("embed_ready"):
            admitted.append(decision)
        else:
            rejected.append(decision)
    admitted = admitted[:max_embeds]
    return {
        "schema": "SymbolThesisEmbedPlan@v1",
        "target_table": "content_embeddings",
        "indexer": "scripts/rag_indexer.py",
        "second_vector_store": False,
        "apply": False,
        "admitted_count": len(admitted),
        "rejected_count": len(rejected),
        "admitted": admitted,
        "rejected": rejected[:20],
        "authority": AUTHORITY,
        "as_of": _now(),
    }


def dry_run_searx_step(queries: list[str]) -> list[dict[str, Any]]:
    """Optional live SearXNG probe via SHARED searxng_client (no second client).

    Fail-soft. Catalogs hits as pending evidence (not yet embedded).
    """
    out: list[dict[str, Any]] = []
    try:
        from scripts.lib.searxng_client import searx_search
        from scripts.lib.symbol_thesis_evidence import evidence_item, POLARITY_NEUTRAL
    except Exception as exc:
        return [{"error": f"import:{exc}"}]

    for q in queries[:3]:
        for hit in searx_search(q, limit=5):
            if hit.get("error"):
                out.append(hit)
                continue
            out.append(evidence_item(
                fact=(hit.get("snippet") or hit.get("title") or "")[:400],
                title=(hit.get("title") or "")[:200],
                source_type="searxng_web",
                source_id=_digest(hit.get("url"), hit.get("title")),
                polarity=POLARITY_NEUTRAL,
                quality="SECONDARY_RESEARCH",
                rag_status="pending",
                url=hit.get("url"),
                observed_at=_now(),
                provenance={"query": q, "engine": "searxng", "domain": hit.get("domain")},
            ))
    return out
