#!/usr/bin/env python3
"""Archive historical threshold-tuning noise after the bounded writer is deployed.

Default is read-only preview. ``--apply`` changes only Hermes research metadata:
it preserves every row, marks legacy staged tuning claims archived, and adds the
``duplicate_collapsed`` tag. It does not mutate any freshness configuration.
"""
from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from db_adapter import _get_conn

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT count(*), min(created_at), max(created_at),
                  count(distinct summary), count(distinct pattern_signature)
           FROM hermes_research_intelligence
           WHERE hermes_agent_name='hermes_health_inspector'
             AND research_type='threshold_tuning'
             AND status='staged'"""
    )
    count, oldest, newest, summaries, signatures = cur.fetchone()
    updated = 0
    if args.apply and count:
        cur.execute(
            """UPDATE hermes_research_intelligence
               SET status='archived',
                   tags=(SELECT ARRAY(SELECT DISTINCT x FROM unnest(
                       COALESCE(tags, ARRAY[]::text[]) || ARRAY['duplicate_collapsed','proposal_only']
                   ) AS x)),
                   threshold_adjusted=false,
                   updated_at=NOW()
               WHERE hermes_agent_name='hermes_health_inspector'
                 AND research_type='threshold_tuning'
                 AND status='staged'"""
        )
        updated = cur.rowcount
        conn.commit()
    else:
        conn.rollback()
    cur.close()
    conn.close()
    print(json.dumps({
        "schema": "HealthThresholdNoiseRepair@v1",
        "mode": "APPLY" if args.apply else "PREVIEW",
        "eligible_rows": int(count or 0),
        "updated_rows": int(updated or 0),
        "distinct_summaries": int(summaries or 0),
        "distinct_pattern_signatures": int(signatures or 0),
        "oldest": str(oldest) if oldest else None,
        "newest": str(newest) if newest else None,
        "config_mutations": 0,
        "financial_writes": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
