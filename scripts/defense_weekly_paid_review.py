#!/usr/bin/env python3
"""Weekly paid oversight (v8.5) — Friday post-build Claude-seat review of the
week-final desk state. Config-gated (oversight_paid.weekly_paid_review) and
budget-gated at send like every paid call. Telegram OPERATIONAL one-liner."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    cfg = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())["oversight_paid"]
    if not cfg.get("weekly_paid_review"):
        print("[weekly-paid] config OFF — skipping")
        return 0
    from db_adapter import _get_conn
    import defense_oversight as do
    conn = _get_conn()
    res = do.run_paid_review(conn.cursor(), seats=["paid"])
    conn.commit()
    print(f"[weekly-paid] {res}")
    try:
        from telegram_alert import send_telegram
        r = (res.get("results") or {}).get("paid", {})
        send_telegram(f"[OPERATIONAL] Weekly paid oversight ({r.get('model')}): {r.get('status')} "
                      f"· ${res.get('spent_usd', 0)} — memo on the Defense page", bypass_router=True)
    except Exception as e:
        print(f"[weekly-paid] telegram failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
