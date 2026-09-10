#!/usr/bin/env python3
"""run_governed_commitment_shadow.py — Phase 8 shadow mint of GovernedCommitment@v1.

Thin CLI. Does NOT install cron/systemd. Default OFF via
``GOVERNED_COMMITMENT_ENABLED``. When the flag is off, exits 0 with no writes.

When on, builds a governed commitment and appends one JSONL row under
``--state-root/commitments.jsonl``. Authority: READ_ONLY_ADVISORY (MBI=0).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from scripts.lib.governed_commitment import (  # noqa: E402
    FEATURE_FLAG,
    build_governed_commitment,
    feature_enabled,
)


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--state-root", type=Path, required=True,
                   help="directory for commitments.jsonl (tests use tmp_path)")
    p.add_argument("--subject-guid", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--falsifier", required=True)
    p.add_argument("--confidence", type=float, default=0.6)
    p.add_argument("--horizon", default="7d")
    p.add_argument("--evidence-ref", action="append", default=[],
                   dest="evidence_refs",
                   help="repeatable evidence ref; default one synthetic ref")
    p.add_argument("--source-identity", default="governed_commitment_shadow")
    p.add_argument("--source-sha", default="")
    p.add_argument("--served-sha", default="")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="build + print; do not append (default)")
    p.add_argument("--execute", action="store_true",
                   help="append to commitments.jsonl (overrides --dry-run)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = dict(os.environ)

    if not feature_enabled(env):
        print(json.dumps({
            "ok": True,
            "outcome": "disabled",
            "reason": "feature_flag_off",
            "flag": FEATURE_FLAG,
            "mbi_behavior": 0,
        }, sort_keys=True))
        return 0

    now = datetime.now(timezone.utc)
    due = now + timedelta(days=7)
    evidence = list(args.evidence_refs) or [f"shadow:{args.subject_guid}"]
    source_sha = args.source_sha or env.get("TRADEAI_SOURCE_SHA") or env.get("BUILD_SHA") or "unknown"
    served_sha = args.served_sha or source_sha

    commitment = build_governed_commitment(
        claim=args.claim,
        confidence=args.confidence,
        horizon=args.horizon,
        due_at=due,
        falsifier=args.falsifier,
        evidence_refs=evidence,
        source_identity=args.source_identity,
        source_sha=source_sha,
        served_sha=served_sha,
        subject_guid=args.subject_guid,
        trigger_provenance={
            "producer": "run_governed_commitment_shadow",
            "trigger": "cli_shadow",
        },
        created_at=now,
        frozen_at=now,
    )

    dry_run = not args.execute
    out_path = args.state_root / "commitments.jsonl"
    if dry_run:
        print(json.dumps({
            "ok": True,
            "outcome": "dry_run",
            "would_append": str(out_path),
            "commitment": commitment,
            "mbi_behavior": 0,
        }, sort_keys=True, default=str))
        return 0

    _append_jsonl(out_path, commitment)
    print(json.dumps({
        "ok": True,
        "outcome": "appended",
        "path": str(out_path),
        "commitment_id": commitment["commitment_id"],
        "mbi_behavior": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
