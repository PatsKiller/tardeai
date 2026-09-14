#!/usr/bin/env python3
"""Daily, weekly and monthly AI and search spend, texted to the operator. Dry run by default.

    python scripts/llm_spend_report.py --period daily            # yesterday, printed
    python scripts/llm_spend_report.py --period weekly --send    # last Mon–Sun, sent
    python scripts/llm_spend_report.py --period monthly --send   # last calendar month, sent

WHY
---
Operator, 2026-09-14: "make sure that I am texted via Telegram daily on what the daily spend has been,
weekly on what the weekly has been, and monthly on what the monthly has been", with the breakdown of
what ran peak and off-peak ("anything that's on a schedule should be off peak").

WHAT
----
One HTML message per period, built from `lib/llm_spend.build_report`. It carries:
- real dollars and tokens;
- what the cap ledger counted, and the daily cap;
- the peak and off-peak split;
- by provider and top processes (scheduled or ad hoc);
- scheduled work that ran on peak;
- Brave requests;
- a link to the Command Center Consumption page.

Each period is sent once, keyed by its start date in the ledger. The router is bypassed so the report
is not digested.

READ_ONLY_ADVISORY. Reads spend; sends a notification; changes nothing.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import llm_spend  # noqa: E402

AUTHORITY = "READ_ONLY_ADVISORY"
PERIOD_OF = {"daily": "yesterday", "weekly": "last_week", "monthly": "last_month"}
LEDGER = PROJECT_ROOT / "data" / "runtime" / "llm_spend_report_sent.json"
RECEIPT = PROJECT_ROOT / "data" / "runtime" / "llm_spend_report_last_{cadence}.json"
NO_CONSUMER_REASON = "scheduled operator report; Telegram is its consumer, the receipt its output"


def money(v: float) -> str:
    v = float(v or 0)
    return f"${v:,.2f}" if v >= 1 else f"${v:.4f}".rstrip("0").rstrip(".") if v else "$0"


def tokens(n: int) -> str:
    n = int(n or 0)
    return f"{n / 1_000_000:.2f}M" if n >= 1_000_000 else f"{n / 1_000:.1f}k" if n >= 1_000 else str(n)


def pct(part: float, whole: float) -> str:
    return f"{(100.0 * part / whole):.0f}%" if whole else "—"


def cc_link() -> str:
    try:
        from lib.comms_editor import cc_base  # noqa: PLC0415
        return f"{cc_base()}/v3/consumption"
    except Exception:  # noqa: BLE001
        return ""


def format_report(r: dict, *, cadence: str, mtd: dict | None = None) -> str:
    """HTML for Telegram. Pure."""
    e = html.escape
    t = r["totals"]
    usd = t["usd"]
    cap = r.get("global_cap_usd_per_day")
    title = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}[cadence]
    lines = [
        f"💵 <b>{title} AI &amp; search spend — {e(r['label'])}</b>",
        f"Real spend <b>{money(usd)}</b> ({money(t['usd_per_day'])}/day) · counted by caps {money(r['counted_by_caps_usd'])}"
        + (f" · cap {money(cap)}/day" if cap else ""),
        f"{t['calls']:,} calls ({t['paid_calls']:,} paid, {t['failures']:,} failed) · tokens {tokens(t['tokens_in'])} in / {tokens(t['tokens_out'])} out",
        f"🌙 Off-peak <b>{money(t['usd_offpeak'])}</b> ({pct(t['usd_offpeak'], usd)}) · {t['calls_offpeak']:,} calls"
        f"  ·  ☀️ Peak <b>{money(t['usd_peak'])}</b> ({pct(t['usd_peak'], usd)}) · {t['calls_peak']:,} calls",
    ]
    if mtd:
        lines.append(f"Month to date: <b>{money(mtd['totals']['usd'])}</b> ({money(mtd['totals']['usd_per_day'])}/day)")
    lines.append("")
    lines.append("<b>By provider</b>")
    for p in r["by_provider"][:5]:
        lines.append(f"• {e(p['provider'])}: {money(p['usd'])} · {int(p['calls']):,} calls · {tokens(p['tokens_in'] + p['tokens_out'])} tokens")
    lines.append("")
    lines.append("<b>Top processes</b>")
    for p in [x for x in r["by_process"] if x["usd"] > 0][:6]:
        kind = "🗓 scheduled" if p["kind"] == "scheduled" else "👤 ad hoc"
        peak = f" · ☀️ {p['calls_peak']:,} on peak" if p["calls_peak"] else ""
        lines.append(f"• {e(p['process_name'])} — {kind} · {money(p['usd'])} · {p['calls']:,} calls{peak}")
    if r["scheduled_on_peak"]:
        lines.append("")
        worst = ", ".join(f"{e(x['process_name'])} ({x['calls_peak']:,} calls, {money(x['usd_peak'])})"
                          for x in r["scheduled_on_peak"][:4])
        lines.append(f"⚠️ <b>Scheduled work ran on peak</b>: {worst}")
    brave = r.get("brave") or {}
    if brave.get("requests") is not None:
        lines.append(f"🔎 Brave Search: {int(brave['requests']):,} requests (paid plan, per-request price not configured)")
    link = cc_link()
    if link:
        lines.append("")
        lines.append(f'<a href="{e(link, quote=True)}">Open spend in Command Center</a>')
    lines.append(f"<i>{AUTHORITY} · real = provider tokens × price schedule; peak = DeepSeek official peak hours (Mon–Fri)</i>")
    return "\n".join(lines)


def _load_ledger() -> dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=sorted(PERIOD_OF), required=True)
    ap.add_argument("--send", action="store_true", help="send to Telegram (default: dry run)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = llm_spend.build_report(PERIOD_OF[args.period])
    mtd = llm_spend.build_report("month") if args.period == "daily" else None
    text = format_report(report, cadence=args.period, mtd=mtd)
    key = f"{args.period}:{report['start_utc'][:10]}"
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    print(text)
    if not args.send:
        print(f"\n(dry run — not sent; ledger key {key})")
        return 0
    ledger = _load_ledger()
    if key in ledger:
        print(f"already sent {key} at {ledger[key]}")
        return 0
    from telegram_alert import send_telegram  # noqa: PLC0415

    ok = bool(send_telegram(text, bypass_router=True, message_class="operator_alert"))
    if ok:
        ledger[key] = datetime.now(timezone.utc).isoformat()
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    receipt = Path(str(RECEIPT).format(cadence=args.period))
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"schema": "LlmSpendReportRun@v1", "ran_at": datetime.now(timezone.utc).isoformat(),
                                   "cadence": args.period, "key": key, "sent": ok, "usd": report["totals"]["usd"],
                                   "authority": AUTHORITY}, indent=2), encoding="utf-8")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
