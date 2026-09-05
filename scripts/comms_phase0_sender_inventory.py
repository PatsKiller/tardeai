#!/usr/bin/env python3
"""Build Phase 0 communications sender inventory with dispositions.

Scans scripts/apps/tests for provider send patterns, merges chokepoint baseline
bypasses, and emits docs/audit/_evidence/sender_inventory.json.

Every retained row gets exactly one disposition:
  MIGRATE | REMOVE | DISABLE | EXEMPT_WITH_EXPIRY

Usage:
  python3 scripts/comms_phase0_sender_inventory.py
  python3 scripts/comms_phase0_sender_inventory.py --root /path/to/CURRENT
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SEND_PATTERNS = {
    "send_telegram": re.compile(r"\bsend_telegram\b"),
    "publish_event": re.compile(r"\bpublish_event\b"),
    "publish_legacy_message": re.compile(r"\bpublish_legacy_message\b"),
    "publish_operator_message": re.compile(r"\bpublish_operator_message\b"),
    "send_cio_message": re.compile(r"\bsend_cio_message\b"),
    "send_email": re.compile(r"\bsend_email\b"),
    "send_slack": re.compile(r"\bsend_slack\b"),
    "send_whatsapp": re.compile(r"\bsend_whatsapp\b"),
    "api.telegram.org": re.compile(r"api\.telegram\.org"),
    "smtplib": re.compile(r"\bsmtplib\b"),
    "SLACK_WEBHOOK": re.compile(r"SLACK_WEBHOOK"),
    "twilio": re.compile(r"\btwilio\b", re.I),
}

APPROVED_ADAPTERS = {
    "scripts/telegram_transport.py",
    "scripts/telegram_alert.py",
    "scripts/alert_outbox.py",
    "scripts/lib/cio_telegram_transport.py",
    "scripts/lib/autonomy_watchdog/telegram_system.py",
    "scripts/lib/cio_notification_delivery.py",
}
APPROVED_INBOUND = {
    "scripts/telegram_callback_handler.py",
    "scripts/telegram_reply_processor.py",
    "scripts/telegram_command_handler.py",
    "scripts/run_telegram_callback_poller.py",
    "scripts/discover_telegram_chat_id.py",
    "scripts/cio_telegram_bot.py",
}
APPROVED_TOOLING = {
    "scripts/audit_direct_telegram_senders.py",
    "scripts/check_telegram_chokepoint.py",
    "scripts/secret_validators.py",
    "scripts/secrets/rotation_probes.py",
    "scripts/comms_phase0_attest.py",
    "scripts/comms_phase0_sender_inventory.py",
}


def _scan(root: Path) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for folder in ("scripts", "apps", "tests"):
        base = root / folder
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in {".py", ".sh", ".ts", ".tsx", ".js", ".mjs"}:
                continue
            rel = p.relative_to(root).as_posix()
            if "/node_modules/" in rel or "/dist/" in rel:
                continue
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            kinds = [k for k, rx in SEND_PATTERNS.items() if rx.search(text)]
            if kinds:
                hits[rel] = kinds
    return hits


def _cron_scripts(crontab_text: str) -> set[str]:
    found: set[str] = set()
    for line in crontab_text.splitlines():
        if line.strip().startswith("#"):
            continue
        for m in re.finditer(r"(scripts/[\w./-]+\.py)", line):
            found.add(m.group(1))
    return found


def classify(rel: str, kinds: set[str], baseline_n: int | None, approved: bool) -> tuple[str, str, str | None, str]:
    if rel.startswith("tests/"):
        return (
            "EXEMPT_WITH_EXPIRY",
            "comms-gateway",
            "2026-12-31",
            "Test/tooling mention of provider patterns; must not gain real send capability.",
        )
    if rel in APPROVED_ADAPTERS:
        return (
            "EXEMPT_WITH_EXPIRY",
            "comms-gateway",
            "2026-12-31",
            "Approved outbound adapter/chokepoint until CommunicationEvent transport supersedes.",
        )
    if rel in APPROVED_INBOUND:
        return (
            "EXEMPT_WITH_EXPIRY",
            "comms-gateway",
            "2026-12-31",
            "Approved inbound handler/poller; Phase 1 must mint CommunicationEvent on intake.",
        )
    if rel in APPROVED_TOOLING or approved and "check_telegram" in rel:
        return (
            "EXEMPT_WITH_EXPIRY",
            "comms-gateway",
            "2026-12-31",
            "Approved audit/tooling scanner.",
        )
    if baseline_n:
        return (
            "MIGRATE",
            "TBD",
            None,
            "Chokepoint baseline bypass — direct Bot API or credential selection outside approved transport.",
        )
    if "send_email" in kinds or "smtplib" in kinds:
        return ("MIGRATE", "TBD", None, "Email sender — route through gateway email adapter.")
    if "send_slack" in kinds or "SLACK_WEBHOOK" in kinds:
        return ("MIGRATE", "TBD", None, "Slack sender — gateway-mediate; currently not production-activated.")
    if "send_whatsapp" in kinds or "twilio" in kinds:
        return ("MIGRATE", "TBD", None, "WhatsApp/Twilio sender — gateway-mediate after channel choice.")
    if kinds & {"send_cio_message", "publish_event", "publish_legacy_message", "publish_operator_message", "send_telegram"}:
        return (
            "MIGRATE",
            "TBD",
            None,
            "Uses wrapper/outbox today; must mint universal CommunicationEvent and eliminate dual-path.",
        )
    return ("MIGRATE", "TBD", None, "Matched provider-related patterns.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    root = args.root or Path(__file__).resolve().parent.parent
    out_dir = args.out or (root / "docs" / "audit" / "_evidence")
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_path = root / "config" / "telegram_chokepoint_baseline.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.is_file() else {"files": {}, "_approved_boundaries": []}
    bypass = baseline.get("files", {})
    approved_set = set(baseline.get("_approved_boundaries", []))

    hits = _scan(root)
    cron_text = ""
    cron_file = out_dir / "crontab_full.txt"
    if cron_file.is_file():
        cron_text = cron_file.read_text(errors="replace")
    cron_scripts = _cron_scripts(cron_text)

    send_keys = set(SEND_PATTERNS)
    final = []
    excluded = 0
    all_paths = sorted(set(bypass) | set(hits) | approved_set)
    for rel in all_paths:
        kinds = set(hits.get(rel, []))
        is_senderish = bool(kinds & send_keys) or rel in bypass
        if not is_senderish:
            excluded += 1
            continue
        disp, owner, expiry, notes = classify(rel, kinds, bypass.get(rel), rel in approved_set)
        final.append(
            {
                "path": rel,
                "disposition": disp,
                "owner": owner,
                "expiry": expiry,
                "chokepoint_baseline_violations": bypass.get(rel),
                "approved_boundary": rel in approved_set,
                "in_crontab": rel in cron_scripts,
                "patterns": sorted(kinds),
                "notes": notes,
            }
        )

    migrate = [x for x in final if x["disposition"] == "MIGRATE"]

    def risk(x: dict) -> tuple:
        return (
            0 if x.get("chokepoint_baseline_violations") else 1,
            0 if x.get("in_crontab") else 1,
            -(x.get("chokepoint_baseline_violations") or 0),
            x["path"],
        )

    migrate_sorted = sorted(migrate, key=risk)
    source_commit = ""
    sc = root / "SOURCE_COMMIT"
    if sc.is_file():
        source_commit = sc.read_text().strip()

    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "attested_SOURCE_COMMIT": source_commit,
        "root": str(root),
        "disposition_enum": ["MIGRATE", "REMOVE", "DISABLE", "EXEMPT_WITH_EXPIRY"],
        "counts": {
            "senders_classified": len(final),
            "excluded_non_senders": excluded,
            "by_disposition": dict(Counter(x["disposition"] for x in final)),
            "migrate_with_baseline_bypass": sum(1 for x in migrate if x.get("chokepoint_baseline_violations")),
            "owners_tbd": sum(1 for x in final if x.get("owner") == "TBD"),
            "unclassified": 0,
        },
        "senders": sorted(final, key=lambda x: (x["disposition"], x["path"])),
        "migrate_risk_order": [x["path"] for x in migrate_sorted],
        "notes": [
            "Approved adapters/inbound/tooling mapped to EXEMPT_WITH_EXPIRY with expiry 2026-12-31.",
            "Owners marked TBD must be assigned before Phase 0 operator sign-off.",
            "REMOVE/DISABLE require observation evidence; none auto-assigned by this scanner.",
        ],
    }
    (out_dir / "sender_inventory.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
