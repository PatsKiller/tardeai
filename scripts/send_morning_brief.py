#!/usr/bin/env python3
"""send_morning_brief.py — Send daily morning brief via Telegram.

Calls /api/v2/morning-brief, formats for Telegram, sends to configured chat IDs.

Usage:
    .venv/bin/python scripts/send_morning_brief.py
    .venv/bin/python scripts/send_morning_brief.py --dry-run
    .venv/bin/python scripts/send_morning_brief.py --chat-id <chat_id>
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("morning_brief")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def fetch_brief():
    """Fetch morning brief from local API."""
    import requests
    try:
        r = requests.get("http://localhost:7777/api/v2/morning-brief", timeout=10)
        r.raise_for_status()
        d = r.json()
        if d.get("ok"):
            return d["data"]
        log.error(f"Brief API returned ok=false: {d}")
        return None
    except Exception as e:
        log.error(f"Brief API failed: {e}")
        return None


def format_telegram(data):
    """Format brief data as compact Telegram message (<1500 chars)."""
    if not data:
        return "Trade AI Morning Brief: API unavailable. Check server."

    hg = data.get("holdings_guard", {})
    pa = data.get("paper_account", {})
    oa = data.get("overnight_activity", {})
    sh = data.get("strategy_health", {})
    ct = data.get("closed_trades_24h", [])
    al = data.get("alerts_24h", {})
    items = data.get("action_items", [])

    lines = []
    lines.append("TRADE AI BRIEF -- " + (data.get("generated_at", "")[:10] or "today"))
    lines.append("")

    # Holdings
    hg_icon = "OK" if hg.get("ok") else "FAIL"
    lines.append(f"Portfolio: {hg_icon} ${hg.get('portfolio_value', 0):,.0f}")

    # Paper
    if pa.get("equity"):
        lines.append(f"Paper: ${pa['equity']:,.0f}, {pa.get('open_positions', 0)} open, heat {pa.get('heat_pct', 0):.1%}")
    else:
        lines.append(f"Paper: {pa.get('open_positions', 0)} open, heat {pa.get('heat_pct', 0):.1%}")

    # Overnight
    lines.append("")
    lines.append(f"OVERNIGHT: {oa.get('proposals_created', 0)} proposals, {oa.get('proposals_approved', 0)} approved, {oa.get('trades_opened', 0)} trades")
    blocks = oa.get("risk_gate_blocks", {})
    if blocks:
        block_str = ", ".join(f"{k}:{v}" for k, v in blocks.items() if v > 0)
        if block_str:
            lines.append(f"  Risk gates: {block_str}")

    # Strategy health
    lines.append("")
    stuck = sh.get("stuck_strategies", [])
    lines.append(f"STRATEGIES: {sh.get('total_active', 0)} active, {sh.get('newly_activated', 0)} newly activated"
                 + (f", {len(stuck)} stuck" if stuck else ""))

    # Closed trades
    if ct:
        lines.append("")
        net = sum(float(t.get("pnl", 0) or 0) for t in ct)
        wins = sum(1 for t in ct if t.get("outcome_verdict") == "WIN")
        losses = sum(1 for t in ct if t.get("outcome_verdict") == "LOSS")
        lines.append(f"CLOSED 24h: {len(ct)} trades ({wins}W/{losses}L), net ${net:+.2f}")
        for t in ct[:3]:
            pnl = float(t.get("pnl", 0) or 0)
            tight = " [stop too tight]" if t.get("stop_too_tight") else ""
            lines.append(f"  {t.get('symbol', '?')}: {t.get('outcome_verdict', '?')} ${pnl:+.2f}{tight}")

    # Alerts
    lines.append("")
    lines.append(f"ALERTS: {al.get('urgent', 0)} urgent, {al.get('digest', 0)} digest")

    # Action items
    if items:
        lines.append("")
        lines.append("ACTION ITEMS:")
        for it in items[:5]:
            sev = "!!" if it.get("severity") == "warning" else "--"
            lines.append(f"  {sev} {it.get('message', '')}")

    lines.append("")
    lines.append("Dashboard: https://ms01-openclaw.tail163d14.ts.net/v3/")

    return "\n".join(lines)


def send_telegram(text, chat_ids=None, dry_run=False):
    """Send text to Telegram via the shared chokepoint (captures to Reports portal)."""
    if dry_run:
        # chat_ids is optional CLI override for logging only — chokepoint owns delivery targets.
        suffix = f" (cli chat_id={chat_ids})" if chat_ids else ""
        log.info(f"DRY RUN — would send via telegram_alert.send_telegram{suffix}:")
        print(text)
        return True

    from telegram_alert import send_telegram as _send
    ok = _send(text, bypass_router=True)
    if ok:
        log.info("Sent")
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="send_morning_brief", subject_key="ops:morning_brief",
                retention_class="operational", severity="info",
                sanitized_body=text[:500], short_summary=text[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    else:
        log.error("Telegram send failed")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Send morning brief via Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Print but don't send")
    parser.add_argument("--chat-id", type=str, default=None, help="Send to specific chat ID only")
    args = parser.parse_args()

    # R18-DATA.1: Trade AI Brief is not a competing CIO product. Fold paper /
    # overnight / strategy facts into the canonical morning renderer.
    if os.getenv("CANONICAL_OPERATOR_BRIEF", "1").strip() != "0":
        try:
            from lib.cio_operator_renderers import deliver_morning
        except ImportError:
            from scripts.lib.cio_operator_renderers import deliver_morning  # type: ignore
        api_brief = fetch_brief() or {}
        supplemental = {
            "paper": api_brief.get("paper_account"),
            "overnight": api_brief.get("overnight_activity"),
            "closed_trades": api_brief.get("closed_trades_24h"),
            "health": api_brief.get("strategy_health"),
        }
        result = deliver_morning(
            root=PROJECT_ROOT,
            supplemental_bundle=supplemental,
            send=not args.dry_run,
        )
        text = result.get("text") or ""
        if args.dry_run:
            print(text)
        log_path = PROJECT_ROOT / "logs" / "morning_brief.log"
        with open(log_path, "a") as f:
            f.write(f"\n{'='*60}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("CANONICAL_MORNING\n")
            f.write(text + "\n")
        sys.exit(0 if result.get("ok") else 1)

    brief = fetch_brief()
    text = format_telegram(brief)

    chat_ids = [args.chat_id] if args.chat_id else None
    ok = send_telegram(text, chat_ids=chat_ids, dry_run=args.dry_run)

    # Log full brief to disk
    log_path = PROJECT_ROOT / "logs" / "morning_brief.log"
    with open(log_path, "a") as f:
        f.write(f"\n{'='*60}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(json.dumps(brief, default=str, indent=2) if brief else "BRIEF FETCH FAILED")
        f.write(f"\n\nTelegram text:\n{text}\n")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
