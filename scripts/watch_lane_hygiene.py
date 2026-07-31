#!/usr/bin/env python3
"""watch_lane_hygiene.py — W4: park no-setup / low-quality names off MAIN without deleting.

Actions (audit-only demotions; never DELETE):
  • Tag watchlist_items.notes / a lane flag for no-trade setup rows that were force-shown
  • Clear accidental main_promoted style flags if present
  • Report counts for operator Telegram optional

Usage:
  python3 scripts/watch_lane_hygiene.py --dry-run
  python3 scripts/watch_lane_hygiene.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    apply = bool(args.apply) and not args.dry_run

    from db_adapter import _get_conn
    from watch_lane_admission import annotate_item, is_no_trade_setup, load_policy

    pol = load_policy()
    conn = _get_conn()
    cur = conn.cursor()
    # Pull active/researched candidates that look like main-window noise:
    # ai_discovered + bearish/no enrichment, not starred
    cur.execute(
        """
        SELECT wi.symbol, wi.source, wi.status, wi.trend, wi.rsi,
               wi.provenance_reason, wi.bucket, wi.hermes_rank,
               EXISTS (SELECT 1 FROM operator_starred_symbols s
                       WHERE upper(s.symbol)=upper(wi.symbol)) AS starred
        FROM watchlist_items wi
        WHERE wi.status IN ('active','researched')
          AND wi.source IN ('ai_discovered','topic_research','paper_proposal')
          AND NOT EXISTS (SELECT 1 FROM operator_starred_symbols s
                          WHERE upper(s.symbol)=upper(wi.symbol))
        ORDER BY wi.hermes_rank ASC NULLS LAST
        LIMIT %s
        """,
        (int(args.limit),),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    park = []
    for r in rows:
        # synthesize setup_context-ish from trend for offline hygiene
        trend = (r.get("trend") or "").lower()
        sc_type = "no-trade (downtrend)" if trend == "bearish" else ("trend continuation" if trend == "bullish" else "range / mean-reversion")
        item = {
            "symbol": r["symbol"],
            "source": r["source"],
            "starred": r.get("starred"),
            "setup_context": {"type": sc_type},
            "decision_actionable": False,
            "rsi": r.get("rsi"),
            "trend": r.get("trend"),
        }
        ann = annotate_item(item, pol)
        if ann.get("lane") != "main" and (is_no_trade_setup(item, pol) or trend == "bearish"):
            park.append(r["symbol"])

    tag = f"lane:research_parked:{datetime.now(timezone.utc).date().isoformat()}"
    updated = 0
    if apply and park:
        for sym in park:
            # Tag via provenance_reason + bucket — never delete; MAIN admission ignores unstarred ai_discovered
            cur.execute(
                """
                UPDATE watchlist_items
                SET bucket = COALESCE(NULLIF(bucket,''), 'research_parked'),
                    provenance_reason = CASE
                      WHEN provenance_reason IS NULL OR provenance_reason = '' THEN %s
                      WHEN provenance_reason LIKE %s THEN provenance_reason
                      ELSE left(provenance_reason || ' | ' || %s, 500)
                    END,
                    updated_at = NOW()
                WHERE upper(symbol)=%s AND status IN ('active','researched')
                """,
                (tag, "%research_parked%", tag, sym.upper()),
            )
            updated += cur.rowcount
        conn.commit()

    out = {
        "ok": True,
        "apply": apply,
        "scanned": len(rows),
        "park_candidates": len(park),
        "updated_rows": updated,
        "sample": park[:25],
        "tag": tag,
        "note": "Demotion tag only — names stay in RESEARCH warehouse; MAIN admission ignores them without star/allowlist",
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
