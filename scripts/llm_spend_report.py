#!/usr/bin/env python3
"""Daily, weekly and monthly AI and search spend, texted to the operator. Dry run by default.

    python scripts/llm_spend_report.py --period daily            # yesterday, printed
    python scripts/llm_spend_report.py --period weekly --send    # last Mon–Sun, sent
    python scripts/llm_spend_report.py --period monthly --send   # last calendar month, sent
    python scripts/llm_spend_report.py --period auto --dry-run   # every period due today (ET), nothing written
    python scripts/llm_spend_report.py --period auto --prepare   # build + write the message artifact, NO send

n8n refactor (2026-10-10, wave 1): ``--dry-run`` computes the report(s) and prints what a send or a
prepare WOULD do, and returns before any ledger, receipt, artifact or send is reachable (AGENTS.md §6).
``--prepare`` is the preparer half of the preparer/sender split: it writes
``data/runtime/llm_spend_report_prepared_<period>.json`` (the message) and the lane receipt
``data/runtime/llm_spend_report_prepare_last.json`` (``ok_at``), and never sends — the send stays the
host chokepoint (``--send``, unchanged apart from ``ok_at`` on its receipt). ``--period auto`` = daily,
plus weekly on Monday and monthly on the 1st (America/New_York). Ledger and receipts resolve under the
persistent-state root, not the release directory.

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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import llm_spend  # noqa: E402


def _runtime_dir() -> Path:
    """data/runtime under the persistent-state root (a release's data/runtime is a symlink to it)."""
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env) / "data" / "runtime"
    from lib.lane_registry import state_root  # noqa: PLC0415

    return state_root() / "data" / "runtime"


AUTHORITY = "READ_ONLY_ADVISORY"
PERIOD_OF = {"daily": "yesterday", "weekly": "last_week", "monthly": "last_month"}
PERIOD_CHOICES = sorted([*PERIOD_OF, "auto"])
LEDGER = _runtime_dir() / "llm_spend_report_sent.json"
RECEIPT = _runtime_dir() / "llm_spend_report_last_{cadence}.json"
PREPARED = _runtime_dir() / "llm_spend_report_prepared_{cadence}.json"
PREPARE_LANE = "llm_spend_report_prepare"
PREPARE_RECEIPT = _runtime_dir() / f"{PREPARE_LANE}_last.json"
ET = ZoneInfo("America/New_York")
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
    outside = r.get("scheduled_outside_window") or []
    if outside:
        # Operator rule 2026-09-14: scheduled work runs weekdays 9 a.m.-9 p.m. ET or weekends.
        names = ", ".join(f"{e(x['process_name'])} ({x['calls']:,} calls, {money(x['usd'])})" for x in outside[:4])
        lines.append(f"🕘 <b>Scheduled work outside 9 a.m.–9 p.m. ET weekdays</b>: {names}")
    bal = r.get("deepseek_balance")
    if bal:
        gap = bal["deducted_usd"] - bal.get("logged_usd", 0.0)
        span = f"{bal['from'][5:16].replace('T', ' ')}→{bal['to'][5:16].replace('T', ' ')} UTC"
        lines.append(f"🏦 DeepSeek balance: {money(bal['deducted_usd'])} deducted vs {money(bal.get('logged_usd', 0.0))} logged"
                     f" ({'+' if gap >= 0 else '−'}{money(abs(gap))}) · {span}"
                     + (f" · topped up {money(bal['topped_up_usd'])}" if bal.get("topped_up_usd") else "")
                     + f" · balance {money(bal['balance_usd'])}" + (" · partial window" if bal.get("partial") else ""))
    brave = r.get("brave") or {}
    if brave.get("requests") is not None:
        lines.append(f"🔎 Brave Search: {int(brave['requests']):,} requests (paid plan, per-request price not configured)")
    link = cc_link()
    if link:
        lines.append("")
        lines.append(f'<a href="{e(link, quote=True)}">Open spend in Command Center</a>')
    lines.append(f"<i>{AUTHORITY} · real = provider tokens × price schedule; peak = DeepSeek official peak hours (Mon–Fri); window = weekdays 9 a.m.–9 p.m. ET + weekends</i>")
    return "\n".join(lines)


def _load_ledger() -> dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def due_periods(now: datetime | None = None) -> list[str]:
    """``--period auto``: daily every day, weekly on Monday, monthly on the 1st (America/New_York).

    The same days the three crontab lines (5 7 * * * / 10 7 * * 1 / 15 7 1 * *) fire on.
    """
    local = (now or datetime.now(timezone.utc)).astimezone(ET)
    out = ["daily"]
    if local.weekday() == 0:
        out.append("weekly")
    if local.day == 1:
        out.append("monthly")
    return out


def build(period: str) -> tuple[dict, str, str]:
    """(report, text, ledger key) for one period. Read-only: SELECTs on the spend tables only."""
    report = llm_spend.build_report(PERIOD_OF[period])
    mtd = llm_spend.build_report("month") if period == "daily" else None
    text = format_report(report, cadence=period, mtd=mtd)
    return report, text, f"{period}:{report['start_utc'][:10]}"


def dry_run(period: str, report: dict, text: str, key: str) -> int:
    """What a send / prepare WOULD do. Writes nothing, sends nothing (the caller continues right after)."""
    sent_at = _load_ledger().get(key)
    plan = {
        "mode": "dry_run",
        "period": period,
        "ledger_key": key,
        "already_sent_at": sent_at,
        "would_send": sent_at is None,
        "would_write_prepared": str(PREPARED).format(cadence=period),
        "would_write_receipt": str(RECEIPT).format(cadence=period),
        "message_chars": len(text),
        "usd": report["totals"]["usd"],
    }
    print(f"\n(dry run — nothing written, nothing sent) {json.dumps(plan, default=str)}")
    return 0


def prepare(period: str, report: dict, text: str, key: str) -> dict:
    """Preparer half of the split: the message artifact the host sender delivers. No send."""
    from lib.atomic_json_store import atomic_write_json  # noqa: PLC0415

    sent_at = _load_ledger().get(key)
    path = Path(str(PREPARED).format(cadence=period))
    atomic_write_json(path, {
        "schema": "LlmSpendReportMessage@v1", "built_at": datetime.now(timezone.utc).isoformat(),
        "cadence": period, "key": key, "already_sent_at": sent_at, "text": text,
        "usd": report["totals"]["usd"], "authority": AUTHORITY,
    })
    print(f"prepared {key} -> {path} (already_sent_at={sent_at})")
    return {"period": period, "key": key, "path": str(path), "already_sent_at": sent_at}


def send(period: str, report: dict, text: str, key: str) -> int:
    """The host sender (unchanged): once per ledger key, then the per-cadence receipt (now with ok_at)."""
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
    receipt = Path(str(RECEIPT).format(cadence=period))
    receipt.parent.mkdir(parents=True, exist_ok=True)
    ran_at = datetime.now(timezone.utc).isoformat()
    try:
        prev_ok = json.loads(receipt.read_text(encoding="utf-8")).get("ok_at")
    except (OSError, ValueError, AttributeError):
        prev_ok = None
    receipt.write_text(json.dumps({"schema": "LlmSpendReportRun@v1", "ran_at": ran_at,
                                   "cadence": period, "key": key, "sent": ok, "usd": report["totals"]["usd"],
                                   "ok_at": ran_at if ok else prev_ok,
                                   "authority": AUTHORITY}, indent=2), encoding="utf-8")
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=PERIOD_CHOICES, required=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true", help="send to Telegram (default: print only)")
    mode.add_argument("--prepare", action="store_true", help="write the message artifact + lane receipt; never send")
    mode.add_argument("--dry-run", action="store_true", help="compute and report what would happen; write and send nothing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    periods = due_periods() if args.period == "auto" else [args.period]
    started = datetime.now(timezone.utc).isoformat()
    codes: list[int] = []
    prepared: list[dict] = []
    for period in periods:
        report, text, key = build(period)
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        print(text)
        if args.dry_run:
            codes.append(dry_run(period, report, text, key))
            continue  # AGENTS.md §6: prepare/send/receipt below are not reachable from a dry run
        if args.prepare:
            prepared.append(prepare(period, report, text, key))
            codes.append(0)
            continue
        if not args.send:
            print(f"\n(dry run — not sent; ledger key {key})")
            codes.append(0)
            continue
        codes.append(send(period, report, text, key))
    code = max(codes) if codes else 0
    if args.prepare:
        from lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415

        write_lane_receipt(PREPARE_LANE, ok=code == 0, exit_code=code, started_at=started,
                           summary={"periods": periods, "prepared": prepared}, path=PREPARE_RECEIPT)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
