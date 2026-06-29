#!/usr/bin/env python3
"""backfill_hermes_research_provenance.py — populate provenance on HISTORICAL Hermes research rows.

The provenance columns (added by migrate_hermes_research_provenance.py) are only filled for new rows.
This backfills the ~23k external + ~6k intelligence rows that pre-date enforcement, deriving FACTUAL
provenance from what each row already records:

  trigger_source  <- normalized trigger_reason (external) / research_type (intelligence)
  budget_tier     <- the policy tier that source maps to (UNMAPPED if unknown — surfaced, not hidden)
  lane_used       <- lane (external) / model_used (intelligence)
  budget_decision <- 'legacy' (these ran before the guard existed; we do NOT fabricate ALLOW/DEFER)
  research_expires_at <- created_at + tier TTL (so old rows read as expired, which they are)

It also reports the RETROSPECTIVE what-if: how many historical rows the current policy would have
sent to METADATA_ONLY (broad T3) or BLOCK (cold T4) — the governance value, surfaced not stored.

Idempotent: only touches rows where budget_tier IS NULL. UPDATEs are grouped by tier (a handful of
statements), not per-row. Read-mostly metadata; no broker calls, no LLM calls, no gate bypass.

  python3 scripts/backfill_hermes_research_provenance.py --dry-run    # preview counts, write nothing
  python3 scripts/backfill_hermes_research_provenance.py              # apply
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# research_type -> tier for hermes_research_intelligence (the external trigger_source_tier map in
# config/hermes_research_budget.yaml covers hermes_external_research).
INTEL_TIER = {
    "protection_advisory": "T0", "stop_curation": "T0", "stop_health": "T0", "trade_reflection": "T0",
    "momentum_catalyst": "T1", "options_desk": "T1", "operator_knowledge": "T1",
    "ticker_thesis_challenge": "T2", "topic_research": "T2", "news_research_reframe": "T2",
    "deep_research_local": "T2",
    "research_backlog": "T3", "backlog_resolution": "T3", "youtube_discovery": "T3",
    "source_discovery": "T3", "source_discovery_followup": "T3", "ops_backlog": "T3",
    "pipeline_quality_validation": "T3",
}
# external normalized trigger_reason values not in the YAML map (test/legacy aliases)
EXTRA_EXTERNAL_TIER = {"manual_test": "T1"}

TTL_HOURS = {"T0": 12, "T1": 12, "T2": 24, "T3": 72, "T4": 0, "UNMAPPED": 24}


def _load_external_map():
    import yaml
    with open(os.path.join(ROOT, "config", "hermes_research_budget.yaml")) as f:
        pol = yaml.safe_load(f)
    m = dict(pol.get("trigger_source_tier", {}))
    m.update(EXTRA_EXTERNAL_TIER)
    return m


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _tier_buckets(conn, table, source_expr, tier_map, fallback_intel=False):
    """Return {tier: [source values]} for distinct sources in `table` with NULL budget_tier."""
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT {source_expr} src FROM {table} WHERE budget_tier IS NULL")
    buckets = {}
    for (src,) in cur.fetchall():
        s = src or "manual"
        tier = (INTEL_TIER.get(s) if fallback_intel else tier_map.get(s)) or tier_map.get(s) or "UNMAPPED"
        buckets.setdefault(tier, []).append(s)
    return buckets


def backfill(conn, table, source_expr, lane_expr, tier_map, fallback_intel=False, apply=True):
    cur = conn.cursor()
    report = {"table": table, "by_tier": {}, "rows_updated": 0}
    buckets = _tier_buckets(conn, table, source_expr, tier_map, fallback_intel)
    for tier, sources in buckets.items():
        ttl = TTL_HOURS.get(tier, 24)
        # count first (for dry-run + report)
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE budget_tier IS NULL AND {source_expr} = ANY(%s)",
            (sources,))
        n = cur.fetchone()[0]
        report["by_tier"][tier] = {"rows": n, "distinct_sources": len(sources)}
        if not apply or n == 0:
            continue
        cur.execute(
            f"""UPDATE {table}
                   SET trigger_source = {source_expr},
                       budget_tier = %s,
                       lane_used = COALESCE(lane_used, {lane_expr}),
                       budget_decision = COALESCE(budget_decision, 'legacy'),
                       research_expires_at = COALESCE(research_expires_at,
                                                      created_at + (%s || ' hours')::interval)
                 WHERE budget_tier IS NULL AND {source_expr} = ANY(%s)""",
            (tier, str(ttl), sources))
        report["rows_updated"] += cur.rowcount
    if apply:
        conn.commit()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="preview counts, write nothing")
    a = ap.parse_args()
    conn = _conn()
    ext_map = _load_external_map()

    out = {"applied": not a.dry_run, "tables": []}
    out["tables"].append(backfill(
        conn, "hermes_external_research",
        "split_part(COALESCE(trigger_reason,'manual'),':',1)", "lane", ext_map, apply=not a.dry_run))
    out["tables"].append(backfill(
        conn, "hermes_research_intelligence",
        "COALESCE(research_type,'manual')", "model_used", INTEL_TIER, fallback_intel=True, apply=not a.dry_run))

    # Retrospective what-if: T3 -> would be METADATA_ONLY, T4 -> would be BLOCK under current policy.
    whatif = {"metadata_only_T3": 0, "blocked_T4": 0, "allowed_T0_T2": 0, "unmapped": 0}
    for t in out["tables"]:
        for tier, info in t["by_tier"].items():
            if tier == "T3":
                whatif["metadata_only_T3"] += info["rows"]
            elif tier == "T4":
                whatif["blocked_T4"] += info["rows"]
            elif tier == "UNMAPPED":
                whatif["unmapped"] += info["rows"]
            else:
                whatif["allowed_T0_T2"] += info["rows"]
    out["retrospective_whatif"] = whatif
    out["note"] = ("Factual provenance backfilled; budget_decision='legacy' (pre-enforcement, not "
                   "fabricated). retrospective_whatif shows how much the CURRENT policy would have cut. "
                   "No broker/LLM calls.")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
