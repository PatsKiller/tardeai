#!/usr/bin/env python3
"""Automated intelligence maturity loop — close gaps without operator clicks.

Runs on a timer (systemd/cron). Responsibilities:
  1. Auto-enqueue research gaps into RI queue (coverage_gap source)
  2. Auto-archive stale / ensemble-BLOCK signals in intelligence_item_state
  3. Auto-enqueue ensemble verification for weak/critical command-center signals
  4. Persist run metrics for Learning tab

Usage:
  python scripts/intelligence_remediation.py --dry-run
  python scripts/intelligence_remediation.py --run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _intel_item_id(item_type: str, source: str, symbol: str | None, title: str) -> str:
    s = f"{item_type}|{source}|{symbol or ''}|{title}"
    h = 5381
    for ch in s:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return f"{item_type}-{(h & 0xFFFFFFFF):x}"


def _db():
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        raise RuntimeError("DB unavailable")
    return _execute


def _ensure_tables(ex):
    ex("""
        CREATE TABLE IF NOT EXISTS intelligence_item_state (
            item_id TEXT PRIMARY KEY,
            item_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            note TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by TEXT NOT NULL DEFAULT 'operator'
        )""", fetch="none")
    ex("""
        CREATE TABLE IF NOT EXISTS intelligence_remediation_runs (
            id BIGSERIAL PRIMARY KEY,
            run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            gaps_enqueued INT NOT NULL DEFAULT 0,
            items_archived INT NOT NULL DEFAULT 0,
            ensemble_queued INT NOT NULL DEFAULT 0,
            watch_critics INT NOT NULL DEFAULT 0,
            note TEXT
        )""", fetch="none")
    ex("""
        ALTER TABLE intelligence_remediation_runs
          ADD COLUMN IF NOT EXISTS external_retries INT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS proposal_backfills INT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS s0_refreshes INT NOT NULL DEFAULT 0
    """, fetch="none")


def compute_research_gaps(ex) -> list[dict]:
    """Reuse GET /api/v2/research-topics gap detection (single source of truth)."""
    try:
        import api_v2
        data = api_v2._research_topics_unified()
        return data.get("research_gaps") or []
    except Exception:
        return []


def auto_enqueue_gaps(ex, dry_run: bool) -> int:
    from research_intelligence_queue import enqueue
    n = 0
    for g in compute_research_gaps(ex):
        tid = g.get("topic_id")
        if not tid:
            continue
        if dry_run:
            n += 1
            continue
        res = enqueue(tid, requested_by="gap_remediation", source="coverage_gap")
        if res.get("queued"):
            n += 1
    return n


def auto_archive_items(ex, dry_run: bool) -> int:
    """Archive ensemble consensus-BLOCK signals and stale active items (>7d)."""
    n = 0
    block_rows = ex("""
        SELECT target_id, subject, final_decision, consensus_reached, created_at
        FROM inference_ensemble_results
        WHERE target_type = 'signal'
          AND final_decision = 'block'
          AND consensus_reached IS TRUE
          AND created_at > NOW() - INTERVAL '14 days'
        ORDER BY created_at DESC
        LIMIT 100
    """, fetch="all") or []
    for r in block_rows:
        iid = r.get("target_id")
        if not iid:
            continue
        existing = ex("SELECT status FROM intelligence_item_state WHERE item_id=%s", (iid,), fetch="one")
        if existing and existing.get("status") != "active":
            continue
        if dry_run:
            n += 1
            continue
        ex("""
            INSERT INTO intelligence_item_state (item_id, item_type, status, note, updated_by)
            VALUES (%s, 'signal', 'dismissed', %s, 'gap_remediation')
            ON CONFLICT (item_id) DO UPDATE SET
              status='dismissed', note=EXCLUDED.note, updated_at=NOW(), updated_by='gap_remediation'
            WHERE intelligence_item_state.status = 'active'
        """, (iid, f"auto-archived: ensemble BLOCK ({r.get('subject') or ''})"), fetch="none")
        n += 1

    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    stale = ex("""
        SELECT item_id FROM intelligence_item_state
        WHERE status = 'active' AND updated_at < %s AND updated_by != 'operator'
    """, (stale_cutoff,), fetch="all") or []
    for r in stale:
        if dry_run:
            n += 1
            continue
        ex("""
            UPDATE intelligence_item_state SET status='dismissed',
                note=COALESCE(note,'') || ' · auto-archived: stale >7d',
                updated_at=NOW(), updated_by='gap_remediation'
            WHERE item_id=%s AND status='active'
        """, (r["item_id"],), fetch="none")
        n += 1
    return n


def _signal_candidates(ex) -> list[dict]:
    """High-priority signals needing ensemble verification."""
    out: list[dict] = []
    try:
        positions = ex("""
            SELECT symbol, stop_price, current_price
            FROM schwab_positions_live
            WHERE stop_price IS NOT NULL
            LIMIT 30
        """, fetch="all") or []
    except Exception:
        positions = []
    for p in positions:
        sym = p.get("symbol")
        if not sym:
            continue
        title = f"{sym} risk/stop review"
        out.append({
            "id": _intel_item_id("risk", "/api/v2/risk", sym, title),
            "subject": sym,
            "content": title,
            "severity": "critical",
        })
    inf = ex("""
        SELECT id, title, body, subject, severity, inference_type
        FROM inference_results
        WHERE created_at > NOW() - INTERVAL '48 hours'
          AND severity IN ('critical', 'high')
        ORDER BY created_at DESC
        LIMIT 20
    """, fetch="all") or []
    for r in inf:
        out.append({
            "id": str(r["id"]),
            "subject": r.get("subject") or "",
            "content": f"{r.get('title')}\n{r.get('body') or ''}",
            "severity": r.get("severity"),
            "target_type": "inference",
        })
    return out


def auto_enqueue_ensemble(ex, dry_run: bool) -> int:
    n = 0
    for sig in _signal_candidates(ex):
        tt = sig.get("target_type", "signal")
        tid = sig["id"]
        existing = ex("""
            SELECT id FROM inference_ensemble_jobs
            WHERE target_type=%s AND target_id=%s AND status IN ('queued','running')
            LIMIT 1
        """, (tt, tid), fetch="one")
        if existing:
            continue
        recent = ex("""
            SELECT id FROM inference_ensemble_results
            WHERE target_type=%s AND target_id=%s
              AND created_at > NOW() - INTERVAL '24 hours'
            LIMIT 1
        """, (tt, tid), fetch="one")
        if recent:
            continue
        if dry_run:
            n += 1
            continue
        ex("""
            INSERT INTO inference_ensemble_jobs
            (target_type, target_id, subject, content, task, requested_by, status)
            VALUES (%s,%s,%s,%s,'signal_quality','auto_remediation','queued')
        """, (tt, tid, (sig.get("subject") or "")[:300], sig.get("content", "")[:8000]), fetch="none")
        n += 1
    return n


def remediation_summary(ex) -> dict:
    last = ex("""
        SELECT * FROM intelligence_remediation_runs ORDER BY run_at DESC LIMIT 1
    """, fetch="one")
    totals = ex("""
        SELECT
          COALESCE(SUM(gaps_enqueued),0) AS gaps_enqueued,
          COALESCE(SUM(items_archived),0) AS items_archived,
          COALESCE(SUM(ensemble_queued),0) AS ensemble_queued,
          COALESCE(SUM(watch_critics),0) AS watch_critics,
          COALESCE(SUM(external_retries),0) AS external_retries,
          COALESCE(SUM(proposal_backfills),0) AS proposal_backfills,
          COALESCE(SUM(s0_refreshes),0) AS s0_refreshes,
          COUNT(*) AS run_count
        FROM intelligence_remediation_runs
        WHERE run_at > NOW() - INTERVAL '7 days'
    """, fetch="one") or {}
    hermes_totals = ex("""
        SELECT
          COALESCE(SUM(external_retries),0) AS external_retries,
          COALESCE(SUM(proposal_backfills),0) AS proposal_backfills,
          COALESCE(SUM(s0_refreshes),0) AS s0_refreshes,
          COUNT(*) AS run_count
        FROM intelligence_remediation_runs
        WHERE note = 'hermes_research_quality'
          AND run_at > NOW() - INTERVAL '7 days'
    """, fetch="one") or {}
    hermes_gates = {}
    hermes_candidates = {}
    try:
        from hermes_research_quality_remediation import (
            failed_external_symbols,
            proposals_missing_prior_research,
            stale_s0_symbols,
        )
        hermes_candidates = {
            "failed_external": len(failed_external_symbols(ex)),
            "proposals_missing_prior": len(proposals_missing_prior_research(ex)),
            "stale_s0": len(stale_s0_symbols(ex)),
        }
        from hermes_maturity_gates import _gates_research
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        hermes_gates = _gates_research(cur)
    except Exception:
        pass
    pending_gaps = len(compute_research_gaps(ex))
    pending_ensemble = ex("""
        SELECT COUNT(*) AS n FROM inference_ensemble_jobs WHERE status IN ('queued','running')
    """, fetch="one") or {}
    return {
        "last_run": last,
        "totals_7d": totals,
        "hermes_research_7d": hermes_totals,
        "research_gates": hermes_gates,
        "hermes_candidates": hermes_candidates,
        "pending_gaps": pending_gaps,
        "pending_ensemble_jobs": int(pending_ensemble.get("n") or 0),
    }


def run_loop(dry_run: bool = False) -> dict:
    ex = _db()
    _ensure_tables(ex)
    gaps = auto_enqueue_gaps(ex, dry_run)
    archived = auto_archive_items(ex, dry_run)
    ensemble = auto_enqueue_ensemble(ex, dry_run)
    watch_critics = 0  # counted by watch_decision_scheduler
    out = {
        "dry_run": dry_run,
        "gaps_enqueued": gaps,
        "items_archived": archived,
        "ensemble_queued": ensemble,
        "watch_critics": watch_critics,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if not dry_run:
        ex("""
            INSERT INTO intelligence_remediation_runs
            (gaps_enqueued, items_archived, ensemble_queued, watch_critics, note)
            VALUES (%s,%s,%s,%s,%s)
        """, (gaps, archived, ensemble, watch_critics, "intelligence_remediation"), fetch="none")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.summary:
        ex = _db()
        _ensure_tables(ex)
        print(json.dumps(remediation_summary(ex), indent=2, default=str))
        return
    result = run_loop(dry_run=not args.run)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
