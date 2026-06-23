#!/usr/bin/env python3
"""Seed topic_monitor rows for small-cap / Russell 2000 news curation."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

TOPICS = [
    {
        "topic_id": "small_cap_rotation",
        "display_name": "Small-Cap Rotation & Russell 2000",
        "search_queries": [
            "Russell 2000 outperformance IWM",
            "small cap stocks rally regional banks",
            "IWM vs SPY relative strength",
            "small cap momentum swing trades",
        ],
        "priority": 8,
    },
    {
        "topic_id": "russell_2000_catalysts",
        "display_name": "Russell 2000 Catalysts",
        "search_queries": [
            "Russell 2000 earnings movers",
            "small cap breakout stocks",
            "value rotation small caps",
        ],
        "priority": 7,
    },
]


def main():
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        print("DB unavailable — skip seed")
        return 1
    n = 0
    for t in TOPICS:
        exists = _execute("SELECT 1 FROM topic_monitor WHERE topic_id=%s", [t["topic_id"]], fetch="one")
        if exists:
            _execute(
                """UPDATE topic_monitor SET display_name=%s, search_queries=%s::jsonb,
                   enabled=true, priority=GREATEST(priority, %s), updated_at=now()
                   WHERE topic_id=%s""",
                [t["display_name"], __import__("json").dumps(t["search_queries"]), t["priority"], t["topic_id"]],
            )
            print(f"  updated {t['topic_id']}")
        else:
            _execute(
                """INSERT INTO topic_monitor (topic_id, display_name, search_queries, enabled, priority, owner)
                   VALUES (%s, %s, %s::jsonb, true, %s, 'shared')""",
                [t["topic_id"], t["display_name"], __import__("json").dumps(t["search_queries"]), t["priority"]],
            )
            print(f"  inserted {t['topic_id']}")
        n += 1
    print(f"Seeded {n} small-cap topics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())