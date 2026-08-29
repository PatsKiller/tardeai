#!/usr/bin/env python3
"""Expire revisit-overdue duplicate S1 plans. Keep newest per symbol. Dry by default.

  python scripts/cio_duplicate_s1_hygiene.py           # dry
  python scripts/cio_duplicate_s1_hygiene.py --apply   # cancel (never delete)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")


def main() -> int:
    ap = argparse.ArgumentParser(description="Duplicate S1 hygiene")
    ap.add_argument("--root", default=str(LIVE))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    os.environ.setdefault("TRADEAI_ROOT", a.root)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from scripts.lib.cio_duplicate_s1_hygiene import expire_duplicate_s1
    from scripts.lib.cio_plans import CIOPlanStore

    live = Path(a.root)
    store = CIOPlanStore(
        event_path=live / "data/cio/cio_plans.jsonl",
        projection_path=live / "data/cio/cio_plans_projection.json",
    )
    out = expire_duplicate_s1(store, apply=a.apply, limit=a.limit)
    out["expire"] = [r["plan_id"] for r in out["expire"]][:20]
    out["retained_not_overdue"] = [r["plan_id"] for r in out["retained_not_overdue"]][:20]
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
