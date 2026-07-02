#!/usr/bin/env python3
"""stop_over_consensus_monitor.py — Alert when a live protective stop sits ABOVE Street consensus mean.

A stop above the analyst mean target means a triggered exit would realize below where sell-side
consensus sees fair value — often a trailing stop ratcheted too tight or a mis-set fixed floor.

  python3 scripts/stop_over_consensus_monitor.py           # dry-run
  python3 scripts/stop_over_consensus_monitor.py --send    # SIEM + Telegram
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

DEDUP_HOURS = 12


def _recently_alerted(cur, sym: str) -> bool:
    try:
        cur.execute(
            """SELECT 1 FROM alert_events
               WHERE symbol=%s AND source_script='stop_over_consensus_monitor'
                 AND parsed_payload->>'kind' = 'stop_over_consensus'
                 AND created_at > now() - %s * interval '1 hour'
               LIMIT 1""",
            (sym, DEDUP_HOURS),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def run(send: bool = False) -> dict:
    from db_adapter import _get_conn
    from stop_consensus_check import detect_conflicts

    conn = _get_conn()
    cur = conn.cursor()
    conflicts = detect_conflicts(cur, project_root=PROJECT_ROOT)
    scanned = sum(1 for _ in conflicts)  # conflicts only; evaluated count filled below
    try:
        from stop_consensus_check import load_consensus_targets, load_live_stops_by_symbol

        consensus = load_consensus_targets(project_root=PROJECT_ROOT, cur=cur)
        live = load_live_stops_by_symbol(cur, project_root=PROJECT_ROOT)
        holds = json.loads((PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        held = {
            str(h.get("symbol") or "").upper()
            for h in holds.get("holdings") or []
            if h.get("symbol") and not h.get("is_cash")
        }
        scanned = sum(1 for sym in held if sym in live and sym in consensus)
    except Exception:
        scanned = len(conflicts)
    emitted, sent = [], 0

    for c in conflicts:
        sym = c["symbol"]
        if _recently_alerted(cur, sym):
            continue
        msg = (
            f"⚠ Stop over consensus: {sym} stop ${c['stop_price']} is "
            f"{c['consensus_gap_pct']}% above Street mean ${c['consensus_target_mean']} "
            f"({c.get('consensus_analysts')} analysts) — review trailing width / ratchet "
            f"(advisory; never auto-modifies stops)."
        )
        try:
            from alert_event_writer import save_alert_event

            save_alert_event(
                alert_type="strategic_alert",
                severity="warning",
                source_script="stop_over_consensus_monitor",
                symbol=sym,
                raw_text=msg,
                parsed_payload={"kind": "stop_over_consensus", **c},
            )
        except Exception:
            pass
        if send:
            try:
                from telegram_alert import send_telegram

                send_telegram(msg)
                sent += 1
            except Exception:
                pass
        emitted.append(c)

    conn.close()
    return {
        "ok": True,
        "checked": scanned,
        "alerted": len(emitted),
        "telegram_sent": sent if send else 0,
        "conflicts": emitted,
        "dry_run": not send,
        "note": "advisory only — never places/modifies a stop",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(send=args.send), indent=2, default=str))


if __name__ == "__main__":
    main()