# Source Export: scripts/discover_telegram_chat_id.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/discover_telegram_chat_id.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `68695a23c76c1f6cafcf54a0b33c10d06531bc14cdefbf9eeb72475b0d310164` |
| **File Size** | 3747 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""discover_telegram_chat_id.py — Discover Telegram chat IDs from recent bot updates.

Never prints bot token. Redacts chat IDs unless --show-full-id is passed.

Usage:
    .venv/bin/python scripts/discover_telegram_chat_id.py --verbose
    .venv/bin/python scripts/discover_telegram_chat_id.py --show-full-id  # local only, do not commit output
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description="Discover Telegram chat IDs (token never printed)")
    p.add_argument("--show-full-id", action="store_true", help="Show full chat ID (do not commit output)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    # Load token from .env without printing
    token = ""
    for line in (PROJ / ".env").read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not found in .env")
        sys.exit(1)

    import requests
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
        data = resp.json()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not data.get("ok"):
        print(f"Telegram API error: {data.get('description', 'unknown')}")
        print("Tip: Send a message in the dedicated channel/group, then rerun this script.")
        sys.exit(1)

    results = data.get("result", [])
    if not results:
        print("No recent updates found.")
        print("Tip: Send a message like 'ALERT-3C setup' in the dedicated proposal channel, then rerun.")
        sys.exit(0)

    chats = {}
    for update in results:
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat", {})
        cid = chat.get("id")
        if not cid:
            continue
        chats[cid] = {
            "chat_id_full": str(cid) if args.show_full_id else None,
            "chat_id_redacted": f"***{str(cid)[-4:]}",
            "title": chat.get("title", chat.get("first_name", "?")),
            "type": chat.get("type", "?"),
            "thread_id": msg.get("message_thread_id"),
            "text_snippet": (msg.get("text") or "")[:60],
            "date": msg.get("date"),
        }

    chat_list = sorted(chats.values(), key=lambda c: c.get("date") or 0, reverse=True)

    if args.verbose:
        print(f"Found {len(chat_list)} unique chats:")
        for c in chat_list:
            cid_display = c["chat_id_full"] if args.show_full_id else c["chat_id_redacted"]
            thread = f" thread={c['thread_id']}" if c.get("thread_id") else ""
            print(f"  {cid_display} | {c['type']:10s} | {c['title']}{thread} | {c['text_snippet']}")

    # For committed output, always redact
    committed = [
        {k: v for k, v in c.items() if k != "chat_id_full"}
        for c in chat_list
    ]

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(committed, indent=2, default=str))
    if args.output_md:
        md = ["# Telegram Chat Discovery (Redacted)\n",
              "| Chat ID | Type | Title | Thread | Snippet |",
              "|---------|------|-------|--------|---------|"]
        for c in committed:
            md.append(f"| {c['chat_id_redacted']} | {c['type']} | {c['title']} | {c.get('thread_id') or '-'} | {c['text_snippet'][:40]} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
