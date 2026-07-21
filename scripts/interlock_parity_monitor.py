#!/usr/bin/env python3
"""interlock_parity_monitor.py — Telegram if interlock_parity_log has disagreements.

R1 hourly (market-hours) monitor: canonical broker_accounts vs legacy accounts.
Target: 5–7 clean days before R1b (fallback removal).

  .venv/bin/python scripts/interlock_parity_monitor.py
  .venv/bin/python scripts/interlock_parity_monitor.py --hours 24
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("no db")
        return 1
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT count(*) FROM interlock_parity_log
               WHERE agreed = false AND created_at > now() - (%s || ' hours')::interval""",
            (args.hours,),
        )
        n = int(cur.fetchone()[0] or 0)
        cur.execute(
            """SELECT account, canonical_answer, legacy_answer, caller, created_at
               FROM interlock_parity_log
               WHERE agreed = false AND created_at > now() - (%s || ' hours')::interval
               ORDER BY created_at DESC LIMIT 8""",
            (args.hours,),
        )
        rows = cur.fetchall()
    except Exception as e:
        print(f"parity table missing or error: {e}")
        return 1

    msg = (f"interlock parity: {n} disagreement(s) in last {args.hours}h")
    if not args.quiet:
        print(msg)
        for r in rows:
            print(f"  {r[0]} can={r[1]} leg={r[2]} caller={r[3]} @ {r[4]}")

    if n > 0:
        try:
            from telegram_alert import send_telegram
            detail = "\n".join(
                f"• {r[0]}: can={r[1]} leg={r[2]} ({r[3]})" for r in rows[:5]
            )
            send_telegram(
                f"⚠️ Interlock parity drift — {n} disagree last {args.hours}h\n{detail}",
                bypass_router=True,
            )
        except Exception as e:
            print(f"telegram failed: {e}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
