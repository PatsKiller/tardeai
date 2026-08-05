#!/usr/bin/env python3
"""Phase 2: persist durable recurring Maria/CIO review policy. Zero provider calls.

Does NOT enable workers or the event watcher.
Does NOT unquarantine CECO artifacts.
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
    ap.add_argument("--operator-id", default="operator")
    ap.add_argument("--expires-days", type=int, default=90)
    args = ap.parse_args()

    from lib.watch_review_policy_ledger import (
        build_intended_policy,
        persist_policy,
        policy_api_payload,
        validate_policy,
    )

    pol = build_intended_policy(operator_id=args.operator_id, expires_days=args.expires_days)
    pol["workers_enabled"] = False
    pol["event_watcher_enabled"] = False
    saved = persist_policy(pol)
    ok, reason = validate_policy(saved)
    out = {
        "ok": True,
        "provider_calls": 0,
        "phase": 2,
        "authorization_policy_id": saved.get("authorization_policy_id"),
        "policy_valid": ok,
        "policy_validation_reason": reason,
        "workers_enabled": False,
        "event_watcher_enabled": False,
        "authorization_endpoint": "/api/v3/data-broker/watch-review-policy",
        "api_payload": policy_api_payload(),
    }
    print(json.dumps(out, indent=2, default=str))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
