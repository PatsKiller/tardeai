#!/usr/bin/env python3
"""Score advisory desk verdicts at 30/60/90d horizons (deterministic).

Usage:
  .venv/bin/python scripts/advisory_outcome_scorer.py --once
  .venv/bin/python scripts/advisory_outcome_scorer.py --once --max 100
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def score_pending_outcomes(**kwargs):
    from lib.advisory.advisory_memory import score_pending_outcomes as score
    return score(**kwargs)


def run_outcome_cycle(**kwargs):
    from lib.advisory_outcome_record import run_outcome_cycle as run
    return run(**kwargs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--once", action="store_true", help="Run one sweep (default)")
    ap.add_argument("--max", type=int, default=200, help="Max new outcome rows")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="offline plan; no reads, scoring or writes")
    args = ap.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN advisory-outcome-scorer: would score at most {args.max} pending advisory outcomes and refresh lineage/reconciliation; no portfolio reads, DB, network or writes")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        code, summary = _run(args)
    except Exception as exc:
        write_lane_receipt("advisory-outcome-scorer", ok=False, exit_code=1,
                           started_at=started, error=type(exc).__name__)
        raise
    write_lane_receipt("advisory-outcome-scorer", ok=code == 0, exit_code=code,
                       started_at=started, summary=summary)
    return code


def _run(args):
    result = score_pending_outcomes(max_new=args.max)
    root = Path(os.environ.get("TRADEAI_ROOT") or PROJECT_ROOT)
    result["outcome_record_v1"] = run_outcome_cycle(root=root)
    closed_loop: dict = {}
    try:
        from lib.intelligence_lineage import observe_overdue_cases, rebuild_lineages
        from lib.cio_reconciliation import persist as persist_recon
        closed_loop["observe"] = observe_overdue_cases(apply=True, horizon_days=7)
        snap = rebuild_lineages()
        closed_loop["lineage"] = {
            "count": snap.get("count"),
            "by_status": snap.get("by_status"),
            "pending_challenges": snap.get("pending_challenges"),
        }
        closed_loop["reconciliation"] = persist_recon()
        closed_loop["ok"] = True
    except Exception as exc:
        closed_loop = {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:240]}
    result["closed_loop"] = closed_loop
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        cal = result.get("calibration") or {}
        g = cal.get("global") or {}
        print(
            f"advisory outcomes: written={result.get('written')} "
            f"scored_total={g.get('n')} hit_rate={g.get('hit_rate')}"
        )
        obs = closed_loop.get("observe") or {}
        print(
            f"closed-loop observe expired={obs.get('observed_expired')} "
            f"scored={obs.get('scored')} lineages={(closed_loop.get('lineage') or {}).get('count')} "
            f"ok={closed_loop.get('ok')}"
        )
    ok = bool(result.get("ok")) and bool(closed_loop.get("ok"))
    code = 0 if ok else 1
    return code, {"written": result.get("written"), "scoring_ok": bool(result.get("ok")),
                  "closed_loop_ok": bool(closed_loop.get("ok")),
                  "closed_loop_error": closed_loop.get("error")}


if __name__ == "__main__":
    raise SystemExit(main())
