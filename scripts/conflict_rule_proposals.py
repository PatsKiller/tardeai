#!/usr/bin/env python3
"""Lane `conflict-rule-proposals`: AI-proposed rules for UNMATCHED conflict patterns, for operator approval.

    python3 scripts/conflict_rule_proposals.py --dry-run --state-root <persistent-state>
    python3 scripts/conflict_rule_proposals.py --apply   --state-root <persistent-state>

Reads the UNMATCHED patterns the conflict-resolver shadow run recorded (data/conflicts/rule_proposals.jsonl), and for
each pattern with no pending/approved proposal (deduped by signature, capped per run/day/cost; caps in
config/conflict_rule_proposals.json) asks the governed bridge (caller n8n_model_job, task conflict_rule_proposal:
grok OAuth -> chatgpt OAuth -> DeepSeek) for one RuleProposal@v1, validates it here, appends it, and queues ONE
grouped P2 comms intent for the new pending proposals. ``--dry-run``: no model call, no write, no intent; prints
the due signatures and prompt sizes. Exit 0 = pass complete; 1 = store/source failure; 2 = usage.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Never a broker, order, stop, send, delete, crontab or systemd.
Scheduling is a separate [shared-infra] PR (lane_registry / n8n_run_allowlist / host_comms_intent_routes are
sha-pinned by docs/ops/packets/disk-standing-apply-20261024).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.conflicts import proposals as P  # noqa: E402

NO_CONSUMER_REASON = ("lane script; its receipt data/runtime/conflict-rule-proposals_last.json is read by Jobs & "
                      "health and its proposals by GET /api/v3/conflicts/proposals")


def _deferral(process_id):
    from lib import llm_deferral
    return llm_deferral.evaluate(process_id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--state-root", required=True)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    run_id = os.environ.get("TRADEAI_RUN_ID") or "crp-" + uuid.uuid4().hex[:16]
    root = Path(args.state_root)
    try:
        report = P.propose(root, now=now, apply=args.apply, deferral=_deferral if args.apply else None,
                           sleep=time.sleep, run_id=run_id)
        report["notification"] = (P.notify_pending(root, now=now, run_id=run_id) if args.apply
                                  else {"queued": False, "reason": "dry_run"})
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)[:200], "run_id": run_id}))
        return 1
    if args.apply:
        from scripts.lib.lane_last_receipt import write_lane_receipt
        write_lane_receipt("conflict-rule-proposals", ok=True, exit_code=0, started_at=now.isoformat(),
                           script="scripts/conflict_rule_proposals.py",
                           path=root / "data/runtime/conflict-rule-proposals_last.json",
                           summary={"created": len(report["created"]), "failed": len(report["failed"]),
                                    "model_calls": report["model_calls"], "cost_today_usd": report["cost_today_usd"],
                                    "notification": report["notification"].get("reason") or "queued"},
                           produced_count=len(report["created"]), attempted_count=len(report["due"]),
                           empty_reason=None if report["created"] else "no_pattern_due_or_capped")
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
