#!/usr/bin/env python3
"""Dry report: run ResearchNeedDecision@v2 over open plans. No model calls.

    python3 scripts/cio_research_gate_report.py --root CURRENT [--limit 10]

Default backend is a stub: this prints what *would* run. It never calls a
model, never writes, and never persists. `--json` emits the schedule surface.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.cio_research_gate import (  # noqa: E402
    collapse_same_day_duplicates, decide, schedule_surface,
)
from scripts.lib import cio_corpus_index as corpus  # noqa: E402
from scripts.lib.cio_research_history import (  # noqa: E402
    gate_inputs_for, history_by_plan,
)

# S-types whose plans may carry a research need at all.
RESEARCHABLE = {
    "S1_POSITION_LIFECYCLE": "held_core_thesis",
    "S3_REENTRY_CANDIDATE": "new_position_if",
    "S6_CONCENTRATION_OR_DISPOSITION": "s6_concentration",
    "S5_CASH_DEPLOYMENT": "default",
    "S7_WATCH_PROMOTION": "watch_block",
}
OPEN_STATUS = {"draft", "proposed"}


def load_plans(root: Path) -> list[dict]:
    path = root / "data" / "cio" / "cio_plans_projection.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [p for p in (doc.get("plans") or {}).values() if isinstance(p, dict)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("TRADEAI_ROOT") or ".")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    os.environ.setdefault("TRADEAI_ROOT", str(root))
    now = datetime.now(timezone.utc)

    earnings = corpus.earnings_within(5, root=root, now=now)
    # Wave 3D: feed the gate its prior outcomes. Without this the fail-closed
    # rule never fires, because the gate is never told an artifact was tainted.
    hist = history_by_plan(root)
    plans = load_plans(root)
    decisions = []
    for p in plans:
        if str(p.get("status")) not in OPEN_STATUS:
            continue
        kind = RESEARCHABLE.get(str(p.get("situation_type")))
        if kind is None:
            continue
        syms = p.get("symbols") or []
        sym = str(syms[0]).upper() if syms else None
        dim = "seasonality" if kind == "s6_concentration" else "bear_case"
        gate_in = {
            "plan_id": p.get("plan_id"),
            "symbol": sym,
            "kind": kind,
            "material": bool(p.get("material")),
            "days_to_event": earnings.get(sym) if sym else None,
            "corpus": corpus.consult(dim, now=now),
        }
        gate_in.update(gate_inputs_for(p.get("plan_id"), hist))
        if gate_in.get("prior_outcome") is None:
            gate_in["prior_outcome"] = (
                p.get("llm_status")
                if p.get("llm_status") in {"VALID", "PARTIAL", "FAIL", "truncated"}
                else None)
        decisions.append(decide(gate_in, now=now))

    # One model class per SUBJECT per calendar day. The law now lives in
    # cio_research_gate.collapse_same_day_duplicates so it is testable and so
    # this script cannot drift from it.
    collapse = collapse_same_day_duplicates(decisions, now=now)

    surface = schedule_surface(decisions, cap=args.limit, now=now)
    if args.json:
        print(json.dumps(surface, indent=2, default=str))
        return 0

    print(f"ResearchNeedDecision@v2 dry report — root={root}")
    print(f"  open researchable plans considered : {surface['considered']}")
    print(f"  earnings within 5d                 : {len(earnings)}")
    print()
    print("  by decision:")
    for k, v in sorted(surface["by_decision"].items(), key=lambda kv: -kv[1]):
        print(f"    {k:<16} {v}")
    print()
    print("  skipped by reason:")
    for k, v in surface["skipped_by_reason"].items():
        print(f"    {k:<36} {v}")
    print()
    print(f"  next eligible (cap {args.limit}, total {surface['next_eligible_total']}):")
    for row in surface["next_eligible"]:
        sym = row["symbol"] or "(no symbol)"
        print(f"    {sym:<12} {row['decision']:<14} {row['reason']}")
    if not surface["next_eligible"]:
        print("    (none — claimed=0 is healthy)")
    print()
    print(f"  collapsed as duplicate subject same day: {collapse['collapsed']}")
    print("  LIVE PAID CALLS MADE: 0 (dry report, stub backend)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
