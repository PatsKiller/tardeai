#!/usr/bin/env python3
"""cio_opportunity_curator.py — curate OpportunityAssessment@v1 for the whole universe into CIO memory.

Investment Command Center (operator 2026-10-08). Deterministic, zero LLM, zero provider calls:
  universe (~1,400: held + active watchlist + re-entry desk + fresh technicals + fresh analyst targets)
  → lib/data_broker/opportunity.gather/assess/rank
  → CIO memory: data/cio/cio_opportunity_assessments.jsonl (a version only on material change)
                data/cio/cio_opportunity_projection.json (latest full ranking, read by /api/v3/opportunities)
Dry run unless --apply. Receipt: data/runtime/cio_opportunity_curator_latest.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

RECEIPT = ROOT / "data" / "runtime" / "cio_opportunity_curator_latest.json"


def _db_query(sql, params=None, fetch="all"):
    from db_adapter import _execute

    return _execute(sql, params, fetch=fetch)


def run(apply: bool, limit_print: int = 10) -> dict:
    from lib.data_broker import opportunity as op
    from scripts.lib.cio_opportunity_store import CIOOpportunityStore

    t0 = time.time()
    syms = op.universe(_db_query)
    ctx = op.gather(_db_query, syms)
    assessments = op.rank([op.assess(s, ctx[s]) for s in syms])
    cfg = op.load_config()
    store = CIOOpportunityStore()
    lines = store.plan(assessments, cfg.get("material_change") or {})
    run_id = f"opp-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    provenance = {"writer": "cio_opportunity_curator", "run_id": run_id, "owner_agent": "cio",
                  "config_version": cfg.get("version"),
                  "source_sha": os.getenv("TRADEAI_SOURCE_SHA") or os.getenv("SOURCE_SHA")}
    top = [a for a in op.sort_items([a for a in assessments if a.get("rank")], "rank")][:limit_print]
    report = {
        "mode": "APPLY" if apply else "DRY-RUN", "run_id": run_id, "at": datetime.now(timezone.utc).isoformat(),
        "universe": len(syms), "rankable": sum(1 for a in assessments if a.get("rankable")),
        "with_rr": sum(1 for a in assessments if (a.get("risk_reward") or {}).get("rr") is not None),
        "factor_coverage": dict(Counter(k for a in assessments for k in a.get("factors") or {})),
        "types": dict(Counter(a.get("type") for a in assessments)),
        "stances": dict(Counter(a.get("stance") for a in assessments)),
        "material_versions": len(lines),
        "top": [{"rank": a["rank"], "symbol": a["symbol"], "conviction": a["conviction"],
                 "rr": (a.get("risk_reward") or {}).get("rr"), "upside_pct": a.get("upside_pct"),
                 "type": a.get("type")} for a in top],
        "seconds": round(time.time() - t0, 1),
    }
    if apply:
        report["appended"] = store.append(lines, provenance)
        store.write_projection(assessments, {"as_of": report["at"], "run_id": run_id, "provenance": provenance})
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.apply), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
