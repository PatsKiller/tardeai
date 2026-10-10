#!/usr/bin/env python3
"""
Generate Hermes ops backlog items from recurring unresolved SIEM events.
Reads normalized alert events, groups by dedupe_key, creates backlog candidates.

Usage (cron L835, lane siem-to-hermes-backlog):
  python3 scripts/siem_to_hermes_backlog.py [--apply] [--dry-run] [--max N]

--dry-run WINS over --apply (refactor wave 3, 2026-10-10); without --apply the run is a preview too (legacy
behaviour, kept). A preview builds the candidates (normalize(dry_run=True): SELECTs only), then checks the 14-day
dedupe on a READ ONLY connection (lane_last_receipt.enforce_readonly) and prints a DRY-RUN report of what would be
inserted vs skipped; it never imports the writer (write_research_rows), never commits and writes no receipt.

Exit codes (--apply): 0 = ran (zero candidates / all duplicates is a finding); 1 = a crash (failed receipt,
re-raised) or every non-duplicate candidate was rejected by the writer (one rejection is a soft failure);
2 = usage error (argparse). A real run writes <state_root>/data/runtime/siem-to-hermes-backlog_last.json
(LaneRunReceipt@v1; ok_at only on success).
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

LANE_ID = "siem-to-hermes-backlog"

SIEM_BACKLOG_MAP = {
    "AGENT_STALENESS": ("ops_backlog", "OPS_AGENT"),
    "LLM_ESCALATION": ("ops_backlog", "OPS_LLM"),
    "FEED_HEALTH": ("ops_backlog", "OPS_FEED"),
    "PIPELINE_FAILURE": ("ops_backlog", "OPS_PIPELINE"),
    "DATA_QUALITY": ("research_backlog", "DATA_QUALITY"),
    "CLOSED_TRADE_REVIEW": ("research_backlog", "JOURNAL_QUALITY"),
    "SYSTEM_HEALTH": ("ops_backlog", "OPS"),
}


def _connect():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _dedupe_key(c):
    return json.loads(c["source_urls_json"])[0].get("dedupe_key", "")


def _already_filed(cur, c):
    """Engine Room v1 (WS-4) dedupe: same SIEM dedupe_key within 14 days = already filed. SELECT only."""
    cur.execute("""SELECT 1 FROM hermes_research_intelligence
                   WHERE research_type=%s AND source_urls_json::text LIKE %s
                     AND created_at > NOW() - INTERVAL '14 days' LIMIT 1""",
                [c["research_type"], f'%"dedupe_key": "{_dedupe_key(c)}"%'])
    return bool(cur.fetchone())


def preview_backlog(candidates):
    """Dry run: the 14-day dedupe check on a READ ONLY session. Returns (would_insert, would_skip_duplicate)."""
    if not candidates:
        return 0, 0
    try:
        from lib.lane_last_receipt import enforce_readonly
    except ImportError:  # repo root on sys.path, scripts/ not
        from scripts.lib.lane_last_receipt import enforce_readonly
    conn = _connect()
    try:
        enforce_readonly(conn)
        cur = conn.cursor()
        dup = sum(1 for c in candidates if _already_filed(cur, c))
    finally:
        conn.rollback()
        conn.close()
    return len(candidates) - dup, dup


LAST_STATS = {}


def generate_backlog(max_items=5, dry_run=True):
    """Generate backlog candidates from SIEM events."""
    from normalize_tradeai_alerts import normalize
    events, rollup = normalize(days=14, dry_run=True)

    # Group by dedupe_key, find recurring unresolved
    groups = {}
    for e in events:
        dk = e["dedupe_key"]
        if dk not in groups:
            groups[dk] = {"count": 0, "events": [], "severity": e["severity"], "event_type": e["event_type"]}
        groups[dk]["count"] += 1
        if len(groups[dk]["events"]) < 3:
            groups[dk]["events"].append(e)

    # Filter to recurring (>5 repeats) and P1/P2
    candidates = []
    for dk, g in groups.items():
        if g["count"] < 5:
            continue
        if g["severity"] not in ("P1", "P2"):
            continue

        mapping = SIEM_BACKLOG_MAP.get(g["event_type"], ("ops_backlog", "OPS"))
        research_type, display_cat = mapping
        sample = g["events"][0]

        candidates.append({
            "symbol": None,
            "research_type": research_type,
            "hermes_agent_name": "siem_backlog_generator",
            "topic": f"{g['event_type']}: {sample.get('component', 'system')} — {g['count']}× in 14 days",
            "summary": f"Recurring {g['severity']} event. Last: {sample.get('raw_message_excerpt', sample.get('message', ''))[:150]}. Repeat count: {g['count']}×. Dedupe key: {dk}",
            "confidence_score": min(0.7, 0.3 + g["count"] * 0.02),
            "source_urls_json": json.dumps([{"type": "siem", "dedupe_key": dk, "count": g["count"]}]),
            "display_category": display_cat,
            "recommended_action": f"Investigate {g['event_type']} from {sample.get('component', 'unknown')}. {g['count']} occurrences suggest unresolved root cause.",
        })

    candidates.sort(key=lambda c: -c["confidence_score"])
    candidates = candidates[:max_items]

    LAST_STATS.clear()
    LAST_STATS.update({"candidates": len(candidates), "duplicates": 0, "rejected": 0, "inserted": 0})
    if dry_run or not candidates:
        # Preview / nothing to do: return BEFORE any write connection or writer import (AGENTS.md §6).
        return candidates, 0

    conn = _connect()
    cur = conn.cursor()
    inserted = 0
    for c in candidates:
        # Engine Room v1 (WS-4): dedup is enforced, not just measured — same SIEM
        # dedupe_key within 14 days means the finding is already filed.
        dk = _dedupe_key(c)
        if _already_filed(cur, c):
            print(f"  Skipped duplicate (14d): {c['topic'][:60]}")
            LAST_STATS["duplicates"] += 1
            continue
        # One write module per store (SoT Phase 9): SQL lives in lib.writers.hermes_research_writer.
        from lib.writers.hermes_research_writer import write_research_rows
        rc = write_research_rows(cur, [{
            "symbol": c["symbol"], "research_type": c["research_type"],
            "hermes_agent_name": c["hermes_agent_name"], "topic": c["topic"], "summary": c["summary"],
            "confidence_score": c["confidence_score"], "source_urls_json": c["source_urls_json"],
            "evidence_json": json.dumps([{"type": "siem_backlog_finding", "source_surface": "siem",
                                          "priority": "high" if c["confidence_score"] >= 0.5 else "medium",
                                          "dedupe_key": dk, "advisory_only": True, "not_execution": True}]),
            "status": "staged", "source": "hermes", "model_used": "siem_normalizer",
        }], producer=c["hermes_agent_name"])
        if not rc.ids:
            print(f"  Rejected (not written): {rc.rows_rejected}")
            LAST_STATS["rejected"] += 1
            continue
        rid = rc.ids[0]
        inserted += 1
        print(f"  Inserted backlog id={rid}: {c['topic'][:60]}")
    conn.commit()
    conn.close()
    LAST_STATS["inserted"] = inserted
    return candidates, inserted


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="preview only; wins over --apply")
    args = ap.parse_args(argv)
    live = args.apply and not args.dry_run

    if not live:
        candidates, inserted = generate_backlog(max_items=args.max, dry_run=True)
        would_insert, would_skip = preview_backlog(candidates)
        print(f"\nBacklog candidates: {len(candidates)}")
        for c in candidates:
            print(f"  [{c['display_category']}] {c['topic'][:70]} (conf {c['confidence_score']:.2f})")
        try:
            from lib.lane_last_receipt import dry_run_report
        except ImportError:
            from scripts.lib.lane_last_receipt import dry_run_report
        dry_run_report(LANE_ID, {"candidates": len(candidates), "would_insert": would_insert,
                                 "would_skip_duplicate": would_skip, "max": args.max},
                       would_write=[f"hermes_research_intelligence: {would_insert} rows (lib.writers.hermes_research_writer)"])
        print("\nDry-run. Use --apply (without --dry-run) to insert.")
        return 0

    try:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
    except ImportError:
        from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        candidates, inserted = generate_backlog(max_items=args.max, dry_run=False)
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started, script="siem_to_hermes_backlog.py",
                           error=f"{type(exc).__name__}: {exc}")
        raise
    print(f"\nBacklog candidates: {len(candidates)}")
    for c in candidates:
        print(f"  [{c['display_category']}] {c['topic'][:70]} (conf {c['confidence_score']:.2f})")
    print(f"\nInserted: {inserted}")
    stats = dict(LAST_STATS)
    # every non-duplicate candidate rejected by the writer = the run failed; one rejection is a soft failure
    failed = stats.get("rejected", 0) > 0 and inserted == 0
    write_lane_receipt(LANE_ID, ok=not failed, exit_code=1 if failed else 0, started_at=started,
                       script="siem_to_hermes_backlog.py", summary={**stats, "max": args.max},
                       error="all_candidates_rejected" if failed else None)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
