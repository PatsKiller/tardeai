#!/usr/bin/env python3
"""Cancel open S1/S6 plans with no held non-dust subject. Dry by default.

  python scripts/cio_orphan_plan_hygiene.py                      # dry
  python scripts/cio_orphan_plan_hygiene.py --apply              # cancel
  python scripts/cio_orphan_plan_hygiene.py --situations S6      # one type
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
    ap = argparse.ArgumentParser(description="Orphan S1/S6 plan hygiene")
    ap.add_argument("--root", default=str(LIVE))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--situations", default="",
                    help="comma list, e.g. S1_POSITION_LIFECYCLE (default: S1+S6)")
    ap.add_argument("--reasons", default="",
                    help="comma list of orphan reasons, e.g. dust_residual "
                         "(default: all). Lets an authorisation boundary be "
                         "stated in the command.")
    a = ap.parse_args()

    os.environ.setdefault("TRADEAI_ROOT", a.root)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from scripts.lib.cio_investment_product import collect_holdings
    from scripts.lib.cio_orphan_plan_hygiene import SUBJECT_SITUATIONS, cancel_orphan_plans
    from scripts.lib.cio_plans import CIOPlanStore

    live = Path(a.root)
    store = CIOPlanStore(
        event_path=live / "data/cio/cio_plans.jsonl",
        projection_path=live / "data/cio/cio_plans_projection.json",
    )
    sits = tuple(x.strip() for x in a.situations.split(",") if x.strip()) or SUBJECT_SITUATIONS
    reasons = tuple(x.strip() for x in a.reasons.split(",") if x.strip()) or None
    out = cancel_orphan_plans(
        store, holdings=collect_holdings(live), apply=a.apply, limit=a.limit,
        situations=sits, reasons=reasons,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
