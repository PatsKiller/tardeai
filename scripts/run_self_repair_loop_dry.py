#!/usr/bin/env python3
"""Dry harness for Lane J self-repair loop (non-financial).

detect_poller_identity_drift → proposal(executable=False) → verify_effect
on synthetic before/after. Prints JSON. Exit 0 on dry success.

Never recycles services, never mutates brokers/orders. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.lib.self_repair_loop_v1 import (  # noqa: E402
    detect_poller_identity_drift,
    verify_effect,
)

SCHEMA = "SelfRepairLoopDry@v1"
MBI_BEHAVIOR = 0

DEFAULT_BEFORE = {
    "matches_current": False,
    "mismatch_reason": "cwd_ne_current",
    "current_source_commit": "deadbeef",
    "poller_cwd": "/tmp/stale-release",
    "current_path": "/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT",
}
DEFAULT_AFTER = {
    "matches_current": True,
    "mismatch_reason": None,
    "current_source_commit": "deadbeef",
    "poller_cwd": "/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT",
    "current_path": "/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT",
}


def run_dry(
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = dict(before or DEFAULT_BEFORE)
    after = dict(after or DEFAULT_AFTER)
    proposal = detect_poller_identity_drift(before)
    proposal_dict = proposal.to_dict() if proposal is not None else None
    verification = verify_effect(before=before, after=after)
    dry_ok = (
        proposal is not None
        and proposal.executable is False
        and proposal.financial_surface_reachable is False
        and verification.get("passed") is True
    )
    return {
        "schema": SCHEMA,
        "mbi_behavior": MBI_BEHAVIOR,
        "authority": "READ_ONLY_ADVISORY",
        "production_mutation": False,
        "proposal": proposal_dict,
        "verify": verification,
        "dry_ok": bool(dry_ok),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before-json", type=Path, default=None)
    ap.add_argument("--after-json", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    before = (
        json.loads(Path(args.before_json).read_text(encoding="utf-8"))
        if args.before_json
        else None
    )
    after = (
        json.loads(Path(args.after_json).read_text(encoding="utf-8"))
        if args.after_json
        else None
    )
    report = run_dry(before=before, after=after)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if report.get("dry_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
