# Source Export: scripts/set_telegram_proposal_channel_env.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/set_telegram_proposal_channel_env.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `a8a9e8ec1d4996eba21c8f9b847466a59e8eb9231f4f1ec7a28430a7d4c71c9b` |
| **File Size** | 2820 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""set_telegram_proposal_channel_env.py — Set dedicated proposal alert chat ID in .env.

Default: dry-run. Requires --apply to modify .env.
Never prints full chat ID or token. Backs up .env before modification.

Usage:
    .venv/bin/python scripts/set_telegram_proposal_channel_env.py --chat-id ID --dry-run
    .venv/bin/python scripts/set_telegram_proposal_channel_env.py --chat-id ID --apply
"""
import argparse, shutil, sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
ENV_PATH = PROJ / ".env"
ALLOWED_KEYS = {
    "TRADEAI_ALERT_ROUTING_MODE",
    "TRADEAI_PROPOSAL_ALERT_CHAT_ID",
    "TRADEAI_PROPOSAL_ALERT_THREAD_ID",
}


def _redact(v: str) -> str:
    if not v or len(v) <= 4:
        return "***"
    return f"***{v[-4:]}"


def main():
    p = argparse.ArgumentParser(description="Set dedicated proposal alert channel (default: dry-run)")
    p.add_argument("--chat-id", required=True, help="Dedicated proposal alert chat ID")
    p.add_argument("--thread-id", default="", help="Forum topic/thread ID (optional)")
    p.add_argument("--routing-mode", default="dedicated_proposal_channel",
                   choices=["dedicated_proposal_channel", "forum_topics", "single_channel"])
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if args.apply:
        args.dry_run = False

    updates = {
        "TRADEAI_ALERT_ROUTING_MODE": args.routing_mode,
        "TRADEAI_PROPOSAL_ALERT_CHAT_ID": args.chat_id,
    }
    if args.thread_id:
        updates["TRADEAI_PROPOSAL_ALERT_THREAD_ID"] = args.thread_id

    print(f"{'DRY RUN' if args.dry_run else 'APPLY'}: Setting proposal alert channel")
    for k, v in updates.items():
        print(f"  {k}={_redact(v)}")

    if args.dry_run:
        print("\nDry-run complete. Use --apply to modify .env.")
        return

    # Backup
    backup = ENV_PATH.parent / f".env.alert3c.bak"
    shutil.copy2(ENV_PATH, backup)
    print(f"  Backup: {backup.name}")

    # Read, update, write
    lines = ENV_PATH.read_text().splitlines()
    existing_keys = set()
    new_lines = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            existing_keys.add(key)
        else:
            new_lines.append(line)

    # Append missing keys
    for k, v in updates.items():
        if k not in existing_keys:
            new_lines.append(f"{k}={v}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n")
    print(f"\n.env updated. Keys modified: {list(updates.keys())}")
    print("Do NOT commit .env or .env.alert3c.bak.")


if __name__ == "__main__":
    main()
```
