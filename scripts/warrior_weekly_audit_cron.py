#!/usr/bin/env python3
"""P6 — Weekly Ross vs TradeAI audit (Mon AM Telegram + JSON for Command Center).

  python3 scripts/warrior_weekly_audit_cron.py
  python3 scripts/warrior_weekly_audit_cron.py --days 14 --no-telegram
"""
from __future__ import annotations

import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (the bare scheduled run (sends unless --no-telegram)). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "run-warrior-weekly-audit"
    _dr_would = (
        "build the Ross-vs-TradeAI audit for the last --days, write the Command Center JSON (and --csv) and, "
        "unless --no-telegram, send the summary through send_telegram"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="audit_day"))
    raise SystemExit(0)

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="Lookback window")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    until = date.today()
    since = until - timedelta(days=max(1, args.days))

    from warrior_tradeai_audit import audit, write_csv
    from lib.warrior_audit_summary import format_telegram, format_panel

    rows, summary = audit(since, until)
    summary["generated_at"] = datetime.now().isoformat(timespec="seconds")
    csv_path = Path(args.csv or PROJECT_ROOT / "data" / "audit" / f"warrior_weekly_{until.isoformat()}.csv")
    write_csv(csv_path, rows)
    summary["csv_path"] = str(csv_path.relative_to(PROJECT_ROOT))

    out_dir = PROJECT_ROOT / "data" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    latest_json = out_dir / "warrior_weekly_latest.json"
    panel = format_panel(summary)
    latest_json.write_text(json.dumps(panel, indent=2))

    print(json.dumps(summary, indent=2))
    print(f"Wrote {len(rows)} rows → {csv_path}")
    print(f"Panel → {latest_json}")

    if not args.no_telegram:
        try:
            from telegram_alert import send_telegram
            msg = format_telegram(summary, label=f"{args.days}d")
            if send_telegram(msg, priority="P2", producer="warrior_weekly_audit_cron"):
                print("  [warrior-audit] Telegram sent")
            else:
                print("  [warrior-audit] Telegram skipped (router/disabled)")
        except Exception as exc:
            print(f"  [warrior-audit] Telegram error: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())