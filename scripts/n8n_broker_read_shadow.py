#!/usr/bin/env python3
"""Offline SHADOW plan for a §27.1 read lane. Never imports or executes a read step.

The executor supplies --step and --plan. Any other argv refuses. No .env load,
runtime lock/mode read, file write, subprocess, database, broker, network or sender.
Activation and an executable live path require a separate operator §17 action.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import lane_output  # noqa: E402
from lib import n8n_broker_read_carveout as carve  # noqa: E402
from lib import n8n_broker_read_shadow as shadow  # noqa: E402


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3 or args[0] != "--step" or args[2] != "--plan":
        print("REFUSED: shadow_plan_only", file=sys.stderr)
        return 64
    step = next((s for s in carve.READ_LANES if s.id == args[1]), None)
    if step is None or not carve.is_active():
        print("REFUSED: unknown_or_inactive_read_lane", file=sys.stderr)
        return 65
    lane = shadow.lane_id(step.id)
    binding = {
        "run_id": os.environ.get("TRADEAI_RUN_ID", ""),
        "attempt": os.environ.get("TRADEAI_RUN_ATTEMPT", "1"),
        "code_sha": os.environ.get("TRADEAI_CODE_SHA", ""),
    }
    print(f"DRY-RUN {lane}: offline plan; no broker call")
    print(
        json.dumps(
            {
                "schema": "N8nBrokerReadShadowPlan@v1",
                "lane_id": lane,
                "step_id": step.id,
                "command": ["$PY", step.script, *step.apply_argv],
                "stage": "shadow",
                "execution_available": False,
                **binding,
            },
            sort_keys=True,
        )
    )
    lane_output.emit(
        lane,
        "dry_run",
        {
            **lane_output.output_block(produced=0, attempted=0, empty_reason=shadow.EMPTY_REASON, unit="read_steps"),
            **binding,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
