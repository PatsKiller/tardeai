#!/usr/bin/env python3
"""migrate_synthesis_source_provenance.py — extend Hermes research provenance to the synthesis &
source-curation tables (the tables that create research-LIKE conclusions but pre-dated the guard).

Two safe, idempotent steps:
  1. ADD COLUMN IF NOT EXISTS — nullable provenance columns (additive, reversible, no rewrites/drops).
  2. Backfill HISTORICAL rows (budget_tier IS NULL) with FACTUAL provenance derived from what each row
     already records. budget_decision is set to 'legacy' — these rows pre-date enforcement, so we do
     NOT fabricate an ALLOW/DEFER decision. trigger_id / downstream_outcome / source_row_id stay NULL
     for legacy rows (no real lineage to claim).

Covered tables (all lacked provenance before this migration):
  watchlist_final_synthesis, risk_synthesis_results, watchlist_synthesis_safety_history   (LLM synthesis)
  source_weights, source_performance, source_learning_scores, rec_source_quality          (source scoring)

Source-scoring tables do NOT call an LLM — they compute statistics. Their lane is recorded honestly as
'computed' and they map to T3 (broad/metadata), never claiming an LLM research decision.

NOT a broker/execution write. Advisory metadata only. No LLM calls, no gate bypass.

  python3 scripts/migrate_synthesis_source_provenance.py --check     # report only, no writes (= --dry-run)
  python3 scripts/migrate_synthesis_source_provenance.py --dry-run   # alias for --check
  python3 scripts/migrate_synthesis_source_provenance.py             # apply DDL + legacy backfill
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# Uniform provenance column set (matches the vocabulary already on hermes_external_research /
# hermes_research_intelligence, plus source_table/source_row_id lineage pointers). All nullable.
PROV_COLUMNS = [
    ("trigger_source", "text"),
    ("trigger_id", "text"),
    ("budget_tier", "text"),
    ("budget_decision", "text"),       # ALLOW | DEFER | METADATA_ONLY | BLOCK | legacy
    ("lane_used", "text"),
    ("research_expires_at", "timestamptz"),
    ("research_reason", "text"),
    ("downstream_outcome", "text"),
    ("source_table", "text"),          # lineage: upstream table this conclusion drew from
    ("source_row_id", "text"),         # lineage: upstream row id
]

# table -> (timestamp_col, tier, trigger_source label, lane_expr, research_reason)
TABLES = {
    "watchlist_final_synthesis":           ("created_at",   "T2", "watchlist_synthesis",
                                             "COALESCE(model_used,'metadata')", "watchlist_final_synthesis"),
    "risk_synthesis_results":              ("generated_at", "T2", "risk_synthesis",
                                             "'metadata'", "portfolio_risk_synthesis"),
    "watchlist_synthesis_safety_history":  ("created_at",   "T2", "synthesis_safety_audit",
                                             "'metadata'", "synthesis_safety_audit"),
    "source_weights":                      ("computed_at",  "T3", "source_scoring",
                                             "'computed'", "source_weight_scoring"),
    "source_performance":                  ("updated_at",   "T3", "source_scoring",
                                             "'computed'", "source_performance_scoring"),
    "source_learning_scores":              ("created_at",   "T3", "source_learning",
                                             "'computed'", "source_learning_scoring"),
    "rec_source_quality":                  ("computed_at",  "T3", "source_scoring",
                                             "'computed'", "rec_source_quality_scoring"),
}

TTL_HOURS = {"T2": 24, "T3": 72}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _existing_cols(conn, table):
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
    return {r[0] for r in cur.fetchall()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--dry-run", action="store_true", help="alias for --check")
    a = ap.parse_args()
    preview = a.check or a.dry_run

    conn = _conn()
    report = {"applied": not preview, "preview": preview, "tables": [],
              "columns_added": [], "columns_present": [], "would_add": [], "rows_backfilled": 0}

    for table, (ts_col, tier, src_label, lane_expr, reason) in TABLES.items():
        have = _existing_cols(conn, table)
        t_rep = {"table": table, "tier": tier, "trigger_source": src_label,
                 "cols_added": [], "rows_to_backfill": 0, "rows_backfilled": 0}

        # --- 1. additive DDL ---
        for name, typ in PROV_COLUMNS:
            if name in have:
                report["columns_present"].append(f"{table}.{name}")
                continue
            if preview:
                report["would_add"].append(f"{table}.{name} {typ}")
                t_rep["cols_added"].append(f"{name} (would add)")
                continue
            cur = conn.cursor()
            cur.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{name}" {typ}')
            conn.commit()
            report["columns_added"].append(f"{table}.{name} {typ}")
            t_rep["cols_added"].append(name)

        # --- 2. legacy backfill (rows with NULL budget_tier) ---
        ttl = TTL_HOURS.get(tier, 24)
        if preview and "budget_tier" not in have:
            # column doesn't exist yet — every row would be backfilled
            cur = conn.cursor(); cur.execute(f"SELECT COUNT(*) FROM {table}")
            t_rep["rows_to_backfill"] = cur.fetchone()[0]
        else:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE budget_tier IS NULL")
            t_rep["rows_to_backfill"] = cur.fetchone()[0]
            if not preview and t_rep["rows_to_backfill"]:
                cur.execute(
                    f"""UPDATE {table}
                           SET trigger_source = COALESCE(trigger_source, %s),
                               budget_tier = %s,
                               budget_decision = COALESCE(budget_decision, 'legacy'),
                               lane_used = COALESCE(lane_used, {lane_expr}),
                               research_reason = COALESCE(research_reason, %s),
                               research_expires_at = COALESCE(research_expires_at,
                                                              {ts_col} + (%s || ' hours')::interval)
                         WHERE budget_tier IS NULL""",
                    (src_label, tier, reason, str(ttl)))
                conn.commit()
                t_rep["rows_backfilled"] = cur.rowcount
                report["rows_backfilled"] += cur.rowcount

        report["tables"].append(t_rep)

    report["note"] = ("Additive provenance columns + FACTUAL legacy backfill (budget_decision='legacy', "
                      "never fabricated ALLOW/DEFER). Source-scoring tables recorded lane='computed' (no LLM). "
                      "trigger_id/downstream_outcome/source_row_id left NULL for legacy rows. No broker/LLM calls.")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
