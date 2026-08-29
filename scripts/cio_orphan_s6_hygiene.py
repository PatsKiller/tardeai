#!/usr/bin/env python3
"""Cancel open S6 plans with no held non-dust subject. Dry by default.

  python scripts/cio_orphan_s6_hygiene.py                # dry
  python scripts/cio_orphan_s6_hygiene.py --apply        # cancel (never delete)
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
    ap = argparse.ArgumentParser(description="Orphan S6 hygiene")
    ap.add_argument("--root", default=str(LIVE))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    os.environ.setdefault("TRADEAI_ROOT", a.root)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from scripts.lib.cio_investment_product import collect_holdings
    from scripts.lib.cio_orphan_s6_hygiene import cancel_orphan_s6
    from scripts.lib.cio_plans import CIOPlanStore

    live = Path(a.root)
    store = CIOPlanStore(
        event_path=live / "data/cio/cio_plans.jsonl",
        projection_path=live / "data/cio/cio_plans_projection.json",
    )
    out = cancel_orphan_s6(
        store, holdings=collect_holdings(live), apply=a.apply, limit=a.limit,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
