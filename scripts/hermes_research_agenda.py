#!/usr/bin/env python3
"""Hermes Research Agenda Engine — autonomous topic pivoting (Phase 2).

Hermes builds its own research agenda:
  - CREATE: new topic_monitor rows from 6 signal sources
  - RETIRE: auto_created topics with zero research yield >21d
  - BOOST: auto topics that produced actioned outcomes → priority +1
  - PIVOT: sector RS rotation deltas → research topics for LEADING underweight sectors

Safety:
  - dry-run by default, --apply to commit
  - kill switches: HERMES_DISABLED + HERMES_AGENDA_DISABLED
  - 12h minimum between applies (agenda is a slow signal)
  - never touches operator-created topics
  - all actions audited to hermes_research_agenda_audit
  - advisory-only, zero broker imports

Usage:
  python scripts/hermes_research_agenda.py [--apply] [--dry-run] [--limit N]
"""
import argparse
import json
import os
import sys
import re
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

KILL_HERMES = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
KILL_AGENDA = PROJECT_ROOT / "data" / "runtime" / "HERMES_AGENDA_DISABLED"
STATE_FILE = PROJECT_ROOT / "data" / "runtime" / "hermes_agenda_last_run.json"
CONFIG_FILE = PROJECT_ROOT / "config" / "hermes_research_agenda.yaml"


# ── config ────────────────────────────────────────────────────────────────────

def _load_config():
    if CONFIG_FILE.exists():
        import yaml
        return yaml.safe_load(CONFIG_FILE.read_text())
    return {}

CFG = _load_config()
MIN_HOURS_BETWEEN = CFG.get("min_hours_between_runs", 12)
MAX_CREATES = CFG.get("max_creates_per_day", 3)
MAX_RETIRES = CFG.get("max_retires_per_day", 2)
MAX_BOOSTS = CFG.get("max_boosts_per_day", 5)
RETIRE_DAYS_NO_YIELD = CFG.get("retire_after_days_no_yield", 21)
MIN_RANK_SCORE = CFG.get("min_rank_score", 0.35)
DOMAINS_NEVER_AUTO = frozenset(CFG.get("domains_never_auto", ["tax", "legal", "planning", "medical"]))
BOOK_RELEVANCE_WEIGHT = CFG.get("book_relevance_weight", 0.15)


# ── helpers ────────────────────────────────────────────────────────────────────

def get_db():
    env_path = PROJECT_ROOT / ".env"
    db_pass = None
    for line in env_path.read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            db_pass = line.split("=", 1)[1]
    if not db_pass:
        raise RuntimeError("DB_PASSWORD not found")
    import psycopg2
    return psycopg2.connect(
        host="localhost", dbname="trade_ai", user="trade_ai",
        password=db_pass, keepalives=1, keepalives_idle=30,
        keepalives_interval=10, keepalives_count=3, connect_timeout=10)


def _slug(text, max_len=40):
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:max_len]


def _load_book_map():
    """Load sector weights from fund_lookthrough.json → effective book relevance per sector."""
    path = PROJECT_ROOT / "config" / "fund_lookthrough.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        sector_weights = Counter()
        for fund in (data.get("funds") or {}).values():
            for sector, w in (fund.get("weights") or {}).items():
                sector_weights[sector] += float(w)
        return dict(sector_weights)
    except Exception:
        return {}


def _gate_check() -> str | None:
    """Check kill switches and cadence gate. Returns None if OK, reason string if blocked."""
    if KILL_HERMES.exists():
        return "HERMES_DISABLED"
    if KILL_AGENDA.exists():
        return "HERMES_AGENDA_DISABLED"
    if not STATE_FILE.exists():
        return None  # first run
    try:
        state = json.loads(STATE_FILE.read_text())
        last = datetime.fromisoformat(state.get("last_apply_ts", "2000-01-01T00:00:00"))
        if (datetime.now(timezone.utc) - last).total_seconds() < MIN_HOURS_BETWEEN * 3600:
            hours_ago = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            return f"cadence_gate: {hours_ago:.1f}h since last (min {MIN_HOURS_BETWEEN}h)"
    except Exception:
        return None
    return None


def _today_action_count(conn, decision):
    cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) FROM hermes_research_agenda_audit
                   WHERE decision = %s AND run_at::date = CURRENT_DATE""", (decision,))
    n = cur.fetchone()[0]
    cur.close()
    return n


# ── build: discover candidate topics ──────────────────────────────────────────

def build_agenda(conn, *, horizon_hours=168, limit=15):
    """Candidate topics from 6 signal sources, in priority order."""
    cur = conn.cursor()
    candidates = []

    # Source 1: Inbox TREND/TOPIC with llm_review approve (Phase 1 overflow)
    cur.execute("""
        SELECT id, label, candidate_type, discovery_score, meta_json, created_at
        FROM hermes_discovery_candidates
        WHERE status = 'READY_FOR_REVIEW'
          AND candidate_type IN ('TREND_CANDIDATE', 'TOPIC_CANDIDATE')
          AND discovery_score >= 0.60
          AND meta_json->'llm_review_json'->>'recommended_action' = 'approve_research_topic'
        ORDER BY discovery_score DESC LIMIT %s
    """, (limit,))
    for row in cur.fetchall():
        meta = row["meta_json"] or {}
        keywords = meta.get("keywords") or [row["label"]]
        candidates.append({
            "key": f"inbox_{row['id']}",
            "label": row["label"],
            "keywords": keywords[:8],
            "score": float(row["discovery_score"] or 0),
            "source": "discovery_inbox",
            "why": f"LLM-reviewed inbox candidate #{row['id']}",
            "domain": meta.get("research_domain", "general"),
            "provenance": {"inbox_candidate_id": row["id"], "llm_review": True},
        })

    # Source 2: Industry novelty GAP_CANDIDATE (MISSING_SECTOR)
    cur.execute("""
        SELECT id, label, candidate_type, discovery_score, meta_json, created_at
        FROM hermes_discovery_candidates
        WHERE status = 'READY_FOR_REVIEW'
          AND candidate_type = 'GAP_CANDIDATE'
          AND meta_json->>'gap_type' = 'MISSING_SECTOR'
          AND discovery_score >= 0.50
        ORDER BY discovery_score DESC LIMIT %s
    """, (limit,))
    for row in cur.fetchall():
        meta = row["meta_json"] or {}
        sector = row["label"] or meta.get("gap_label", "unknown sector")
        keywords = [sector] + (meta.get("keywords") or [])
        candidates.append({
            "key": f"gap_{row['id']}",
            "label": f"Emerging Sector: {sector}",
            "keywords": keywords[:8],
            "score": float(row["discovery_score"] or 0) * 0.9,  # slight discount for gap-only
            "source": "industry_novelty",
            "why": f"Uncovered sector gap #{row['id']}: {sector}",
            "domain": "sector_thematic",
            "provenance": {"gap_candidate_id": row["id"], "gap_type": "MISSING_SECTOR"},
        })

    # Source 3: Entity spikes not yet in topic_monitor
    cur.execute("""
        SELECT entity_value, entity_type, COUNT(*) as mentions, MAX(created_at) as last_seen
        FROM content_entity_links
        WHERE entity_type IN ('topic', 'sector', 'person', 'organization')
          AND created_at > NOW() - INTERVAL '%s hours'
        GROUP BY entity_value, entity_type
        HAVING COUNT(*) >= 3
        ORDER BY mentions DESC LIMIT %s
    """, (horizon_hours, limit))
    entity_rows = [{"entity_value": r[0], "entity_type": r[1],
                     "mentions": r[2], "last_seen": r[3]} for r in cur.fetchall()]
    if entity_rows:
        cur.execute("SELECT LOWER(display_name) FROM topic_monitor WHERE enabled = true")
        existing = {r[0].lower() for r in cur.fetchall()}
        for er in entity_rows:
            if er["entity_value"].lower() in existing:
                continue
            candidates.append({
                "key": f"entity_{_slug(er['entity_value'])}",
                "label": f"Trending: {er['entity_value']}",
                "keywords": [er["entity_value"], er["entity_type"]],
                "score": min(0.7, float(er["mentions"]) / 10),
                "source": "entity_spike",
                "why": f"{er['mentions']} mentions as {er['entity_type']} in {horizon_hours}h",
                "domain": "sector_thematic" if er["entity_type"] == "sector" else "general",
                "provenance": {"entity": er["entity_value"], "mentions": er["mentions"]},
            })
            if len(candidates) >= limit:
                break

    # Source 4: Sector RS rotation deltas (LEADING sectors not well covered)
    if len(candidates) < limit:
        try:
            cur.execute("""
                SELECT etf, sector, state, rs20, slope
                FROM sector_momentum_state
                WHERE state = 'LEADING'
                ORDER BY rs20 DESC NULLS LAST LIMIT 10
            """)
            book_map = _load_book_map()
            for etf, sector, state, rs20, slope in cur.fetchall():
                key = f"rotation_{_slug(sector)}"
                book_weight = book_map.get(sector, 0)
                # Prioritize underweight LEADING sectors
                if book_weight < 0.10:
                    candidates.append({
                        "key": key,
                        "label": f"Sector Rotation: {sector} ({etf})",
                        "keywords": [sector, etf, "rotation", "momentum"],
                        "score": 0.55 + (0.15 if book_weight == 0 else 0.05),
                        "source": "sector_rotation",
                        "why": f"LEADING sector {sector} (RS20={float(rs20):+.1f}%), "
                               f"book weight={book_weight:.0%} — underweight opportunity",
                        "domain": "sector_thematic",
                        "provenance": {"etf": etf, "sector": sector, "state": state,
                                       "rs20": float(rs20), "book_weight": book_weight},
                    })
        except Exception:
            pass

    # Source 5: Think-tank themes (from hermes_think_tank rows — last 7d themes)
    if len(candidates) < limit:
        try:
            cur.execute("""
                SELECT topic, COUNT(*) as ct, MAX(created_at) as last_seen
                FROM hermes_research_intelligence
                WHERE research_type = 'momentum_catalyst'
                  AND created_at > NOW() - INTERVAL '7 days'
                  AND topic IS NOT NULL AND topic != ''
                GROUP BY topic
                ORDER BY ct DESC LIMIT %s
            """, (limit,))
            for topic, ct, last_seen in cur.fetchall():
                if len(topic) < 10:
                    continue
                candidates.append({
                    "key": f"thinktank_{_slug(topic[:30])}",
                    "label": f"Catalyst Theme: {topic[:60]}",
                    "keywords": topic.split()[:8],
                    "score": min(0.7, float(ct) / 5),
                    "source": "think_tank",
                    "why": f"{ct} momentum_catalyst mentions in 7d, last={last_seen}",
                    "domain": "catalyst_event",
                    "provenance": {"mentions": ct, "last_seen": str(last_seen)},
                })
        except Exception:
            pass

    # Source 6: Coverage gaps for macro/geopolitical (if config has them)
    if len(candidates) < limit:
        try:
            cur.execute("""
                SELECT entity_value, entity_type, COUNT(*) as mentions
                FROM content_entity_links
                WHERE entity_type = 'topic'
                  AND LOWER(entity_value) ~ '(inflation|fed|rate|tariff|geopolitic|war|supply.chain|recession)'
                  AND created_at > NOW() - INTERVAL '%s hours'
                GROUP BY entity_value, entity_type
                HAVING COUNT(*) >= 2
                ORDER BY mentions DESC LIMIT %s
            """, (horizon_hours, limit))
            for ev, et, mentions in cur.fetchall():
                candidates.append({
                    "key": f"macro_{_slug(ev)}",
                    "label": f"Macro Theme: {ev}",
                    "keywords": [ev, "macro", "geopolitical"],
                    "score": min(0.75, float(mentions) / 8),
                    "source": "macro_coverage",
                    "why": f"{mentions} macro mentions in {horizon_hours}h",
                    "domain": "macro_geo",
                    "provenance": {"entity": ev, "mentions": mentions},
                })
        except Exception:
            pass

    # Source 7 (soft): material-only CIO YouTube research queue (Q>=70 promoted).
    # Never raises into agenda apply — queue file may be absent.
    if len(candidates) < limit:
        try:
            from cio_youtube_research_queue import agenda_candidates_from_queue
            room = max(0, limit - len(candidates))
            for c in agenda_candidates_from_queue(limit=min(3, room or 1)):
                candidates.append(c)
        except Exception:
            pass

    cur.close()
    return candidates[:limit]


# ── rank: pure scoring function ────────────────────────────────────────────────

def rank_agenda(candidates, *, book_map=None, tag_efficacy=None):
    """Rank by composite: novelty * recurrence * cross_source * domain_gap * book_relevance.
    Pure function — no DB access, unit-testable."""
    if not candidates:
        return []

    if book_map is None:
        book_map = {}
    if tag_efficacy is None:
        tag_efficacy = {}

    # Group by source: same-source candidates share a source-bonus pool
    source_counts = Counter(c["source"] for c in candidates)

    ranked = []
    for c in candidates:
        score = c.get("score", 0.5)

        # Source bonus: fewer candidates from same source → higher novelty weight
        source_novelty = 1.0 / max(source_counts.get(c["source"], 1), 1)

        # Book relevance: if any keyword matches a sector in the book
        book_bonus = 0.0
        for kw in c.get("keywords", []):
            for sector, weight in book_map.items():
                if kw.lower() in sector.lower() or sector.lower() in kw.lower():
                    book_bonus = max(book_bonus, weight)
        book_bonus *= BOOK_RELEVANCE_WEIGHT

        # Tag efficacy prior: if similar tags have positive lift, boost
        efficacy_bonus = 0.0
        for tag, eff in tag_efficacy.items():
            if tag in c.get("label", "").lower():
                eff_val = eff.get("avg_realized_r", 0) or 0
                efficacy_bonus = max(efficacy_bonus, float(eff_val) * 0.05)

        # Domain gap: macro/geopolitical/technology get a premium (typically uncovered)
        domain_bonus = 0.0
        domain = c.get("domain", "general")
        if domain in ("macro_geo", "geopolitical"):
            domain_bonus = 0.10
        elif domain == "sector_thematic":
            domain_bonus = 0.05

        composite = score * (1.0 + source_novelty * 0.1 + book_bonus +
                             efficacy_bonus + domain_bonus)
        ranked.append({**c, "composite_score": round(composite, 4),
                        "score_breakdown": {
                            "base": score, "source_novelty": round(source_novelty, 3),
                            "book_bonus": round(book_bonus, 3),
                            "efficacy_bonus": round(efficacy_bonus, 3),
                            "domain_bonus": round(domain_bonus, 3),
                        }})

    ranked.sort(key=lambda c: c["composite_score"], reverse=True)
    return ranked


# ── apply: create/retire/boost ─────────────────────────────────────────────────

def apply_agenda(conn, ranked, *, apply=False, max_creates=3, max_retires=2, max_boosts=5):
    """Apply agenda decisions. Returns summary dict."""
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    created_count = _today_action_count(conn, "create")
    retired_count = _today_action_count(conn, "retire")
    boosted_count = _today_action_count(conn, "boost")

    create_room = max(0, max_creates - created_count)
    retire_room = max(0, max_retires - retired_count)
    boost_room = max(0, max_boosts - boosted_count)

    results = {"creates": [], "retires": [], "boosts": [], "mode": "dry-run" if not apply else "apply"}

    # CREATE: top-ranked above min_rank_score
    for c in ranked:
        if create_room <= 0:
            break
        if c["composite_score"] < MIN_RANK_SCORE:
            continue
        # Skip if already in topic_monitor
        cur.execute("SELECT topic_id FROM topic_monitor WHERE LOWER(display_name) = LOWER(%s)",
                    (c["label"][:80],))
        if cur.fetchone():
            continue

        topic_id = f"agd{now.strftime('%Y%m%d')}_{_slug(c['label'])}"[:60]
        sql_rollback = f"UPDATE topic_monitor SET enabled=false WHERE topic_id='{topic_id}';"

        if apply:
            cur.execute("""
                INSERT INTO topic_monitor
                    (topic_id, display_name, search_queries, priority, agent_owner,
                     owner, enabled, max_age_days, min_articles, personal_context,
                     auto_created)
                VALUES (%s, %s, %s::jsonb, 4, 'Alex', 'hermes', true, 30, 3, '', true)
                ON CONFLICT (topic_id) DO UPDATE
                    SET priority = EXCLUDED.priority,
                        enabled = true
                RETURNING topic_id
            """, (topic_id, c["label"][:80], json.dumps(c.get("keywords", [])[:8])))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    INSERT INTO hermes_research_agenda_audit
                        (run_at, decision, topic_id, rationale, rollback_sql, detail)
                    VALUES (NOW(), 'create', %s, %s, %s, %s::jsonb)
                """, (topic_id, c["why"], sql_rollback,
                      json.dumps({"label": c["label"], "source": c["source"],
                                  "composite_score": c["composite_score"],
                                  "provenance": c.get("provenance", {})})))

        results["creates"].append({"topic_id": topic_id, "label": c["label"],
                                    "score": c["composite_score"], "applied": apply})
        create_room -= 1

    # RETIRE: auto_created topics with zero research yield > RETIRE_DAYS
    if retire_room > 0:
        cur.execute("""
            SELECT tm.topic_id, tm.display_name, tm.created_at
            FROM topic_monitor tm
            WHERE tm.auto_created = true
              AND tm.enabled = true
              AND tm.created_at < NOW() - INTERVAL '%s days'
              AND NOT EXISTS (
                  SELECT 1 FROM hermes_research_intelligence hri
                  WHERE LOWER(hri.topic) LIKE '%%' || LOWER(tm.display_name) || '%%'
                    AND hri.status = 'promoted'
                    AND hri.created_at > tm.created_at
              )
            LIMIT %s
        """, (RETIRE_DAYS_NO_YIELD, retire_room))
        for topic_id, display_name, created_at in cur.fetchall():
            sql_rollback = f"UPDATE topic_monitor SET enabled=true WHERE topic_id='{topic_id}';"
            if apply:
                cur.execute("UPDATE topic_monitor SET enabled = false WHERE topic_id = %s",
                           (topic_id,))
                cur.execute("""
                    INSERT INTO hermes_research_agenda_audit
                        (run_at, decision, topic_id, rationale, rollback_sql, detail)
                    VALUES (NOW(), 'retire', %s, %s, %s, %s::jsonb)
                """, (topic_id,
                      f"Zero research yield in {RETIRE_DAYS_NO_YIELD}d (created {created_at})",
                      sql_rollback,
                      json.dumps({"display_name": display_name, "created_at": str(created_at)})))
            results["retires"].append({"topic_id": topic_id, "display_name": display_name,
                                        "applied": apply})
            retire_room -= 1

    # BOOST: auto topics whose research rows produced actioned outcomes → priority +1
    if boost_room > 0:
        cur.execute("""
            SELECT tm.topic_id, tm.display_name, tm.priority, COUNT(hri.id) as actioned
            FROM topic_monitor tm
            JOIN hermes_research_intelligence hri
              ON LOWER(hri.topic) LIKE '%%' || LOWER(tm.display_name) || '%%'
            WHERE tm.auto_created = true
              AND tm.enabled = true
              AND hri.status = 'promoted'
              AND hri.created_at > NOW() - INTERVAL '30 days'
            GROUP BY tm.topic_id, tm.display_name, tm.priority
            HAVING COUNT(hri.id) >= 3
            ORDER BY actioned DESC
            LIMIT %s
        """, (boost_room,))
        for topic_id, display_name, priority, actioned in cur.fetchall():
            sql_rollback = f"UPDATE topic_monitor SET priority={priority} WHERE topic_id='{topic_id}';"
            new_priority = min(2, max(1, (priority or 4) - 1))  # boost: lower number = higher pri
            if apply:
                cur.execute("UPDATE topic_monitor SET priority = %s WHERE topic_id = %s",
                           (new_priority, topic_id))
                cur.execute("""
                    INSERT INTO hermes_research_agenda_audit
                        (run_at, decision, topic_id, rationale, rollback_sql, detail)
                    VALUES (NOW(), 'boost', %s, %s, %s, %s::jsonb)
                """, (topic_id,
                      f"{actioned} promoted research rows in 30d → priority {priority}→{new_priority}",
                      sql_rollback,
                      json.dumps({"old_priority": priority, "new_priority": new_priority,
                                  "actioned_rows": actioned})))
            results["boosts"].append({"topic_id": topic_id, "display_name": display_name,
                                       "old_priority": priority, "new_priority": new_priority,
                                       "actioned": actioned, "applied": apply})
            boost_room -= 1

    if apply:
        conn.commit()

    cur.close()
    return results


# ── orchestrate ────────────────────────────────────────────────────────────────

def run_agenda(*, apply=False, limit=15):
    """Full agenda pipeline: gate → build → rank → apply."""
    gate = _gate_check()
    if gate:
        return {"status": "blocked", "reason": gate, "creates": 0, "retires": 0, "boosts": 0}

    conn = get_db()
    try:
        candidates = build_agenda(conn, limit=limit)
        if not candidates:
            return {"status": "ok", "reason": "no_candidates", "creates": 0, "retires": 0, "boosts": 0}

        book_map = _load_book_map()
        ranked = rank_agenda(candidates, book_map=book_map)

        results = apply_agenda(conn, ranked, apply=apply,
                               max_creates=MAX_CREATES, max_retires=MAX_RETIRES,
                               max_boosts=MAX_BOOSTS)

        # Update state file
        if apply:
            state = {"last_apply_ts": datetime.now(timezone.utc).isoformat(),
                     "candidates_found": len(candidates),
                     "created": len(results["creates"]),
                     "retired": len(results["retires"]),
                     "boosted": len(results["boosts"])}
            STATE_FILE.write_text(json.dumps(state, indent=2))

        return {
            "status": "ok",
            "mode": "apply" if apply else "dry-run",
            "candidates_found": len(candidates),
            "top_candidates": [{"label": r["label"], "score": r["composite_score"],
                                "source": r["source"]} for r in ranked[:5]],
            "creates": len(results["creates"]),
            "retires": len(results["retires"]),
            "boosts": len(results["boosts"]),
            "details": results,
        }

    finally:
        try: conn.close()
        except Exception: pass


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hermes Research Agenda Engine (Phase 2)")
    parser.add_argument("--apply", action="store_true", help="Apply agenda (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run (explicit)")
    parser.add_argument("--limit", type=int, default=15, help="Max candidates to consider")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    apply = args.apply and not args.dry_run
    result = run_agenda(apply=apply, limit=args.limit)

    if args.json:
        print(json.dumps(result, default=str, indent=2))
    else:
        print(f"[{result['mode'].upper()}] Research Agenda: {result.get('reason','')}")
        print(f"  Candidates found: {result.get('candidates_found', 0)}")
        if result.get("top_candidates"):
            for c in result["top_candidates"]:
                print(f"    [{c['source']}] {c['label'][:60]} (score={c['score']:.3f})")
        print(f"  Creates: {result.get('creates', 0)}")
        print(f"  Retires: {result.get('retires', 0)}")
        print(f"  Boosts:  {result.get('boosts', 0)}")


if __name__ == "__main__":
    main()
