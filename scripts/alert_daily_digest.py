#!/usr/bin/env python3
"""Reports Desk v1 (WS-D): deterministic daily Alert Digest.

Summarizes material NEW / ONGOING / RECOVERED / SUPPRESSED findings rather
than celebrating thousands of repetitive events. Raw audit stays in Command
Center. Cron: 17:55 weekdays.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def _build_message() -> str | None:
    from db_adapter import _execute as ex
    try:
        from alert_condition_state import today_metrics, unresolved_conditions
        metrics = today_metrics()
    except Exception:
        metrics = {"new": 0, "ongoing": 0, "recovered": 0, "suppressed": 0, "unresolved": 0}

    sev = ex("""SELECT coalesce(severity,'info') s, count(*) n FROM alert_events
                WHERE created_at::date = CURRENT_DATE GROUP BY 1 ORDER BY 2 DESC""", fetch="all") or []
    types = ex("""SELECT coalesce(alert_type,'?') t, count(*) n FROM alert_events
                  WHERE created_at::date = CURRENT_DATE GROUP BY 1 ORDER BY 2 DESC LIMIT 8""", fetch="all") or []
    unacked = ex("""SELECT count(*) n FROM alert_events
                    WHERE created_at::date = CURRENT_DATE AND severity IN ('critical','urgent')
                      AND acknowledged_at IS NULL""", fetch="one") or {}
    watch = ex("""SELECT count(*) n FROM alert_events
                  WHERE created_at::date = CURRENT_DATE AND alert_type='watch_alert'""", fetch="one") or {}
    total = sum(r["n"] for r in sev)

    new_n = int(metrics.get("new") or 0)
    ongoing_n = int(metrics.get("unresolved") or 0)
    recovered_n = int(metrics.get("recovered") or 0)
    suppressed_n = int(metrics.get("suppressed") or 0)
    # Fall back to raw counts if the state store is empty (first day after deploy).
    if new_n + ongoing_n + recovered_n + suppressed_n == 0 and total:
        new_n = total

    if total == 0 and new_n == 0 and recovered_n == 0:
        return None

    lines = [
        "🗞 Alert Digest",
        f"NEW {new_n:,}  ONGOING {ongoing_n:,}  RECOVERED {recovered_n:,}  SUPPRESSED {suppressed_n:,}",
    ]
    if total:
        lines.append(f"raw events today: {total:,}  (" +
                     " · ".join(f"{r['s']} {r['n']:,}" for r in sev) + ")")
    if types:
        lines.append("top classes: " + " · ".join(f"{r['t']} {r['n']:,}" for r in types[:5]))
    try:
        unresolved = unresolved_conditions()
        if unresolved:
            top_keys = {}
            for c in unresolved:
                fam = (c.get("key") or "?").split(":")[0]
                top_keys[fam] = top_keys.get(fam, 0) + 1
            fams = ", ".join(f"{k} {v}" for k, v in sorted(top_keys.items(), key=lambda kv: -kv[1])[:6])
            lines.append(f"unresolved families: {fams}")
    except Exception:
        pass
    if (watch.get("n") or 0) > 0:
        lines.append(f"🔔 watch alerts fired: {watch['n']}")
    if (unacked.get("n") or 0) > 0:
        lines.append(f"⚠ unacked critical/urgent: {unacked['n']} — review Command Center → alerts")
    lines.append("raw audit: Command Center /v3/")
    return "\n".join(lines)


def main() -> int:
    msg = _build_message()
    if not msg:
        print("[alert-digest] zero alerts today — nothing to send")
        return 0
    try:
        from telegram_alert import send_telegram
        send_telegram(msg, bypass_router=True)  # operator-specced daily ops digest
        print("[alert-digest] sent:\n" + msg)
    except Exception as e:
        print(f"[alert-digest] telegram failed: {e}\n{msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
