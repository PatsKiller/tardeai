"""Real FREE_FIRST_ONLY circulation: Hermes → RAG → structured → residual SearXNG.

Never enters dispatch_paid_provider. Projects existing Hermes into artifacts.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


from scripts.lib.artifact_embed import embed_artifact
from scripts.lib.evidence_refresh_job import (
    PAID_FORBIDDEN,
    assert_not_paid,
    paid_dispatch_entered,
    reset_paid_dispatch_probe,
    transition,
)
from scripts.lib.free_first_refresh import reject_paid_transition
from scripts.lib.librarian_assessment import assess_artifact
from scripts.lib.security_identity import attach_identity_v2, classify_unresolved_symbol, normalize_symbol
from scripts.lib.ticker_knowledge_graph import (
    append_record,
    classify_artifact,
    retrieve_context,
)
from scripts.lib.ticker_research_state import build_state, upsert_state

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "FreeFirstCirculationReport@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_hermes_sql(symbol: str, *, research_limit: int = 8, external_limit: int = 4) -> dict[str, list]:
    """Read existing Hermes stores. Fail-soft."""
    try:
        from db_adapter import _execute
    except Exception:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from db_adapter import _execute
        except Exception:
            return {"research": [], "external": []}
    sym = normalize_symbol(symbol)
    research = _execute(
        """SELECT id, topic, summary, thesis, status, research_type, source_urls_json,
                  freshness_date, created_at, quality_score
           FROM hermes_research_intelligence
           WHERE symbol=%s AND status NOT IN ('rejected','superseded')
             AND summary IS NOT NULL
           ORDER BY COALESCE(quality_score,0) DESC, created_at DESC LIMIT %s""",
        (sym, research_limit), fetch="all",
    ) or []
    external = _execute(
        """SELECT id, lane, recommendation, dissent, created_at, status
           FROM hermes_external_research
           WHERE symbol=%s AND recommendation IS NOT NULL AND recommendation NOT LIKE '[%%'
           ORDER BY created_at DESC LIMIT %s""",
        (sym, external_limit), fetch="all",
    ) or []
    return {
        "research": [dict(r) for r in research],
        "external": [dict(r) for r in external],
    }


def project_hermes_rows(root: Path | str, symbol: str, rows: dict[str, list] | None = None) -> dict[str, Any]:
    """Idempotent projection of EXISTING Hermes rows. No new research."""
    state = transition("PLANNED", "FREE_FIRST_RUNNING")
    reject_paid_transition(state, False)
    sym = normalize_symbol(symbol)
    data = rows if rows is not None else _load_hermes_sql(sym)
    before = retrieve_context(root, sym, limit=500)["artifact_count"]
    added = 0
    assessed = []
    for row in data.get("research") or []:
        urls = row.get("source_urls_json") or []
        if isinstance(urls, str):
            try:
                urls = json.loads(urls)
            except json.JSONDecodeError:
                urls = [urls] if urls.startswith("http") else []
        if isinstance(urls, dict):
            urls = list(urls.values())
        sources = [u for u in (urls or []) if u] or [None]
        for url in sources[:3]:
            art = classify_artifact(sym, {
                "source_id": f"hri:{row.get('id')}:{url or row.get('topic')}",
                "source_type": str(row.get("research_type") or "hermes_research"),
                "source_url": url if isinstance(url, str) else None,
                "title": row.get("topic") or f"Hermes {sym}",
                "summary": row.get("thesis") or row.get("summary") or "",
                "as_of": str(row.get("freshness_date") or row.get("created_at") or "")[:32],
                "relationship": "LINEAR",
                "provenance": {
                    "producer": "hermes_research_intelligence",
                    "research_id": row.get("id"),
                    "status": row.get("status"),
                },
            })
            aid = append_record(root, art)
            assessed.append(assess_artifact(art))
            if aid:
                added += 1
    for row in data.get("external") or []:
        rec = str(row.get("recommendation") or "")
        art = classify_artifact(sym, {
            "source_id": f"ext:{row.get('id')}",
            "source_type": f"hermes_external_{str(row.get('lane') or 'lane').lower()}",
            "title": f"Hermes external {row.get('lane')}",
            "summary": rec[:1000],
            "as_of": str(row.get("created_at") or "")[:32],
            "relationship": "LATERAL",
            "provenance": {"producer": "hermes_external_research", "research_id": row.get("id")},
        })
        append_record(root, art)
        assessed.append(assess_artifact(art))
        added += 1
    after = retrieve_context(root, sym, limit=500)
    # append_record returns existing id on dup; count unique artifacts after
    return {
        "ok": True,
        "symbol": sym,
        "rows_examined": len(data.get("research") or []) + len(data.get("external") or []),
        "artifacts_before": before,
        "artifacts_after": after["artifact_count"],
        "assessments": assessed,
        "job_state": "FREE_FIRST_RUNNING",
    }


def _rag(symbol: str, *, limit: int = 4) -> dict[str, Any]:
    try:
        from scripts.lib.symbol_thesis_evidence import retrieve_rag_for_gap
        out = retrieve_rag_for_gap(symbol, question=f"{symbol} thesis catalysts risks", limit_each=limit)
        if out.get("supporting") or out.get("contradictory"):
            return out
    except Exception as exc:
        out = {"ok": False, "error": str(exc), "supporting": [], "contradictory": []}
    # Keyword/SQL over existing content_embeddings — no new vector DB, no paid LLM.
    try:
        from db_adapter import _execute
        rows = _execute(
            """SELECT id, source_type, source_id, title, created_at
               FROM content_embeddings
               WHERE title ILIKE %s
               ORDER BY created_at DESC LIMIT %s""",
            (f"%{normalize_symbol(symbol)}%", limit), fetch="all",
        ) or []
        supporting = [{
            "source_id": dict(r).get("source_id") or dict(r).get("id"),
            "source_type": dict(r).get("source_type") or "rag",
            "title": dict(r).get("title") or "",
            "fact": dict(r).get("title") or "",
            "observed_at": str(dict(r).get("created_at") or ""),
            "polarity": "SUPPORTING",
        } for r in rows]
        return {"ok": bool(supporting), "supporting": supporting, "contradictory": [], "path": "sql_title"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "supporting": [], "contradictory": []}


def _structured(symbol: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Gap-specific structured resolution. A card is identity, not thesis evidence."""
    gaps_ok: list[str] = []
    unresolved_kind = classify_unresolved_symbol(symbol)["kind"]
    if unresolved_kind in ("cusip_or_fixed_income", "fund", "invalid_or_stale"):
        gaps_ok.append("identity_kind:" + unresolved_kind)
    if profile.get("company") and profile.get("sector"):
        gaps_ok.append("identity_metadata")
    items = []
    try:
        from scripts.lib.symbol_thesis_evidence import retrieve_structured_sources
        items = retrieve_structured_sources(symbol, limit=6) or []
        if items:
            gaps_ok.append("news_or_primary_ingested")
    except Exception:
        items = []
    return {"items": items, "gaps_ok": gaps_ok}


def _searx(symbol: str, gap: str) -> list[dict[str, Any]]:
    try:
        from scripts.lib.searxng_client import searx_search
        url = os.getenv("SEARXNG_URL", "http://127.0.0.1:18888/search")
        hits = searx_search(f"{symbol} {gap}", limit=4, timeout=8.0, searx_url=url) or []
        return [h for h in hits if not h.get("error")]
    except Exception:
        return []


def circulate_symbol(
    root: Path | str,
    profile: dict[str, Any],
    *,
    allow_searx: bool = True,
    embed_fn: Callable | None = None,
    hermes_rows: dict[str, list] | None = None,
    rag_fn: Callable | None = None,
    structured_fn: Callable | None = None,
) -> dict[str, Any]:
    """One security through the production free-first sequence. Zero paid."""
    reset_paid_dispatch_probe()
    state = "PLANNED"
    state = transition(state, "FREE_FIRST_RUNNING")
    paid_attempts_before = paid_dispatch_entered()
    sym = normalize_symbol(profile.get("symbol"))
    profile = attach_identity_v2(profile)
    proj = project_hermes_rows(root, sym, rows=hermes_rows)
    hermes_n = int(proj.get("rows_examined") or 0)
    ctx = retrieve_context(root, sym, limit=200)
    artifact_rows = [r for r in (ctx["linear"] + ctx["lateral"] + ctx["vertical"] + ctx["macro"] + ctx["calendar"]) if r.get("research_artifact_guid")]
    hermes_resolved = hermes_n > 0 and len(artifact_rows) > 0

    rag = (rag_fn or _rag)(sym) if True else {}
    rag_items = list(rag.get("supporting") or []) + list(rag.get("contradictory") or [])
    rag_ok = bool(rag.get("ok") and rag_items)
    # Project RAG hits as artifacts (idempotent)
    for item in rag_items[:6]:
        art = classify_artifact(sym, {
            "source_id": f"rag:{item.get('source_id') or item.get('id')}",
            "source_type": item.get("source_type") or "rag",
            "source_url": item.get("url"),
            "title": item.get("title") or item.get("fact") or "",
            "summary": item.get("fact") or "",
            "as_of": item.get("observed_at"),
            "relationship": "LINEAR",
            "provenance": {"producer": "content_embeddings", "polarity": item.get("polarity")},
        })
        append_record(root, art)
        embed_artifact(root, art, embed_fn=embed_fn)

    structured = (structured_fn or _structured)(sym, profile)
    # Structured resolves IDENTITY gaps only unless ingested news/primary exists
    struct_thesis = "news_or_primary_ingested" in structured["gaps_ok"]
    struct_identity_only = bool(structured["gaps_ok"]) and not struct_thesis and not hermes_resolved and not rag_ok

    still_need_research = not hermes_resolved and not rag_ok and not struct_thesis
    searx_hits: list[dict[str, Any]] = []
    searx_accepted: list[dict[str, Any]] = []
    searx_rejected: list[dict[str, Any]] = []
    if allow_searx and still_need_research:
        searx_hits = _searx(sym, "earnings catalyst 2026")
        prior = {str(a.get("content_hash")) for a in artifact_rows}
        for hit in searx_hits:
            a = assess_artifact({
                "title": hit.get("title"), "summary": hit.get("snippet"),
                "source_url": hit.get("url"), "as_of": _now(), "source_type": "news_catalyst",
            }, prior_hashes=prior)
            if a.get("material") and a.get("source_valid"):
                art = classify_artifact(sym, {
                    "source_id": hit.get("url") or hit.get("title"),
                    "source_type": "searxng_web",
                    "source_url": hit.get("url"),
                    "title": hit.get("title") or "",
                    "summary": hit.get("snippet") or "",
                    "relationship": "MACRO",
                    "provenance": {"producer": "searxng", "query": f"{sym} earnings catalyst 2026"},
                })
                append_record(root, art)
                searx_accepted.append(hit)
            else:
                searx_rejected.append(hit)

    ctx2 = retrieve_context(root, sym, limit=400)
    arts = [r for r in (ctx2["linear"] + ctx2["lateral"] + ctx2["vertical"] + ctx2["macro"] + ctx2["calendar"]) if r.get("research_artifact_guid")]
    watermark = str(sorted(r.get("research_artifact_guid") for r in arts))
    assessments = [assess_artifact(r) for r in arts[:12]]

    if hermes_resolved and not searx_accepted:
        decision = "NO_NEW_INFO"
        bucket = "Hermes_resolved"
        next_review = "FRESH_NO_CHANGE"
    elif rag_ok and not hermes_resolved and not searx_accepted:
        decision = "NO_NEW_INFO"
        bucket = "RAG_resolved"
        next_review = "FRESH_NO_CHANGE"
    elif struct_thesis:
        decision = "NO_NEW_INFO"
        bucket = "structured_resolved"
        next_review = "news_or_primary_ingested"
    elif searx_accepted:
        decision = "MATERIAL_CHANGE"
        bucket = "SearXNG_resolved"
        next_review = "LLM_ELIGIBLE_NOT_AUTHORIZED"
    elif struct_identity_only:
        decision = "LLM_ELIGIBLE"
        bucket = "structured_identity_only"
        next_review = "LLM_ELIGIBLE_NOT_AUTHORIZED"
    else:
        decision = "LLM_ELIGIBLE"
        bucket = "unresolved_after_free"
        next_review = "LLM_ELIGIBLE_NOT_AUTHORIZED"

    state = transition(state, "FREE_EVIDENCE_COMPLETE")
    if decision == "NO_NEW_INFO":
        state = transition(state, "COMPLETED")
        llm_flag = None
    else:
        state = transition(state, "LLM_ELIGIBLE")
        state = transition(state, "LLM_ELIGIBLE_NOT_AUTHORIZED")
        llm_flag = "Flash"
        # stop — do not dispatch paid from LLM_ELIGIBLE_NOT_AUTHORIZED

    st = build_state(
        symbol=sym,
        ticker_guid=profile.get("ticker_guid"),
        security_guid=profile.get("security_guid"),
        artifact_guids=[r.get("research_artifact_guid") for r in arts],
        support_guids=[r.get("research_artifact_guid") for r in ctx2["linear"][:8]],
        counter_guids=[r.get("research_artifact_guid") for r in ctx2["lateral"][:4]],
        open_gaps=[] if decision == "NO_NEW_INFO" else [next_review],
        watermark=watermark,
        decision=decision if decision != "LLM_ELIGIBLE" else "LLM_ELIGIBLE_NOT_AUTHORIZED",
        freshness="CURRENT" if arts else "STALE",
        next_review=next_review,
        catalyst_guids=profile.get("catalyst_guids") or [],
    )
    upsert = upsert_state(root, st)
    from scripts.lib.curation_cycle import curate_security
    curation = curate_security(root, profile, {
        "symbol": sym,
        "decision": st["decision"],
        "hermes_resolved": hermes_resolved,
        "searx_accepted": len(searx_accepted),
        "path": [st["decision"]],
    })

    return {
        "symbol": sym,
        "job_state": state,
        "bucket": bucket,
        "decision": st["decision"],
        "hermes_rows_examined": hermes_n,
        "hermes_resolved": hermes_resolved,
        "artifacts": len(arts),
        "rag_attempts": 1,
        "rag_items": len(rag_items),
        "rag_ok": rag_ok,
        "structured_gaps_ok": structured["gaps_ok"],
        "structured_items": len(structured["items"]),
        "searx_queries": 1 if searx_hits or (allow_searx and still_need_research) else 0,
        "searx_accepted": len(searx_accepted),
        "searx_rejected": len(searx_rejected),
        "librarian_assessments": len(assessments),
        "llm_eligible": llm_flag,
        "paid_dispatch_entered": paid_dispatch_entered() - paid_attempts_before,
        "state_wrote": upsert.get("wrote"),
        "curation_wrote": curation.get("curation_wrote"),
        "curation_reason": curation.get("curation_reason"),
        "watermark": watermark,
        "path": [
            "HERMES" if hermes_resolved else None,
            "RAG" if rag_ok else None,
            "STRUCTURED" if structured["gaps_ok"] else None,
            "SEARXNG" if searx_accepted else None,
            st["decision"],
        ],
        "authority": AUTHORITY,
        "financial_action": False,
    }


def circulate_universe(
    root: Path | str,
    *,
    symbols: list[str] | None = None,
    allow_searx: bool = True,
    embed_fn: Callable | None = None,
) -> dict[str, Any]:
    from scripts.lib.free_first_refresh import load_profiles as lp
    profiles = lp(root)
    if symbols:
        want = {normalize_symbol(s) for s in symbols}
        profiles = [p for p in profiles if normalize_symbol(p.get("symbol")) in want]
    rows = [circulate_symbol(root, p, allow_searx=allow_searx, embed_fn=embed_fn) for p in profiles]
    buckets: dict[str, list[str]] = {}
    for r in rows:
        buckets.setdefault(r["bucket"], []).append(r["symbol"])
    flash = [r["symbol"] for r in rows if r.get("llm_eligible") == "Flash"]
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "mode": "FREE_FIRST_ONLY",
        "as_of": _now(),
        "total_symbols": len(rows),
        "persistent_graph_profiled": len(rows),
        "graph_profiled_count": len(rows),
        "free_first_circulated_count": len(rows),
        "not_the_canonical_universe": True,
        "Hermes_resolved": len(buckets.get("Hermes_resolved") or []),
        "RAG_resolved": len(buckets.get("RAG_resolved") or []),
        "structured_resolved": len(buckets.get("structured_resolved") or []),
        "structured_identity_only": len(buckets.get("structured_identity_only") or []),
        "SearXNG_resolved": len(buckets.get("SearXNG_resolved") or []),
        "unresolved_after_free": len(buckets.get("unresolved_after_free") or []),
        "fresh_no_change": sum(1 for r in rows if r["decision"] == "NO_NEW_INFO"),
        "LLM_eligible_not_authorized": sum(1 for r in rows if r["decision"] == "LLM_ELIGIBLE_NOT_AUTHORIZED"),
        "Flash_eligible_count": len(flash),
        "Flash_symbols": flash,
        "OAuth_challenger_count": 0,
        "Pro_eligible_count": 0,
        "paid_dispatch_entered": sum(r["paid_dispatch_entered"] for r in rows),
        "hermes_rows_examined": sum(r["hermes_rows_examined"] for r in rows),
        "artifacts": sum(r["artifacts"] for r in rows),
        "rag_attempts": sum(r["rag_attempts"] for r in rows),
        "rag_items": sum(r["rag_items"] for r in rows),
        "searx_queries": sum(r["searx_queries"] for r in rows),
        "librarian_assessments": sum(r["librarian_assessments"] for r in rows),
        "buckets": {k: sorted(v) for k, v in buckets.items()},
        "rows": rows,
        "financial_action": False,
        "memory_behavior_influence": int(os.getenv("MEMORY_BEHAVIOR_INFLUENCE", "0") or 0),
    }
