#!/usr/bin/env python3
"""strategy_rotation_engine.py — Detect strategy rotation opportunities.

Classification-first. No ticker-hard-coded logic. No broker execution.

Usage:
    python3 scripts/strategy_rotation_engine.py --run [--json]
"""
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def detect_rotations() -> list:
    """Detect strategy rotation candidates by group allocation drift and signal strength."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get target allocations
    cur.execute("SELECT * FROM portfolio_target_allocations WHERE active=TRUE")
    targets = {r["allocation_id"]: dict(r) for r in cur.fetchall()}

    # Get current allocations from portfolio QA
    cur.execute("SELECT group_allocations FROM portfolio_level_qa_history ORDER BY evaluated_at DESC LIMIT 1")
    qa = cur.fetchone()
    current_allocs = qa.get("group_allocations", {}) if qa else {}
    if isinstance(current_allocs, str):
        current_allocs = json.loads(current_allocs)

    # Get recent signal strength by strategy group
    cur.execute("""
        SELECT strategy_type, AVG(fused_score) as avg_score, COUNT(*) as signal_count,
               MAX(severity) as max_sev
        FROM fused_signals WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY strategy_type
    """)
    signal_strength = {r["strategy_type"]: dict(r) for r in cur.fetchall()}

    rotations = []
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")

    for alloc_id, target in targets.items():
        current = current_allocs.get(alloc_id, {})
        actual_pct = float(current.get("pct", 0)) if isinstance(current, dict) else 0
        target_min = float(target.get("target_min_pct", 0) or 0)
        target_max = float(target.get("target_max_pct", 100) or 100)
        hard_cap = float(target.get("hard_cap_pct", 100) or 100)
        members = target.get("member_strategy_types") or []

        if actual_pct < target_min - 5:
            # Significantly underweight — rotation INTO this group
            # Find overweight group as source
            for other_id, other_target in targets.items():
                if other_id == alloc_id:
                    continue
                other_actual = float(current_allocs.get(other_id, {}).get("pct", 0) if isinstance(current_allocs.get(other_id), dict) else 0)
                other_max = float(other_target.get("target_max_pct", 100) or 100)
                if other_actual > other_max:
                    rid = f"rot-{alloc_id}-from-{other_id}-{ts}"
                    rot = {
                        "rotation_id": rid,
                        "source_group_id": other_id,
                        "target_group_id": alloc_id,
                        "rotation_amount_pct": round(min(other_actual - other_max, target_min - actual_pct), 1),
                        "rationale": f"{alloc_id} underweight ({actual_pct:.1f}% vs {target_min:.0f}% min). {other_id} overweight ({other_actual:.1f}% vs {other_max:.0f}% max).",
                        "confidence": 0.6,
                        "human_review_required": True,
                        "status": "proposed",
                    }

                    cur.execute("""
                        INSERT INTO strategy_rotation_recommendations
                            (rotation_id, source_group_id, target_group_id, rotation_amount_pct,
                             rationale, confidence, human_review_required, status)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (rid, other_id, alloc_id, rot["rotation_amount_pct"],
                          rot["rationale"][:500], 0.6, True, "proposed"))

                    rotations.append(rot)

        elif actual_pct > hard_cap:
            # Over hard cap — rotation OUT of this group
            rid = f"rot-{alloc_id}-overcap-{ts}"
            rot = {
                "rotation_id": rid,
                "source_group_id": alloc_id,
                "target_group_id": "income_generators" if alloc_id != "income_generators" else "core_compounders",
                "rotation_amount_pct": round(actual_pct - target_max, 1),
                "rationale": f"{alloc_id} exceeds hard cap ({actual_pct:.1f}% vs {hard_cap:.0f}% cap). Rebalance required.",
                "confidence": 0.7,
                "human_review_required": True,
                "status": "proposed",
            }
            cur.execute("""
                INSERT INTO strategy_rotation_recommendations
                    (rotation_id, source_group_id, target_group_id, rotation_amount_pct,
                     rationale, confidence, human_review_required, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (rid, alloc_id, rot["target_group_id"], rot["rotation_amount_pct"],
                  rot["rationale"][:500], 0.7, True, "proposed"))
            rotations.append(rot)

    conn.commit()
    conn.close()
    return rotations


if __name__ == "__main__":
    rotations = detect_rotations()
    print(f"[rotation] Detected {len(rotations)} rotation opportunities")
    for r in rotations:
        print(f"  {r['source_group_id']} → {r['target_group_id']}: {r['rotation_amount_pct']:.1f}% ({r['rationale'][:60]})")
    if "--json" in sys.argv:
        print(json.dumps(rotations, indent=2, default=str))
