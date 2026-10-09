"""SYSTEM Telegram — distinct from CIO financial notifications.

Uses the generic ops bot (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).
Never uses TELEGRAM_CIO_* or CIO notification lineage.
CIO_TELEGRAM_INTERDICT does not apply to this family: sends pass
``family=SendFamily.SYSTEM_OPS`` and the transport confirms the claim (this
module, the ops bot token, the ops chat, SYSTEM_TELEGRAM_ENABLED on). The switch
for this family is SYSTEM_TELEGRAM_INTERDICT. CI / pytest never send.

Volume: one daily heartbeat per NY date (identity ``system-heartbeat:<date>``)
and at most one alert per transition kind per NY date
(``system-alert:<date>:<kind>``). A recorded DELIVERED send makes every later run
that day a dedupe that never reaches the transport. A comms-editor hold
(``suppressed``) is recorded ok but is not a delivery: the next run retries it.
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


def _delivered(rec: dict[str, Any]) -> bool:
    """True only for a send the transport actually delivered.

    A comms-editor hold/drop is recorded ``ok: True`` (it is not a failure) with
    ``suppressed`` set and ``reason: "suppressed:<why>"``; it was NOT delivered, so it
    must never satisfy the dedupe, or a held message is silently never retried
    (N8N maturity B2 round 2, 2026-10-09)."""
    if not rec.get("ok") or rec.get("deduped"):
        return False
    if rec.get("suppressed") or rec.get("held"):
        return False
    return not str(rec.get("reason") or "").startswith("suppressed")


def already_sent(identity: str, *, root=None) -> Optional[dict[str, Any]]:
    """The first DELIVERED record for ``identity`` (held/suppressed records never count)."""
    for rec in read_jsonl(paths(root)["system_sends"]):
        if rec.get("identity") == identity and _delivered(rec):
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
    # Shared Communications Editor chokepoint (deliver_text). Direct Bot API
    # bypassed CIO disagreement holds — 2026-09-18 audit.
    try:
        try:
            from telegram_transport import SendFamily, deliver_text
        except ImportError:
            from scripts.telegram_transport import SendFamily, deliver_text  # type: ignore

        def _post(url: str, payload: dict[str, Any]):
            body, status = _http_post(url, payload)
            return {"ok": bool(body.get("ok")), "status_code": status, "response": body}

        result = deliver_text(token=token, chat_id=chat, text=text, parse_mode=None, post=_post,
                              family=SendFamily.SYSTEM_OPS)
        if result.get("suppressed"):
            rec.update({
                "ok": True,
                "suppressed": result.get("suppressed"),
                "reason": f"suppressed:{result.get('suppressed')}",
                "message_id": None,
                "status_code": 200,
            })
        else:
            body = result.get("response") if isinstance(result.get("response"), dict) else {}
            rec["ok"] = bool(result.get("ok"))
            rec["message_id"] = result.get("message_id") or (
                (body.get("result") or {}) if isinstance(body.get("result"), dict) else {}
            ).get("message_id")
            rec["status_code"] = result.get("status_code")
            if not rec["ok"]:
                rec["reason"] = str(body.get("description") or result.get("status_code") or "")[:160]
    except Exception as e:
        rec["ok"] = False
        rec["reason"] = type(e).__name__
    record_send(rec, root=root)
    try:  # Communications hub (operator 2026-10-07): every operator-facing message is in the ledger.
        try:
            from telegram_alert import record_operator_message
        except ImportError:
            from scripts.telegram_alert import record_operator_message  # type: ignore
        record_operator_message(text, producer="autonomy_watchdog.telegram_system", message_class="ops",
                                delivered=bool(rec.get("ok")) and not rec.get("suppressed"))
    except Exception:  # noqa: BLE001 — recording never changes the watchdog's send
        pass
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


def preview_send(text: str, *, identity: str, kind: str, root=None, env=None) -> dict[str, Any]:
    """What ``send_system`` WOULD do now, without sending or recording anything."""
    src = env or os.environ
    out: dict[str, Any] = {"identity": identity, "kind": kind, "family": FAMILY, "would_send": False,
                           "text": text, "dry_run": True}
    if _ci_locked(src):
        out["reason"] = "ci_or_interdict"
        return out
    if not configured(src)["ready"]:
        out["reason"] = "not_configured"
        return out
    prior = already_sent(identity, root=root)
    if prior:
        out.update({"reason": "deduped", "prior_at": prior.get("at"), "prior_message_id": prior.get("message_id")})
        return out
    token = str(src.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = str(src.get("TELEGRAM_CHAT_ID") or "").split(",")[0].strip()
    try:
        try:
            from telegram_transport import system_send_gate
        except ImportError:
            from scripts.telegram_transport import system_send_gate  # type: ignore
        gate = system_send_gate(token=token, chat_id=chat)
    except Exception as e:  # noqa: BLE001 — a preview never raises
        out["reason"] = f"gate_unavailable:{type(e).__name__}"
        return out
    out["transport_gate"] = gate
    if gate.get("interdicted"):
        out["reason"] = f"interdicted:{gate.get('governing_switch')}"
        return out
    out.update({"would_send": True, "reason": "would_send"})
    return out


def preview_daily(text: str, *, root=None, env=None, now=None) -> dict[str, Any]:
    if not after_daily_window(now):
        return {"identity": daily_identity(now), "kind": "daily_heartbeat", "would_send": False,
                "reason": "before_0815_et", "deferred": True, "dry_run": True}
    return preview_send(text, identity=daily_identity(now), kind="daily_heartbeat", root=root, env=env)


def preview_alert(kind: str, text: str, *, root=None, env=None, now=None) -> dict[str, Any]:
    return preview_send("TRADE AI SYSTEM ALERT\n" + text, identity=f"{ALERT_PREFIX}{ny_date(now)}:{kind}",
                        kind=kind, root=root, env=env)
