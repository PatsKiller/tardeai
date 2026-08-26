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

from lib.advisory.advisory_memory import score_pending_outcomes  # noqa: E402
from lib.advisory_outcome_record import run_outcome_cycle  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="Run one sweep (default)")
    ap.add_argument("--max", type=int, default=200, help="Max new outcome rows")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
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
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
