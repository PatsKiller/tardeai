#!/usr/bin/env python3
"""weekly_incubator_builder.py — Build/refresh incubator universe from latest scans.

Run weekly (Sunday 7 PM). Pulls qualified tickers from trade_ai_scans,
strategy_signals, and prospects. Inserts/updates incubator_universe.

Usage:
    .venv/bin/python scripts/weekly_incubator_builder.py --run-label 1000 --dry-run
    .venv/bin/python scripts/weekly_incubator_builder.py --run-label 1000 --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn
from multi_strategy_classifier import load_all_strategies, classify_symbol, load_enrichment_cache

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

log = logging.getLogger("weekly_incubator_builder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

QUALIFYING_QUERY = """
SELECT DISTINCT ON (s.symbol)
    s.symbol,
    s.score, s.decision, s.grade,
    s.rvol, s.float_m, s.gap_pct, s.change_pct,
    s.catalyst, s.catalyst_verified, s.sector, s.industry,
    s.run_label, s.run_type, s.scanned_at, s.screener_label, s.price
FROM trade_ai_scans s
WHERE s.scanned_at > NOW() - INTERVAL '7 days'
AND (
    s.score >= 30
    OR s.decision IN ('GO', 'WAIT')
    OR s.grade IN ('A+', 'A', 'B+', 'B')
    OR s.rvol >= 3.0
    OR s.catalyst_verified = true
)
ORDER BY s.symbol, s.score DESC NULLS LAST
LIMIT %s
"""

MULTI_SOURCE_QUERY = """
SELECT symbol, COUNT(DISTINCT run_type) as src_count
FROM trade_ai_scans
WHERE scanned_at > NOW() - INTERVAL '7 days'
GROUP BY symbol
HAVING COUNT(DISTINCT run_type) > 1
"""

CHECK_EXISTING_QUERY = """
SELECT id, symbol, strategy_id, baseline_score, best_score, days_active,
       status, lifecycle_state
FROM incubator_universe
WHERE symbol = %s AND strategy_id = %s
"""

UPSERT_QUERY = """
INSERT INTO incubator_universe (
    symbol, strategy_id, status, lifecycle_state,
    source_first_seen, source_latest, source_run_label,
    baseline_score, latest_score, best_score, score_delta,
    rvol_baseline, rvol_latest, gap_baseline, gap_latest,
    catalyst, catalyst_verified, sector, industry,
    days_active, first_seen_at, last_seen_at, updated_at,
    evidence_payload
) VALUES (
    %s, %s, 'ACTIVE', 'ROLLED_ON',
    %s, %s, %s,
    %s, %s, %s, 0,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    0, NOW(), NOW(), NOW(),
    %s
)
ON CONFLICT (symbol, strategy_id) DO UPDATE SET
    status = 'ACTIVE',
    lifecycle_state = CASE
        WHEN incubator_universe.status = 'ROLLED_OFF' THEN 'ROLLED_ON'
        ELSE incubator_universe.lifecycle_state
    END,
    source_latest = EXCLUDED.source_latest,
    source_run_label = EXCLUDED.source_run_label,
    latest_score = EXCLUDED.latest_score,
    score_delta = EXCLUDED.latest_score - incubator_universe.baseline_score,
    best_score = GREATEST(COALESCE(incubator_universe.best_score, 0), EXCLUDED.latest_score),
    rvol_latest = EXCLUDED.rvol_latest,
    gap_latest = EXCLUDED.gap_latest,
    catalyst = EXCLUDED.catalyst,
    catalyst_verified = EXCLUDED.catalyst_verified,
    last_seen_at = NOW(),
    updated_at = NOW(),
    days_active = incubator_universe.days_active + 1,
    evidence_payload = EXCLUDED.evidence_payload
RETURNING id, (xmax = 0) AS is_insert
"""

EVENT_INSERT = """
INSERT INTO incubator_events (symbol, strategy_id, event_type, reason_codes, old_score, new_score, payload)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def fetch_qualifying_tickers(conn, limit):
    """Fetch tickers meeting incubator qualification criteria."""
    cur = conn.cursor()
    cur.execute(QUALIFYING_QUERY, [limit])
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    log.info("Fetched %d qualifying tickers from trade_ai_scans", len(rows))
    return rows


def fetch_multi_source_symbols(conn):
    """Get symbols appearing in multiple scan sources (extra qualification)."""
    cur = conn.cursor()
    cur.execute(MULTI_SOURCE_QUERY)
    return {row[0]: row[1] for row in cur.fetchall()}


def get_existing(conn, symbol, strategy_id):
    """Check if symbol+strategy already exists in incubator."""
    cur = conn.cursor()
    cur.execute(CHECK_EXISTING_QUERY, [symbol, strategy_id or ''])
    row = cur.fetchone()
    if row:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    return None


def build_evidence(tick, multi_source_map):
    """Build evidence payload for the incubator entry."""
    reasons = []
    score = float(tick.get("score") or 0)
    if score >= 30:
        reasons.append(f"score={score}")
    if tick.get("decision") in ("GO", "WAIT"):
        reasons.append(f"decision={tick['decision']}")
    if tick.get("grade") in ("A+", "A", "B+", "B"):
        reasons.append(f"grade={tick['grade']}")
    rvol = float(tick.get("rvol") or 0)
    if rvol >= 3.0:
        reasons.append(f"rvol={rvol}")
    if tick.get("catalyst_verified"):
        reasons.append("catalyst_verified")
    if tick["symbol"] in multi_source_map:
        reasons.append(f"multi_source={multi_source_map[tick['symbol']]}")

    return {
        "qualification_reasons": reasons,
        "scan_data": {
            "score": score,
            "decision": tick.get("decision"),
            "grade": tick.get("grade"),
            "rvol": rvol,
            "gap_pct": float(tick.get("gap_pct") or 0),
            "change_pct": float(tick.get("change_pct") or 0),
            "float_m": float(tick.get("float_m") or 0),
            "run_label": tick.get("run_label"),
            "run_type": tick.get("run_type"),
        },
    }


def upsert_ticker(conn, tick, multi_source_map, strategy_id=None, match_info=None, dry_run=False):
    """Upsert a single ticker+strategy into incubator_universe and write event."""
    symbol = tick["symbol"]
    strategy_id = strategy_id or tick.get("strategy_id") or "screener"
    score = float(tick.get("score") or 0)
    rvol = float(tick.get("rvol") or 0)
    gap_pct = float(tick.get("gap_pct") or 0)
    source = tick.get("screener_label") or tick.get("run_type") or "trade_ai_scans"
    run_label = tick.get("run_label")
    evidence = build_evidence(tick, multi_source_map)
    if match_info:
        evidence["strategy_match"] = match_info

    existing = get_existing(conn, symbol, strategy_id)

    if dry_run:
        action = "UPDATE" if existing else "INSERT"
        src = match_info.get("match_source", "?") if match_info else "legacy"
        log.info("[DRY-RUN] %s %s strategy=%s score=%.1f src=%s",
                 action, symbol, strategy_id, score, src)
        return "stayed" if existing else "rolled_on"

    cur = conn.cursor()
    cur.execute(UPSERT_QUERY, [
        symbol, strategy_id,
        source, source, run_label,
        score, score, score,
        rvol, rvol, gap_pct, gap_pct,
        tick.get("catalyst"), tick.get("catalyst_verified"),
        tick.get("sector"), tick.get("industry"),
        json.dumps(evidence),
    ])
    result = cur.fetchone()
    is_insert = result[1] if result else True

    old_score = existing["baseline_score"] if existing else None
    event_type = "ROLLED_ON" if is_insert else "STAYED_ACTIVE"

    cur.execute(EVENT_INSERT, [
        symbol, strategy_id, event_type,
        json.dumps(evidence["qualification_reasons"]),
        float(old_score) if old_score is not None else None,
        score,
        json.dumps(evidence),
    ])

    return "rolled_on" if is_insert else "stayed"


def main():
    parser = argparse.ArgumentParser(description="Weekly incubator universe builder")
    parser.add_argument("--run-label", type=str, default=None, help="Run label for tracking")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing to DB")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    parser.add_argument("--limit", type=int, default=200, help="Max tickers to process (default 200)")
    parser.add_argument("--llm", action="store_true", help="Enable LLM-assisted classification via qwen3:14b")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        log.error("Must specify --dry-run or --apply")
        sys.exit(1)

    # Load all strategies + enrichment data dynamically
    all_strategies = load_all_strategies()
    enrichment = load_enrichment_cache()
    log.info("Loaded %d strategies, %d enriched symbols for matching",
             len(all_strategies), len(enrichment))

    conn = get_conn()
    try:
        tickers = fetch_qualifying_tickers(conn, args.limit)
        multi_source_map = fetch_multi_source_symbols(conn)

        rolled_on = 0
        stayed = 0
        total_strategy_matches = 0
        multi_match_count = 0

        for tick in tickers:
            # Multi-strategy classification with full enrichment data
            matches = classify_symbol(tick, all_strategies, use_llm=args.llm,
                                      enrichment_cache=enrichment)

            if not matches:
                # Fallback: still insert as 'screener' so nothing is lost
                result = upsert_ticker(conn, tick, multi_source_map,
                                       strategy_id="screener", dry_run=args.dry_run)
                if result == "rolled_on":
                    rolled_on += 1
                else:
                    stayed += 1
                total_strategy_matches += 1
            else:
                if len(matches) > 1:
                    multi_match_count += 1
                for match in matches:
                    result = upsert_ticker(
                        conn, tick, multi_source_map,
                        strategy_id=match["strategy_id"],
                        match_info=match,
                        dry_run=args.dry_run,
                    )
                    if result == "rolled_on":
                        rolled_on += 1
                    else:
                        stayed += 1
                    total_strategy_matches += 1

        if args.apply:
            conn.commit()
            log.info("Committed changes to database")
        else:
            conn.rollback()

        # Count total active
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM incubator_universe WHERE status = 'ACTIVE'")
        total_active = cur.fetchone()[0]

        # Strategy distribution
        cur.execute("""
            SELECT strategy_id, COUNT(*) as cnt
            FROM incubator_universe WHERE status = 'ACTIVE'
            GROUP BY strategy_id ORDER BY cnt DESC
        """)
        dist = cur.fetchall()

        log.info("=== SUMMARY ===")
        log.info("Symbols processed: %d", len(tickers))
        log.info("Strategy matches:  %d (%.1f avg per symbol)",
                 total_strategy_matches, total_strategy_matches / max(1, len(tickers)))
        log.info("Multi-strategy:    %d symbols matched 2+ strategies", multi_match_count)
        log.info("Rolled on (new):   %d", rolled_on)
        log.info("Stayed active:     %d", stayed)
        log.info("Total active:      %d", total_active)
        log.info("LLM enabled:       %s", "YES" if args.llm else "NO")
        log.info("Run label:         %s", args.run_label)
        log.info("Mode:              %s", "DRY-RUN" if args.dry_run else "APPLIED")
        if dist:
            log.info("Strategy distribution:")
            for sid, cnt in dist:
                log.info("  %-30s %d", sid, cnt)

    except Exception:
        conn.rollback()
        log.exception("weekly_incubator_builder failed")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    with PipelineRun("weekly_incubator_builder") as _run:
        main()

