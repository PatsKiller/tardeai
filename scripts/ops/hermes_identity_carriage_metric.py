#!/usr/bin/env python3
"""Hermes identity carriage metric — % of last N results with registry subject_guid.

Target after identity 4/5 ship: >=95% on last 200 completed results.
Does not rewrite history. READ_ONLY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _is_guid(v) -> bool:
    try:
        from scripts.lib.identity_carriage import is_registry_guid
        return is_registry_guid(v)
    except Exception:
        s = str(v or "")
        return len(s) == 36 and s.count("-") == 4


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--min-pct", type=float, default=0.0, help="exit 1 if below this pct")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    path = args.root / "data" / "cio" / "hermes_research_results.jsonl"
    rows: list[dict] = []
    if path.exists():
        with path.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("event") == "HERMES_RESEARCH_COMPLETED":
                    rows.append(row)
    tail = rows[-max(1, args.n) :]
    with_guid = sum(1 for r in tail if _is_guid(r.get("subject_guid")))
    pct = round(100.0 * with_guid / max(len(tail), 1), 1)
    out = {
        "ok": True,
        "file": str(path),
        "n": len(tail),
        "with_subject_guid": with_guid,
        "pct": pct,
        "target_pct": 95.0,
        "authority": "READ_ONLY_ADVISORY",
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"hermes_last_{len(tail)} subject_guid={with_guid} pct={pct}% (target 95%)")
    if args.min_pct and pct < args.min_pct:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
