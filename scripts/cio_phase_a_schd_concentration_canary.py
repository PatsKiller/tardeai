#!/usr/bin/env python3
"""Phase A operator step — SCHD concentration CIO Telegram canary.

One material concentration message. READ_ONLY_ADVISORY. No orders/stops.
Also proves signal-gate: first ACT_NOW → IMMEDIATE; sticky replay → DIGEST.
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
    os.environ["AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY"] = "1"
    os.environ["CIO_TELEGRAM_CANARY_ENABLE"] = "1"
    os.environ["CIO_TELEGRAM_CANARY_APPROVAL"] = CANARY_APPROVAL
    os.environ.pop("CIO_TELEGRAM_INTERDICT", None)
    os.environ["ENABLE_TELEGRAM"] = "1"
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    os.environ.pop("PYTEST_VERSION", None)

    from lib import cio_alex_telegram as alex
    from lib import cio_telegram_transport as tg
    from lib.cio_notification_signal import (
        DELIVERY_DIGEST,
        DELIVERY_IMMEDIATE,
        NotificationStateStore,
        decide_notification,
    )

    decision = {
        "decision_id": "dec_phase_a_schd_concentration_canary",
        "symbol": "SCHD",
        "action": "TRIM",
        "stance_code": "TRIM",
        "standing_recommendation": "TRIM",
        "current_action": "TRIM",
        "act_now": True,
        "weight_pct": 17.6,
        "current_weight_pct": 17.6,
        "recommended_delta_usd": -44000.0,
        "why_now": (
            "Phase A operator canary — SCHD concentration over single-name fire. "
            "READ_ONLY_ADVISORY; no portfolio action from this canary."
        ),
        "what_changes_call": "Weight under fire threshold or operator disposition.",
        "counter_thesis": "None — canary has no book impact.",
        "status": "canary",
        "urgency": "high",
    }

    store = NotificationStateStore(
        state_path="/tmp/cio_phase_a_canary_notify_state.jsonl",
        audit_path="/tmp/cio_phase_a_canary_notify_audit.jsonl",
        metrics_path="/tmp/cio_phase_a_canary_notify_metrics.jsonl",
    )
    nd1 = decide_notification(decision, store=store)
    store.record(nd1)
    nd2 = decide_notification(decision, store=store)

    pre = {
        "env_files_loaded": loaded,
        "cio_token_configured": bool(tg.cio_bot_token()),
        "cio_chat_count": len(tg.cio_chat_ids()),
        "live_authorized": tg.live_authorized(),
        "network_interdicted": tg.network_interdicted(),
        "canary_approval_granted": alex.canary_approval_granted(),
        "first_class": nd1.get("notification_class"),
        "sticky_class": nd2.get("notification_class"),
        "signal_gate_ok": (
            nd1.get("notification_class") == DELIVERY_IMMEDIATE
            and nd2.get("notification_class") == DELIVERY_DIGEST
        ),
    }
    if not pre["cio_token_configured"] or pre["cio_chat_count"] < 1:
        print(json.dumps({"ok": False, "error": "CIO credentials incomplete", "pre": pre}, indent=2))
        return 2
    if pre["network_interdicted"] or not pre["canary_approval_granted"]:
        print(json.dumps({"ok": False, "error": "gates not open", "pre": pre}, indent=2))
        return 3
    if not pre["signal_gate_ok"]:
        print(json.dumps({"ok": False, "error": "signal gate classes unexpected", "pre": pre}, indent=2))
        return 4

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
