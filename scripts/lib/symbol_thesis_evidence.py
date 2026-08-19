"""Symbol-thesis evidence catalog over the EXISTING RAG / RI corpus.

Symbol thesis = structured versioned belief object.
RAG (content_embeddings + governed source tables) = evidence retrieval layer.

Retrieves SUPPORTING and CONTRADICTORY evidence. Does NOT create a second
vector store or ingestion system. READ_ONLY_ADVISORY by default.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolThesisEvidenceCatalog@v1"

# Polarity for thesis refactoring
POLARITY_SUPPORT = "SUPPORTING"
POLARITY_COUNTER = "CONTRADICTORY"
POLARITY_NEUTRAL = "CONTEXT"

# Minimum evidence to skip new acquisition
MIN_SUPPORTING = 2
MIN_COUNTER = 1
MIN_TOTAL_APPROVED = 3


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _age_days(ts: Any) -> Optional[float]:
    if not ts:
        return None
    try:
        if hasattr(ts, "timestamp"):
            dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return None


def _freshness(age: Optional[float], *, soft: float = 14.0, hard: float = 45.0) -> str:
    if age is None:
        return "UNKNOWN"
    if age <= soft:
        return "FRESH"
    if age <= hard:
        return "AGING"
    return "STALE"


def evidence_item(
    *,
    fact: str,
    source_type: str,
    source_id: Any,
    polarity: str,
    title: str = "",
    quality: str = "UNKNOWN",
    rag_status: str | None = None,
    research_source_active: bool | None = None,
    credibility: float | None = None,
    observed_at: Any = None,
    provenance: Optional[dict[str, Any]] = None,
    url: str | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    age = _age_days(observed_at)
    return {
        "evidence_id": "ev_" + _digest(source_type, source_id, polarity, fact[:80]),
        "fact": (fact or title or "")[:500],
        "title": (title or "")[:200],
        "source_type": source_type,
        "source_id": str(source_id) if source_id is not None else None,
        "polarity": polarity,
        "quality": quality,
        "freshness": _freshness(age),
        "age_days": round(age, 1) if age is not None else None,
        "rag_status": rag_status,
        "research_source_active": research_source_active,
        "credibility_score": credibility,
        "observed_at": observed_at.isoformat() if hasattr(observed_at, "isoformat") else (
            str(observed_at) if observed_at else None
        ),
        "url": url,
        "rag_score": score,
        "provenance": provenance or {},
        "authority": AUTHORITY,
    }


def _rag_query_pair(symbol: str, question: str, *, role: str = "") -> tuple[str, str]:
    """Build supporting + contradictory free-text queries for the same gap."""
    base = f"{symbol} {question} {role}".strip()
    support = (
        f"{base} bull case positive catalysts growth drivers why own hold thesis intact"
    )
    counter = (
        f"{base} bear case risks invalidation counter thesis why sell avoid "
        f"competitive threat valuation stretch"
    )
    return support[:500], counter[:500]


def retrieve_rag_for_gap(
    symbol: str,
    *,
    question: str,
    role: str = "",
    limit_each: int = 8,
    conn=None,
) -> dict[str, Any]:
    """RAG-first retrieval: supporting AND contradictory passes.

    Uses existing scripts/rag_retrieval.get_rag_context → content_embeddings.
    Fail-soft if Ollama/DB unavailable.
    """
    support_q, counter_q = _rag_query_pair(symbol, question, role=role)
    supporting: list[dict[str, Any]] = []
    contradictory: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        from rag_retrieval import get_rag_context
    except ImportError:
        try:
            import sys
            root = Path(__file__).resolve().parents[2]
            if str(root / "scripts") not in sys.path:
                sys.path.insert(0, str(root / "scripts"))
            from rag_retrieval import get_rag_context
        except Exception as exc:
            return {
                "ok": False,
                "error": f"rag_import:{exc}",
                "supporting": [],
                "contradictory": [],
                "authority": AUTHORITY,
            }

    for polarity, qtext, bucket in (
        (POLARITY_SUPPORT, support_q, supporting),
        (POLARITY_COUNTER, counter_q, contradictory),
    ):
        try:
            rows = get_rag_context(
                symbol.upper(),
                query_text=qtext,
                limit=limit_each,
                conn=conn,
            ) or []
            for r in rows:
                bucket.append(evidence_item(
                    fact=r.get("title") or "",
                    title=r.get("title") or "",
                    source_type=str(r.get("source_type") or "rag"),
                    source_id=r.get("source_id"),
                    polarity=polarity,
                    quality="RAG_HIT",
                    observed_at=r.get("indexed_at"),
                    score=r.get("rag_score"),
                    provenance={
                        "retrieval": "content_embeddings",
                        "query": qtext[:160],
                        "source_label": r.get("source_label"),
                    },
                ))
        except Exception as exc:
            errors.append(f"{polarity}:{type(exc).__name__}:{exc}")

    return {
        "ok": not errors or bool(supporting or contradictory),
        "symbol": symbol.upper(),
        "support_query": support_q,
        "counter_query": counter_q,
        "supporting": supporting,
        "contradictory": contradictory,
        "errors": errors,
        "authority": AUTHORITY,
    }


def retrieve_structured_sources(
    symbol: str,
    *,
    limit: int = 8,
    conn=None,
) -> list[dict[str, Any]]:
    """Pull already-ingested structured / primary sources (read-only SQL).

    Surfaces: approved news, youtube (approved/pending), sec_form4, FRED via
    embeddings titles, Financial Senses-eligible filing metadata when present.
    Does not call paid providers.
    """
    items: list[dict[str, Any]] = []
    close = False
    cur = None
    try:
        if conn is None:
            from rag_retrieval import _get_conn
            conn = _get_conn()
            close = True
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        sym = symbol.upper()

        # Approved news only (rag_status governance)
        try:
            cur.execute(
                """
                SELECT id, title, source, rag_status, relevance_score, created_at, url
                FROM news_articles
                WHERE symbol=%s AND rag_status='approved'
                ORDER BY created_at DESC LIMIT %s
                """,
                (sym, limit),
            )
            for r in cur.fetchall() or []:
                items.append(evidence_item(
                    fact=r.get("title") or "",
                    title=r.get("title") or "",
                    source_type="news",
                    source_id=r.get("id"),
                    polarity=POLARITY_NEUTRAL,
                    quality="APPROVED_NEWS",
                    rag_status=r.get("rag_status"),
                    observed_at=r.get("created_at"),
                    url=r.get("url"),
                    score=float(r["relevance_score"]) if r.get("relevance_score") is not None else None,
                    provenance={"table": "news_articles", "publisher": r.get("source")},
                ))
        except Exception:
            if conn:
                conn.rollback()

        # YouTube transcripts (prefer approved)
        try:
            cur.execute(
                """
                SELECT id, title, channel_name, rag_status, quality_score, ingested_at
                FROM youtube_transcripts
                WHERE (title ILIKE %s OR COALESCE(strategy_tags::text,'') ILIKE %s)
                  AND COALESCE(rag_status,'pending') NOT IN ('blocked','low_quality')
                ORDER BY (rag_status='approved') DESC, ingested_at DESC
                LIMIT %s
                """,
                (f"%{sym}%", f"%{sym}%", limit),
            )
            for r in cur.fetchall() or []:
                items.append(evidence_item(
                    fact=r.get("title") or "",
                    title=r.get("title") or "",
                    source_type="youtube",
                    source_id=r.get("id"),
                    polarity=POLARITY_NEUTRAL,
                    quality="YOUTUBE",
                    rag_status=r.get("rag_status"),
                    observed_at=r.get("ingested_at"),
                    score=float(r["quality_score"]) if r.get("quality_score") is not None else None,
                    provenance={"table": "youtube_transcripts", "channel": r.get("channel_name")},
                ))
        except Exception:
            if conn:
                conn.rollback()

        # SEC Form 4
        try:
            cur.execute(
                """
                SELECT id, symbol, filer_name, transaction_type, created_at
                FROM sec_form4 WHERE symbol=%s
                ORDER BY created_at DESC LIMIT %s
                """,
                (sym, min(limit, 5)),
            )
            for r in cur.fetchall() or []:
                items.append(evidence_item(
                    fact=f"Form 4 {r.get('transaction_type')} by {r.get('filer_name')}",
                    title=f"{sym} Form 4",
                    source_type="sec_form4",
                    source_id=r.get("id"),
                    polarity=POLARITY_NEUTRAL,
                    quality="PRIMARY_REGULATORY",
                    observed_at=r.get("created_at"),
                    provenance={"table": "sec_form4"},
                ))
        except Exception:
            if conn:
                conn.rollback()

        # research_sources active registry snapshot (governance, not content)
        try:
            cur.execute(
                """
                SELECT source_type, source_name, credibility_score, active, specialty
                FROM research_sources WHERE active=true
                ORDER BY credibility_score DESC NULLS LAST LIMIT 20
                """
            )
            active_sources = cur.fetchall() or []
            items.append(evidence_item(
                fact=f"{len(active_sources)} active research_sources registered for curation gate",
                title="research_sources_active",
                source_type="research_sources_registry",
                source_id="registry",
                polarity=POLARITY_NEUTRAL,
                quality="GOVERNANCE",
                research_source_active=True,
                provenance={
                    "active_names": [r.get("source_name") for r in active_sources[:10]],
                },
            ))
        except Exception:
            if conn:
                conn.rollback()

    except Exception as exc:
        items.append(evidence_item(
            fact=f"structured_retrieve_error:{exc}"[:200],
            source_type="error",
            source_id="structured",
            polarity=POLARITY_NEUTRAL,
            quality="ERROR",
        ))
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if close and conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return items


def catalog_sufficiency(catalog: dict[str, Any]) -> dict[str, Any]:
    """Decide whether existing RAG/structured evidence is enough to synthesize."""
    supporting = list(catalog.get("supporting") or [])
    contradictory = list(catalog.get("contradictory") or [])
    structured = list(catalog.get("structured") or [])
    approved_structured = [
        s for s in structured
        if s.get("rag_status") in ("approved", None) and s.get("quality") not in ("ERROR",)
        and s.get("source_type") != "research_sources_registry"
    ]
    # Prefer approved news / primary regulatory
    primary = [
        s for s in approved_structured
        if s.get("quality") in ("APPROVED_NEWS", "PRIMARY_REGULATORY")
        or s.get("rag_status") == "approved"
    ]
    n_sup = len(supporting)
    n_ctr = len(contradictory)
    n_pri = len(primary)
    gaps = []
    if n_sup < MIN_SUPPORTING:
        gaps.append("insufficient_supporting_rag")
    if n_ctr < MIN_COUNTER:
        gaps.append("insufficient_contradictory_rag")
    if n_pri < 1:
        gaps.append("no_approved_primary_or_news")
    # Sufficient only when BOTH polarity floors met AND no hard gaps remain.
    # Agent-memory RAG hits alone are not enough without approved/primary evidence.
    sufficient = (
        n_sup >= MIN_SUPPORTING
        and n_ctr >= MIN_COUNTER
        and (n_sup + n_ctr + n_pri) >= MIN_TOTAL_APPROVED
        and not gaps
    )
    return {
        "sufficient_for_synthesis": sufficient,
        "counts": {
            "supporting": n_sup,
            "contradictory": n_ctr,
            "structured": len(structured),
            "primary_or_approved": n_pri,
        },
        "remaining_evidence_gaps": gaps,
        "authority": AUTHORITY,
    }


def build_evidence_catalog(
    symbol: str,
    *,
    question: str,
    role: str = "",
    limit_each: int = 8,
    conn=None,
) -> dict[str, Any]:
    """Full RAG-first catalog for one thesis gap (read-only)."""
    rag = retrieve_rag_for_gap(
        symbol, question=question, role=role, limit_each=limit_each, conn=conn
    )
    structured = retrieve_structured_sources(symbol, limit=limit_each, conn=conn)
    catalog = {
        "schema": SCHEMA,
        "as_of": _now(),
        "symbol": symbol.upper(),
        "question": question,
        "portfolio_role": role or None,
        "supporting": rag.get("supporting") or [],
        "contradictory": rag.get("contradictory") or [],
        "structured": structured,
        "support_query": rag.get("support_query"),
        "counter_query": rag.get("counter_query"),
        "rag_ok": rag.get("ok"),
        "rag_errors": rag.get("errors") or [],
        "authority": AUTHORITY,
        "financial_action": False,
        "note": (
            "RAG is the evidence retrieval layer for the living symbol thesis. "
            "Hermes/Flash are NOT acquisition sources."
        ),
    }
    catalog["sufficiency"] = catalog_sufficiency(catalog)
    return catalog
