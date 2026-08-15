"""CIO Telegram operating mode vs isolation.

Isolation (G14) is not the same as proactive delivery.

  INTERDICTED   — kill switch on; no normal outbound HTTP
  PREPARE_ONLY  — packages may be built; no live send
  CIO_ONLY_LIVE — dedicated CIO bot/allowlist, interdict off, live authorized

Authority: READ_ONLY_ADVISORY. This module never changes env.
"""
from __future__ import annotations

import os
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MODES = ("INTERDICTED", "PREPARE_ONLY", "CIO_ONLY_LIVE")


def _flag(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _truthy(name: str, default: str = "") -> bool:
    return _flag(name, default).lower() in ("1", "true", "yes", "on")


def classify_delivery_mode(env: dict[str, str] | None = None) -> dict[str, Any]:
    get = (env or os.environ).get
    interdict = str(get("CIO_TELEGRAM_INTERDICT") or "").lower() in ("1", "true", "yes", "on")
    enable = str(get("ENABLE_TELEGRAM") or "true").lower() not in ("0", "false", "no", "off")
    live_auth = str(get("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY") or "") == "1"
    cio_token = bool(str(get("TELEGRAM_CIO_BOT_TOKEN") or "").strip())
    cio_chats = bool(str(get("TELEGRAM_CIO_CHAT_IDS") or get("TELEGRAM_CIO_ALLOWLIST") or "").strip())
    general_token = bool(str(get("TELEGRAM_BOT_TOKEN") or "").strip())
    pytest_on = bool(str(get("PYTEST_CURRENT_TEST") or get("PYTEST_VERSION") or "").strip())

    if interdict or pytest_on:
        mode = "INTERDICTED"
    elif not enable or not live_auth:
        mode = "PREPARE_ONLY"
    elif cio_token and cio_chats:
        mode = "CIO_ONLY_LIVE"
    else:
        mode = "PREPARE_ONLY"

    blockers = []
    if mode == "CIO_ONLY_LIVE" and general_token:
        # Dedicated path may still exist; flag that general creds are present
        # in the process env (transport must not use them).
        blockers.append("general_bot_token_present_in_env")
    live_ready = (
        mode == "CIO_ONLY_LIVE"
        and not interdict
        and enable
        and live_auth
        and cio_token
        and cio_chats
    )
    return {
        "CIO_DELIVERY_MODE": mode,
        "interdict": interdict,
        "enable_telegram": enable,
        "live_authorized": live_auth,
        "dedicated_cio_token_set": cio_token,
        "dedicated_chat_allowlist_set": cio_chats,
        "general_token_present": general_token,
        "proactive_delivery_ready": live_ready,
        "isolation_is_not_delivery": True,
        "blockers": blockers,
        "authority": AUTHORITY,
        "note": (
            "G14 isolation PASS is not CIO_ONLY_LIVE. "
            "INTERDICTED is a deliberate kill-switch state."
        ),
    }


def assert_cio_only_live(env: dict[str, str] | None = None) -> dict[str, Any]:
    rec = classify_delivery_mode(env)
    ok = rec["CIO_DELIVERY_MODE"] == "CIO_ONLY_LIVE" and rec["proactive_delivery_ready"]
    rec["ok"] = ok
    return rec
