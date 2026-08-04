"""Autonomous candidate promotion lane — curator acts, operator audits.

Only candidates meeting ALL rails may auto-promote; everything else waits:
  * status READY_FOR_REVIEW
  * safe_action_level in {RESEARCH_ONLY, AUTO_STAGE_INSIDE_RAILS}
  * meta_json.llm_review_json.recommended_action in PROMOTIVE_ACTIONS
  * discovery_score >= config min_score (default 0.60)
  * domain_risk_level NOT IN {tax, legal, planning, medical}
  * do_no_harm scorecard recommendation != "pause"
  * per-day caps: max_research_topics 4, max_sources 1, max_ticker_stages 3

Every action: hermes_discovery_audit row with actor='autonomous_curator',
rollback_sql, and the promotion stamp (promoted_ref_type/ref_id). Never
imports broker modules — import-time _forbidden_path_guard (same regex as
promotion.py).

Phase 1 — advisory-only, kill-switched via HERMES_DISABLED.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

import psycopg2

from . import inbox
from . import promotion as _promo


# ── config ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "hermes_discovery_autonomy.json"
SCORECARD_PATH = ROOT / "data" / "runtime" / "hermes_discovery_scorecard.json"
KILL_FILE = ROOT / "data" / "runtime" / "HERMES_DISABLED"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


CONFIG = _load_config()

MIN_SCORE = CONFIG.get("min_score", 0.60)
REQUIRE_LLM_REVIEW = CONFIG.get("require_llm_review", True)
MAX_TOPICS_PER_DAY = CONFIG.get("max_research_topics_per_day", 4)
MAX_SOURCES_PER_DAY = CONFIG.get("max_sources_per_day", 1)
MAX_TICKER_STAGES_PER_DAY = CONFIG.get("max_ticker_stages_per_day", 3)
DOMAINS_NEVER_AUTO = frozenset(CONFIG.get("domains_never_auto",
    ["tax", "legal", "planning", "medical"]))
RESPECT_DO_NO_HARM = CONFIG.get("respect_do_no_harm", True)

# recommended_action values that map to promotion pathways
PROMOTIVE_ACTIONS: dict[str, str] = {
    "approve_research_topic": "research_topic",
    "approve_source":          "source",
    "stage_ticker_review":     "ticker",
}


# ── guards ─────────────────────────────────────────────────────────────────────

def _forbidden_path_guard() -> None:
    """Import-time self-check: no broker imports, no direct watch-table SQL."""
    src = Path(__file__).read_text(encoding="utf-8")
    import_re = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?"
        r"(brokers\b|schwab\w*|alpaca\w*)", re.MULTILINE)
    m = import_re.search(src)
    assert not m, f"autonomous_governance.py must never import broker modules: {m.group(0)!r}"
    write_sql_re = re.compile(
        r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:watchlist_"
        r"items|strategy_watchpool)\b", re.IGNORECASE)
    m = write_sql_re.search(src)
    assert not m, f"autonomous_governance.py must never write watch tables directly: {m.group(0)!r}"


# ── helpers ────────────────────────────────────────────────────────────────────

def get_db_connection():
    env_path = ROOT / ".env"
    db_pass = None
    for line in env_path.read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            db_pass = line.split("=", 1)[1]
    if not db_pass:
        raise RuntimeError("DB_PASSWORD not found in .env")
    return psycopg2.connect(
        host="localhost", dbname="trade_ai", user="trade_ai",
        password=db_pass, keepalives=1, keepalives_idle=30,
        keepalives_interval=10, keepalives_count=3, connect_timeout=10)


def _scorecard_ok() -> bool:
    """Check do-no-harm scorecard. If pause or missing, block."""
    if not RESPECT_DO_NO_HARM:
        return True
    if not SCORECARD_PATH.exists():
        return True  # no scorecard yet → allow (first-run grace)
    try:
        sc = json.loads(SCORECARD_PATH.read_text())
        recommendation = (sc.get("recommendation") or "").lower()
        return recommendation != "pause"
    except Exception:
        return True  # unreadable → allow (don't block on infrastructure)


def _today_count(conn, pathway: str) -> int:
    """How many candidates were auto-promoted via a pathway today."""
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM hermes_discovery_audit
           WHERE actor = 'autonomous_curator'
             AND action = 'PROMOTE'
             AND created_at::date = CURRENT_DATE
             AND after_json->>'promoted_ref_type' = %s""",
        (pathway,))
    n = cur.fetchone()[0]
    cur.close()
    return n


def _daily_room(conn) -> dict[str, int]:
    """Remaining capacity per pathway today."""
    return {
        "research_topic": max(0, MAX_TOPICS_PER_DAY - _today_count(conn, "research_topic")),
        "source":        max(0, MAX_SOURCES_PER_DAY - _today_count(conn, "source")),
        "ticker":        max(0, MAX_TICKER_STAGES_PER_DAY - _today_count(conn, "watch_evaluation")),
    }


# ── core logic ─────────────────────────────────────────────────────────────────

def eligible_candidates(conn, *, limit: int = 8) -> list[dict]:
    """Return READY_FOR_REVIEW candidates that pass the rail checks.

    Filters applied in SQL where possible, then in Python for JSONB fields.
    Ordered by discovery_score DESC.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, candidate_type, label, discovery_score, status,
               safe_action_level, meta_json, created_at
        FROM hermes_discovery_candidates
        WHERE status = 'READY_FOR_REVIEW'
          AND discovery_score >= %s
        ORDER BY discovery_score DESC
        LIMIT %s
    """, (MIN_SCORE, limit * 2))  # overfetch: Python-side filtering may drop some
    rows = cur.fetchall()
    cur.close()

    eligible = []
    for row in rows:
        cand = dict(row)
        meta = cand.get("meta_json") or {}

        # 1. safe_action_level gate
        sal = (cand.get("safe_action_level") or "").upper()
        if sal not in {"RESEARCH_ONLY", "AUTO_STAGE_INSIDE_RAILS"}:
            continue

        # 2. domain_risk_level gate (stored in meta_json)
        drl = (meta.get("domain_risk_level") or "").lower()
        if drl in DOMAINS_NEVER_AUTO:
            continue

        # 3. llm_review gate (required unless config says no)
        llm_review = meta.get("llm_review_json")
        if REQUIRE_LLM_REVIEW and not llm_review:
            continue
        if REQUIRE_LLM_REVIEW and llm_review:
            action = llm_review.get("recommended_action", "")
            if action not in PROMOTIVE_ACTIONS:
                continue

        cand["_pathway"] = PROMOTIVE_ACTIONS.get(
            (llm_review or {}).get("recommended_action", ""))
        eligible.append(cand)

    return eligible[:limit]


def decide(cand: dict) -> str | None:
    """Map llm_review recommended_action → promotion pathway id.

    Also checks candidate_type alignment and ticker validation.
    Returns pathway string or None if not actionable.
    """
    meta = cand.get("meta_json") or {}
    llm_review = meta.get("llm_review_json") or {}
    action = llm_review.get("recommended_action", "")
    pathway = PROMOTIVE_ACTIONS.get(action)
    if not pathway:
        return None

    ctype = cand.get("candidate_type", "")

    # Type-pathway alignment: only promote matching types
    if pathway == "research_topic":
        if ctype not in ("TOPIC_CANDIDATE", "TREND_CANDIDATE"):
            return None
    elif pathway == "source":
        if ctype not in ("SOURCE_CANDIDATE", "CONNECTOR_CANDIDATE"):
            return None
    elif pathway == "ticker":
        if ctype != "TICKER_CANDIDATE":
            return None
        # Must have passed ticker validation
        verdict = meta.get("ticker_validation", {}).get("verdict")
        if verdict != "VALID":
            return None

    return pathway


def run_autonomous_governance(*, apply: bool = False, limit: int = 5) -> dict:
    """Select eligible candidates, decide pathway, call existing promotion.py.

    Args:
        apply: if False, dry-run only (log what would happen)
        limit: max candidates to promote this tick

    Returns:
        dict with summary of actions taken
    """
    if KILL_FILE.exists():
        return {"status": "kill_switch", "reason": "HERMES_DISABLED", "actions": 0}

    if not _scorecard_ok():
        return {"status": "blocked", "reason": "do_no_harm_scorecard_pause", "actions": 0}

    conn = get_db_connection()

    try:
        room = _daily_room(conn)
        total_room = sum(room.values())
        if total_room == 0:
            return {"status": "capped", "reason": "daily_caps_reached", "caps": room, "actions": 0}

        candidates = eligible_candidates(conn, limit=min(limit, total_room * 2))
    except Exception as e:
        try: conn.close()
        except Exception: pass
        return {"status": "error", "phase": "query", "error": str(e)[:200], "actions": 0}

    actions = []
    skipped = []

    for cand in candidates:
        if not apply:
            # Dry-run: just report what would happen
            pathway = decide(cand)
            if pathway and room.get(pathway, 0) > 0:
                actions.append({
                    "candidate_id": cand["id"],
                    "label": cand.get("label", ""),
                    "candidate_type": cand.get("candidate_type"),
                    "pathway": pathway,
                    "score": cand.get("discovery_score"),
                    "status": "would_promote",
                })
                room[pathway] -= 1
            else:
                reason = "no_pathway" if not pathway else f"cap_{pathway}_reached"
                skipped.append({"candidate_id": cand["id"], "reason": reason})
            continue

        # APPLY mode
        pathway = decide(cand)
        if not pathway:
            skipped.append({"candidate_id": cand["id"], "reason": "no_pathway"})
            continue
        if room.get(pathway, 0) <= 0:
            skipped.append({"candidate_id": cand["id"], "reason": f"cap_{pathway}_reached"})
            continue

        try:
            if pathway == "research_topic":
                result = _promo.promote_research_topic(
                    cand["id"], actor="autonomous_curator",
                    notes="auto-promoted by autonomous governance (Phase 1)")
            elif pathway == "source":
                result = _promo.promote_source(
                    cand["id"], actor="autonomous_curator",
                    notes="auto-promoted by autonomous governance (Phase 1)")
            elif pathway == "ticker":
                result = _promo.promote_ticker(
                    cand["id"], actor="autonomous_curator",
                    notes="auto-promoted by autonomous governance (Phase 1)")
            else:
                skipped.append({"candidate_id": cand["id"], "reason": f"unknown_pathway_{pathway}"})
                continue

            actions.append({
                "candidate_id": cand["id"],
                "label": cand.get("label", ""),
                "pathway": pathway,
                "score": cand.get("discovery_score"),
                "result": result,
                "status": "promoted",
            })
            room[pathway] -= 1

        except Exception as e:
            skipped.append({
                "candidate_id": cand["id"],
                "reason": f"promotion_error: {str(e)[:200]}",
            })

    try: conn.close()
    except Exception: pass

    return {
        "status": "ok",
        "mode": "dry-run" if not apply else "apply",
        "actions": len(actions),
        "skipped": len(skipped),
        "promoted": actions,
        "skip_reasons": skipped,
        "remaining_caps": room,
    }


_forbidden_path_guard()
