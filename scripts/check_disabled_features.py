#!/usr/bin/env python3
"""Page once a day for every feature that was switched off with a review date that has passed.

Operator 2026-10-31: "there needs to be a reminder to switch it back on. We just don't want to leave it off".
Scans ``config/`` for ``disabled_until`` blocks (scripts/lib/disabled_features.py). Overdue or malformed blocks send
one P2 per feature per day through ``telegram_alert.send_telegram``; ``--dry-run`` (the default) prints and sends
nothing. Exit 0 = nothing overdue, 3 = finding(s) (scripts/lib/monitor_exit_codes.py convention), 1 = crash.

Under TRADE_AI_CI / PYTEST_CURRENT_TEST / TRADEAI_TEST_HARNESS the real sender is refused even with ``--apply``
(2026-10-31 incident: a reviewer harness paged the operator for real).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import disabled_features as df  # noqa: E402

PRODUCER = "check_disabled_features"
HARNESS_ENV = ("TRADE_AI_CI", "PYTEST_CURRENT_TEST", "TRADEAI_TEST_HARNESS")


def _harness() -> bool:
    return any(os.environ.get(k) for k in HARNESS_ENV)


def message_for(e: dict, today: date | None = None) -> str:
    """The body carries today's date, so the daily page is not swallowed by the body-hash dedupe (review #2399 F9)."""
    day = (today or date.today()).isoformat()
    if e.get("error"):
        due = e.get("review_by") or "no valid date"
        return f"⚠️ *Disabled feature unreadable* ({day}): {e['name']} ({e['file']}), due {due}"
    return (
        f"⏰ *Disabled feature overdue* ({day}): {e['name']}\n"
        f"Off since {e.get('disabled_at')}, review was due {e.get('review_by')} (owner {e.get('owner')}).\n"
        f"Why off: {e.get('reason')}\nTo re-enable: {e.get('reenable_plan')}"
    )


def deliver(message: str, sender=None) -> bool:
    if sender is None:
        if _harness():
            print("[disabled-features] test harness detected — real send refused", file=sys.stderr)
            return False
        from scripts import telegram_alert as ta  # type: ignore

        sender = ta.send_telegram
    return bool(sender(message, priority="P2", dedupe_minutes=1380, producer=PRODUCER, message_class="report"))


def run(*, apply: bool, config_dir: Path = df.CONFIG_DIR, today: date | None = None, sender=None) -> int:
    entries = df.scan(config_dir, today=today)
    due = [e for e in entries if e.get("overdue") or e.get("error")]
    for e in entries:
        err = "  ERROR " + e["error"] if e.get("error") else ""
        print(f"[disabled-features] {df.note(e, e['name'])}{err}")
    if not due:
        print(f"[disabled-features] {len(entries)} disabled feature(s), none overdue")
        return 0
    for e in due:
        msg = message_for(e, today)
        if apply:
            sent = deliver(msg, sender=sender)
            print(f"[disabled-features] P2 {'sent' if sent else 'NOT sent'}: {e['name']}")
        else:
            print(f"[disabled-features] DRY RUN — would send P2: {e['name']}")
    return 3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    a = ap.parse_args(argv)
    return run(apply=bool(a.apply) and not a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
