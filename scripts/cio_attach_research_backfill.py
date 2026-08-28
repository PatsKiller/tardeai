#!/usr/bin/env python3
"""One-shot: join latest successful Hermes results onto open plans missing hermes_result_id.

Idempotent. Append-only PLAN_UPDATED. Default is dry-run (--apply required to write).
Does not notify. Does not rewrite history events.

  PYTHONPATH=.:scripts python3 scripts/cio_attach_research_backfill.py
  PYTHONPATH=.:scripts python3 scripts/cio_attach_research_backfill.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

OPENISH = {"draft", "proposed", "accepted"}


def _fold_plans():
    try:
        from lib.cio_plans import CIOPlanStore
    except Exception:
        from scripts.lib.cio_plans import CIOPlanStore  # type: ignore
    return CIOPlanStore()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write PLAN_UPDATED joins (default dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="Max plans to attach (0 = all)")
    args = ap.parse_args(argv)

    try:
        from lib.cio_hermes_research import latest_research_for_plan
        from lib.hermes_research_loop import (
            _merge_evidence_on_plan_id,
            research_complete_is_attachable,
        )
        from lib.research_quality import critique
        from lib.hermes_research_schema import evidence_domain_from_result
    except Exception:
        from scripts.lib.cio_hermes_research import latest_research_for_plan  # type: ignore
        from scripts.lib.hermes_research_loop import (  # type: ignore
            _merge_evidence_on_plan_id,
            research_complete_is_attachable,
        )
        from scripts.lib.research_quality import critique  # type: ignore
        from scripts.lib.hermes_research_schema import evidence_domain_from_result  # type: ignore

    store = _fold_plans()
    plans = [p for p in store._plans.values() if p.get("status") in OPENISH]
    missing = [p for p in plans if not p.get("hermes_result_id")]
    attached = 0
    skipped = 0
    samples: list[dict[str, Any]] = []
    for plan in missing:
        if args.limit and attached >= args.limit:
            break
        pid = str(plan.get("plan_id") or "")
        info = latest_research_for_plan(pid)
        result = info.get("latest_result") if isinstance(info.get("latest_result"), dict) else None
        if not result:
            skipped += 1
            continue
        crit = critique(result)
        if not research_complete_is_attachable(result, crit):
            skipped += 1
            continue
        row = {
            "plan_id": pid,
            "research_id": result.get("research_id") or plan.get("hermes_research_id"),
            "hermes_result_id": result.get("result_id"),
            "status": plan.get("status"),
            "critique": crit.get("verdict"),
        }
        samples.append(row)
        if not args.apply:
            continue
        try:
            domain = evidence_domain_from_result(result, reused=bool(result.get("reused")))
            _merge_evidence_on_plan_id(
                pid, domain,
                research_id=str(row["research_id"] or ""),
                result_id=str(result.get("result_id") or ""),
                completed_ts=str(result.get("completed_ts") or result.get("as_of") or "") or None,
                attach_result=True,
            )
            attached += 1
        except Exception:
            skipped += 1

    report = {
        "ok": True,
        "apply": bool(args.apply),
        "plans_open": len(plans),
        "plans_missing_result_id": len(missing),
        "would_attach": len(samples) if not args.apply else attached,
        "attached": attached if args.apply else 0,
        "skipped": skipped,
        "sample": samples[:8],
        "authority": "READ_ONLY_ADVISORY",
        "notify": False,
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
