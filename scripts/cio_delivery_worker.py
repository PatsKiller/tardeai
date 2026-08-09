#!/usr/bin/env python3
"""cio_delivery_worker.py — Poll and deliver CIO notifications from the outbox.

Runs as a bounded one-shot. Claims pending notifications from the outbox,
delivers them via the configured adapter, and confirms delivery.

Shadow mode (default): FakeDeliveryAdapter — logs, doesn't send.
Live mode: RealTelegramAdapter — sends via Telegram bot.

Usage:
  python3 scripts/cio_delivery_worker.py --once [--mode shadow|live]

Cron (every 5 min):
  */5 * * * * cd $PROJ && $PY scripts/cio_delivery_worker.py --once >> logs/cio_delivery.log 2>&1
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def main() -> int:
    parser = argparse.ArgumentParser(description="CIO Notification Delivery Worker")
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--mode", choices=("shadow", "live"), default="shadow")
    parser.add_argument("--max-deliveries", type=int, default=5)
    args = parser.parse_args()

    from lib.cio_notification_outbox import NotificationOutbox
    from lib.cio_notification_delivery import CIONotificationDeliveryWorker

    outbox = NotificationOutbox()
    worker = CIONotificationDeliveryWorker(notification_outbox=outbox, mode=args.mode)

    print(f"CIO Delivery Worker — mode={args.mode} max={args.max_deliveries}")
    delivered = 0

    try:
        notification = worker.poll_and_deliver()
        while notification and delivered < args.max_deliveries:
            delivered += 1
            nid = notification.get("notification_id", "?") if isinstance(notification, dict) else "?"
            print(f"  delivered: {nid}")
            notification = worker.poll_and_deliver()
    except Exception as e:
        print(f"  delivery error: {type(e).__name__}: {e}")
        return 1

    print(f"  summary: {delivered} delivered, mode={args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
