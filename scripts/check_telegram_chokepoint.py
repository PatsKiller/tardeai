#!/usr/bin/env python3
"""Static enforcement of the single Telegram delivery chokepoint.

The previous guard matched only the literal `api.telegram.org/bot.../sendMessage`.
A producer could satisfy it by writing

    __import__("telegram_transport").TELEGRAM_SEND_MESSAGE_API.format(token=tok)

and still call requests.post itself, still read the bot token, still pick the chat
id — bypassing routing policy entirely while looking centralized. Thirty-nine
producers did exactly that. A guard that a bypass can walk through is worse than no
guard, because it certifies a false negative.

This checker looks for the BEHAVIOUR, not one spelling:

  transport_import      importing telegram_transport (static or __import__)
  endpoint_constant     referencing TELEGRAM_SEND_MESSAGE_API
  raw_endpoint          building api.telegram.org/bot... for any method
  http_to_telegram      requests/httpx/urllib/curl/wget aimed at Telegram
  chat_id_selection     producer choosing TELEGRAM_CHAT_ID itself
  token_for_delivery    reading TELEGRAM_BOT_TOKEN to send

Approved boundaries are explicit and narrow (see APPROVED). Everything else must go
through publish_event() or the send_telegram() compatibility chokepoint.

Because 39 real bypasses exist today, this runs as a RATCHET against a recorded
baseline — the same convention scripts/check_design_tokens.sh uses. A new bypass in
a new file fails immediately; an existing file may never grow. It never reports zero
unless the baseline is genuinely empty.

    scripts/check_telegram_chokepoint.py            # enforce
    scripts/check_telegram_chokepoint.py --report   # human summary
    scripts/check_telegram_chokepoint.py --update-baseline
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "config" / "telegram_chokepoint_baseline.json"
SCAN_DIRS = ("scripts", "apps", "tests")
SCAN_SUFFIXES = {".py", ".sh", ".ts", ".tsx", ".js", ".mjs"}

# Only these may speak the Bot API. Outbound and inbound are separated on purpose.
APPROVED_OUTBOUND = {
    "scripts/telegram_transport.py",
    # CIO-only wrapper — never reads general bot; calls telegram_transport.send_message.
    "scripts/lib/cio_telegram_transport.py",
    # SYSTEM ops family (heartbeat/canary). Distinct from CIO financial notifications.
    # CI/pytest locked; tests patch _http_post. Not a CIO alert producer.
    "scripts/lib/autonomy_watchdog/telegram_system.py",
}
APPROVED_DELIVERY = {"scripts/alert_outbox.py", "scripts/telegram_alert.py"}
# Inbound polling/command handling is a different concern from outbound delivery;
# it is allowed to talk to getUpdates/answerCallbackQuery but not to send alerts.
APPROVED_INBOUND = {
    "scripts/telegram_callback_handler.py",
    "scripts/telegram_reply_processor.py",
    "scripts/telegram_command_handler.py",
    "scripts/run_telegram_callback_poller.py",
    "scripts/discover_telegram_chat_id.py",
    # CIO dedicated long-poll worker — getUpdates only in this file; outbound
    # replies go through scripts.lib.cio_telegram_converse / cio_telegram_transport.
    "scripts/cio_telegram_bot.py",
}
# Tooling that inspects senders rather than sending, plus the tests that DESCRIBE the
# forbidden patterns in prose. A test documenting "do not write api.telegram.org/..."
# necessarily contains that string; scanning it as a producer is a false positive.
# These are allowed to mention the patterns, never to call them — which the chokepoint
# tests themselves assert.
APPROVED_TOOLING = {
    "scripts/audit_direct_telegram_senders.py",
    "scripts/check_telegram_chokepoint.py",
    "scripts/secret_validators.py",
    "scripts/secrets/rotation_probes.py",
    "tests/test_telegram_notification_normalization.py",
    "tests/test_alert_normalization_blockers.py",
    # Tests that describe/block Bot API patterns; they must mention the tokens.
    "tests/conftest.py",
    "tests/test_cio_phase1_notification_containment.py",
    "tests/test_telegram_p0_card_gate.py",
    # 2026-08-31: tests that ASSERT the interdict and the ratchet. A test proving
    # deliver_text is interdictable must name deliver_text, a token and a chat id;
    # a test proving the ratchet can go red must plant the pattern it detects.
    # Named individually, following this file's own convention -- never a blanket
    # tests/ exclusion, which would let a real producer hide in a test path.
    "tests/test_notification_integrity_waves_cdeg.py",
    "tests/test_telegram_chokepoint_ratchet.py",
    # 2026-08-31 (C1): the alarm-firing capture self-test imports telegram_transport
    # in order to make the real send_message RAISE if it is ever reached, proving the
    # harness sends nothing. It is the strongest possible non-caller: the import
    # exists to forbid the call. Named individually, per this file's convention.
    "tests/test_alarm_capture_selftest.py",
}
APPROVED = APPROVED_OUTBOUND | APPROVED_DELIVERY | APPROVED_INBOUND | APPROVED_TOOLING

BOT_METHODS = ("sendMessage", "sendDocument", "sendPhoto", "getUpdates", "getMe",
               "answerCallbackQuery", "editMessageText", "setWebhook", "deleteWebhook")

# Names on telegram_transport that do NOT send. Importing one of these is not a
# bypass -- it is the migration this repo asked for.
#
# escape_markdown's own docstring says it was "placed on the transport so every
# producer already importing it can reach it, rather than adding a 127th
# convention". But `transport_import` matched ANY `from telegram_transport import
# ...`, so adopting the shared escaper tripped this guard. The rule penalised the
# exact migration it exists to encourage, and the first producer to adopt it (the
# P1 digest sender) was flagged as a new bypass for importing a string function.
#
# Sending capability is what matters: send_message, deliver_text, _http_post and
# the endpoint constants stay flagged.
TRANSPORT_NON_SENDING = {
    "escape_markdown", "smart_split", "MAX_MSG_LEN",
}


def _transport_import_is_sending(text: str) -> bool:
    """True when a file imports something from telegram_transport that can SEND.

    Parsed, not pattern-matched: the regex could not see WHICH names were imported,
    so it had to treat every import as a bypass.
    """
    import ast as _ast
    try:
        tree = _ast.parse(text)
    except SyntaxError:
        return True          # unparseable: fail closed, keep the old verdict
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom) and node.module == "telegram_transport":
            for alias in node.names:
                if alias.name == "*" or alias.name not in TRANSPORT_NON_SENDING:
                    return True
        elif isinstance(node, _ast.Import):
            for alias in node.names:
                if alias.name == "telegram_transport":
                    return True   # whole-module import exposes the senders
    return False


PATTERNS: dict[str, re.Pattern] = {
    "transport_import": re.compile(
        r"""(?:^\s*(?:from\s+telegram_transport\s+import|import\s+telegram_transport)\b)"""
        r"""|__import__\(\s*["']telegram_transport["']\s*\)""", re.M),
    "endpoint_constant": re.compile(r"\bTELEGRAM_SEND_MESSAGE_API\b"),
    "raw_endpoint": re.compile(r"api\.telegram\.org/bot"),
    "http_to_telegram": re.compile(
        r"(?:requests\.(?:post|get)|httpx\.(?:post|get)|urllib\.request\.(?:urlopen|Request)"
        r"|curl\s|wget\s)[^\n]{0,200}?(?:api\.telegram\.org|TELEGRAM_SEND_MESSAGE_API"
        r"|telegram_transport)"),
    "chat_id_selection": re.compile(
        r"""(?:getenv|environ(?:\.get)?)\(\s*["'](?:TELEGRAM_CHAT_ID|TRADEAI_\w*CHAT_ID)["']"""),
    "token_for_delivery": re.compile(
        r"""(?:getenv|environ(?:\.get)?)\(\s*["']TELEGRAM_BOT_TOKEN["']"""),
}


def scan_file(path: Path) -> dict[str, int]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    hits: dict[str, int] = {}
    for name, rx in PATTERNS.items():
        n = len(rx.findall(text))
        if n and name == "transport_import" and not _transport_import_is_sending(text):
            # Importing only non-sending helpers (escape_markdown, smart_split,
            # MAX_MSG_LEN) is not a bypass. See TRANSPORT_NON_SENDING.
            continue
        if n:
            hits[name] = n
    if "raw_endpoint" in hits:
        methods = sorted({m for m in BOT_METHODS if re.search(rf"/{m}\b", text)})
        if methods:
            hits["_methods"] = methods            # type: ignore[assignment]
    return hits


def scan() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for folder in SCAN_DIRS:
        base = ROOT / folder
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_dir() or p.suffix not in SCAN_SUFFIXES:
                continue
            rel = p.relative_to(ROOT).as_posix()
            if "/node_modules/" in rel or "/dist/" in rel or "/dist.old-" in rel:
                continue
            if rel in APPROVED:
                continue
            hits = scan_file(p)
            if hits:
                found[rel] = hits
    return found


def _violation_count(hits: dict) -> int:
    return sum(v for k, v in hits.items() if not k.startswith("_") and isinstance(v, int))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    found = scan()
    totals: dict[str, int] = {}
    for hits in found.values():
        for k, v in hits.items():
            if not k.startswith("_") and isinstance(v, int):
                totals[k] = totals.get(k, 0) + v

    if a.update_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(
            {"_note": "Known Telegram chokepoint bypasses. Ratchet only — may shrink, never grow.",
             "_approved_boundaries": sorted(APPROVED),
             "files": {k: _violation_count(v) for k, v in sorted(found.items())}},
            indent=2) + "\n", encoding="utf-8")
        print(f"[telegram-chokepoint] baseline updated: {len(found)} files, "
              f"{sum(_violation_count(v) for v in found.values())} violations")
        return 0

    if a.json:
        print(json.dumps({"files": found, "totals": totals}, indent=2, default=str))
        return 0

    if a.report or True:
        print(f"[telegram-chokepoint] producers bypassing the chokepoint: {len(found)}")
        for k in sorted(totals):
            print(f"    {k:22s} {totals[k]}")
        if found:
            worst = sorted(found.items(), key=lambda kv: -_violation_count(kv[1]))[:8]
            print("  top offenders:")
            for rel, hits in worst:
                m = hits.get("_methods")
                extra = f"  methods={','.join(m)}" if m else ""
                print(f"    {rel}  ({_violation_count(hits)}){extra}")

    if not BASELINE.is_file():
        print(f"[telegram-chokepoint] FAIL: no baseline at {BASELINE}. "
              f"Run --update-baseline once to record current debt.", file=sys.stderr)
        return 1

    base = json.loads(BASELINE.read_text()).get("files", {})
    failures: list[str] = []
    for rel, hits in sorted(found.items()):
        n = _violation_count(hits)
        allowed = int(base.get(rel, 0))
        if rel not in base:
            failures.append(f"NEW bypass in {rel} ({n}) — route via publish_event()/send_telegram()")
        elif n > allowed:
            failures.append(f"{rel} grew {allowed} -> {n}")
    if failures:
        print("\n[telegram-chokepoint] FAIL", file=sys.stderr)
        for f in failures:
            print("   " + f, file=sys.stderr)
        return 1

    remaining = sum(_violation_count(v) for v in found.values())
    if remaining:
        print(f"[telegram-chokepoint] pass (ratchet): {len(found)} known files, "
              f"{remaining} violations — NOT zero, tracked as a release blocker")
    else:
        print("[telegram-chokepoint] pass: zero bypasses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
