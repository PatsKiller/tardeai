#!/usr/bin/env python3
"""Deliver the daily agent brief — what the agent actually did.

    python3 scripts/send_agent_brief.py            # render, print, do not send
    python3 scripts/send_agent_brief.py --send     # deliver on the operator path
    python3 scripts/send_agent_brief.py --json

REPORTING ONLY. Changes no decision, ranking or position. See
scripts/lib/cio_agent_brief.py for why this artifact exists: the system had
completed hundreds of workflows the operator could not see, and a silent system
and a working one looked identical.

Delivery goes through publish_operator_message, so it inherits the content-keyed
dedupe added for the CIO check-in: an unchanged brief does not re-page, and the
window keeps a genuinely unchanged day arriving once rather than never.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

SCHEDULED_ENTRYPOINT = "cron: 5 18 * * * -- daily 18:05 (wired 2026-08-30)"

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--send", action="store_true", help="deliver (default: print only)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--window-hours", type=float, default=24.0)
    args = ap.parse_args()

    from scripts.lib.cio_agent_brief import build_brief, render_telegram

    brief = build_brief(window_hours=args.window_hours)
    text = render_telegram(brief)

    if args.json:
        print(json.dumps(brief, indent=2, sort_keys=True, default=str))
    else:
        print(text)

    if not args.send:
        return 0

    try:
        from telegram_alert import publish_operator_message
    except Exception as e:
        print(f"[agent-brief] cannot import operator path: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    res = publish_operator_message(text) or {}
    if res.get("delivered"):
        outcome = "delivered"
    elif res.get("queued"):
        outcome = f"queued for digest ({res.get('route_mode') or 'digest'})"
    elif res.get("accepted"):
        # Accepted and deliberately not sent to the phone. Normal routing, not a
        # failure -- and not "sent" either. Same distinction as PR #573.
        outcome = f"not sent — routed {res.get('route_mode') or 'DASHBOARD_ONLY'}"
    else:
        outcome = f"failed ({res.get('reason') or 'unknown'})"
    print(f"[agent-brief] {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
