#!/usr/bin/env python3
"""migrate_momentum_scalp_stop_tagging.py — additive journal columns for the layered stop/trail policy.

Adds the ~6 tag fields the MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY requires that don't already exist on
paper_trades. EXISTING fields are reused (do NOT duplicate): max_adverse_excursion (MAE),
max_favorable_excursion (MFE), market_regime, vix_at_entry, rvol_at_entry, planned_stop, current_stop,
stop_type, trailing_active, trailing_policy_version, dollar_risk, signal_grade, bracket_state.

All columns are nullable + additive (no backfill, no rewrite). lock_timeout so the ALTER can never block
behind the dashboard server's long-lived connection (lesson from the OCO work). Idempotent.

  python3 scripts/migrate_momentum_scalp_stop_tagging.py [--apply]   (default: dry-run / show plan)
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# col -> (type, comment). Only the genuinely-missing ones; existing fields are reused.
NEW_COLUMNS = {
    "initial_stop_atr":        ("numeric", "initial stop distance in ATR multiples at entry (Layer 1)"),
    "initial_stop_method":     ("text",    "structure | atr | chandelier | hybrid (Layer 1 method tag)"),
    "trail_multiplier_used":   ("numeric", "ATR multiplier applied to the trailing stop (Layer 3)"),
    "trail_activation_r":      ("numeric", "R-multiple at which the trailing stop activated (Layer 3)"),
    "breakeven_trigger_r":     ("numeric", "R-multiple at which the stop was moved to breakeven (Layer 2)"),
    "final_r_vs_planned_stop": ("numeric", "final exit R vs the planned-initial-stop R (was it better/worse)"),
    "stop_quality_score":      ("smallint","operator/AI stop-quality rating 1-5 (post-trade)"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    a = ap.parse_args()
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT column_name FROM information_schema.columns WHERE table_name='paper_trades'""")
    existing = {r[0] for r in cur.fetchall()}
    todo = {c: v for c, v in NEW_COLUMNS.items() if c not in existing}
    print(f"paper_trades: {len(existing)} columns; {len(todo)} to add, {len(NEW_COLUMNS)-len(todo)} already present")
    for c, (typ, comment) in NEW_COLUMNS.items():
        print(f"  {'+ ADD' if c in todo else '= have'} {c:24} {typ:9} — {comment}")
    if not a.apply:
        print("\nDRY-RUN — re-run with --apply to add the columns."); return
    if not todo:
        print("\nnothing to add — already migrated."); return
    try:
        cur.execute("SET lock_timeout='5s'")
        for c, (typ, comment) in todo.items():
            cur.execute(f"ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS {c} {typ}")
            cur.execute(f"COMMENT ON COLUMN paper_trades.{c} IS %s", (comment,))
        conn.commit()
        print(f"\nAPPLIED — added {len(todo)} columns: {', '.join(todo)}")
    except Exception as e:
        conn.rollback()
        print(f"\nFAILED (rolled back) — {type(e).__name__}: {str(e)[:120]} "
              "(lock_timeout? retry off-hours when the server connection is idle)")


if __name__ == "__main__":
    main()
