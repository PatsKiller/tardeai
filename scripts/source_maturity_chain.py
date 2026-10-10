#!/usr/bin/env python3
"""source_maturity_chain.py — the daily Hermes source-maturity tick as ONE command (cron L431).

The cron line is a three-script ``bash -c "A && B && C"`` chain, which an n8n run allowlist cannot
express as a single argv. This runs the same three steps in the same order, in one process, and
stops at the first failure exactly as ``&&`` did:

  1. source_outcome_attribution  (upserts source_performance)
  2. source_maturity             (writes data/runtime/source_maturity_latest.json)
  3. source_vetting_ladder       (research_sources rows, the actions file, auto-approval)

  python3 scripts/source_maturity_chain.py             # live
  python3 scripts/source_maturity_chain.py --dry-run   # read-only, all three steps

--dry-run runs every step's read path on READ ONLY sessions and returns before any step's writer is
reachable (AGENTS.md §6). Step 3 is fed the maturity document step 2 just computed in memory, so the
preview is of THIS tick, not of yesterday's file. Note that step 2's dry read sees source_performance
as it is now (step 1 wrote nothing), so on a day with new attributions the live tiers can differ.

A real run writes data/runtime/source_maturity_chain_last.json (LaneRunReceipt@v1; ok_at only when all
three steps succeeded) under the persistent state root and exits 1 on the first failed step.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

RECEIPT_NAME = "source_maturity_chain"
STEPS = ("source_outcome_attribution", "source_maturity", "source_vetting_ladder")


def run_chain(dry_run: bool = False) -> dict:
    """Run the three steps; returns {"ok": bool, "failed_step": str|None, "steps": {...}}."""
    import source_maturity as sm
    import source_outcome_attribution as soa
    import source_vetting_ladder as svl

    steps: dict = {}
    try:
        rep = soa.run(dry_run=dry_run)
        steps["source_outcome_attribution"] = {k: rep.get(k) for k in ("sources", "upserted", "with_matched_trades")}
    except Exception as exc:  # noqa: BLE001 -- `&&` semantics: stop here, report the step
        return {
            "ok": False,
            "failed_step": "source_outcome_attribution",
            "error": f"{type(exc).__name__}: {exc}",
            "steps": steps,
        }
    try:
        doc = sm.run(dry_run=dry_run)
        steps["source_maturity"] = {"source_count": doc.get("source_count"), "tier_counts": doc.get("tier_counts")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "failed_step": "source_maturity", "error": f"{type(exc).__name__}: {exc}", "steps": steps}
    try:
        rep = svl.run(dry_run=dry_run, maturity=doc if dry_run else None)
        steps["source_vetting_ladder"] = {
            k: rep.get(k) for k in ("registered_new_candidates", "tier_updates", "vetting_actions")
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "failed_step": "source_vetting_ladder",
            "error": f"{type(exc).__name__}: {exc}",
            "steps": steps,
        }
    return {"ok": True, "failed_step": None, "steps": steps}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hermes source-maturity tick (attribution -> maturity -> ladder).")
    ap.add_argument("--dry-run", action="store_true", help="read-only, all three steps; writes nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        res = run_chain(dry_run=True)
        if not res["ok"]:
            print(f"[source-maturity-chain] DRY RUN failed at {res['failed_step']}: {res['error']}", file=sys.stderr)
            return 1
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    res = run_chain(dry_run=False)
    write_receipt(
        RECEIPT_NAME,
        ok=res["ok"],
        started_at=started,
        summary={"steps": res["steps"], "failed_step": res["failed_step"]},
        error=res.get("error"),
    )
    if not res["ok"]:
        print(f"[source-maturity-chain] FAILED at {res['failed_step']}: {res['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
