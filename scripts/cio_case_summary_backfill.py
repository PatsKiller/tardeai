#!/usr/bin/env python3
"""One-shot: mint CASE_SUMMARY memories for open plans that already have hermes_result_id.

Dry-run by default. --apply writes through admit_candidate (durable JSONL).
Does not notify. Does not run research. Does not attach missing result ids.

Source set = open plans WITH hermes_result_id (Step 1 join), not the missing set.

  PYTHONPATH=.:scripts python3 scripts/cio_case_summary_backfill.py
  PYTHONPATH=.:scripts python3 scripts/cio_case_summary_backfill.py --apply --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

OPENISH = {"draft", "proposed", "accepted"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write CASE_SUMMARY memories (default dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="Max mints (0 = all eligible)")
    args = ap.parse_args(argv)

    try:
        from lib.cio_plans import CIOPlanStore
        from lib.cio_hermes_research import latest_research_for_plan
        from lib.hermes_research_loop import research_complete_is_attachable
        from lib.hermes_case_summary import (
            mint_case_summary_from_attached_research,
            safe_case_subject,
        )
        from lib.research_quality import critique
        from lib.agent_durable_memory import get_durable_provider
        from lib.agent_memory_governance import is_forbidden_authoritative
    except Exception:
        from scripts.lib.cio_plans import CIOPlanStore  # type: ignore
        from scripts.lib.cio_hermes_research import latest_research_for_plan  # type: ignore
        from scripts.lib.hermes_research_loop import research_complete_is_attachable  # type: ignore
        from scripts.lib.hermes_case_summary import (  # type: ignore
            mint_case_summary_from_attached_research,
            safe_case_subject,
        )
        from scripts.lib.research_quality import critique  # type: ignore
        from scripts.lib.agent_durable_memory import get_durable_provider  # type: ignore
        from scripts.lib.agent_memory_governance import is_forbidden_authoritative  # type: ignore

    store = CIOPlanStore()
    joined = [
        p for p in store._plans.values()
        if p.get("status") in OPENISH and p.get("hermes_result_id")
    ]
    would = 0
    minted = 0
    skipped = 0
    samples: list[dict[str, Any]] = []
    prov = get_durable_provider() if args.apply else None
    for plan in joined:
        if args.limit and (would if not args.apply else minted) >= args.limit:
            break
        pid = str(plan.get("plan_id") or "")
        info = latest_research_for_plan(pid)
        result = info.get("latest_result") if isinstance(info.get("latest_result"), dict) else None
        if not result or str(result.get("result_id") or "") != str(plan.get("hermes_result_id") or ""):
            skipped += 1
            continue
        crit = critique(result)
        if not research_complete_is_attachable(result, crit):
            skipped += 1
            continue
        subj = safe_case_subject(plan, result)
        if is_forbidden_authoritative(subj):
            skipped += 1
            continue
        row = {
            "plan_id": pid,
            "research_id": result.get("research_id") or plan.get("hermes_research_id"),
            "hermes_result_id": plan.get("hermes_result_id"),
            "subject": subj,
            "critique": crit.get("verdict"),
            "status": plan.get("status"),
        }
        samples.append(row)
        if not args.apply:
            would += 1
            continue
        out = mint_case_summary_from_attached_research(
            plan, result, critique=crit, provider=prov,
        )
        if out.get("ok") and not out.get("skipped"):
            minted += 1
            row["memory_id"] = out.get("memory_id")
        else:
            skipped += 1
            row["skip"] = out.get("reason")

    report = {
        "ok": True,
        "apply": bool(args.apply),
        "plans_with_hermes_result_id": len(joined),
        "would_mint": would if not args.apply else minted,
        "minted": minted if args.apply else 0,
        "skipped": skipped,
        "sample": samples[:8],
        "authority": "READ_ONLY_ADVISORY",
        "notify": False,
        "memory_behavior_influence": "0",
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
