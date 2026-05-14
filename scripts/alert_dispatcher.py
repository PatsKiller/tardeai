"""alert_dispatcher.py — Central alert dispatcher for Trade AI v12.

All alerts should route through this module. It provides:
  1. Cross-script deduplication (same alert won't fire from multiple scripts)
  2. Escalation tiers: INFO (dashboard only), ALERT (Telegram), URGENT (Telegram + priority)
  3. Alert fatigue detection (auto-downgrade after N consecutive days)
  4. Rate limiting (max alerts per hour per channel)
  5. Unified notification_log writing

Usage:
    from alert_dispatcher import dispatch_alert

    dispatch_alert(
        alert_type="stop_triggered",
        symbol="V",
        title="Stop Triggered: V",
        body="Visa hit trailing stop at $315.00",
        tier="ALERT",            # INFO, ALERT, URGENT
        source="recovery_watch_daily",
        dedupe_scope="symbol",   # symbol, global, none
    )
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v

# ── Configuration ──────────────────────────────────────────────────────

# Alerts that fire > this many consecutive days get auto-downgraded to INFO
FATIGUE_THRESHOLD_DAYS = int(os.getenv("ALERT_FATIGUE_DAYS", "3"))

# Max Telegram alerts per hour (across all scripts)
MAX_TELEGRAM_PER_HOUR = int(os.getenv("ALERT_MAX_PER_HOUR", "15"))

# Tiers
TIER_INFO = "INFO"           # Dashboard only — no Telegram
TIER_ALERT = "ALERT"         # Telegram notification
TIER_URGENT = "URGENT"       # Telegram with priority flag
TIER_DIGEST = "DIGEST"       # Aggregated into morning/evening brief
TIER_DASHBOARD = "DASHBOARD_ONLY"  # No Telegram at all

# ── Three-tier classification rules ─────────────────────────────────────
# Maps alert_type to tier + dedup behavior. Unknown types default to ALERT.

ALERT_TIER_RULES = {
    # URGENT — first occurrence only, dedup 24h per symbol+condition
    'stop_triggered': {'tier': TIER_URGENT, 'dedup_window_hours': 24, 'escalate_on_worsen_pct': 2.0},
    'iris_block': {'tier': TIER_URGENT, 'dedup_window_hours': 12},
    'credential_expired': {'tier': TIER_URGENT, 'dedup_window_hours': 24},
    'api_credits_depleted': {'tier': TIER_URGENT, 'dedup_window_hours': 24},
    'pipeline_failure': {'tier': TIER_URGENT, 'dedup_window_hours': 4},
    'proposal_approved_ready': {'tier': TIER_URGENT, 'dedup_window_hours': 24},
    'sector_event': {'tier': TIER_URGENT, 'dedup_window_hours': 4},

    # DIGEST — aggregated into morning (8 AM) or evening (4 PM) briefs
    'premarket_catalyst': {'tier': TIER_DIGEST, 'digest_slot': 'morning'},
    'topic_ingestion': {'tier': TIER_DIGEST, 'digest_slot': 'evening'},
    'rag_curation_summary': {'tier': TIER_DIGEST, 'digest_slot': 'evening'},
    'covered_call_candidates': {'tier': TIER_DIGEST, 'digest_slot': 'evening'},
    'iris_library_audit': {'tier': TIER_DIGEST, 'digest_slot': 'morning'},
    'new_go_normal': {'tier': TIER_DIGEST, 'digest_slot': 'morning'},

    # DASHBOARD_ONLY — no Telegram at all
    'youtube_backfill_progress': {'tier': TIER_DASHBOARD},
    'pipeline_run_ok': {'tier': TIER_DASHBOARD},
    'duplicate_recap': {'tier': TIER_DASHBOARD},
    'go_confirmation_repeat': {'tier': TIER_DASHBOARD},
}


def _get_conn():
    """Get DB connection."""
    try:
        import psycopg2
        pw = os.getenv("DB_PASSWORD", "")
        return psycopg2.connect(host="127.0.0.1", port=5432,
                                dbname="trade_ai", user="trade_ai", password=pw)
    except Exception:
        return None


def _check_fatigue(conn, alert_type: str, symbol: str = "") -> int:
    """Check how many consecutive days this alert has fired.

    Returns: number of consecutive days (0 if first occurrence).
    """
    try:
        cur = conn.cursor()
        # Count distinct dates in last 7 days with this alert type + symbol
        if symbol:
            cur.execute("""
                SELECT COUNT(DISTINCT notification_date) FROM notification_log
                WHERE notification_type = %s
                  AND (subject LIKE %s OR payload::text LIKE %s)
                  AND notification_date >= CURRENT_DATE - 7
                  AND status = 'sent'
            """, (alert_type, f"%{symbol}%", f"%{symbol}%"))
        else:
            cur.execute("""
                SELECT COUNT(DISTINCT notification_date) FROM notification_log
                WHERE notification_type = %s
                  AND notification_date >= CURRENT_DATE - 7
                  AND status = 'sent'
            """, (alert_type,))
        return cur.fetchone()[0] or 0
    except Exception:
        return 0


def _check_rate_limit(conn) -> bool:
    """Check if we're under the hourly Telegram rate limit.

    Returns: True if we can send, False if rate-limited.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM notification_log
            WHERE channel = 'telegram'
              AND sent_at > NOW() - INTERVAL '1 hour'
              AND status = 'sent'
        """)
        count = cur.fetchone()[0] or 0
        return count < MAX_TELEGRAM_PER_HOUR
    except Exception:
        return True  # fail-open


def _already_sent(conn, dedupe_key: str) -> bool:
    """Check if this exact alert was already sent."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM notification_log WHERE dedupe_key = %s", (dedupe_key,))
        return cur.fetchone() is not None
    except Exception:
        return False


def _send_telegram(message: str) -> bool:
    """Send via Telegram. Uses the existing telegram_alert module."""
    try:
        from telegram_alert import send_telegram
        return send_telegram(message)
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


def _log_notification(conn, alert_type: str, tier: str, title: str, body: str,
                      dedupe_key: str, channel: str, source: str,
                      symbol: str = "", sent: bool = False, error: str = None):
    """Write to notification_log."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notification_log
                (notification_date, notification_type, channel, subject, body_summary,
                 payload, status, dedupe_key, sent_at, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedupe_key) DO NOTHING
        """, (
            date.today(), alert_type, channel, title[:200], body[:500],
            json.dumps({"tier": tier, "source": source, "symbol": symbol}),
            "sent" if sent else ("rate_limited" if not error else "failed"),
            dedupe_key,
            datetime.now() if sent else None,
            error,
        ))
        conn.commit()
    except Exception as e:
        log.error(f"notification_log write failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def dispatch_alert(
    alert_type: str,
    title: str,
    body: str,
    tier: str = TIER_ALERT,
    symbol: str = "",
    source: str = "unknown",
    dedupe_scope: str = "symbol",
    force: bool = False,
) -> dict:
    """Central alert dispatcher. All scripts should route alerts through here.

    Args:
        alert_type: Category (e.g., "stop_triggered", "dividend_payers", "pipeline_failure")
        title: Short title for the alert
        body: Full message body (Telegram-formatted)
        tier: INFO (dashboard only), ALERT (Telegram), URGENT (Telegram + flag)
        symbol: Symbol context (for per-symbol dedup)
        source: Calling script name
        dedupe_scope: "symbol" (per symbol per day), "global" (per type per day), "none" (no dedup)
        force: Skip all checks and send immediately

    Returns:
        dict with: sent (bool), reason (str), tier (str), fatigued (bool)
    """
    today = str(date.today())

    # Build dedupe key
    if dedupe_scope == "symbol" and symbol:
        dedupe_key = f"{today}:{alert_type}:{symbol}"
    elif dedupe_scope == "global":
        dedupe_key = f"{today}:{alert_type}:global"
    else:
        dedupe_key = f"{today}:{alert_type}:{source}:{hash(body) % 100000}"

    conn = _get_conn()
    if not conn:
        # No DB — fall through to direct Telegram
        if tier in (TIER_ALERT, TIER_URGENT):
            sent = _send_telegram(body)
            return {"sent": sent, "reason": "no_db_fallback", "tier": tier, "fatigued": False}
        return {"sent": False, "reason": "info_tier_no_db", "tier": tier, "fatigued": False}

    try:
        # 1. Dedup check (unless force)
        if not force and _already_sent(conn, dedupe_key):
            return {"sent": False, "reason": "already_sent_today", "tier": tier, "fatigued": False}

        # 2. Fatigue check — auto-downgrade if same alert for too many days
        fatigued = False
        consecutive_days = _check_fatigue(conn, alert_type, symbol)
        if consecutive_days >= FATIGUE_THRESHOLD_DAYS and tier != TIER_URGENT and not force:
            fatigued = True
            # Downgrade to INFO (dashboard only)
            original_tier = tier
            tier = TIER_INFO
            # Fire a META alert about the unresolved condition (once)
            meta_dk = f"{today}:alert_fatigue_meta:{alert_type}:{symbol}"
            if not _already_sent(conn, meta_dk):
                meta_body = (
                    f"*Alert Fatigue Detected*\n\n"
                    f"'{alert_type}' for {symbol or 'system'} has fired {consecutive_days} consecutive days.\n"
                    f"Auto-downgraded from {original_tier} to INFO (dashboard only).\n\n"
                    f"Resolve the underlying condition or dismiss the alert."
                )
                if _check_rate_limit(conn):
                    _send_telegram(meta_body)
                _log_notification(conn, "alert_fatigue_meta", TIER_ALERT,
                                  f"Alert Fatigue: {alert_type} ({symbol or 'system'})",
                                  meta_body, meta_dk, "telegram", "alert_dispatcher",
                                  symbol=symbol, sent=True)

        # 3. Check tier classification rules
        tier_rules = ALERT_TIER_RULES.get(alert_type, {})
        classified_tier = tier_rules.get('tier')
        if classified_tier and not force:
            # Override caller's tier with classification
            if classified_tier == TIER_DIGEST:
                action = _queue_digest(conn, alert_type, symbol, body,
                                       metadata={"source": source, "title": title})
                _log_dispatch(conn, alert_type, TIER_DIGEST, symbol, dedupe_key,
                              body, {"source": source}, action)
                return {"sent": False, "reason": action, "tier": TIER_DIGEST, "fatigued": False}
            elif classified_tier == TIER_DASHBOARD:
                _log_dispatch(conn, alert_type, TIER_DASHBOARD, symbol, dedupe_key,
                              body, {"source": source}, 'dashboard_only')
                _log_notification(conn, alert_type, TIER_DASHBOARD, title, body, dedupe_key,
                                  "dashboard", source, symbol=symbol, sent=True)
                return {"sent": False, "reason": "dashboard_only", "tier": TIER_DASHBOARD, "fatigued": False}

        # 4. Route by tier
        channel = "dashboard"
        sent = False
        error = None

        if tier == TIER_INFO:
            channel = "dashboard"
            sent = True  # "sent" to dashboard = logged

        elif tier == TIER_ALERT:
            channel = "telegram"
            if _check_rate_limit(conn):
                sent = _send_telegram(body)
                if not sent:
                    error = "telegram_send_failed"
            else:
                error = "rate_limited"
                channel = "dashboard"  # fallback to dashboard

        elif tier == TIER_URGENT:
            channel = "telegram"
            # Urgent alerts bypass rate limit
            sent = _send_telegram(body)
            if not sent:
                error = "telegram_send_failed"

        # 5. Log to notification_log and dispatch_log
        _log_notification(conn, alert_type, tier, title, body, dedupe_key,
                          channel, source, symbol=symbol, sent=sent, error=error)
        _log_dispatch(conn, alert_type, tier, symbol, dedupe_key,
                      body, {"source": source}, 'sent_telegram' if sent else (error or 'logged'))

        return {"sent": sent, "reason": error or "ok", "tier": tier, "fatigued": fatigued}

    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Digest queue helper ────────────────────────────────────────────────

def _queue_digest(conn, alert_type, symbol, body, metadata=None):
    """Queue an alert for the next morning or evening digest."""
    rules = ALERT_TIER_RULES.get(alert_type, {})
    slot = rules.get('digest_slot', 'morning')
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO digest_queue
                (digest_slot, alert_type, symbol, message, metadata, queued_at, sent)
            VALUES (%s, %s, %s, %s, %s, NOW(), FALSE)
        """, [slot, alert_type, symbol, body[:1000],
              json.dumps(metadata or {})])
        conn.commit()
        return f'queued_{slot}_digest'
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return f'digest_queue_error: {e}'


def _log_dispatch(conn, alert_type, tier, symbol, condition_key,
                  message, metadata, action):
    """Write to alert_dispatch_log for visibility."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO alert_dispatch_log
                (alert_type, tier, symbol, condition_key, message, metadata, action_taken)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, [alert_type, tier, symbol, condition_key,
              (message or '')[:500], json.dumps(metadata or {}), action])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def classify_alert(alert_type):
    """Return the tier rules for an alert type. Unknown types get ALERT tier."""
    return ALERT_TIER_RULES.get(alert_type, {'tier': TIER_ALERT})


# ── Convenience functions for common alert patterns ────────────────────

def alert_stop_triggered(symbol: str, price: float, stop: float, source: str = "portfolio_orchestrator"):
    """Alert for stop loss trigger."""
    return dispatch_alert(
        alert_type="stop_triggered",
        symbol=symbol,
        title=f"Stop Triggered: {symbol}",
        body=f"\U0001f6a8 *Stop Triggered: {symbol}*\nPrice: ${price:,.2f}\nStop: ${stop:,.2f}",
        tier=TIER_ALERT,
        source=source,
        dedupe_scope="symbol",
    )


def alert_dividend_payers(month_name: str, total: float, symbols: list, annual: float, source: str = "portfolio_orchestrator"):
    """Alert for current month dividend payers."""
    syms = ", ".join(symbols[:10])
    return dispatch_alert(
        alert_type="dividend_payers",
        title=f"Dividend Payers — {month_name}: ${total:,.0f}",
        body=(f"\U0001f4b0 *Dividend Payers This Month ({month_name})*\n\n"
              f"Expected: ${total:,.0f} from {len(symbols)} positions\n"
              f"Symbols: {syms}\n\n"
              f"Annual income: ${annual:,.0f}/yr"),
        tier=TIER_ALERT,
        source=source,
        dedupe_scope="global",
    )


def alert_pipeline_failure(pipeline_name: str, error_text: str, source: str = "pipeline_alert"):
    """Alert for pipeline execution failure."""
    return dispatch_alert(
        alert_type="pipeline_failure",
        title=f"Pipeline Failure: {pipeline_name}",
        body=(f"\U0001f6a8 *Pipeline Failure: {pipeline_name}*\n\n"
              f"Error: {error_text[:300]}\n\n"
              f"Reply: run {pipeline_name}"),
        tier=TIER_URGENT,
        source=source,
        dedupe_scope="global",
    )


def alert_proposal_aging(symbol: str, days_pending: int, source: str = "system"):
    """Alert when a proposal has been pending too long."""
    return dispatch_alert(
        alert_type="proposal_aging",
        symbol=symbol,
        title=f"Stale Proposal: {symbol} ({days_pending}d)",
        body=(f"*Proposal Aging: {symbol}*\n\n"
              f"Status: PENDING for {days_pending} days\n"
              f"Action needed: approve, reject, or expire."),
        tier=TIER_ALERT,
        source=source,
        dedupe_scope="symbol",
    )


def alert_api_credits_depleted(provider: str, error: str, source: str = "system"):
    """Alert when API credits are exhausted."""
    return dispatch_alert(
        alert_type="api_credits_depleted",
        title=f"API Credits Depleted: {provider}",
        body=(f"*API Credits Depleted: {provider}*\n\n"
              f"Error: {error[:200]}\n\n"
              f"Services affected: rebalance advisor, cloud LLM fallback\n"
              f"Action: top up credits at provider dashboard."),
        tier=TIER_URGENT,
        source=source,
        dedupe_scope="global",
    )


def alert_recovery_escalation(symbol: str, verdict: str, confidence: float,
                               summary: str, escalated_to: str, source: str = "recovery_watch_daily"):
    """Alert for recovery watch escalation."""
    return dispatch_alert(
        alert_type="recovery_escalation",
        symbol=symbol,
        title=f"Recovery: {symbol} → {escalated_to}",
        body=(f"*Recovery Watch Escalation*\n"
              f"Symbol: *{symbol}*\n"
              f"Verdict: {verdict.replace('_', ' ').title()} ({confidence*100:.0f}%)\n"
              f"Escalated to: *{escalated_to.title()}*\n"
              f"Summary: {summary[:200]}"),
        tier=TIER_ALERT,
        source=source,
        dedupe_scope="symbol",
    )
