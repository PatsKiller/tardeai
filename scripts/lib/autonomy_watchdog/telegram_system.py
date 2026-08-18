"""SYSTEM Telegram — distinct from CIO financial notifications.

Uses the generic ops bot (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).
Never uses TELEGRAM_CIO_* or CIO notification lineage.
CIO_TELEGRAM_INTERDICT does not apply to this family.
CI / pytest never send.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from scripts.lib.autonomy_watchdog.heartbeat import paths
from scripts.lib.autonomy_watchdog.io import append_jsonl, read_jsonl
from scripts.lib.autonomy_watchdog.model import ny_date, now_utc

def _http_post(url: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """stdlib POST. Tests patch this. Never used under CI lock."""
    import json as _json
    import urllib.error
    import urllib.request
    data = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    try:
        body = _json.loads(raw) if raw else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return body, int(status)


FAMILY = "TRADE_AI_SYSTEM"
DAILY_PREFIX = "system-heartbeat:"
CANARY_PREFIX = "system-canary:"
ALERT_PREFIX = "system-alert:"


def _ci_locked(env: Optional[dict[str, str]] = None) -> bool:
    src = env if env is not None else os.environ
    if src.get("TRADE_AI_CI") == "1":
        return True
    if str(src.get("SYSTEM_TELEGRAM_INTERDICT") or "").lower() in {"1", "true", "yes", "on"}:
        return True
    # Implicit pytest lock only when reading the real process env.
    if env is None and src.get("PYTEST_CURRENT_TEST"):
        return True
    return False


def configured(env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    src = env or os.environ
    token = bool(str(src.get("TELEGRAM_BOT_TOKEN") or "").strip())
    chat = bool(str(src.get("TELEGRAM_CHAT_ID") or "").strip())
    enabled = str(src.get("SYSTEM_TELEGRAM_ENABLED") or "1").lower() not in {"0", "false", "off"}
    return {
        "token_present": token,
        "chat_present": chat,
        "enabled": enabled,
        "ready": bool(token and chat and enabled and not _ci_locked(src)),
        "channel": "generic_ops_TELEGRAM_CHAT_ID",
        "separate_from_cio_financial": True,
        "family": FAMILY,
    }


def already_sent(identity: str, *, root=None) -> Optional[dict[str, Any]]:
    for rec in read_jsonl(paths(root)["system_sends"]):
        if rec.get("identity") == identity and rec.get("ok"):
            return rec
    return None


def record_send(rec: dict[str, Any], *, root=None) -> None:
    append_jsonl(paths(root)["system_sends"], rec)


def send_system(
    text: str,
    *,
    identity: str,
    kind: str,
    root=None,
    env: Optional[dict[str, str]] = None,
    force: bool = False,
) -> dict[str, Any]:
    src = env or os.environ
    rec: dict[str, Any] = {
        "at": now_utc().isoformat(),
        "identity": identity,
        "kind": kind,
        "family": FAMILY,
        "ok": False,
        "message_id": None,
        "financial_action": False,
        "cio_lineage": False,
    }
    if _ci_locked(src):
        rec["reason"] = "ci_or_interdict"
        record_send(rec, root=root)
        return rec
    cfg = configured(src)
    if not cfg["ready"]:
        rec["reason"] = "not_configured"
        record_send(rec, root=root)
        return rec
    prior = already_sent(identity, root=root)
    if prior and not force:
        rec.update({"ok": True, "deduped": True, "message_id": prior.get("message_id"), "reason": "deduped"})
        return rec
    token = str(src.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = str(src.get("TELEGRAM_CHAT_ID") or "").split(",")[0].strip()
    # Direct Bot API via stdlib — no CIO transport, no `requests` CI dependency.
    try:
        body, status = _http_post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": chat, "text": text},
        )
        rec["ok"] = bool(body.get("ok"))
        rec["message_id"] = ((body.get("result") or {}) if isinstance(body.get("result"), dict) else {}).get("message_id")
        rec["status_code"] = status
        if not rec["ok"]:
            rec["reason"] = str(body.get("description") or status)[:160]
    except Exception as e:
        rec["ok"] = False
        rec["reason"] = type(e).__name__
    record_send(rec, root=root)
    return rec


def daily_identity(now: Optional[datetime] = None) -> str:
    return DAILY_PREFIX + ny_date(now)


def canary_identity(now: Optional[datetime] = None) -> str:
    return CANARY_PREFIX + ny_date(now)


def after_daily_window(now: Optional[datetime] = None) -> bool:
    from scripts.lib.autonomy_watchdog.model import ny_now
    t = ny_now(now)
    return (t.hour, t.minute) >= (8, 15)


def send_daily(text: str, *, root=None, env=None, now=None) -> dict[str, Any]:
    if not after_daily_window(now):
        return {"ok": False, "reason": "before_0815_et", "identity": daily_identity(now), "deferred": True}
    return send_system(text, identity=daily_identity(now), kind="daily_heartbeat", root=root, env=env)


def send_canary(*, root=None, env=None, now=None) -> dict[str, Any]:
    text = (
        "TRADE AI SYSTEM TEST\n"
        "Explicit operator canary. Not a financial recommendation.\n"
        f"Identity {canary_identity(now)}"
    )
    return send_system(text, identity=canary_identity(now), kind="canary", root=root, env=env)


def send_alert(kind: str, text: str, *, root=None, env=None, now=None) -> dict[str, Any]:
    ident = f"{ALERT_PREFIX}{ny_date(now)}:{kind}"
    return send_system(
        "TRADE AI SYSTEM ALERT\n" + text,
        identity=ident, kind=kind, root=root, env=env,
    )
