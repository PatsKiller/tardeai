"""paper_position_alerts.py — PR2 UI + Telegram delivery for options position monitor.

Advisory only — never submits orders. Persists options_monitored_alerts and optionally
routes formatted messages through telegram_alert (operator policy + dedupe).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

Executor = Callable[..., Any]

ALERT_PREFIX = "OPTIONS POSITION MONITOR"

LIFECYCLE_FILLED = "alpaca_paper_filled"
LIFECYCLE_CLOSED = "alpaca_paper_closed"
LIFECYCLE_ORPHAN = "orphan_error"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x


def _display_symbol(position: dict) -> str:
    """Underlying for Telegram — fall back to OCC root when registry row is sparse."""
    sym = str(position.get("underlying_symbol") or position.get("symbol") or "").strip().upper()
    if sym and sym != "?":
        return sym
    from lib.options_pipeline.paper_positions import underlying_from_occ
    occ = str(position.get("option_symbol") or "")
    return underlying_from_occ(occ) or sym or "?"


def panel_url() -> str:
    try:
        from notification_url_builder import build_dashboard_url
        return build_dashboard_url("/v3/trading?tab=Options")
    except Exception:
        return "/v3/trading?tab=Options"


def format_telegram_message(
    position: dict,
    alert_type: str,
    message: str,
    *,
    advice_label: str | None = None,
    unrealized_pnl: float | None = None,
    unrealized_pnl_pct: float | None = None,
    mark: float | None = None,
    extra: dict | None = None,
) -> str:
    """Build operator-facing Telegram body (routed via telegram_alert)."""
    sym = _display_symbol(position)
    strat = str(position.get("strategy") or "options").replace("_", " ")
    route = str(position.get("execution_route") or "review").replace("_", " ")
    label = advice_label or alert_type.replace("_", " ").upper()
    extra = extra or {}

    if alert_type == LIFECYCLE_FILLED:
        fill_px = _f(extra.get("fill_price") or position.get("entry_fill_price"))
        lines = [
            f"✅ *{ALERT_PREFIX}* — ALPACA PAPER FILLED",
            f"*{sym}* {strat} @ ${fill_px:.2f}",
            f"Route: {route} · {int(position.get('contracts') or 1)} contract",
            "_Validation credit starts after fill, close, and outcome reconciliation._",
        ]
    elif alert_type == LIFECYCLE_CLOSED:
        pnl = extra.get("pnl")
        pnl_s = f"${_f(pnl):,.2f}" if pnl is not None else "—"
        lines = [
            f"📋 *{ALERT_PREFIX}* — OUTCOME READY",
            f"*{sym}* {strat} closed on Alpaca paper · P/L {pnl_s}",
            "_Record outcome in desk when ready (advisory — no auto-submit)._",
        ]
    elif alert_type == LIFECYCLE_ORPHAN:
        lines = [
            f"🚨 *{ALERT_PREFIX}* — ORPHAN POSITION",
            f"*{sym}* {position.get('option_symbol') or ''}",
            f"_{message[:200]}_",
        ]
    else:
        pnl_line = ""
        if unrealized_pnl_pct is not None:
            sign = "+" if unrealized_pnl_pct >= 0 else ""
            pnl_amt = f" (${unrealized_pnl:,.0f})" if unrealized_pnl is not None else ""
            pnl_line = f"P/L: {sign}{unrealized_pnl_pct:.1f}%{pnl_amt}"
        mark_line = f" · Mark ${mark:.2f}" if mark else ""
        lines = [
            f"📊 *{ALERT_PREFIX}* — {label}",
            f"*{sym}* {strat} · {route}",
        ]
        if pnl_line or mark_line:
            lines.append(f"{pnl_line}{mark_line}".strip())
        lines.append(f"_Advisory: {message[:220]}_")

    lines.extend(["", f"→ {panel_url()}"])
    return "\n".join(lines)


def is_telegram_enabled(cfg: dict) -> bool:
    return bool(cfg.get("alert_telegram_enabled", True))


def is_ui_enabled(cfg: dict) -> bool:
    return bool(cfg.get("alert_ui_enabled", True))


def should_dedupe_telegram(
    position_id: int,
    alert_type: str,
    *,
    cfg: dict,
    executor: Executor,
    option_symbol: str | None = None,
    proposal_id: str | None = None,
) -> bool:
    """True when an equivalent alert was sent recently (skip duplicate Telegram)."""
    minutes = int(cfg.get("telegram_dedupe_minutes") or 60)
    row = executor(
        """SELECT id FROM options_monitored_alerts
           WHERE position_id = %s AND alert_type = %s
             AND created_at > NOW() - (%s || ' minutes')::interval
           ORDER BY created_at DESC LIMIT 1""",
        (position_id, alert_type, str(minutes)), fetch="one")
    if row:
        return True
    occ = str(option_symbol or "").strip().upper()
    pid = str(proposal_id or "").strip()
    if occ:
        row = executor(
            """SELECT a.id FROM options_monitored_alerts a
               JOIN options_monitored_positions p ON p.id = a.position_id
               WHERE a.alert_type = %s
                 AND a.created_at > NOW() - (%s || ' minutes')::interval
                 AND (
                   UPPER(COALESCE(p.option_symbol, '')) = %s
                   OR a.meta_json->>'proposal_id' = %s
                 )
               ORDER BY a.created_at DESC LIMIT 1""",
            (alert_type, str(minutes), occ, pid or None), fetch="one")
        if row:
            return True
    return False


def write_db_alert(
    position: dict,
    alert_type: str,
    message: str,
    *,
    severity: str = "warn",
    executor: Executor,
    meta: dict | None = None,
) -> None:
    payload = {
        "proposal_id": position.get("proposal_id"),
        "option_symbol": position.get("option_symbol"),
        **(meta or {}),
    }
    executor(
        """INSERT INTO options_monitored_alerts (
            position_id, alert_type, severity, message, broker, execution_route, meta_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)""",
        (position["id"], alert_type, severity, message,
         position.get("broker"), position.get("execution_route"),
         json.dumps(payload, default=str)))


def send_telegram(message: str) -> bool:
    try:
        from telegram_alert import send_telegram as _send
        return bool(_send(message))
    except Exception as e:
        print(f"[options_monitor] telegram skipped: {e}")
        return False


def dispatch_alert(
    position: dict,
    alert_type: str,
    message: str,
    *,
    severity: str = "warn",
    cfg: dict,
    executor: Executor,
    dry_run: bool = False,
    advice_label: str | None = None,
    unrealized_pnl: float | None = None,
    unrealized_pnl_pct: float | None = None,
    mark: float | None = None,
    extra: dict | None = None,
    force_telegram: bool = False,
) -> dict:
    """Persist UI alert and optionally send Telegram (PR2 default: both on)."""
    out = {"alert_type": alert_type, "ui": False, "telegram": False, "deduped": False}
    if dry_run:
        out["dry_run"] = True
        return out

    meta = {"advice_label": advice_label, **(extra or {})}
    if is_ui_enabled(cfg):
        write_db_alert(position, alert_type, message, severity=severity,
                       executor=executor, meta=meta)
        out["ui"] = True

    if not is_telegram_enabled(cfg) and not force_telegram:
        return out

    pos_id = int(position.get("id") or 0)
    if pos_id and should_dedupe_telegram(
        pos_id, alert_type, cfg=cfg, executor=executor,
        option_symbol=str(position.get("option_symbol") or ""),
        proposal_id=str(position.get("proposal_id") or ""),
    ):
        out["deduped"] = True
        return out

    body = format_telegram_message(
        position, alert_type, message,
        advice_label=advice_label,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        mark=mark,
        extra=extra,
    )
    out["telegram"] = send_telegram(body)
    if out["telegram"] and pos_id:
        executor(
            """UPDATE options_monitored_alerts
               SET meta_json = meta_json || %s::jsonb
               WHERE id = (
                   SELECT id FROM options_monitored_alerts
                   WHERE position_id = %s AND alert_type = %s
                   ORDER BY created_at DESC LIMIT 1
               )""",
            (json.dumps({"telegram_sent_at": _now_iso()}, default=str),
             pos_id, alert_type))
    return out


def dispatch_lifecycle_alert(
    position: dict | None,
    *,
    alert_type: str,
    message: str,
    cfg: dict | None = None,
    executor: Optional[Executor] = None,
    extra: dict | None = None,
) -> dict:
    """Lifecycle hook from reconcile / orphan ingest (fill, close, ERROR)."""
    from lib.options_pipeline.paper_position_monitor import load_config
    ex = executor or _default_executor()
    config = cfg or load_config()
    if not position or not position.get("id"):
        return {"ok": False, "error": "position required"}
    severity = "info" if alert_type == LIFECYCLE_FILLED else "warn"
    if alert_type == LIFECYCLE_ORPHAN:
        severity = "critical"
    res = dispatch_alert(
        position, alert_type, message,
        severity=severity, cfg=config, executor=ex,
        extra=extra, force_telegram=alert_type == LIFECYCLE_FILLED)
    return {"ok": True, **res}