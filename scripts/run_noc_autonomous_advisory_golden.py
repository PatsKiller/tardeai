#!/usr/bin/env python3
"""Generate isolated NOC autonomous-advisory loop acceptance evidence."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.noc_golden_loop import run_noc_golden_loop


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/_evidence/autonomous_advisory_loop/noc_golden_loop_isolated.json"),
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tradeai-noc-golden-") as tmp:
        proof = run_noc_golden_loop(Path(tmp))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "output": str(args.output),
        "mode": proof["mode"],
        "live_proven": proof["live_proven"],
        "thesis_version": proof["replay"]["final_thesis_version"],
        "replay_classification": proof["replay"]["delta_classification"],
        "financial_writes": proof["financial_writes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
