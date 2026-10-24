#!/usr/bin/env python3
"""Read-only C3 review aging evaluator. No send, provider or repair API."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.lib.cio_review_lifecycle import aging, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--stance-requests", type=Path, help="explicit captured stance-request JSONL; no live store loader")
    ap.add_argument("--now", help="pinned aware ISO timestamp")
    args = ap.parse_args(argv)
    requests, measurements = [], []
    for path in [args.root / "data/cio/symbol_thesis_priority_queue.jsonl", *([args.stance_requests] if args.stance_requests else [])]:
        try:
            lines = path.read_text().splitlines()
            bad, batch = 0, []
            for line in lines:
                if not line.strip(): continue
                try:
                    r = json.loads(line)
                    if isinstance(r, dict): batch.append(r)
                    else: bad += 1
                except ValueError: bad += 1
            by_id, legacy = {}, []
            for r in batch:
                rid = r.get("request_id") or r.get("review_request_id")
                if rid: by_id[rid] = r
                else: legacy.append(r)
            requests += legacy + list(by_id.values())
            measurements.append({"input": path.name, "status": "PARTIAL" if bad else "MEASURED", "rows": len(batch), "invalid": bad})
        except OSError as exc:
            measurements.append({"input": path.name, "status": "NOT_MEASURED", "reason": type(exc).__name__})
    at = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    if at and at.tzinfo is None: ap.error("--now requires timezone")
    doc = aging(args.root, requests=requests, at=at)
    doc["input_measurements"] = measurements
    for m in measurements:
        if m["status"] != "MEASURED":
            doc["findings"].append({"status": "NOT_MEASURED", "reason": "input_" + m["status"].lower(), "input": m["input"]})
    print(json.dumps(doc, indent=2))
    return 1 if doc["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
