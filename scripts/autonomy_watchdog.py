#!/usr/bin/env python3
"""Canonical autonomous intelligence watchdog CLI.

READ_ONLY_ADVISORY. Observe / classify / record / alert. No trades.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.autonomy_watchdog.engine import run_cycle


def would_send_plan(out: dict) -> dict:
    """The Telegram part of a dry-run cycle: one row per message the next run would consider."""
    tg = out.get("telegram") or {}
    rows = [r for r in [tg.get("daily"), *(tg.get("alerts") or [])] if isinstance(r, dict)]
    return {
        "ok": out.get("ok"),
        "error": out.get("error"),
        "overall": (out.get("receipt") or {}).get("overall"),
        "would_send_count": sum(1 for r in rows if r.get("would_send")),
        "messages": [
            {k: r.get(k) for k in ("kind", "identity", "would_send", "reason", "prior_at", "transport_gate", "text")}
            for r in rows
        ],
        "sent": False,
    }


def format_would_send(out: dict) -> str:
    plan = would_send_plan(out)
    if not plan["ok"]:
        return f"watchdog dry run failed: {plan.get('error')}"
    lines = [f"overall={plan['overall']} would_send={plan['would_send_count']} (dry run: nothing sent, nothing recorded)"]
    for m in plan["messages"]:
        verdict = "WOULD SEND" if m["would_send"] else "skip"
        lines.append(f"- [{verdict}] {m['kind']} {m['identity']} reason={m['reason']}")
        if m["would_send"] and m.get("text"):
            lines.extend("    " + ln for ln in str(m["text"]).splitlines())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Trade AI autonomy watchdog")
    p.add_argument("--once", action="store_true", default=True, help="run one cycle (default)")
    p.add_argument("--dry-run", action="store_true", help="classify and print; no persist, no Telegram")
    p.add_argument("--no-telegram", action="store_true", help="persist receipt but do not send Telegram")
    p.add_argument("--telegram-canary", action="store_true", help="explicit operator SYSTEM test send")
    p.add_argument("--what-would-send", action="store_true",
                   help="dry run: print what the next run WOULD send on Telegram; sends and records nothing")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if args.what_would_send:
        out = run_cycle(dry_run=True, send_telegram=False)
        if args.json:
            print(json.dumps(would_send_plan(out), indent=2, default=str))
        else:
            print(format_would_send(out))
        return 0 if out.get("ok") else 1
    out = run_cycle(
        dry_run=args.dry_run,
        send_telegram=not args.no_telegram and not args.dry_run,
        telegram_canary=args.telegram_canary,
    )
    if args.json or args.dry_run:
        print(json.dumps(out, indent=2, default=str))
    else:
        rec = out.get("receipt") or {}
        print(f"ok={out.get('ok')} overall={rec.get('overall')} date={rec.get('date')} sha={str(rec.get('release_sha') or '')[:12]}")
        if out.get("error"):
            print("error", out["error"])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
