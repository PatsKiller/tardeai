#!/usr/bin/env python3
"""purge_error_synthesis.py — remove failed-LLM artifacts from watchlist_final_synthesis.

During the Apr 29 – May 8 2026 provider outage, 404 rows were upserted with the literal
narrative "LLM error: All providers failed" (recommendation RESEARCH_MORE, confidence 0.5 —
pure boilerplate). Because the table is one-row-per-symbol, those rows rendered as CIO notes
on cards for months (ANET showed the error text for 65 days). The write path is now guarded
(run_synthesis skips the upsert when every lane fails); this script cleans up the backlog:

  1. Backs up matching rows to data/runtime/synthesis_error_purge_<ts>.json (restore-ready).
  2. Deletes them — a missing row simply renders as "no CIO note yet"; the next synthesis
     pass recreates it via the normal upsert.
  3. Enqueues a full_chain re-synthesis (deduped, priority 3, capped) ONLY for purged symbols
     in the Hermes top-200 — the set the watch page actually shows. The other ~350 regenerate
     organically via the research scheduler / holdings-change trigger; re-queueing all 404
     would flood the LLM job queue for symbols nobody is looking at.

Dry-run by default; --apply to execute. Advisory-only — research queue writes, never orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

BACKUP_DIR = PROJECT_ROOT / "data" / "runtime"

ERROR_PATTERN = "LLM error:%"  # conservative: only the known failure prefix


def main() -> int:
    ap = argparse.ArgumentParser(description="Purge failed-LLM synthesis narratives.")
    ap.add_argument("--apply", action="store_true", help="backup + delete + enqueue (default: dry-run report)")
    ap.add_argument("--max-enqueue", type=int, default=60, help="hard cap on re-synthesis jobs queued (default 60)")
    args = ap.parse_args()

    from db_adapter import _execute

    rows = _execute(
        """SELECT symbol, recommendation, confidence, synthesis_narrative, model_used,
                  created_at, updated_at
           FROM watchlist_final_synthesis
           WHERE synthesis_narrative ILIKE %s
           ORDER BY symbol""", (ERROR_PATTERN,), fetch="all") or []
    if not rows:
        print("no error-narrative rows found — nothing to do")
        return 0

    visible = _execute(
        """SELECT DISTINCT fs.symbol
           FROM watchlist_final_synthesis fs
           JOIN watchlist_items wi ON wi.symbol = fs.symbol
           WHERE fs.synthesis_narrative ILIKE %s
             AND wi.hermes_rank IS NOT NULL AND wi.hermes_rank <= 200""",
        (ERROR_PATTERN,), fetch="all") or []
    visible_syms = sorted({r["symbol"] for r in visible})[:max(0, args.max_enqueue)]

    print(f"{len(rows)} error-narrative rows "
          f"(updated {min(str(r['updated_at']) for r in rows)[:10]} → {max(str(r['updated_at']) for r in rows)[:10]}); "
          f"{len(visible_syms)} in Hermes top-200 (re-enqueue set): {', '.join(visible_syms) or '—'}")

    if not args.apply:
        print("dry run — re-run with --apply to backup, delete, and enqueue re-synthesis")
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"synthesis_error_purge_{ts}.json"
    backup_path.write_text(json.dumps([{k: str(v) for k, v in r.items()} for r in rows], indent=2))
    print(f"backed up {len(rows)} rows → {backup_path}")

    _execute("DELETE FROM watchlist_final_synthesis WHERE synthesis_narrative ILIKE %s", (ERROR_PATTERN,), fetch=None)
    print(f"deleted {len(rows)} rows")

    enqueued, skipped = [], []
    for sym in visible_syms:
        dup = _execute("""SELECT 1 FROM watchlist_agent_jobs WHERE symbol=%s AND requested_agent='full_chain'
                          AND status IN ('queued','running') LIMIT 1""", (sym,), fetch="one")
        if dup:
            skipped.append(sym)
            continue
        job_id = f"errpurge-{sym}-{ts}"
        _execute("""INSERT INTO watchlist_agent_jobs
                    (id, symbol, requested_agent, request_type, note, priority, status, submitted_from, payload, created_at)
                    VALUES (%s,%s,'full_chain','error_narrative_purge',
                            'prior synthesis was a failed-LLM artifact — regenerate',3,'queued',
                            'purge_error_synthesis','{}',NOW())
                    ON CONFLICT (id) DO NOTHING""", (job_id, sym), fetch=None)
        enqueued.append(sym)
    print(f"re-synthesis enqueued: {', '.join(enqueued) or '—'}"
          + (f" | already queued: {', '.join(skipped)}" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
