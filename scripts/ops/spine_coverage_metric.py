#!/usr/bin/env python3
"""CADI-013 — SecurityResearchSpine coverage metric (researched → spine present).

READ_ONLY_ADVISORY. Writes runtime JSON for dashboards; never trades.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "ops CLI / dashboard metric writer; operator or agent invokes; "
    "runtime JSON under data/runtime/ is the consumer artifact"
)

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--write", action="store_true", help="write runtime metric JSON")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = args.root

    researched: set[str] = set()
    results = root / "data" / "cio" / "hermes_research_results.jsonl"
    if results.exists():
        with results.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("event") == "HERMES_RESEARCH_COMPLETED":
                    sym = str(row.get("symbol") or "").upper()
                    if sym:
                        researched.add(sym)

    spine_syms: set[str] = set()
    spine_populated = 0
    spine_path = root / "data" / "cio" / "security_research_spine.jsonl"
    latest: dict[str, dict] = {}
    if spine_path.exists():
        with spine_path.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("symbol"):
                    latest[str(row["symbol"]).upper()] = row
    for sym, row in latest.items():
        spine_syms.add(sym)
        th = row.get("thesis") or {}
        if th.get("state") == "POPULATED" or th.get("summary"):
            spine_populated += 1

    overlap = researched & spine_syms
    pct = round(100.0 * len(overlap) / max(len(researched), 1), 1)
    out = {
        "schema": "SecurityResearchSpineCoverage@v1",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": _now(),
        "researched_symbols": len(researched),
        "spine_symbols": len(spine_syms),
        "spine_populated": spine_populated,
        "researched_with_spine": len(overlap),
        "pct_researched_with_spine": pct,
        "target_pct": 80.0,
    }
    if args.write:
        dest = root / "data" / "runtime" / "security_research_spine_coverage.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        out["written"] = str(dest)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(
            f"researched={out['researched_symbols']} with_spine={out['researched_with_spine']} "
            f"pct={pct}% (target 80%)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
