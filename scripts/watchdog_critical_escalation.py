#!/usr/bin/env python3
"""Prove, and once test, that a cron-watchdog CRIT reaches the operator through the governed critical hub (LQ-20261113-3064).

  --dry-run    (default) A synthetic CRIT report goes through the REAL hub code with FAKE senders, a SYNTHETIC contact
               (example.invalid) and a placeholder chat id set in this process only. Reads the repo's text allowlist
               (config only). Sends nothing, reads no credential, never opens operator_contact.json.
  --live-test  OPERATOR ONLY. One real TEST escalation through the hub's real senders to the operator's real contact.
               Requires --confirm SEND-ONE-TEST-NOW and refuses outside the live release (the hub's own guard).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIRM = "SEND-ONE-TEST-NOW"
PLACEHOLDER_CHAT = "dry-run-placeholder-chat"
SYNTHETIC_REPORT = {
    "status": "CRIT", "observed_at": "2026-11-13T00:00:00Z", "missed_lane_ids": ["synthetic-lane"],
    "monitor_incidents": [{"id": "wrapper_journal_unavailable", "kind": "MONITOR_BLINDNESS"}],
}
SYNTHETIC_CONTACT = {
    "critical_email_to": "operator@example.invalid",
    "critical_sms_email_gateways": [{"address": "0000000000@sms.example.invalid", "label": "dry run", "verified": True}],
}


def dry_run() -> dict:
    from scripts.lib import critical_channels, critical_delivery, critical_texts
    from scripts.lib.watchdog_critical_escalation import escalate

    sent: list[dict] = []
    saved = os.environ.get(critical_delivery.CRITICAL_CHAT_ENV)
    os.environ[critical_delivery.CRITICAL_CHAT_ENV] = PLACEHOLDER_CHAT  # in-process only; the real value is never read
    try:
        result = escalate(
            SYNTHETIC_REPORT, contact=dict(SYNTHETIC_CONTACT), policy=critical_delivery.load_text_allowlist(),
            email_sender=lambda to, subject, body: sent.append({"channel": "email", "to": to, "subject": subject}) or "dry-run-email",
            telegram_sender=lambda chat, text: sent.append({"channel": "telegram_critical", "text": text}) or {"ok": True, "message_id": 1, "status": "DELIVERED"},
            text_sender=lambda event, **k: sent.append({"channel": "text_gateway", "text": event.get("what")}) or {"sent": True},
        )
    finally:
        if saved is None:
            os.environ.pop(critical_delivery.CRITICAL_CHAT_ENV, None)
        else:
            os.environ[critical_delivery.CRITICAL_CHAT_ENV] = saved
    policy = critical_delivery.load_text_allowlist()
    event = result.get("event") or {}
    # The text sender above is fake, so also run the REAL text formatter: a sentence the primitive would refuse shows here.
    preview = critical_texts.format_text(event, max_chars=critical_texts.class_max_chars(policy, event.get("alert_class")))
    channels = sorted(r["channel"] for r in result["receipts"] if r["status"] == "sent")
    return {"mode": "dry_run", "sent_anything_real": False, "alert_class": (result.get("event") or {}).get("alert_class"),
            "would_send_channels": channels, "all_three": channels == sorted(critical_channels.CHANNELS),
            "real_text_format_preview": preview, "fake_sender_calls": sent, "receipts": result["receipts"], "event": result.get("event")}


def live_test() -> dict:
    from scripts.lib.watchdog_critical_escalation import escalate

    result = escalate(SYNTHETIC_REPORT, test=True)  # real senders, real contact; the hub refuses off the live release
    return {"mode": "live_test", **result}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="default: fake senders, synthetic contact, nothing sent")
    p.add_argument("--live-test", action="store_true", help="OPERATOR ONLY: one real test send")
    p.add_argument("--confirm", default="", help=f"must equal {CONFIRM} with --live-test")
    args = p.parse_args(argv)
    if args.live_test and args.dry_run:
        p.error("--live-test and --dry-run are mutually exclusive")
    if args.live_test:
        if args.confirm != CONFIRM:
            print(json.dumps({"mode": "live_test", "status": "REFUSED", "reason": f"--confirm {CONFIRM} required; nothing sent"}))
            return 2
        doc = live_test()
        print(json.dumps(doc, indent=2))
        return 0 if doc.get("delivered") else 1
    doc = dry_run()
    print(json.dumps(doc, indent=2))
    return 0 if doc["all_three"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
