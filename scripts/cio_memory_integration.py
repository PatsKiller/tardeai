#!/usr/bin/env python3
"""CLI for CIO bitemporal memory integration (isolated :55432 only)."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

NO_CONSUMER_REASON = (
    "CIO bitemporal memory integrator CLI; wake/AEC import scripts.lib.cio_memory_integration. "
    "Isolated :55432 only until operator grants production shadow cutover."
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_memory_integration import (  # noqa: E402
    CIOEnvelopeIntegrator,
    apply_bitemporal_schema_v2,
    integrate_wake_envelope,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--apply-schema", action="store_true")
    ap.add_argument("--envelope-json", default=None)
    ap.add_argument("--subject-key", default="WATCH:SCHG")
    ap.add_argument("--claim", default="Advisor cognitive thesis touch (non-financial)")
    args = ap.parse_args()
    apply = bool(args.apply)

    if args.apply_schema:
        from scripts.lib.memory_m2_v2 import connect

        conn = connect()
        try:
            verify = apply_bitemporal_schema_v2(conn)
            print(json.dumps({"schema_apply": verify, "production_sql_applied": False}, indent=2))
            if not all(verify.values()):
                return 2
        finally:
            conn.close()

    if args.envelope_json:
        envelope = json.loads(Path(args.envelope_json).read_text(encoding="utf-8"))
    else:
        envelope = {
            "subject_key": args.subject_key,
            "symbol": args.subject_key.split(":")[-1] if ":" in args.subject_key else args.subject_key,
            "predicate": "thesis",
            "claim": args.claim,
            "object": {"text": args.claim, "kind": "cognitive_hypothesis"},
            "wake_job_id": f"dry-{uuid.uuid4().hex[:8]}",
        }

    out = integrate_wake_envelope(envelope, apply=apply)
    print(json.dumps(out, indent=2, default=str))
    if not apply:
        print("DRY_RUN no durable write", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
