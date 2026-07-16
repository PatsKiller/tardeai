#!/usr/bin/env python3
"""Seed / upsert retirement + priority intelligence topics into topic_monitor.

Makes retirement a first-class monitored pillar with tight max_age_days so
topic_ingestion + hermes_topic_monitor_bridge refresh them frequently.

Usage:
  python scripts/research_intelligence_retirement_seed.py           # dry-run
  python scripts/research_intelligence_retirement_seed.py --apply
  python scripts/research_intelligence_retirement_seed.py --apply --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TOPICS_PATH = ROOT / "config" / "research_intelligence_retirement_topics.json"


def _load_topics(path: Path | None = None) -> dict:
    return json.loads((path or TOPICS_PATH).read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write to topic_monitor")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--config", default=None,
                    help="Alternate topic catalog (e.g. config/research_intelligence_compounding_topics.json)")
    args = ap.parse_args()

    cfg = _load_topics(Path(args.config) if args.config else None)
    topics = cfg.get("topics") or []
    owner = cfg.get("default_owner") or "shared"
    agent = cfg.get("default_agent_owner") or "Alex"

    from db_adapter import _execute, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2

    cols = {
        r["column_name"]
        for r in (_execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='topic_monitor'",
            fetch="all",
        ) or [])
    }
    has_owner = "owner" in cols
    has_personal = "personal_context" in cols

    planned, applied, errors = [], [], []
    for t in topics:
        tid = t["topic_id"]
        row = {
            "topic_id": tid,
            "display_name": t["display_name"],
            "search_queries": t.get("search_queries") or [],
            "video_queries": t.get("video_queries") or [],
            "priority": int(t.get("priority") or 2),
            "agent_owner": agent,
            "strategy_tags": t.get("strategy_tags") or [],
            "max_age_days": int(t.get("max_age_days") or 7),
            "min_articles": int(t.get("min_articles") or 3),
            "personal_context": t.get("personal_context") or "",
            "owner": owner,
        }
        planned.append(row)
        if not args.apply:
            continue
        try:
            # Core upsert (columns present since original topic_monitor migration)
            _execute(
                """
                INSERT INTO topic_monitor (
                    topic_id, display_name, search_queries, video_queries,
                    priority, agent_owner, agent_tags, strategy_tags,
                    max_age_days, min_articles, enabled, updated_at
                ) VALUES (
                    %s, %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s::jsonb, %s::jsonb,
                    %s, %s, TRUE, NOW()
                )
                ON CONFLICT (topic_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    search_queries = EXCLUDED.search_queries,
                    video_queries = EXCLUDED.video_queries,
                    priority = LEAST(topic_monitor.priority, EXCLUDED.priority),
                    agent_owner = EXCLUDED.agent_owner,
                    agent_tags = EXCLUDED.agent_tags,
                    strategy_tags = EXCLUDED.strategy_tags,
                    max_age_days = LEAST(topic_monitor.max_age_days, EXCLUDED.max_age_days),
                    min_articles = EXCLUDED.min_articles,
                    enabled = TRUE,
                    updated_at = NOW()
                """,
                (
                    row["topic_id"], row["display_name"],
                    json.dumps(row["search_queries"]), json.dumps(row["video_queries"]),
                    row["priority"], row["agent_owner"],
                    json.dumps([agent, "Aegis"]), json.dumps(row["strategy_tags"]),
                    row["max_age_days"], row["min_articles"],
                ),
                fetch=None,
            )
            if has_owner:
                _execute(
                    "UPDATE topic_monitor SET owner=%s WHERE topic_id=%s",
                    (owner, tid), fetch=None,
                )
            if has_personal and row["personal_context"]:
                _execute(
                    "UPDATE topic_monitor SET personal_context=%s WHERE topic_id=%s",
                    (row["personal_context"], tid), fetch=None,
                )
            applied.append(tid)
        except Exception as e:
            errors.append({"topic_id": tid, "error": str(e)[:240]})

    out = {
        "ok": len(errors) == 0,
        "apply": args.apply,
        "planned": len(planned),
        "applied": applied,
        "errors": errors,
        "topics": [
            {"topic_id": t["topic_id"], "priority": t["priority"], "max_age_days": t["max_age_days"]}
            for t in planned
        ],
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"[retirement-seed] {mode}: {len(planned)} topics (owner={owner}, agent={agent})")
        for t in planned:
            mark = "✓" if t["topic_id"] in applied else ("·" if not args.apply else "!")
            print(f"  {mark} {t['topic_id']:22} prio={t['priority']} "
                  f"max_age={t['max_age_days']}d  {t['display_name']}")
        if errors:
            print(f"  ERRORS: {json.dumps(errors, indent=2)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
