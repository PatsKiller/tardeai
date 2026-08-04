#!/usr/bin/env python3
"""Hermes Discovery Yield Builder — nightly per-type/domain yield from outcome ledger.

Phase 5: builds data/runtime/hermes_discovery_yield.json consumed by
scoring._load_outcome_yield_map(). Sample-gated at n >= YIELD_MIN_SAMPLES (10).

Linkage paths (in priority order):
  1. Promoted candidate → topic_monitor → hermes_research_intelligence (promoted rows) → outcome ledger
  2. Promoted TICKER → watch_directive → trade_instances → outcome ledger
  3. Broad: all candidates of type X → symbols mentioned → outcome ledger (noise-tolerant baseline)

Every path is advisory-only, zero broker imports.

Usage:
  python scripts/hermes_discovery_yield_builder.py [--apply] [--dry-run]
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

OUTPUT_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_yield.json"
KILL_FILE = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
MIN_SAMPLES = 10
LOOKBACK_DAYS = 90  # outcome window

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    env_path = PROJECT_ROOT / ".env"
    db_pass = None
    for line in env_path.read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            db_pass = line.split("=", 1)[1]
    if not db_pass:
        raise RuntimeError("DB_PASSWORD not found")
    import psycopg2
    return psycopg2.connect(
        host="localhost", dbname="trade_ai", user="trade_ai",
        password=db_pass, keepalives=1, keepalives_idle=30,
        keepalives_interval=10, keepalives_count=3, connect_timeout=10)

# ── yield computation ─────────────────────────────────────────────────────────

def _safe_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

def build_yield_map(conn) -> dict:
    """Build per-type/domain yield map from discovery + outcome data.

    Returns {key: {n, yield_rate, avg_realized_r, last_computed}}
    where key is 'candidate_type' or 'candidate_type:domain'.

    The outcome ledger schema has: symbol, verdict (hit/miss), realized_r,
    outcome_ret_20d, subject_type, subject_id, created_at.
    """
    cur = conn.cursor()
    yield_map = {}

    # ── Path 1: Promoted candidates → research topics → outcomes ──
    # Candidate promoted to research_topic → topic_monitor → hermes_research_intelligence
    # → outcome ledger (where subject_type='promotion' and subject_id links to promotion_audit)
    cur.execute("""
        WITH promoted AS (
            SELECT DISTINCT
                dc.id AS candidate_id,
                dc.candidate_type,
                COALESCE(dc.meta_json->>'research_domain', 'general') AS domain,
                da.after_json->>'promoted_ref_id' AS topic_id
            FROM hermes_discovery_candidates dc
            JOIN hermes_discovery_audit da ON da.candidate_id = dc.id
            WHERE da.action = 'PROMOTE'
              AND da.after_json->>'promoted_ref_type' = 'research_topic'
              AND dc.created_at > CURRENT_DATE - INTERVAL '%s days'
        ),
        research_outcomes AS (
            SELECT p.candidate_type, p.domain,
                   l.symbol, l.realized_r, l.verdict
            FROM promoted p
            JOIN topic_monitor tm ON tm.topic_id = p.topic_id
            JOIN hermes_research_intelligence hri
              ON LOWER(hri.topic) LIKE '%%' || LOWER(tm.display_name) || '%%'
              AND hri.status = 'promoted'
            LEFT JOIN hermes_outcome_ledger l
              ON l.symbol = hri.symbol
              AND l.created_at > hri.created_at - INTERVAL '60 days'
              AND l.created_at < hri.created_at + INTERVAL '60 days'
        )
        SELECT candidate_type, domain,
               COUNT(*) AS n,
               COUNT(*) FILTER (WHERE verdict = 'hit')::float
                 / NULLIF(COUNT(*) FILTER (WHERE verdict IN ('hit','miss')), 0) AS yield_rate,
               AVG(COALESCE(realized_r, 0)) AS avg_realized_r
        FROM research_outcomes
        GROUP BY candidate_type, domain
        HAVING COUNT(*) >= %s
    """, (LOOKBACK_DAYS, MIN_SAMPLES))

    for ctype, domain, n, yield_rate, avg_r in cur.fetchall():
        key = f"{ctype}:{domain}" if domain and domain != "general" else ctype
        entry = yield_map.setdefault(key, {"n": 0, "yield_rate": 0.0, "avg_realized_r": 0.0})
        y = _safe_float(yield_rate) or 0.0
        r = _safe_float(avg_r) or 0.0
        entry["n"] += n
        old_n = max(entry.get("_prior_n", 0), 1)
        entry["yield_rate"] = (entry["yield_rate"] * old_n + y * n) / (old_n + n)
        entry["avg_realized_r"] = (entry["avg_realized_r"] * old_n + r * n) / (old_n + n)
        entry["_prior_n"] = entry["n"]

    # ── Path 2: TICKER candidates → watch evaluation → trade outcomes ──
    cur.execute("""
        WITH ticker_promoted AS (
            SELECT DISTINCT
                dc.id AS candidate_id,
                dc.candidate_type,
                COALESCE(dc.meta_json->>'research_domain', 'general') AS domain,
                UPPER(dc.label) AS symbol
            FROM hermes_discovery_candidates dc
            JOIN hermes_discovery_audit da ON da.candidate_id = dc.id
            WHERE da.action = 'PROMOTE'
              AND da.after_json->>'promoted_ref_type' = 'watch_evaluation'
              AND dc.created_at > CURRENT_DATE - INTERVAL '%s days'
        ),
        symbol_outcomes AS (
            SELECT tp.candidate_type, tp.domain, tp.symbol,
                   l.realized_r, l.verdict
            FROM ticker_promoted tp
            LEFT JOIN hermes_outcome_ledger l
              ON l.symbol = tp.symbol
              AND l.created_at > CURRENT_DATE - INTERVAL '%s days'
        )
        SELECT candidate_type, domain,
               COUNT(*) AS n,
               COUNT(*) FILTER (WHERE verdict = 'hit')::float
                 / NULLIF(COUNT(*) FILTER (WHERE verdict IN ('hit','miss')), 0) AS yield_rate,
               AVG(COALESCE(realized_r, 0)) AS avg_realized_r
        FROM symbol_outcomes
        GROUP BY candidate_type, domain
        HAVING COUNT(*) >= %s
    """, (LOOKBACK_DAYS, LOOKBACK_DAYS, MIN_SAMPLES))

    for ctype, domain, n, yield_rate, avg_r in cur.fetchall():
        key = f"{ctype}:{domain}" if domain and domain != "general" else ctype
        entry = yield_map.setdefault(key, {"n": 0, "yield_rate": 0.0, "avg_realized_r": 0.0})
        old_n = max(entry.get("_prior_n", 0), 1)
        entry["n"] += n
        entry["yield_rate"] = (entry["yield_rate"] * old_n + _safe_float(yield_rate) * n) / (old_n + n)
        entry["avg_realized_r"] = (entry["avg_realized_r"] * old_n + (_safe_float(avg_r) or 0) * n) / (old_n + n)
        entry["_prior_n"] = entry["n"]

    # ── Path 3: Broad per-type baseline ──
    # All discovery candidates of type X, joined to any outcome ledger row
    # where the candidate's extracted_symbols or label matches the ledger symbol.
    # Noisier but provides a baseline when promotion data is thin.
    cur.execute("""
        WITH candidate_symbols AS (
            SELECT id, candidate_type,
                   COALESCE(meta_json->>'research_domain', 'general') AS domain,
                   UNNEST(
                       CASE WHEN extracted_symbols IS NULL OR array_length(extracted_symbols, 1) IS NULL
                            THEN ARRAY[UPPER(label)]
                            ELSE extracted_symbols
                       END
                   ) AS sym
            FROM hermes_discovery_candidates
            WHERE created_at > CURRENT_DATE - INTERVAL '%s days'
              AND candidate_type IN ('TICKER_CANDIDATE', 'TREND_CANDIDATE',
                                     'SOURCE_CANDIDATE', 'TOPIC_CANDIDATE')
        ),
        type_outcomes AS (
            SELECT cs.candidate_type, cs.domain,
                   l.realized_r, l.verdict
            FROM candidate_symbols cs
            JOIN hermes_outcome_ledger l ON l.symbol = cs.sym
            WHERE l.created_at > CURRENT_DATE - INTERVAL '%s days'
        )
        SELECT candidate_type, domain,
               COUNT(*) AS n,
               COUNT(*) FILTER (WHERE verdict = 'hit')::float
                 / NULLIF(COUNT(*) FILTER (WHERE verdict IN ('hit','miss')), 0) AS yield_rate,
               AVG(COALESCE(realized_r, 0)) AS avg_realized_r
        FROM type_outcomes
        GROUP BY candidate_type, domain
        HAVING COUNT(*) >= %s
    """, (LOOKBACK_DAYS, LOOKBACK_DAYS, MIN_SAMPLES))

    for ctype, domain, n, yield_rate, avg_r in cur.fetchall():
        key = f"{ctype}:{domain}" if domain and domain != "general" else ctype
        entry = yield_map.setdefault(key, {"n": 0, "yield_rate": 0.0, "avg_realized_r": 0.0})
        old_n = max(entry.get("_prior_n", 0), 1)
        entry["n"] += n
        # Path 3 is noisier — weight it at 0.5 vs paths 1/2
        w = 0.5
        adj_n = int(n * w)
        entry["yield_rate"] = (entry["yield_rate"] * old_n + _safe_float(yield_rate) * adj_n) / (old_n + adj_n)
        entry["avg_realized_r"] = (entry["avg_realized_r"] * old_n + (_safe_float(avg_r) or 0) * adj_n) / (old_n + adj_n)
        entry["_prior_n"] = entry["n"]

    # ── Clean up internal keys and round ──
    for key in list(yield_map):
        entry = yield_map[key]
        entry.pop("_prior_n", None)
        entry["n"] = int(entry["n"])
        entry["yield_rate"] = round(entry["yield_rate"], 4)
        entry["avg_realized_r"] = round(entry["avg_realized_r"], 6)
        if entry["n"] < MIN_SAMPLES:
            del yield_map[key]

    cur.close()
    return yield_map


def compute_yield_file(*, apply: bool = False) -> dict:
    """Compute and optionally write the yield file."""
    if KILL_FILE.exists():
        return {"status": "kill_switch", "entries": 0}

    conn = get_db()
    try:
        yield_map = build_yield_map(conn)
    finally:
        try: conn.close()
        except Exception: pass

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "hermes_discovery_yield_builder",
        "lookback_days": LOOKBACK_DAYS,
        "min_samples": MIN_SAMPLES,
        "entries": len(yield_map),
        "yield": yield_map,
    }

    if apply:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(result, indent=2, default=str))
        print(f"Wrote {len(yield_map)} yield entries → {OUTPUT_PATH}")

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hermes Discovery Yield Builder (Phase 5)")
    parser.add_argument("--apply", action="store_true", help="Write yield file (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    apply = args.apply and not args.dry_run
    result = compute_yield_file(apply=apply)

    if args.json:
        # Summary only (full yield map can be large)
        summary = {k: v for k, v in result.items() if k != "yield"}
        summary["yield_keys"] = list(result.get("yield", {}).keys())
        summary["yield_sample"] = {k: result["yield"][k] for k in list(result.get("yield", {}).keys())[:10]}
        print(json.dumps(summary, indent=2, default=str))
    else:
        mode = "APPLY" if apply else "DRY-RUN"
        entries = result.get("entries", 0)
        print(f"[{mode}] Discovery yield builder: {entries} entries")
        if entries > 0:
            for key, data in sorted(result.get("yield", {}).items()):
                print(f"  {key}: n={data['n']} yield_rate={data['yield_rate']:.3f} "
                      f"avg_r={data['avg_realized_r']:+.4f}")
        else:
            print("  No entries meet min_samples threshold yet — expected for new system")


if __name__ == "__main__":
    main()
