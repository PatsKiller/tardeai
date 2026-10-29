#!/usr/bin/env python3
"""Daily 08:00 ET incident one-liner to Telegram (dry run by default).

  incident_daily_brief.py [--apply]

One line: unresolved counts by status, the oldest unresolved incident and its age, and incidents fixed in the last
24 h, plus the Command Center link. Sent through the chokepoint (scripts/telegram_alert.send_telegram, P2). The text
carries the date so the comms-editor fingerprint never folds one day's brief into the next.
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts.lib import incidents as L  # noqa: E402

URL = "https://ms01-openclaw.tail163d14.ts.net/v3/ops/incidents"


def brief_line(recs: dict, now=None) -> str:
    now = now or L.utcnow()
    s = L.summarize(recs, now)
    c = s["counts"]
    day = now - timedelta(hours=24)
    fixed24 = sum(1 for r in recs.values() if r["status"] == "fixed" and (L.parse_ts(r.get("closed_at")) or now) >= day)
    try:
        from zoneinfo import ZoneInfo
        label = now.astimezone(ZoneInfo("America/New_York")).strftime("%a %b %d")
    except Exception:  # noqa: BLE001
        label = now.strftime("%a %b %d")
    oldest = ""
    if s["oldest_unresolved_id"]:
        r = recs[s["oldest_unresolved_id"]]
        age = s["oldest_unresolved_age_min"] or 0
        oldest = f" · oldest {r['id']} {age // 60}h{age % 60:02d}m: {r['title'][:70]}"
    return (f"Incidents {label}: {c['open']} open, {c['fixing']} fixing, {c['blocked']} blocked; "
            f"{fixed24} fixed in 24h{oldest} — {URL}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    line = brief_line(L.load_records())
    print(line)
    if a.apply:
        from scripts.telegram_alert import send_telegram
        ok = send_telegram(line, priority="P2", producer="incident_daily_brief")
        print(f"accepted={bool(ok)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
