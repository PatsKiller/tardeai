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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Trade AI autonomy watchdog")
    p.add_argument("--once", action="store_true", default=True, help="run one cycle (default)")
    p.add_argument("--dry-run", action="store_true", help="classify and print; no persist, no Telegram")
    p.add_argument("--no-telegram", action="store_true", help="persist receipt but do not send Telegram")
    p.add_argument("--telegram-canary", action="store_true", help="explicit operator SYSTEM test send")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
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
