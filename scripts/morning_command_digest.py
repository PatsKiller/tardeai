#!/usr/bin/env python3
"""morning_command_digest.py — Single morning Telegram digest (replaces 09:28 burst).

Collects portfolio intelligence, technical signals, dividends, stop reviews, and draft
alerts into one MORNING COMMAND message. Individual sections are archived to Reports.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SECTION_ORDER = [
    ("portfolio", "Portfolio"),
    ("technical", "Technical Signals"),
    ("dividends", "Dividends"),
    ("stops", "Risk / Stops"),
    ("drafts", "Pending Review"),
    ("hermes", "Hermes Movers"),
    ("health", "System Health"),
]


def append_section(bundle: Dict[str, str], key: str, text: str) -> None:
    """Add or extend a bundle section."""
    t = (text or "").strip()
    if not t:
        return
    if key in bundle:
        bundle[key] = bundle[key].rstrip() + "\n" + t
    else:
        bundle[key] = t


def build_message(bundle: Dict[str, str], date_str: Optional[str] = None) -> str:
    """Assemble the morning command digest body."""
    ds = date_str or datetime.now().strftime("%b %d, %Y")
    lines = [f"☀️ MORNING COMMAND — {ds}", ""]
    for key, label in _SECTION_ORDER:
        body = bundle.get(key, "").strip()
        if not body:
            continue
        lines.append(f"--- {label} ---")
        lines.append(body)
        lines.append("")
    lines.append("Open: Command Center → Reports · Home Action Inbox")
    return "\n".join(lines).strip()


def archive_sections(bundle: Dict[str, str]) -> None:
    """Persist each section to telegram_outbox for Reports portal search."""
    try:
        from report_capture import archive_message
        for key, body in bundle.items():
            if body and body.strip():
                archive_message(body.strip(), suppressed=False)
    except Exception:
        pass


def send_morning_command_bundle(bundle: Dict[str, str], project_root: Path | None = None) -> bool:
    """Send one morning digest; archive sections individually."""
    if not bundle:
        return False
    msg = build_message(bundle)
    if len(msg) < 80:
        return False
    archive_sections(bundle)
    try:
        from telegram_alert import send_telegram
        ok = send_telegram(msg, bypass_router=True)
        if ok:
            print(f"  [morning-command] ✅ Digest sent ({len(bundle)} sections)")
        else:
            print("  [morning-command] Digest not sent (router/disabled)")
        return ok
    except Exception as e:
        print(f"  [morning-command] Send failed: {e}")
        return False


def bundle_enabled(run_type: str = "daily") -> bool:
    """True when morning sections should defer to the bundled digest."""
    return run_type == "daily" and os.getenv("MORNING_COMMAND_BUNDLE", "1").strip() == "1"


def fetch_hermes_movers(limit: int = 3) -> str:
    """Top recent Hermes score spikes from alert_events (for bundle section)."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, raw_text FROM alert_events
            WHERE source_script = 'hermes_score_alerts'
              AND alert_type IN ('hermes_score_move', 'hermes_rank_surge')
              AND created_at > NOW() - INTERVAL '6 hours'
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        if not rows:
            return ""
        return "\n".join(r[1] or f"{r[0]} moved" for r in rows)
    except Exception:
        return ""