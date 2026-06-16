#!/usr/bin/env python3
"""report_capture.py — persist outbound operator reports so the v3 Reports portal can surface them.

Many recurring reports/advisories (Incubator LLM Screen, EOD Open Trades, Auto-Research, Trade AI
Critique, Strategy Weekly, Alex Review, Portfolio Brief, monthly reports …) are sent straight to
Telegram and were never stored — so the Reports hub could not show them. This module is called from
the Telegram send chokepoint (telegram_alert._raw_send_telegram) and writes every *recognized* report
to the `telegram_outbox` table, classified by report_type. Best-effort: never raises, never blocks a send.

Only messages that classify to a known report_type are stored — transient alerts/briefs that already
self-log to notification_log / alert_events are intentionally skipped (no duplication).
"""
from __future__ import annotations

import re

# header marker → stable report_type (order matters: most specific first)
_RULES = [
    ("incubator_screen", r"Incubator LLM Screen"),
    ("auto_research",    r"Auto-?Research Complete|🔍\s*Auto-?Research"),
    ("eod_open_trades",  r"EOD OPEN TRADE|OPEN TRADE REPORT"),
    ("closed_trade_digest", r"Closed Trade Digest"),
    ("trade_critique",   r"Trade AI Critique"),
    ("strategy_weekly",  r"Strategy Weekly Review"),
    ("alex_review",      r"Alex (?:Weekly|Daily)(?: Review| Brief)?"),
    ("weekly_summary",   r"Weekly Portfolio Summary|Weekly Report"),
    ("learning_digest",  r"Weekly Learning Digest"),
    ("commanders_summary", r"COMMANDER'?S SUMMARY"),
    ("monthly_report",   r"Monthly (?:Report|Retirement|Review)"),
    ("daily_intel",      r"Daily Intelligence Report"),
    ("cio_summary",      r"CIO Intelligence Summary"),
    ("overnight_brief",  r"OVERNIGHT BRIEF"),
    ("premarket_brief",  r"Pre-?Market Brief|Pre-?Open Brief"),
    ("trade_ai_brief",   r"TRADE AI BRIEF"),
    ("stop_brief",       r"STOP BRIEF"),
    ("recovery_reminder", r"Stop Placement Reminder"),
    ("portfolio_brief",  r"Portfolio Brief"),
]
_COMPILED = [(t, re.compile(p, re.IGNORECASE)) for t, p in _RULES]

_ensured = False


def classify_report(message: str) -> str | None:
    """Return the report_type for a recognized report, else None (skip capture)."""
    if not message:
        return None
    head = message[:400]
    for rtype, pat in _COMPILED:
        if pat.search(head):
            return rtype
    return None


def _title(message: str) -> str:
    """First meaningful line, stripped of markdown/emoji decoration."""
    for raw in (message or "").splitlines():
        line = raw.strip().strip("*_# ").strip()
        # skip pure-decoration separator lines
        if line and not re.fullmatch(r"[━─=•·\-\s]+", line):
            return line[:200]
    return "(report)"


def _ensure_table(cur) -> None:
    global _ensured
    if _ensured:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS telegram_outbox (
            id          BIGSERIAL PRIMARY KEY,
            sent_at     TIMESTAMPTZ DEFAULT now(),
            report_type TEXT,
            title       TEXT,
            body        TEXT,
            char_len    INTEGER,
            ok          BOOLEAN,
            channel     TEXT DEFAULT 'telegram'
        )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tg_outbox_type_time ON telegram_outbox(report_type, sent_at DESC)")
    _ensured = True


def capture(message: str, ok: bool = True, channel: str = "telegram") -> str | None:
    """Store a recognized report in telegram_outbox. Returns the report_type stored, or None if skipped.

    Best-effort: any failure (DB down, classify miss) is swallowed so it can never break a send.
    """
    conn = None
    try:
        rtype = classify_report(message)
        if not rtype:
            return None
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        _ensure_table(cur)
        cur.execute(
            "INSERT INTO telegram_outbox (report_type, title, body, char_len, ok, channel) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (rtype, _title(message), message, len(message), bool(ok), channel),
        )
        conn.commit()
        return rtype
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return None
