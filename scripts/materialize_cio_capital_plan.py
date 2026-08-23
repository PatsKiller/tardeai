#!/usr/bin/env python3
"""Materialize governed cash situation and advisory capital plan versions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import api_v3_cio as cio_api  # noqa: E402
from scripts.lib.cio_cash_capital_v1 import reconcile_capital_plan  # noqa: E402


def materialize(store_path: Path) -> dict:
    preview = cio_api.get_capital_plan_v1()
    return reconcile_capital_plan(
        preview["situation"],
        preview["capital_plan"],
        store_path=str(store_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--store",
        default=os.getenv("CIO_CAPITAL_PLAN_JSONL") or str(ROOT / "data/cio/cio_capital_plans.jsonl"),
    )
    args = parser.parse_args()
    result = materialize(Path(args.store))
    plan = result.get("plan") or {}
    situation = result.get("situation") or {}
    print(json.dumps({
        "ok": True,
        "published": result.get("published"),
        "reason": result.get("reason"),
        "situation_version": situation.get("situation_version"),
        "plan_version": plan.get("plan_version"),
        "state": plan.get("state"),
        "stance": plan.get("stance"),
        "notification_eligible": (plan.get("notification") or {}).get("eligible"),
        "suppression_reason": (plan.get("notification") or {}).get("suppression_reason"),
        "authority": plan.get("authority") or result.get("authority"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
