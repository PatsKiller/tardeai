#!/usr/bin/env python3
"""Organic-style Hermes COMPLETE → SecurityResearchSpine canary.

Runs HermesWorker once against a real enqueue for a traded symbol with
CROSS_ASSET_SPINE=1 so CADI-011 persists the shared spine. Labels result
honestly: WORKER_CANARY (not uncontrolled organic operator ask).

Usage:
  CROSS_ASSET_SPINE=1 python3 scripts/ops/run_hermes_spine_canary.py --symbol NFLX
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="NFLX")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("CROSS_ASSET_SPINE", "1")
    os.chdir(args.root)

    from scripts.lib import cio_hermes_research as hr
    from scripts.lib.cross_asset.security_research_spine import view_for_silo
    from scripts.lib.identity_carriage import resolve_security_identity
    from scripts.lib.hermes_worker import HermesWorker, StubResearchBackend

    sym = str(args.symbol).upper()
    env = resolve_security_identity(sym, root=args.root)
    plan = {
        "plan_id": f"plan_spine_canary_{uuid.uuid4().hex[:10]}",
        "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
        "symbols": [sym],
        "thesis_version": "desk@v5",
        "fire_reasons": ["identity_phase_b_spine_canary"],
    }
    enq = hr.enqueue_research_request(plan, priority="high")
    worker = HermesWorker(store=hr, backend=StubResearchBackend(), worker_id="spine_canary")
    worker.run_once(limit=1)

    views = {}
    for silo in ("options_desk", "watchlist", "reentry", "holdings", "cio"):
        v = view_for_silo(sym, silo, root=args.root, persist_read_receipt=False)
        views[silo] = {
            "found": v.get("found"),
            "subject_guid": v.get("subject_guid"),
            "summary": ((v.get("thesis") or {}).get("summary") or "")[:80],
        }
    summaries = {v.get("summary") for v in views.values() if v.get("found")}
    out = {
        "ok": True,
        "label": "WORKER_CANARY",  # not uncontrolled organic operator ask
        "symbol": sym,
        "registry_guid": env.get("subject_guid"),
        "enqueue": {"created": enq.get("created"), "research_id": enq.get("research_id")},
        "cross_asset_spine": os.environ.get("CROSS_ASSET_SPINE"),
        "views": views,
        "identical_summaries": len(summaries) == 1 and bool(next(iter(summaries), None)),
        "authority": "READ_ONLY_ADVISORY",
    }
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(
            f"label={out['label']} symbol={sym} identical={out['identical_summaries']} "
            f"guid={out['registry_guid']}"
        )
    return 0 if out["identical_summaries"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
