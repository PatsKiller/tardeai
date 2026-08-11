#!/usr/bin/env python3
"""Send / print the Advisory Desk Telegram brief (≤5 body lines).

Does not replace existing alerts — additive section only.
Uses send_telegram → all TELEGRAM_CHAT_ID recipients (comma-separated).

Usage:
  .venv/bin/python scripts/advisory_telegram_brief.py --print
  .venv/bin/python scripts/advisory_telegram_brief.py --send
  .venv/bin/python scripts/advisory_telegram_brief.py --send --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print", action="store_true", help="Print brief to stdout")
    ap.add_argument("--send", action="store_true", help="Send via telegram_alert")
    ap.add_argument("--dry-run", action="store_true", help="With --send, do not actually send")
    args = ap.parse_args()
    if not args.print and not args.send:
        args.print = True

    from api_v3_advisory import get_advisory_brief

    brief = get_advisory_brief(max_items=3)
    text = brief.get("text") or ""
    # Enforce body ≤5 lines (header + ≤5)
    parts = text.split("\n")
    if len(parts) > 6:
        text = "\n".join(parts[:6])
        brief["trimmed"] = True
    brief["body_line_count"] = max(0, len(text.split("\n")) - 1)

    if args.print or args.dry_run:
        print(text)
        print(f"\n[meta] body_lines={brief.get('body_line_count')} ok={brief.get('ok')}")

    if args.send and not args.dry_run:
        from telegram_alert import send_telegram
        # Additive advisory section — bypass router so it is not classified as a
        # competing P1 that could suppress other producers; still uses same transport.
        ok = send_telegram(text, bypass_router=True)
        print(f"send_ok={ok}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
