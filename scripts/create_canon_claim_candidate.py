#!/usr/bin/env python3
"""Create one sourced EXTRACTED CanonClaim candidate from staged canon chunks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_canon_v1 import append_claim_candidate, build_canon_claim  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-record", required=True)
    parser.add_argument("--chunks", required=True)
    parser.add_argument("--chunk-id", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--asset-class", required=True)
    parser.add_argument("--claim-type", required=True)
    parser.add_argument("--output", default=str(ROOT / "data/cio/canon_claims.jsonl"))
    args = parser.parse_args()
    source = json.loads(Path(args.source_record).read_text(encoding="utf-8"))
    chunks = []
    for line in Path(args.chunks).read_text(encoding="utf-8").splitlines():
        try:
            chunks.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    chunk = next((row for row in chunks if row.get("chunk_id") == args.chunk_id), None)
    if not chunk:
        raise SystemExit("chunk_id not found in staged source")
    claim = build_canon_claim(
        source_record=source,
        chunk=chunk,
        claim_summary=args.summary,
        domain=args.domain,
        asset_class=args.asset_class,
        claim_type=args.claim_type,
    )
    receipt = append_claim_candidate(claim, store_path=args.output)
    print(json.dumps({**receipt, "status": claim["status"], "decision_eligible": False, "authority": claim["authority"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
