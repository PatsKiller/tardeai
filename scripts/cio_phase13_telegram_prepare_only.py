#!/usr/bin/env python3
"""Phase 13 — prepare CIO Telegram canary package ONLY (no network send).

Does not set approval env vars. Prints destination identity (no secrets) and
the professional body for operator review.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

# Force interdict for this process
os.environ["CIO_TELEGRAM_INTERDICT"] = "1"
os.environ.pop("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", None)
os.environ.pop("CIO_TELEGRAM_CANARY_APPROVAL", None)


def main() -> int:
    from lib import cio_alex_telegram as alex

    decision = {
        "decision_id": "dec_phase13_prepare_only",
        "symbol": "CANARY",
        "action": "Review",
        "stance": "Review",
        "stance_code": "REVIEW",
        "recommended_delta_usd": 0.0,
        "why_now": "Phase 13 controlled host canary — prepare-only Telegram package; no live send.",
        "what_changes_call": "Operator sets triple env approval if a real canary send is desired later.",
        "counter_thesis": "None — prepare-only path.",
        "status": "prepare_only",
    }
    pkg = alex.prepare_canary_package(decision=decision)
    # Redact any accidental secrets
    safe = {k: v for k, v in pkg.items() if "token" not in k.lower() and "secret" not in k.lower()}
    # Attempt execute must remain blocked
    res = alex.execute_canary_send(decision=decision, force_approve_in_process=True)
    out = {
        "mode": "prepare_only",
        "package": safe,
        "execute_attempt": {
            "delivered": res.get("delivered"),
            "reason": res.get("reason"),
            "REAL_TELEGRAM_SENDS": res.get("REAL_TELEGRAM_SENDS", 0),
        },
        "REAL_TELEGRAM_SENDS": 0,
        "NOTE": "Live send requires AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY + CIO_TELEGRAM_CANARY_ENABLE + CIO_TELEGRAM_CANARY_APPROVAL",
    }
    print(json.dumps(out, indent=2, default=str))
    assert res.get("delivered") is not True
    assert out["REAL_TELEGRAM_SENDS"] == 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
