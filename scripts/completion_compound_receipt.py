#!/usr/bin/env python3
"""Record a non-secret compound-lane result after an owned child has finished.

Private child of agent intelligence, inference, research overnight and cost runners.
This CLI schedules nothing and stores only explicit lane/step/exit metadata.

``--output-receipt PATH`` (repeatable, with ``--since``): the children that count their own work write a run
receipt carrying ``produced_count`` / ``attempted_count`` / ``skipped_reasons`` (LaneRunReceipt@v2 output fields,
docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §5). The compound receipt sums the receipts finished at or after
``--since`` (this run's start) so a health contract's ``expected_output`` rule can tell "ran and produced" from
"exit 0 and nothing". A receipt that is missing or older than ``--since`` is recorded as a typed skip, never
counted (a stale file is not this run's work).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NO_CONSUMER_REASON = "private receipt child of the owned compound cron/timer entrypoints"


def _bump(d: dict, key: str, n: int = 1) -> None:
    d[key] = d.get(key, 0) + int(n)


def _resolve(raw: str) -> Path:
    """A path, or ``lane:<lane_id>`` = that lane's LaneRunReceipt under the persistent state root."""
    if raw.startswith("lane:"):
        from scripts.lib.lane_last_receipt import receipt_path

        return receipt_path(raw[len("lane:") :])
    return Path(raw)


def aggregate_outputs(paths: list[str], since: str | None) -> dict:
    """Sum the v2 output fields of the step receipts finished at/after ``since``. Pure apart from reading files."""
    produced = attempted = 0
    skipped: dict[str, int] = {}
    evidence: list[dict] = []
    for raw in paths:
        p = _resolve(raw)
        name = p.stem
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _bump(skipped, f"step_receipt_missing:{name}")
            continue
        if not isinstance(doc, dict):
            _bump(skipped, f"step_receipt_missing:{name}")
            continue
        finished = str(doc.get("finished_at") or "")
        if since and finished < since:
            _bump(skipped, f"step_receipt_stale:{name}")
            continue
        n = int(doc.get("produced_count") or 0)
        produced += n
        attempted += int(doc.get("attempted_count") or 0)
        for k, v in (doc.get("skipped_reasons") or {}).items():
            _bump(skipped, f"{name}:{k}", int(v or 0))
        evidence.append({"kind": "receipt_field", "ref": f"{p.name}#produced_count", "count": n, "as_of": finished})
    out = {
        "produced_count": produced,
        "attempted_count": attempted,
        "skipped_reasons": skipped,
        "output_evidence": evidence,
    }
    if produced == 0:
        out["empty_reason"] = None
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--step")
    parser.add_argument("--exit", type=int, required=True, dest="exit_code")
    parser.add_argument(
        "--output-receipt",
        action="append",
        default=[],
        help="a child run receipt with produced_count/attempted_count (repeatable)",
    )
    parser.add_argument(
        "--since", default=None, help="ISO-8601 UTC start of this run; receipts finished earlier are not counted"
    )
    args = parser.parse_args(argv)
    from scripts.lib.lane_last_receipt import write_lane_receipt

    lane = args.lane + ("--step-" + args.step if args.step else "")
    output = aggregate_outputs(args.output_receipt, args.since) if args.output_receipt else None
    result = write_lane_receipt(
        lane,
        ok=args.exit_code == 0,
        exit_code=args.exit_code,
        script="completion_compound_receipt.py",
        started_at=args.since,
        summary={
            "step": args.step,
            "status": "RUN_SKIPPED_LOCK"
            if args.exit_code == 75
            else ("completed" if args.exit_code == 0 else "failed"),
        },
        output=output,
    )
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
