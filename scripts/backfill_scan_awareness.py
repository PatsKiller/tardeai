#!/usr/bin/env python3
"""Backfill awareness fields on existing trade_ai_scans rows (no full re-score).

  python3 scripts/backfill_scan_awareness.py --since 2026-07-06 --until 2026-07-10
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    args = ap.parse_args()
    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until)

    from db_adapter import get_connection
    from scan_persist_extra import awareness_persist_values
    from squeeze_manual_review import attach_squeeze_manual_tags
    from micro_float_manual_review import attach_micro_float_manual_tags
    from high_rvol_manual_review import attach_high_rvol_manual_tags
    from low_price_manual_review import attach_low_price_manual_tags
    from catalyst_exception import attach_catalyst_exception_tags

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT symbol, run_date, decision, score, grade, rvol, price, change_pct, gap_pct, float_m,
               disqualified, disqualification_reason, catalyst_verified,
               awareness_status, setup_class
        FROM trade_ai_scans
        WHERE run_date BETWEEN %s AND %s
        ORDER BY run_date, symbol
        """,
        (since, until),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    updated = 0

    for row in rows:
        attach_squeeze_manual_tags([row])
        attach_micro_float_manual_tags([row])
        attach_high_rvol_manual_tags([row])
        attach_low_price_manual_tags([row])
        attach_catalyst_exception_tags([row])
        vals = awareness_persist_values(row)
        cur.execute(
            """
            UPDATE trade_ai_scans SET
                decision = %s, grade = %s, disqualified = %s, disqualification_reason = %s,
                awareness_status = %s, setup_class = %s, symbol_candidate = %s,
                symbol_alias_confidence = %s, manual_review_required = %s,
                operator_pill = %s, operator_subtitle = %s, operator_color_token = %s,
                not_validation_ready = %s, not_tradeable = %s
            WHERE run_date = %s AND symbol = %s
            """,
            (
                row.get("decision"), row.get("grade"), bool(row.get("disqualified")),
                row.get("disqualification_reason"),
                *vals,
                row["run_date"], row["symbol"],
            ),
        )
        updated += 1

    conn.commit()
    print(f"Backfilled awareness on {updated} rows ({since} → {until})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())