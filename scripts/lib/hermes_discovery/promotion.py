"""Promotion pathways for Hermes Discovery Inbox candidates (Stage 2).

These four functions are the ONLY way a discovery candidate leaves the inbox
into a real registry:

  promote_source(id)          SOURCE/CONNECTOR → research_sources registry row
                              (registered inactive/candidate; the AUTONOMOUS
                              curation lifecycle in hermes_source_curation.py
                              owns `active` — promotion never force-activates)
  promote_research_topic(id)  TOPIC/TREND → topic_monitor registry (the research
                              topic registry that api_v2 /research-topics/registry
                              reads; same column conventions as the app path)
  promote_watch_directive(id) TREND/TICKER → watch_directives via the EXISTING
                              app-role creation path (api_v2._watch_directive_create)
                              — never a direct INSERT into watch_directives
  promote_ticker(id)          staged TICKER → Trade AI's governed evaluation brain
                              via directive_promotion.promote_directive_lead(
                              source_system='hermes_discovery') — the tier +
                              divergence governor and scalp firewall still apply

Every promotion:
  1. validates the candidate's current status allows the target transition,
  2. writes/reuses the target registry entry,
  3. moves the candidate through inbox.transition_candidate (audited),
  4. stamps promoted_ref_type / promoted_ref_id into meta_json + a PROMOTE
     audit row.

FORBIDDEN-PATH GUARD (enforced at import time by _forbidden_path_guard below and
again by tests/test_hermes_discovery_integration.py):
  * this module never imports brokers/, schwab*, or alpaca* modules;
  * it never writes watchlist tables or the strategy watchpool directly — the
    only sanctioned writers are directive_promotion (app role, governed) and
    api_v2._watch_directive_create (app role, operator path).

All DB work goes through db_adapter._execute (one statement, immediate commit).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import inbox
from .symbol_validation import VERDICT_VALID, validate_ticker


class PromotionError(inbox.DiscoveryInboxError):
    """Raised when a promotion pathway cannot complete (fail-closed)."""


# ── guards / shared helpers ──────────────────────────────────────────────────

def _forbidden_path_guard() -> None:
    """Import-time self-check: no broker imports, no direct watch-table SQL.

    The write-SQL regex targets INSERT/UPDATE/DELETE against the watchlist item
    table or the strategy watchpool table; reads and the sanctioned app-role
    creation paths are allowed.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    import_re = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?"
        r"(brokers\b|schwab\w*|alpaca\w*)", re.MULTILINE)
    m = import_re.search(src)
    assert not m, f"promotion.py must never import broker modules: {m.group(0)!r}"
    write_sql_re = re.compile(
        r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:watchlist_"
        r"items|strategy_watchpool)\b", re.IGNORECASE)
    m = write_sql_re.search(src)
    assert not m, f"promotion.py must never write watch tables directly: {m.group(0)!r}"


def _require_candidate(candidate_id: int, allowed_types: tuple[str, ...],
                       target_status: str) -> dict[str, Any]:
    """Fetch + gate: candidate exists, type matches, transition is legal NOW.

    The legality pre-check runs BEFORE any registry write so an illegal
    promotion never leaves an orphan registry row behind.
    """
    cand = inbox.get_candidate(int(candidate_id))
    if not cand:
        raise inbox.CandidateNotFoundError(f"candidate {candidate_id} not found")
    if cand["candidate_type"] not in allowed_types:
        raise PromotionError(
            f"candidate {candidate_id} is {cand['candidate_type']}; "
            f"this pathway accepts {allowed_types}")
    cur = cand["status"]
    if target_status not in inbox.ALLOWED_TRANSITIONS.get(cur, frozenset()):
        raise inbox.IllegalTransitionError(
            f"illegal promotion {cur} -> {target_status} for candidate {candidate_id} "
            f"(review it first: legal from {sorted(s for s, t in inbox.ALLOWED_TRANSITIONS.items() if target_status in t)})")
    return cand


def _stamp_promotion(candidate_id: int, ref_type: str, ref_id: Any, actor: str,
                     extra: dict | None = None, notes: str | None = None) -> dict[str, Any]:
    """Stamp promoted_ref_type/promoted_ref_id into meta_json + PROMOTE audit."""
    stamp = {"promoted_ref_type": ref_type,
             "promoted_ref_id": str(ref_id) if ref_id is not None else None,
             "promoted_at": datetime.now(timezone.utc).isoformat(),
             "promoted_by": actor}
    if extra:
        stamp.update(extra)
    row = inbox._exec(
        """UPDATE hermes_discovery_candidates
           SET meta_json = meta_json || %s::jsonb, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (json.dumps(stamp, default=str), candidate_id), fetch="one")
    if row is None:
        raise inbox.DBUnavailableError("promotion stamp failed")
    inbox._audit(candidate_id, "PROMOTE", actor, None, stamp,
                 notes or f"promoted -> {ref_type} {stamp['promoted_ref_id']}")
    return dict(row)


def _scripts_on_path() -> None:
    import sys
    scripts_dir = str(Path(__file__).resolve().parents[2])
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


def _slug(text: str, max_len: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:max_len]


# ── pathway 1: research source registry ──────────────────────────────────────

def promote_source(candidate_id: int, *, actor: str = "operator",
                   notes: str | None = None) -> dict[str, Any]:
    """SOURCE_CANDIDATE / CONNECTOR_CANDIDATE → research_sources registry.

    Follows hermes_source_curation.upsert_source conventions (source_type +
    source_name key, specialty as text[], notes carry state). Registered with
    active=FALSE: the autonomous curation lifecycle (yield scoring + LLM vetting
    + OUTCOME_LEDGER verdicts) owns activation — operator approval here only
    registers the source as a vetted candidate and gets it into that loop.
    """
    cand = _require_candidate(candidate_id, ("SOURCE_CANDIDATE", "CONNECTOR_CANDIDATE"),
                              "APPROVED_SOURCE")
    meta = cand.get("meta_json") or {}
    source_name = (cand.get("source_domain") or cand.get("label") or "").strip()
    if not source_name:
        raise PromotionError(f"candidate {candidate_id} has no source_domain/label")
    source_type = (meta.get("source_type")
                   or ("web" if cand["candidate_type"] == "SOURCE_CANDIDATE" else "connector"))
    specialty = meta.get("specialty") or ["web search"]
    if isinstance(specialty, str):
        specialty = [specialty]
    try:
        credibility = int(round(float(meta.get("credibility"))))
    except (TypeError, ValueError):
        credibility = int(round(float(cand.get("discovery_score") or 0) * 100))
    marker = (f"DISCOVERY_INBOX approved candidate #{candidate_id} by {actor} "
              f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')} — pending curation lifecycle")

    existing = inbox._exec(
        "SELECT id, notes FROM research_sources WHERE source_type = %s AND source_name = %s",
        (source_type, source_name), fetch="one")
    if existing:
        row = inbox._exec(
            """UPDATE research_sources
               SET credibility_score = GREATEST(COALESCE(credibility_score, 0), %s),
                   specialty = %s,
                   notes = LEFT(COALESCE(notes, '') || ' | ' || %s, 1000)
               WHERE id = %s RETURNING id""",
            (credibility, specialty, marker, existing["id"]), fetch="one")
    else:
        row = inbox._exec(
            """INSERT INTO research_sources
                   (source_type, source_name, source_url, credibility_score,
                    specialty, active, notes, created_at)
               VALUES (%s, %s, %s, %s, %s, FALSE, %s, NOW()) RETURNING id""",
            (source_type, source_name, cand.get("source_url") or f"https://{source_name}",
             credibility, specialty, marker), fetch="one")
    if row is None:
        raise inbox.DBUnavailableError("research_sources upsert failed")
    source_id = row["id"]

    updated = inbox.transition_candidate(candidate_id, "APPROVED_SOURCE",
                                         actor=actor, notes=notes or marker)
    _stamp_promotion(candidate_id, "research_source", source_id, actor,
                     extra={"source_type": source_type, "source_name": source_name},
                     notes=notes)
    return {"ok": True, "advisory_only": True, "candidate_id": candidate_id,
            "status": updated["status"], "promoted_ref_type": "research_source",
            "promoted_ref_id": str(source_id), "source_type": source_type,
            "source_name": source_name, "reused_existing": bool(existing),
            "note": "registered inactive — autonomous source curation owns activation"}


# ── pathway 2: research topic registry ───────────────────────────────────────

def promote_research_topic(candidate_id: int, *, actor: str = "operator",
                           notes: str | None = None) -> dict[str, Any]:
    """TOPIC_CANDIDATE / TREND_CANDIDATE → topic_monitor (the research topic
    registry; same columns the app path in api_v2._watch_directive_create uses
    when it routes knowledge themes to research). Idempotent on topic_id.
    """
    cand = _require_candidate(candidate_id, ("TOPIC_CANDIDATE", "TREND_CANDIDATE"),
                              "APPROVED_RESEARCH_ONLY")
    meta = cand.get("meta_json") or {}
    label = (cand.get("label") or "").strip()
    topic_id = f"disc{candidate_id}_{_slug(label)}"[:60]
    keywords = [k for k in (meta.get("keywords") or []) if k] or [label]
    row = inbox._exec(
        """INSERT INTO topic_monitor
               (topic_id, display_name, search_queries, priority, agent_owner,
                owner, enabled, max_age_days, min_articles, personal_context)
           VALUES (%s, %s, %s::jsonb, 4, 'Alex', 'shared', true, 30, 3, '')
           ON CONFLICT (topic_id) DO NOTHING RETURNING topic_id""",
        (topic_id, label[:80], json.dumps(keywords[:8])), fetch="one")
    created = row is not None  # None → already registered (idempotent)

    updated = inbox.transition_candidate(candidate_id, "APPROVED_RESEARCH_ONLY",
                                         actor=actor,
                                         notes=notes or f"research topic {topic_id}")
    _stamp_promotion(candidate_id, "research_topic", topic_id, actor,
                     extra={"topic_created": created}, notes=notes)
    return {"ok": True, "advisory_only": True, "candidate_id": candidate_id,
            "status": updated["status"], "promoted_ref_type": "research_topic",
            "promoted_ref_id": topic_id, "topic_created": created,
            "queries": keywords[:8]}


# ── pathway 3: watch directive via the app-role creation path ────────────────

def promote_watch_directive(candidate_id: int, *, actor: str = "operator",
                            notes: str | None = None) -> dict[str, Any]:
    """TREND_CANDIDATE / TICKER_CANDIDATE → watch_directives via the EXISTING
    app-role creation path (api_v2._watch_directive_create). Never a direct
    INSERT. If the app path routes a knowledge theme to the research pipeline
    instead (its documented behavior), the candidate lands at
    APPROVED_RESEARCH_ONLY with a research_topic ref — honest, not forced.

    If the candidate's meta carries existing_directive_id (trend candidates
    observed FROM directive activity), that directive is reused — no duplicate.
    """
    cand = _require_candidate(candidate_id, ("TREND_CANDIDATE", "TICKER_CANDIDATE"),
                              "APPROVED_WATCH_DIRECTIVE")
    meta = cand.get("meta_json") or {}
    label = (cand.get("label") or "").strip()

    existing_id = meta.get("existing_directive_id")
    if existing_id:
        updated = inbox.transition_candidate(candidate_id, "APPROVED_WATCH_DIRECTIVE",
                                             actor=actor,
                                             notes=notes or f"reuse directive {existing_id}")
        _stamp_promotion(candidate_id, "watch_directive", existing_id, actor,
                         extra={"reused_existing_directive": True}, notes=notes)
        return {"ok": True, "advisory_only": True, "candidate_id": candidate_id,
                "status": updated["status"], "promoted_ref_type": "watch_directive",
                "promoted_ref_id": str(existing_id), "reused_existing_directive": True}

    if cand["candidate_type"] == "TICKER_CANDIDATE":
        symbol = label.upper()
        body = {"kind": "ticker", "label": f"Watch {symbol}",
                "spec": {"symbol": symbol},
                "rationale": cand.get("summary") or f"discovery candidate #{candidate_id}",
                "created_by": "hermes_discovery"}
    else:
        keywords = [k for k in (meta.get("keywords") or []) if k] or [label]
        seeds = [s for s in ((cand.get("seed_symbols") or [])
                             or (cand.get("extracted_symbols") or [])) if s]
        body = {"kind": "trend", "label": label,
                "spec": {"keywords": keywords[:10], "seed_symbols": seeds[:10]},
                "rationale": cand.get("summary") or f"discovery candidate #{candidate_id}",
                "created_by": "hermes_discovery"}

    _scripts_on_path()
    import api_v2  # the app-role creation path — reused, never re-implemented
    status_code, resp = api_v2._watch_directive_create(body)
    if status_code != 200 or not (resp or {}).get("ok"):
        raise PromotionError(
            f"app directive-creation path refused: {status_code} {str(resp)[:200]}")

    if resp.get("kind") == "research_topic" or resp.get("routed_to_research"):
        topic_id = (resp.get("research_topic") or {}).get("topic_id")
        updated = inbox.transition_candidate(candidate_id, "APPROVED_RESEARCH_ONLY",
                                             actor=actor,
                                             notes=notes or "app path routed knowledge theme to research")
        _stamp_promotion(candidate_id, "research_topic", topic_id, actor,
                         extra={"routed_by_app_path": True}, notes=notes)
        return {"ok": True, "advisory_only": True, "candidate_id": candidate_id,
                "status": updated["status"], "promoted_ref_type": "research_topic",
                "promoted_ref_id": topic_id, "routed_to_research": True}

    directive_id = resp.get("directive_id")
    updated = inbox.transition_candidate(candidate_id, "APPROVED_WATCH_DIRECTIVE",
                                         actor=actor,
                                         notes=notes or f"directive {directive_id}")
    _stamp_promotion(candidate_id, "watch_directive", directive_id, actor,
                     extra={"directive_reused": bool(resp.get("reused"))}, notes=notes)
    return {"ok": True, "advisory_only": True, "candidate_id": candidate_id,
            "status": updated["status"], "promoted_ref_type": "watch_directive",
            "promoted_ref_id": str(directive_id) if directive_id is not None else None,
            "directive_reused": bool(resp.get("reused")),
            "serviced": resp.get("serviced")}


# ── pathway 4: staged ticker → governed watch evaluation ─────────────────────

def promote_ticker(candidate_id: int, *, directive_id: int | None = None,
                   actor: str = "operator", notes: str | None = None) -> dict[str, Any]:
    """Staged TICKER_CANDIDATE → Trade AI's governed evaluation via
    directive_promotion.promote_directive_lead(source_system='hermes_discovery').

    Fail-closed: the ticker must validate against symbol_profiles (VALID) —
    a shape-accepted token never reaches the evaluation brain. The tier +
    divergence governor inside promote_directive_lead still decides whether
    the lead auto-evaluates or stages for review (auto is NOT forced here).

    watch_directive_hits.directive_id is NOT NULL, so a directive is required:
    pass one, or an existing active ticker directive for the symbol is reused,
    or one is created through the app-role path.
    """
    cand = _require_candidate(candidate_id, ("TICKER_CANDIDATE",),
                              "PROMOTED_TO_WATCH_EVALUATION")
    symbol = (cand.get("label") or "").strip().upper()
    verdict = (cand.get("meta_json") or {}).get("ticker_validation") or validate_ticker(symbol)
    if verdict.get("verdict") != VERDICT_VALID:
        raise PromotionError(
            f"fail-closed: {symbol!r} is not a validated ticker "
            f"({verdict.get('verdict')}: {verdict.get('reason')})")

    created_directive = False
    if directive_id is None:
        row = inbox._exec(
            """SELECT id FROM watch_directives
               WHERE kind = 'ticker' AND status = 'active' AND UPPER(spec->>'symbol') = %s
               ORDER BY id LIMIT 1""", (symbol,), fetch="one")
        if row:
            directive_id = row["id"]
        else:
            _scripts_on_path()
            import api_v2
            status_code, resp = api_v2._watch_directive_create(
                {"kind": "ticker", "label": f"Watch {symbol}",
                 "spec": {"symbol": symbol},
                 "rationale": cand.get("summary") or f"discovery candidate #{candidate_id}",
                 "created_by": "hermes_discovery"})
            if status_code != 200 or not (resp or {}).get("ok") or not resp.get("directive_id"):
                raise PromotionError(
                    f"could not obtain a ticker directive via the app path: "
                    f"{status_code} {str(resp)[:200]}")
            directive_id = resp["directive_id"]
            created_directive = not resp.get("reused")

    _scripts_on_path()
    import directive_promotion as _dp  # governed engine — governor + scalp firewall intact
    result = _dp.promote_directive_lead(
        symbol, int(directive_id),
        notes or f"hermes discovery candidate #{candidate_id}",
        "hermes_discovery", actor=actor)

    updated = inbox.transition_candidate(candidate_id, "PROMOTED_TO_WATCH_EVALUATION",
                                         actor=actor,
                                         notes=notes or f"promote_directive_lead -> {result.get('status')}")
    _stamp_promotion(candidate_id, "watch_evaluation", directive_id, actor,
                     extra={"symbol": symbol, "promotion_status": result.get("status"),
                            "directive_created": created_directive}, notes=notes)
    return {"ok": True, "advisory_only": True, "candidate_id": candidate_id,
            "status": updated["status"], "promoted_ref_type": "watch_evaluation",
            "promoted_ref_id": str(directive_id), "symbol": symbol,
            "evaluation": result}


_forbidden_path_guard()
