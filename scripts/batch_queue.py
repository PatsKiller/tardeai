#!/usr/bin/env python3
"""batch_queue.py — read the operator's next-batch queue before building a release batch (read-only).

The Work pipeline's Tier 1 actions (operator 2026-10-23) record, in ``<claims_dir>/tasks/batch_queue.json``
(``BatchQueue@v1``), which green PRs the operator wants in the next release batch, in order, and which PRs are held.
A batch builder (agent or human) runs this first and never includes a held PR.

    python3 scripts/batch_queue.py show          # the whole queue (JSON)
    python3 scripts/batch_queue.py next          # the PR numbers to include, in order, held ones dropped

Writes nothing. Changes go through the Work pipeline (POST /api/v2/coordination/commands, operator only).
AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import work_pipeline_commands as C  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("show", "next"))
    ap.add_argument("--claims-dir", default=None, help="default: TRADEAI_AGENT_CLAIMS_DIR or persistent-state")
    a = ap.parse_args(argv)
    view = C.batch_builder_view(a.claims_dir)
    if a.cmd == "show":
        print(json.dumps(view["queue"], indent=2, sort_keys=True))
    else:
        print(" ".join(str(n) for n in view["next_batch"]))
        if view["held_prs"]:
            print(f"# held (skip): {' '.join(str(n) for n in view['held_prs'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
