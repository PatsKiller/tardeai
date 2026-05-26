# Source Export: scripts/telegram_reply_processor.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/telegram_reply_processor.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `d5f8c6a1063594e125d2e6dd6fdbbe8823b5529089e61936210f6b5e0cbe2ecb` |
| **File Size** | 8562 bytes |

## Full Source

```py
"""
telegram_reply_processor.py — Poll Telegram for user replies to stop-confirmation reminders.

Maps conversational replies like:
  "yes JEPI" → confirmed
  "no JEPI" → not_yet
  "intentional JEPI" → intentional_no_stop
  "rec JEPI" → needs_recommendation
  "yes" (no symbol) → applied to most recent unconfirmed reminder

Run after sending stop reminders, or on a short polling interval.
"""
from __future__ import annotations
import json
import os
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

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

TELEGRAM_API = "https://api.telegram.org/bot{token}"
OFFSET_FILE = PROJECT_ROOT / "data" / "portfolios" / "state" / ".telegram_offset"

# Reply patterns — case-insensitive
PATTERNS = [
    (re.compile(r"^(?:yes|confirmed?|stop placed)\b\s*(\w*)", re.I), "confirmed"),
    (re.compile(r"^(?:no|not yet|nope)\b\s*(\w*)", re.I), "not_yet"),
    (re.compile(r"^(?:intentional|no stop needed|exempt)\b\s*(\w*)", re.I), "intentional_no_stop"),
    (re.compile(r"^(?:rec|recommend|need rec|help)\b\s*(\w*)", re.I), "needs_recommendation"),
]


def _token():
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _chat_ids():
    raw = os.getenv("TELEGRAM_CHAT_ID", "")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _get_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text().strip())
    except Exception:
        return 0


def _save_offset(offset: int):
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset))


def poll_updates() -> list[dict]:
    """Fetch new Telegram messages and callback queries since last offset."""
    token = _token()
    if not token:
        return []
    offset = _get_offset()
    try:
        resp = requests.get(
            f"{TELEGRAM_API.format(token=token)}/getUpdates",
            params={"offset": offset, "timeout": 5, "limit": 20,
                    "allowed_updates": json.dumps(["message", "callback_query"])},
            timeout=15,
        )
        data = resp.json()
        if not data.get("ok"):
            return []
        results = data.get("result", [])
        if results:
            _save_offset(results[-1]["update_id"] + 1)
        return results
    except Exception as e:
        print(f"  [telegram_reply] getUpdates failed: {e}")
        return []


def parse_reply(text: str) -> tuple[str | None, str | None]:
    """Parse a message into (response_type, symbol_or_none)."""
    text = text.strip()
    for pattern, response_type in PATTERNS:
        m = pattern.match(text)
        if m:
            sym = m.group(1).upper() if m.group(1) else None
            return response_type, sym if sym else None
    return None, None


def _db_query(sql, params=None, fetch="all"):
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        return None
    return _execute(sql, params, fetch=fetch)


def _db_write(sql, params=None):
    from db_adapter import _get_conn
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    conn.commit()


def process_replies():
    """Poll Telegram, parse replies + callback queries, update stop_confirmations."""
    updates = poll_updates()
    if not updates:
        print("  [telegram_reply] No new messages")
        return 0

    allowed_chats = set(_chat_ids())
    processed = 0

    for update in updates:
        # Handle callback queries (inline button presses)
        if "callback_query" in update:
            try:
                from telegram_callback_handler import handle_callback_query
                handle_callback_query(update["callback_query"])
                processed += 1
            except Exception as e:
                print(f"  [telegram_reply] callback_query error: {e}")
            continue

        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")

        # Only process from authorized chats
        if chat_id not in allowed_chats:
            continue

        response_type, symbol = parse_reply(text)
        if not response_type:
            continue

        # If no symbol specified, find the most recent unconfirmed item
        if not symbol:
            row = _db_query(
                "SELECT id, symbol FROM stop_confirmations WHERE stop_status = 'unconfirmed' ORDER BY market_value DESC LIMIT 1",
                fetch="one"
            )
            if row:
                symbol = row["symbol"]
                conf_id = row["id"]
            else:
                print(f"  [telegram_reply] Got '{response_type}' but no unconfirmed items found")
                continue
        else:
            row = _db_query(
                "SELECT id, symbol FROM stop_confirmations WHERE symbol = %s AND stop_status IN ('unconfirmed', 'pending_response')",
                (symbol,), fetch="one"
            )
            if not row:
                print(f"  [telegram_reply] Got '{response_type} {symbol}' but no matching unconfirmed item")
                continue
            conf_id = row["id"]

        # Map to DB status
        status_map = {
            "confirmed": "confirmed",
            "not_yet": "unconfirmed",
            "intentional_no_stop": "intentional_no_stop",
            "needs_recommendation": "needs_recommendation",
        }

        _db_write(
            """UPDATE stop_confirmations SET
                      stop_status = %s, stop_confirmed = %s, stop_confirmed_at = %s,
                      stop_confirmation_source = 'telegram', stop_exception_reason = %s,
                      updated_at = NOW()
               WHERE id = %s""",
            (status_map[response_type],
             response_type == "confirmed",
             datetime.now() if response_type == "confirmed" else None,
             f"Via Telegram: {text[:100]}",
             conf_id)
        )

        # Log to notification_log for traceability
        try:
            from db_adapter import save_notification_log_entry
            save_notification_log_entry({
                "notification_date": date.today(),
                "notification_type": "stop_reply_processed",
                "channel": "telegram",
                "subject": f"[Stop Reply] {response_type} — {symbol}",
                "body_summary": f"User replied '{text[:50]}' → {response_type} for {symbol}",
                "recommendation_ids": None, "escalation_ids": None, "observation_ids": None,
                "payload": json.dumps({"symbol": symbol, "response": response_type, "text": text[:100]}),
                "status": "sent", "dedupe_key": f"stop_reply_{symbol}_{date.today()}_{response_type}",
                "sent_at": datetime.now(), "error": None,
            })
        except Exception:
            pass

        # Send ack with actionable context
        try:
            from telegram_alert import send_telegram
            ack_map = {
                "confirmed": f"\u2705 Stop confirmed for *{symbol}*. Status updated. Check /v2/risk for full view.",
                "not_yet": f"\u26a0 Noted — *{symbol}* stop not yet placed. Will remind again tomorrow. Set stop in broker when ready.",
                "intentional_no_stop": f"\U0001f6e1 *{symbol}* marked intentionally unprotected. Won't remind again unless you ask.",
                "needs_recommendation": f"\U0001f4cb Noted — Aegis will generate stop recommendation for *{symbol}*. Check /v2/risk after next run.",
            }
            send_telegram(ack_map.get(response_type, f"Processed: {response_type} {symbol}"))
        except Exception:
            pass

        processed += 1
        print(f"  [telegram_reply] {response_type} {symbol} → updated conf_id={conf_id}")

    return processed


def main():
    print(f"[telegram_reply_processor] Polling — {datetime.now().isoformat()}")
    count = process_replies()
    print(f"  Processed: {count} replies")
    return count


if __name__ == "__main__":
    main()
```
