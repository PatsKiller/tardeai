"""Telegram (and future email) notifications for Hermes closed-loop alerts.

2026-10-15 (AGENTS.md §23.23, §24.1, §9.1 5.1.0): every send is a notification INTENT through the host chokepoint
``telegram_alert.send_telegram(priority=..., producer=PRODUCER)``; the router (telegram_alert_router.route_intent)
decides delivery, quiet-hours hold and dedupe. ``bypass_router`` is no longer passed (it was the shrink-only
BYPASS_ALLOWLIST entry in tests/test_notification_intents_20261010.py; the config key
channels.telegram.bypass_router is ignored). Priorities, declared:

  P2  critical / warning closed-loop alerts: operator-attention findings -- delivered now, held 22:00-07:00 ET.
  P3  info (below the default min_severity, only sent when it is lowered): FYI, folded by the digest.

``notify="record"`` emits the intent in the summary (``results[].intent``) and calls NO sender at all: the mode a
fabric-run step uses, so a host lane fired by n8n never sends (n8n asks the host through the send-intent route).

``notify="queue"`` (2026-10-15, n8n fabric cutover prerequisite G5 — the live argv of fabric step
outcome_feedback_agent): each eligible alert is QUEUED as a host comms intent (scripts/lib/host_comms_intents.py,
route research/hermes_closed_loop_alert in config/host_comms_intent_routes.json) in the coordination ledger; the host
comms-intent consumer turns it into an incident and the incident notifier delivers it (DIGEST -> P2). No sender is
called here. A queued (or folded duplicate) intent counts as delivered for the cooldown, exactly like a chokepoint
send; a refused queue is ``failed`` with its reason and leaves the cooldown alone, so the next run tries again.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_alert_notification_state.json"
AUDIT_PATH = PROJECT_ROOT / "state" / "hermes" / "alert_notification_audit.jsonl"
ALERTS_CFG_PATH = PROJECT_ROOT / "config" / "hermes_alerts.yaml"

_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
#: Producer the router receipts and the P3 digest archive name (notification_intent_p3:<producer>).
PRODUCER = "hermes_outcome_feedback_agent"
#: Notify modes: "chokepoint" sends an intent through send_telegram; "record" only returns the intent (no sender);
#: "queue" queues the intent for the host comms-intent consumer (no sender).
NOTIFY_MODES = ("chokepoint", "record", "queue")
#: The host-lane intent route (config/host_comms_intent_routes.json) this producer owns.
INTENT_DOMAIN = "research"
INTENT_KIND = "hermes_closed_loop_alert"


def _queue_host_intent(**kwargs: Any) -> dict[str, Any]:
    """scripts/lib/host_comms_intents.queue_intent (a seam the tests replace)."""
    from lib.host_comms_intents import queue_intent

    return queue_intent(**kwargs)


def intent_priority(severity: str | None) -> str:
    """The declared notification-intent priority of one closed-loop alert (module docstring)."""
    return "P2" if _SEVERITY_ORDER.get(str(severity or "warning"), 1) >= _SEVERITY_ORDER["warning"] else "P3"


def _load_cfg() -> dict[str, Any]:
    try:
        import yaml
        base = yaml.safe_load(ALERTS_CFG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        base = {}
    return base.get("notifications") or {}


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"last_sent": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"last_sent": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _log_audit(entry: dict[str, Any]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {**entry, "ts": datetime.now(timezone.utc).isoformat()}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _cooldown_ok(alert_id: str, cfg: dict[str, Any], state: dict[str, Any]) -> bool:
    hours = float(cfg.get("cooldown_hours", 8))
    last = (state.get("last_sent") or {}).get(alert_id)
    if not last:
        return True
    try:
        prev = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=timezone.utc)
        elapsed_h = (datetime.now(timezone.utc) - prev).total_seconds() / 3600.0
        return elapsed_h >= hours
    except Exception:
        return True


def _severity_meets_min(severity: str, min_sev: str) -> bool:
    return _SEVERITY_ORDER.get(severity, 1) >= _SEVERITY_ORDER.get(min_sev, 1)


def _alert_type_enabled(alert_id: str, cfg: dict[str, Any]) -> bool:
    types = cfg.get("alert_types") or {}
    if alert_id not in types:
        return True
    return bool(types[alert_id])


def _panel_url(cfg: dict[str, Any]) -> str:
    try:
        from notification_url_builder import build_dashboard_url
        path = str(cfg.get("panel_path") or "/v3/hermes")
        return build_dashboard_url(path)
    except Exception:
        return "/v3/hermes"


def _format_telegram_message(alert: dict[str, Any], panel_url: str) -> str:
    label = alert.get("label") or alert.get("id")
    sev = str(alert.get("severity") or "warning").upper()
    detail = alert.get("detail") or ""
    duration = alert.get("duration_days")
    dur_str = f"{duration}d" if duration else (alert.get("metrics") or {}).get("streak_days")
    if dur_str:
        dur_str = f"{dur_str} consecutive days" if isinstance(dur_str, int) else str(dur_str)

    lines = [
        f"⚠️ *Hermes Closed Loop* — {label}",
        f"Severity: *{sev}*" + (f" · Duration: {dur_str}" if dur_str else ""),
        "",
        detail[:400],
    ]

    contributors = alert.get("contributors") or {}
    syms = contributors.get("symbols") or []
    tags = contributors.get("tags") or []
    if syms:
        lines.append("")
        lines.append("*Top symbols:*")
        for s in syms[:3]:
            hr = s.get("hit_rate")
            hr_s = f"{hr:.0%}" if hr is not None else "—"
            lines.append(f"• {s.get('symbol')} — gate {s.get('gate')} · hits {s.get('hits')}/{s.get('n')} ({hr_s})")
    if tags:
        lines.append("")
        lines.append("*Tags:*")
        for t in tags[:2]:
            lines.append(f"• {t.get('tag')} lift {t.get('lift')}")

    lines.extend(["", f"→ {panel_url}"])
    return "\n".join(lines)


def _send_telegram(message: str, cfg: dict[str, Any], severity: str | None = None) -> bool:
    tg = (cfg.get("channels") or {}).get("telegram") or {}
    if not tg.get("enabled", True):
        return False
    try:
        from telegram_alert import send_telegram
        if intent_priority(severity) == "P2":
            return bool(send_telegram(message, priority="P2", producer=PRODUCER))
        return bool(send_telegram(message, priority="P3", producer=PRODUCER))
    except Exception as e:
        print(f"[hermes_alert_notify] telegram error: {e}")
        return False


def _send_email(message: str, cfg: dict[str, Any]) -> bool:
    em = (cfg.get("channels") or {}).get("email") or {}
    if not em.get("enabled", False):
        return False
    _log_audit({"channel": "email", "status": "skipped", "reason": "email_channel_disabled"})
    return False


def dispatch_alert_notifications(
    alerts: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
    dry_run: bool = False,
    notify: str = "chokepoint",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Send notifications for newly active / cooldown-eligible alerts. Returns summary.

    ``notify`` "chokepoint" (default): each eligible alert becomes an intent through the host chokepoint.
    "record": each eligible alert is returned as ``{"status": "intent", "intent": {...}}`` and no sender is called;
    no cooldown state is written (nothing was delivered), one audit line per intent is."""
    if notify not in NOTIFY_MODES:
        raise ValueError(f"notify must be one of {NOTIFY_MODES}, got {notify!r}")
    cfg = cfg or _load_cfg()
    if not cfg.get("enabled", True):
        return {"ok": True, "skipped": "notifications_disabled", "sent": 0}

    min_sev = str(cfg.get("min_severity") or "warning")
    state = _load_state()
    panel_url = _panel_url(cfg)
    sent = 0
    queued = 0
    suppressed = 0
    results: list[dict[str, Any]] = []

    for alert in alerts.get("active") or []:
        aid = str(alert.get("id") or "")
        sev = str(alert.get("severity") or "warning")

        if not _alert_type_enabled(aid, cfg):
            results.append({"id": aid, "status": "skipped", "reason": "type_disabled"})
            continue
        if not _severity_meets_min(sev, min_sev):
            results.append({"id": aid, "status": "skipped", "reason": "below_min_severity"})
            continue
        if not _cooldown_ok(aid, cfg, state):
            suppressed += 1
            results.append({"id": aid, "status": "suppressed", "reason": "cooldown"})
            _log_audit({"alert_id": aid, "channel": "telegram", "status": "suppressed", "reason": "cooldown"})
            continue

        message = _format_telegram_message(alert, panel_url)
        if dry_run:
            results.append({"id": aid, "status": "dry_run", "message_preview": message[:120]})
            continue
        if notify == "record":
            intent = {"producer": PRODUCER, "priority": intent_priority(sev), "severity": sev,
                      "dedupe_key": f"hermes_closed_loop:{aid}", "body": message}
            _log_audit({"alert_id": aid, "severity": sev, "channel": "intent", "status": "intent_recorded",
                        "priority": intent["priority"]})
            results.append({"id": aid, "status": "intent", "intent": intent})
            continue
        if notify == "queue":
            label = alert.get("label") or aid
            try:
                receipt = _queue_host_intent(
                    producer=PRODUCER,
                    domain=INTENT_DOMAIN,
                    kind=INTENT_KIND,
                    subject=f"Hermes closed loop {sev.upper()}: {label}",
                    summary=str(alert.get("detail") or label),
                    execution_id=str(run_id or "hermes_ofb"),
                    node=aid,
                )
            except Exception as e:  # noqa: BLE001 - a refused queue is a failed notification, never a crash
                reason = getattr(e, "reason", type(e).__name__)
                _log_audit({"alert_id": aid, "severity": sev, "channel": "intent_queue", "status": "failed",
                            "reason": reason})
                results.append({"id": aid, "status": "failed", "reason": f"queue:{reason}"})
                continue
            queued += 1
            state.setdefault("last_sent", {})[aid] = datetime.now(timezone.utc).isoformat()
            _save_state(state)
            _log_audit({"alert_id": aid, "severity": sev, "channel": "intent_queue", "status": "queued",
                        "intent_id": receipt.get("intent_id"), "duplicate": bool(receipt.get("duplicate"))})
            results.append({"id": aid, "status": "queued", "intent_id": receipt.get("intent_id"),
                            "duplicate": bool(receipt.get("duplicate")), "tier": receipt.get("tier")})
            continue

        tg_ok = _send_telegram(message, cfg, sev)
        em_ok = _send_email(message, cfg)
        status = "sent" if tg_ok else "failed"
        if tg_ok:
            sent += 1
            state.setdefault("last_sent", {})[aid] = datetime.now(timezone.utc).isoformat()
            _save_state(state)

        _log_audit({
            "alert_id": aid,
            "severity": sev,
            "channel": "telegram",
            "status": status,
            "telegram_ok": tg_ok,
            "email_ok": em_ok,
            "panel_url": panel_url,
            "contributors": alert.get("contributors"),
        })
        results.append({"id": aid, "status": status, "telegram_ok": tg_ok})

    return {
        "ok": True,
        "sent": sent,
        "queued": queued,
        "suppressed": suppressed,
        "dry_run": dry_run,
        "notify": notify,
        "results": results,
    }