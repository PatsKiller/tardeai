#!/usr/bin/env python3
"""Dry/apply observational S1 for held-without-open-plan. Cap 5. No notify."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--cap", type=int, default=5)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(str(ROOT))
    from scripts.lib.cio_observational_s1 import (
        apply_observational_s1,
        collect_held_without_open_s1,
    )
    from scripts.lib.cio_plans import CIOPlanStore

    live = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
    store = CIOPlanStore(
        event_path=live / "data/cio/cio_plans.jsonl",
        projection_path=live / "data/cio/cio_plans_projection.json",
    )
    dry = collect_held_without_open_s1(root=live, plans=store, cap=args.cap)
    receipt = apply_observational_s1(dry, plans=store, apply=bool(args.apply))
    report = {**dry, "apply": bool(args.apply), "receipt": receipt}
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    print(json.dumps({
        "held_n": dry["held_n"],
        "open_s1_n": dry["open_s1_n"],
        "skipped_open_s1": dry["skipped_open_s1"],
        "would_n": dry["would_n"],
        "would_symbols": [r["symbol"] for r in dry["would"]],
        "applied_n": receipt["applied_n"],
        "applied": receipt["applied"],
        "notify": False,
        "apply": bool(args.apply),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
