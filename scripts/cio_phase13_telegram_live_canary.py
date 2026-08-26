#!/usr/bin/env python3
"""Phase 13 operator step — live CIO Telegram canary (one material message).

Requires (already set by this script when operator invokes it):
  AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
  CIO_TELEGRAM_CANARY_ENABLE=1
  CIO_TELEGRAM_CANARY_APPROVAL=I_APPROVE_CIO_CANARY_SEND
  TELEGRAM_CIO_BOT_TOKEN + TELEGRAM_CIO_CHAT_IDS (from env files)
  CIO_TELEGRAM_INTERDICT unset / 0
  Not under pytest

Never prints token values. CIO-only transport (no general bot fallback).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

CANARY_APPROVAL = "I_APPROVE_CIO_CANARY_SEND"
ENV_FILES = [
    Path.home() / ".config" / "tradeai" / "cio-telegram.env",
    ROOT / ".env",
    Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env"),
]


def _load_env_files() -> list[str]:
    loaded = []
    for p in ENV_FILES:
        if not p.is_file():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if not k.isidentifier():
                    continue
                # Prefer dedicated CIO file values; do not overwrite already set
                if k not in os.environ or not os.environ.get(k):
                    os.environ[k] = v
            loaded.append(str(p))
        except Exception:
            pass
    return loaded


def _redact(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        lk = k.lower()
        if any(s in lk for s in ("token", "secret", "password", "authorization")):
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


def main() -> int:
    loaded = _load_env_files()
    # Operator-approved triple gate for THIS process only
    os.environ["AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY"] = "1"
    os.environ["CIO_TELEGRAM_CANARY_ENABLE"] = "1"
    os.environ["CIO_TELEGRAM_CANARY_APPROVAL"] = CANARY_APPROVAL
    os.environ.pop("CIO_TELEGRAM_INTERDICT", None)
    os.environ["ENABLE_TELEGRAM"] = "1"
    # Ensure not treated as pytest
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    os.environ.pop("PYTEST_VERSION", None)

    from lib import cio_alex_telegram as alex
    from lib import cio_telegram_transport as tg

    pre = {
        "env_files_loaded": loaded,
        "cio_token_configured": bool(tg.cio_bot_token()),
        "cio_chat_count": len(tg.cio_chat_ids()),
        "live_authorized": tg.live_authorized(),
        "network_interdicted": tg.network_interdicted(),
        "canary_approval_granted": alex.canary_approval_granted(),
        "under_pytest": tg.under_pytest(),
    }
    if not pre["cio_token_configured"] or pre["cio_chat_count"] < 1:
        print(json.dumps({"ok": False, "error": "CIO credentials incomplete", "pre": pre}, indent=2))
        return 2
    if pre["network_interdicted"] or not pre["canary_approval_granted"]:
        print(json.dumps({"ok": False, "error": "gates not open", "pre": pre}, indent=2))
        return 3

    decision = {
        "decision_id": "dec_phase13_live_canary",
        "symbol": "CANARY",
        "action": "Review",
        "stance": "Review",
        "recommended_delta_usd": 0.0,
        "why_now": (
            "Phase 13 operator live canary — CIO-only routing probe after production "
            "hardening. No portfolio action."
        ),
        "what_changes_call": "Canary complete; operator may re-enable INTERDICT if desired.",
        "counter_thesis": "None — canary has no book impact.",
        "status": "canary",
        "urgency": "low",
    }
    res = alex.execute_canary_send(decision=decision, force_approve_in_process=False)
    out = {
        "ok": bool(res.get("delivered")),
        "pre": pre,
        "result": _redact({
            "delivered": res.get("delivered"),
            "reason": res.get("reason"),
            "live_send": res.get("live_send"),
            "REAL_TELEGRAM_SENDS": res.get("REAL_TELEGRAM_SENDS"),
            "GENERAL_TELEGRAM_RECEIVED": res.get("GENERAL_TELEGRAM_RECEIVED"),
            "decision_id": res.get("decision_id"),
            "dedupe_key": res.get("dedupe_key"),
            "status": res.get("status"),
            "receipt": res.get("receipt"),
            "destination_identity": res.get("destination_identity"),
        }),
    }
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
