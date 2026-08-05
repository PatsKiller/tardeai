#!/usr/bin/env python3
"""Watch review workers entry — FAIL CLOSED when disabled / contained.

Phase 1–4: refuse to call providers.
Phase 5: enable only after canaries via policy.workers_enabled=true.

Usage:
  python3 scripts/run_watch_review_workers.py --mode plan
  python3 scripts/run_watch_review_workers.py --mode event-scan
  python3 scripts/run_watch_review_workers.py --mode execute   # blocked until enabled
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("plan", "event-scan", "execute"), default="plan")
    ap.add_argument("--allow-execute", action="store_true",
                    help="Required with execute; still blocked unless policy.workers_enabled")
    args = ap.parse_args()

    from lib.watch_review_policy_ledger import load_policy, validate_policy, containment_required_ok
    from lib.watch_review_pipeline import plan_jobs, evaluate_event_trigger, schedule_times

    pol = load_policy()
    ok, reason = validate_policy(pol)
    base = {
        "ok": ok,
        "provider_calls": 0,
        "mode": args.mode,
        "policy_validation": reason,
        "authorization_policy_id": (pol or {}).get("authorization_policy_id"),
        "workers_enabled": bool((pol or {}).get("workers_enabled")),
        "event_watcher_enabled": bool((pol or {}).get("event_watcher_enabled")),
        "schedule": schedule_times(),
    }
    if not ok:
        print(json.dumps({**base, "error": reason}, indent=2))
        return 2

    cont_ok, cont_reason = containment_required_ok()
    base["containment"] = cont_reason
    if not cont_ok:
        print(json.dumps({**base, "error": "containment_required", "detail": cont_reason}, indent=2))
        return 78

    if args.mode == "plan":
        # Dry-run plan against empty card set unless cards injected later
        plan = plan_jobs([], dry_run=True)
        print(json.dumps({**base, "plan": plan}, indent=2, default=str))
        return 0

    if args.mode == "event-scan":
        if not (pol or {}).get("event_watcher_enabled"):
            print(json.dumps({
                **base,
                "error": "event_watcher_disabled",
                "message": "Event watcher not enabled (phase 5). No jobs created. No provider calls.",
            }, indent=2))
            return 0
        # Enabled path would scan quotes — still no direct provider LLM calls
        print(json.dumps({
            **base,
            "message": "event watcher enabled flag set but broad scan not activated in this gate",
            "provider_calls": 0,
        }, indent=2))
        return 0

    # execute
    if not args.allow_execute or not (pol or {}).get("workers_enabled"):
        print(json.dumps({
            **base,
            "error": "execute_blocked",
            "message": (
                "Provider execution disabled until phase 5 canaries pass and "
                "policy.workers_enabled=true with --allow-execute."
            ),
            "provider_calls": 0,
        }, indent=2))
        return 78

    print(json.dumps({
        **base,
        "error": "execute_not_implemented_in_phase1",
        "message": "Canary executor lands after phase 2 policy proof; still no silent fallback.",
        "provider_calls": 0,
    }, indent=2))
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
