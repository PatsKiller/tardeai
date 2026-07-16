#!/usr/bin/env python3
"""
Generate Hermes ops backlog items from recurring unresolved SIEM events.
Reads normalized alert events, groups by dedupe_key, creates backlog candidates.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

SIEM_BACKLOG_MAP = {
    "AGENT_STALENESS": ("ops_backlog", "OPS_AGENT"),
    "LLM_ESCALATION": ("ops_backlog", "OPS_LLM"),
    "FEED_HEALTH": ("ops_backlog", "OPS_FEED"),
    "PIPELINE_FAILURE": ("ops_backlog", "OPS_PIPELINE"),
    "DATA_QUALITY": ("research_backlog", "DATA_QUALITY"),
    "CLOSED_TRADE_REVIEW": ("research_backlog", "JOURNAL_QUALITY"),
    "SYSTEM_HEALTH": ("ops_backlog", "OPS"),
}


def generate_backlog(max_items=5, dry_run=True):
    """Generate backlog candidates from SIEM events."""
    from normalize_tradeai_alerts import normalize
    events, rollup = normalize(days=14, dry_run=True)

    # Group by dedupe_key, find recurring unresolved
    groups = {}
    for e in events:
        dk = e["dedupe_key"]
        if dk not in groups:
            groups[dk] = {"count": 0, "events": [], "severity": e["severity"], "event_type": e["event_type"]}
        groups[dk]["count"] += 1
        if len(groups[dk]["events"]) < 3:
            groups[dk]["events"].append(e)

    # Filter to recurring (>5 repeats) and P1/P2
    candidates = []
    for dk, g in groups.items():
        if g["count"] < 5:
            continue
        if g["severity"] not in ("P1", "P2"):
            continue

        mapping = SIEM_BACKLOG_MAP.get(g["event_type"], ("ops_backlog", "OPS"))
        research_type, display_cat = mapping
        sample = g["events"][0]

        candidates.append({
            "symbol": None,
            "research_type": research_type,
            "hermes_agent_name": "siem_backlog_generator",
            "topic": f"{g['event_type']}: {sample.get('component', 'system')} — {g['count']}× in 14 days",
            "summary": f"Recurring {g['severity']} event. Last: {sample.get('raw_message_excerpt', sample.get('message', ''))[:150]}. Repeat count: {g['count']}×. Dedupe key: {dk}",
            "confidence_score": min(0.7, 0.3 + g["count"] * 0.02),
            "source_urls_json": json.dumps([{"type": "siem", "dedupe_key": dk, "count": g["count"]}]),
            "display_category": display_cat,
            "recommended_action": f"Investigate {g['event_type']} from {sample.get('component', 'unknown')}. {g['count']} occurrences suggest unresolved root cause.",
        })

    candidates.sort(key=lambda c: -c["confidence_score"])
    candidates = candidates[:max_items]

    if not dry_run and candidates:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        inserted = 0
        for c in candidates:
            # Engine Room v1 (WS-4): dedup is enforced, not just measured — same SIEM
            # dedupe_key within 14 days means the finding is already filed.
            dk = json.loads(c["source_urls_json"])[0].get("dedupe_key", "")
            cur.execute("""SELECT 1 FROM hermes_research_intelligence
                           WHERE research_type=%s AND source_urls_json::text LIKE %s
                             AND created_at > NOW() - INTERVAL '14 days' LIMIT 1""",
                        [c["research_type"], f'%"dedupe_key": "{dk}"%'])
            if cur.fetchone():
                print(f"  Skipped duplicate (14d): {c['topic'][:60]}")
                continue
            cur.execute("""
                INSERT INTO hermes_research_intelligence
                (symbol, research_type, hermes_agent_name, topic, summary, confidence_score,
                 source_urls_json, evidence_json, status, source, freshness_date, model_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, 'staged', 'hermes', CURRENT_DATE, 'siem_normalizer')
                RETURNING id
            """, [c["symbol"], c["research_type"], c["hermes_agent_name"],
                  c["topic"], c["summary"], c["confidence_score"], c["source_urls_json"],
                  json.dumps([{"type": "siem_backlog_finding", "source_surface": "siem",
                               "priority": "high" if c["confidence_score"] >= 0.5 else "medium",
                               "dedupe_key": dk, "advisory_only": True, "not_execution": True}])])
            rid = cur.fetchone()[0]
            inserted += 1
            print(f"  Inserted backlog id={rid}: {c['topic'][:60]}")
        conn.commit()
        conn.close()
        return candidates, inserted
    return candidates, 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    candidates, inserted = generate_backlog(max_items=args.max, dry_run=not args.apply)
    print(f"\nBacklog candidates: {len(candidates)}")
    for c in candidates:
        print(f"  [{c['display_category']}] {c['topic'][:70]} (conf {c['confidence_score']:.2f})")
    if not args.apply:
        print("\nDry-run. Use --apply to insert.")
    else:
        print(f"\nInserted: {inserted}")
