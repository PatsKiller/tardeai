"""Consume Cursor's watchlist/discovery DATA PLANE for R7.1 (no rediscovery).

Watchlist membership = universe signal ("deserves consideration").
Thesis evidence = actual artifacts with provenance.

Does NOT import Cursor producer scripts. Reads DB tables they populate.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.symbol_thesis_materiality import classify_materiality

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolThesisSupplyPlane@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _conn():
    try:
        from rag_retrieval import _get_conn
        return _get_conn()
    except Exception:
        import sys
        root = Path(__file__).resolve().parents[2]
        if str(root / "scripts") not in sys.path:
            sys.path.insert(0, str(root / "scripts"))
        from rag_retrieval import _get_conn
        return _get_conn()


def _provenance_state(origin_system: Any, origin_detail: Any) -> str:
    if origin_system in (None, "", "unknown"):
        return "LEGACY_UNATTRIBUTED"
    if not origin_detail:
        return "PROVENANCE_INCOMPLETE"
    return "PROVENANCE_OK"


def load_watchlist_supply(symbol: str, *, conn=None) -> dict[str, Any]:
    """Universe + provenance for one symbol from watchlist_items."""
    close = False
    cur = None
    try:
        if conn is None:
            conn = _conn()
            close = True
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT symbol, status, bucket, source_tier, scope_tier, origin_system,
                   origin_detail, provenance_reason, source, score,
                   hermes_research_score, first_seen_at, last_seen_at, updated_at
            FROM watchlist_items WHERE symbol=%s
            ORDER BY updated_at DESC NULLS LAST LIMIT 5
            """,
            (symbol.upper(),),
        )
        rows = [dict(r) for r in (cur.fetchall() or [])]
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif isinstance(v, dict):
                    pass
                elif v is not None and k == "origin_detail" and not isinstance(v, (dict, list, str)):
                    r[k] = str(v)
        primary = rows[0] if rows else {}
        prov = _provenance_state(primary.get("origin_system"), primary.get("origin_detail"))
        return {
            "symbol": symbol.upper(),
            "watchlist_rows": rows,
            "origin_system": primary.get("origin_system"),
            "origin_detail": primary.get("origin_detail"),
            "bucket": primary.get("bucket"),
            "source_tier": primary.get("source_tier"),
            "scope_tier": primary.get("scope_tier"),
            "provenance_state": prov,
            "membership_means": "deserves_consideration",
            "membership_does_not_mean": ["bullish_thesis", "proven_evidence", "BUY"],
            "authority": AUTHORITY,
        }
    except Exception as exc:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return {"symbol": symbol.upper(), "error": f"{type(exc).__name__}:{exc}", "authority": AUTHORITY}
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


def load_discovery_events(symbol: str, *, limit: int = 10, conn=None) -> list[dict[str, Any]]:
    close = False
    cur = None
    try:
        if conn is None:
            conn = _conn()
            close = True
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT event_id, source_key, symbol, discovered_at, source_confidence,
                   degraded, reason, created_at
            FROM candidate_discovery_events WHERE symbol=%s
            ORDER BY discovered_at DESC NULLS LAST LIMIT %s
            """,
            (symbol.upper(), limit),
        )
        rows = []
        for r in cur.fetchall() or []:
            d = dict(r)
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            rows.append(d)
        return rows
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return []
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


def load_social_evidence(symbol: str, *, limit: int = 8, conn=None) -> dict[str, Any]:
    """Primary = social_sentiment_history rows; derived = intelligence_entities.social_score."""
    close = False
    cur = None
    history: list[dict[str, Any]] = []
    derived_score = None
    try:
        if conn is None:
            conn = _conn()
            close = True
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, observed_at, source_family, source_name, mention_count,
                   bullish_count, bearish_count, neutral_count, sentiment_score,
                   unusual_spike, confidence, provenance
            FROM social_sentiment_history WHERE symbol=%s
            ORDER BY observed_at DESC NULLS LAST LIMIT %s
            """,
            (symbol.upper(), limit),
        )
        for r in cur.fetchall() or []:
            d = dict(r)
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            history.append(d)
        try:
            cur.execute(
                """
                SELECT social_score, social_sentiment, last_enriched
                FROM intelligence_entities
                WHERE display_name=%s OR entity_id=%s
                LIMIT 1
                """,
                (symbol.upper(), symbol.upper()),
            )
            row = cur.fetchone()
            if row:
                derived_score = row.get("social_score")
        except Exception:
            conn.rollback()
    except Exception as exc:
        return {
            "history": [],
            "derived_social_score": None,
            "error": f"{type(exc).__name__}:{exc}",
            "derived_is_not_primary_evidence": True,
        }
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
    return {
        "history": history,
        "derived_social_score": float(derived_score) if derived_score is not None else None,
        "derived_is_not_primary_evidence": True,
        "primary_evidence": "social_sentiment_history",
        "authority": AUTHORITY,
    }


def resolve_candidate_to_evidence_refs(symbol: str, *, conn=None) -> dict[str, Any]:
    """candidate/universe record → evidence_refs[] (no large content copy)."""
    wl = load_watchlist_supply(symbol, conn=conn)
    events = load_discovery_events(symbol, conn=conn)
    social = load_social_evidence(symbol, conn=conn)
    refs = []
    for r in wl.get("watchlist_rows") or []:
        refs.append({
            "kind": "watchlist_membership",
            "id": r.get("id") if "id" in r else f"{r.get('symbol')}:{r.get('bucket')}",
            "origin_system": r.get("origin_system"),
            "is_evidence": False,
            "is_universe_signal": True,
        })
    for e in events:
        refs.append({
            "kind": "candidate_discovery_event",
            "id": e.get("event_id"),
            "source_key": e.get("source_key"),
            "is_evidence": False,
            "is_universe_signal": True,
            "may_wake": ["coverage_check", "materiality_check", "rag_check"],
            "may_not": ["auto_thesis_version"],
        })
    for h in social.get("history") or []:
        refs.append({
            "kind": "social_sentiment_history",
            "id": h.get("id"),
            "source_name": h.get("source_name"),
            "observed_at": h.get("observed_at"),
            "is_evidence": True,
            "is_primary": True,
        })
    if social.get("derived_social_score") is not None:
        refs.append({
            "kind": "intelligence_entities.social_score",
            "value": social.get("derived_social_score"),
            "is_evidence": False,
            "is_derived_ranking_feature": True,
        })
    thesis_evidence_state = "OK"
    if wl.get("provenance_state") == "LEGACY_UNATTRIBUTED":
        thesis_evidence_state = "LEGACY_UNATTRIBUTED"
    elif wl.get("provenance_state") == "PROVENANCE_INCOMPLETE":
        thesis_evidence_state = "PROVENANCE_INCOMPLETE"
    elif (wl.get("bucket") == "research_discovery" and not wl.get("origin_detail")):
        thesis_evidence_state = "PROVENANCE_INCOMPLETE"

    return {
        "schema": "CandidateEvidenceResolver@v1",
        "symbol": symbol.upper(),
        "evidence_refs": refs,
        "thesis_evidence_state": thesis_evidence_state,
        "watchlist_supply": wl,
        "discovery_events_n": len(events),
        "social": {
            "history_n": len(social.get("history") or []),
            "derived_social_score": social.get("derived_social_score"),
            "derived_is_not_primary_evidence": True,
        },
        "authority": AUTHORITY,
        "as_of": _now(),
    }


def materiality_from_supply(
    symbol: str,
    *,
    universe_rec: Optional[dict[str, Any]] = None,
    conn=None,
) -> dict[str, Any]:
    """Combine universe memberships + supply-plane provenance into T0–T4."""
    uni = universe_rec or {}
    supply = resolve_candidate_to_evidence_refs(symbol, conn=conn)
    wl = supply.get("watchlist_supply") or {}
    memberships = list(uni.get("memberships") or [])
    if "WATCHLIST" not in memberships and (wl.get("watchlist_rows")):
        memberships = memberships + ["WATCHLIST"]
    mat = classify_materiality(
        memberships=memberships,
        held=bool(uni.get("held") or "HELD" in memberships),
        reentry_state=(uni.get("reentry") or {}).get("intel_state") if isinstance(uni.get("reentry"), dict) else uni.get("reentry_state"),
        opportunity_rank=(uni.get("opportunity") or {}).get("rank") if isinstance(uni.get("opportunity"), dict) else None,
        scope_tier=wl.get("scope_tier"),
        source_tier=wl.get("source_tier"),
        origin_system=wl.get("origin_system"),
        provenance_complete=wl.get("provenance_state") == "PROVENANCE_OK",
        social_score=(supply.get("social") or {}).get("derived_social_score"),
    )
    return {
        **mat,
        "supply_thesis_evidence_state": supply.get("thesis_evidence_state"),
        "evidence_refs_n": len(supply.get("evidence_refs") or []),
        "symbol": symbol.upper(),
    }


def recent_discovery_for_thesis(
    *,
    limit: int = 40,
    conn=None,
) -> dict[str, Any]:
    """List recent research_discovery / discovery events for thesis intake (budgeted)."""
    close = False
    cur = None
    try:
        if conn is None:
            conn = _conn()
            close = True
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT symbol, status, bucket, source_tier, origin_system, origin_detail,
                   provenance_reason, first_seen_at, scope_tier
            FROM watchlist_items
            WHERE bucket='research_discovery' OR source_tier='candidate'
            ORDER BY first_seen_at DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        )
        rows = []
        ignored = 0
        material = 0
        for r in cur.fetchall() or []:
            d = dict(r)
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            prov = _provenance_state(d.get("origin_system"), d.get("origin_detail"))
            mat = classify_materiality(
                memberships=["WATCHLIST"],
                source_tier=d.get("source_tier"),
                scope_tier=d.get("scope_tier"),
                origin_system=d.get("origin_system"),
                provenance_complete=prov == "PROVENANCE_OK",
            )
            d["provenance_state"] = prov
            d["materiality_tier"] = mat["materiality_tier"]
            d["expensive_thesis_work_allowed"] = mat["expensive_thesis_work_allowed"]
            d["membership_is_not_evidence"] = True
            if mat["expensive_thesis_work_allowed"]:
                material += 1
            else:
                ignored += 1
            rows.append(d)
        return {
            "schema": SCHEMA,
            "as_of": _now(),
            "new_candidates": len(rows),
            "material_for_expensive_thesis": material,
            "ignored_low_priority": ignored,
            "rows": rows,
            "note": "Discovery candidates are universe signals; thesis still requires evidence artifacts.",
            "authority": AUTHORITY,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "authority": AUTHORITY}
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
