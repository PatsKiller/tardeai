#!/usr/bin/env python3
"""Static ratchet for non-Telegram provider egress (Slack, SMTP, Twilio, Meta WA).

Mirrors scripts/check_telegram_chokepoint.py:
  - behaviour patterns, not one spelling
  - narrow APPROVED allowlists per channel
  - baseline ratchet: may shrink, never grow; NEW files fail immediately

    scripts/check_provider_chokepoint.py
    scripts/check_provider_chokepoint.py --report
    scripts/check_provider_chokepoint.py --update-baseline
    scripts/check_provider_chokepoint.py --channel slack
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "config" / "provider_chokepoint_baseline.json"
SCAN_DIRS = ("scripts", "apps", "tests")
SCAN_SUFFIXES = {".py", ".sh", ".ts", ".tsx", ".js", ".mjs"}

# Approved adapters only. Producers must not speak these providers directly.
APPROVED = {
    "slack": {
        "scripts/alerting.py",  # send_slack webhook adapter (source-built)
    },
    "smtp": {
        "scripts/alerting.py",  # smtplib send_email
    },
    "twilio": {
        "scripts/alerting.py",  # Twilio WhatsApp legacy adapter
    },
    "meta_whatsapp": {
        "scripts/lib/cio_whatsapp_egress.py",
        "scripts/lib/cio_whatsapp_ingress.py",
        "scripts/cio_whatsapp_webhook.py",
    },
}

# Tooling that must mention provider tokens in prose / scanners.
APPROVED_TOOLING = {
    "scripts/check_provider_chokepoint.py",
    "scripts/check_comms_gateway_enforcement.py",
    "scripts/check_telegram_chokepoint.py",
    "scripts/check_secret_exposure.sh",
    "scripts/comms_phase0_sender_inventory.py",
    "scripts/comms_phase0_attest.py",
    "tests/test_provider_chokepoint_ratchet.py",
    "tests/test_comms_gateway_enforcement.py",
    "tests/test_comms_communication_event.py",
    "tests/test_communications_portal.py",
    "tests/test_comms_channel_adapters.py",
    "tests/test_comms_shadow_compare.py",
    "tests/test_cio_whatsapp_p4.py",
    "tests/test_active_trader_session_control.py",
    "tests/test_cio_cc_record_narrative_slice_c.py",
    "tests/conftest.py",
}

CHANNEL_PATTERNS: dict[str, dict[str, re.Pattern[str]]] = {
    "slack": {
        "slack_webhook_env": re.compile(
            r"""(?:getenv|environ(?:\.get)?)\(\s*['"]SLACK_WEBHOOK"""
        ),
        "slack_webhook_url": re.compile(r"SLACK_WEBHOOK_URL|hooks\.slack\.com"),
        "slack_web_api": re.compile(r"slack\.com/api/|WebClient\(|slack_sdk"),
    },
    "smtp": {
        "smtplib_import": re.compile(r"\bsmtplib\b"),
        "smtp_connect": re.compile(r"\bsmtplib\.SMTP\b|\bSMTP\s*\("),
        "smtp_env_creds": re.compile(
            r"""(?:getenv|environ(?:\.get)?)\(\s*['"]SMTP_(?:HOST|USERNAME|PASSWORD)"""
        ),
    },
    "twilio": {
        "twilio_import": re.compile(r"from\s+twilio\b|import\s+twilio\b|twilio\.rest"),
        "twilio_env": re.compile(
            r"""(?:getenv|environ(?:\.get)?)\(\s*['"]TWILIO_"""
        ),
        "twilio_whatsapp_from": re.compile(r"TWILIO_WHATSAPP_|whatsapp:\+"),
    },
    "meta_whatsapp": {
        "graph_facebook": re.compile(r"graph\.facebook\.com"),
        "meta_wa_env": re.compile(
            r"""(?:getenv|environ(?:\.get)?)\(\s*['"](?:CIO_WHATSAPP_|WHATSAPP_|META_WA_)"""
        ),
        "messaging_product_whatsapp": re.compile(
            r"messaging_product['\"]\s*:\s*['\"]whatsapp['\"]"
        ),
    },
}


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def scan_file(path: Path, channel: str) -> dict[str, int]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    hits: dict[str, int] = {}
    for name, rx in CHANNEL_PATTERNS[channel].items():
        n = len(rx.findall(text))
        if n:
            hits[name] = n
    return hits


def scan_channel(channel: str) -> dict[str, dict]:
    approved = set(APPROVED.get(channel, set())) | APPROVED_TOOLING
    found: dict[str, dict] = {}
    for folder in SCAN_DIRS:
        base = ROOT / folder
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_dir() or p.suffix not in SCAN_SUFFIXES:
                continue
            rel = _rel(p)
            if "/node_modules/" in rel or "/dist/" in rel or "/dist.old-" in rel:
                continue
            if rel in approved:
                continue
            hits = scan_file(p, channel)
            if hits:
                found[rel] = hits
    return found


def _violation_count(hits: dict) -> int:
    return sum(v for v in hits.values() if isinstance(v, int))


def _load_baseline() -> dict:
    if not BASELINE.is_file():
        return {"channels": {}}
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--channel",
        choices=sorted(CHANNEL_PATTERNS.keys()) + ["all"],
        default="all",
    )
    a = ap.parse_args()

    channels = sorted(CHANNEL_PATTERNS.keys()) if a.channel == "all" else [a.channel]
    scanned: dict[str, dict[str, dict]] = {ch: scan_channel(ch) for ch in channels}

    if a.update_baseline:
        # Preserve channels not rescanned when --channel is narrow.
        existing = _load_baseline()
        files_by_channel = dict(existing.get("channels") or {})
        for ch, found in scanned.items():
            files_by_channel[ch] = {
                k: _violation_count(v) for k, v in sorted(found.items())
            }
        payload = {
            "_note": (
                "Known non-Telegram provider egress bypasses. Ratchet only — "
                "may shrink, never grow. Approved adapters live in check_provider_chokepoint.APPROVED."
            ),
            "_approved": {ch: sorted(APPROVED[ch]) for ch in sorted(APPROVED)},
            "_approved_tooling": sorted(APPROVED_TOOLING),
            "channels": files_by_channel,
        }
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        total_files = sum(len(v) for v in files_by_channel.values())
        total_viol = sum(sum(v.values()) for v in files_by_channel.values())
        print(f"[provider-chokepoint] baseline updated: {total_files} files, {total_viol} violations")
        return 0

    if a.json:
        print(json.dumps({"channels": scanned}, indent=2, default=str))
        return 0

    # Report
    for ch, found in scanned.items():
        totals: dict[str, int] = {}
        for hits in found.values():
            for k, v in hits.items():
                totals[k] = totals.get(k, 0) + v
        print(f"[provider-chokepoint:{ch}] producers outside approved adapter: {len(found)}")
        for k in sorted(totals):
            print(f"    {k:28s} {totals[k]}")
        if found:
            worst = sorted(found.items(), key=lambda kv: -_violation_count(kv[1]))[:8]
            print("  top offenders:")
            for rel, hits in worst:
                print(f"    {rel}  ({_violation_count(hits)})")

    if not BASELINE.is_file():
        print(
            f"[provider-chokepoint] FAIL: no baseline at {BASELINE}. "
            f"Run --update-baseline once to record current debt.",
            file=sys.stderr,
        )
        return 1

    base = _load_baseline().get("channels", {})
    failures: list[str] = []
    remaining = 0
    for ch, found in scanned.items():
        ch_base = base.get(ch, {})
        for rel, hits in sorted(found.items()):
            n = _violation_count(hits)
            remaining += n
            allowed = int(ch_base.get(rel, 0))
            if rel not in ch_base:
                failures.append(
                    f"NEW {ch} bypass in {rel} ({n}) — route via approved adapter / gateway"
                )
            elif n > allowed:
                failures.append(f"{ch}:{rel} grew {allowed} -> {n}")

    if failures:
        print("\n[provider-chokepoint] FAIL", file=sys.stderr)
        for f in failures:
            print("   " + f, file=sys.stderr)
        return 1

    if remaining:
        print(
            f"[provider-chokepoint] pass (ratchet): outstanding pattern hits={remaining} "
            f"— NOT zero, tracked as a release blocker"
        )
    else:
        print("[provider-chokepoint] pass: zero non-approved provider egress patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
