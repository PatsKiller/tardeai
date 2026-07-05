#!/usr/bin/env python3
"""SIEM critical notifier — one deduped Telegram per new P0/P1 incident.

Reads the SIEM dashboard (/api/v2/system/siem), takes the critical (P0/P1) correlated
incidents, and Telegrams the operator — but only on the FIRST occurrence of an incident
group. A still-open group is then suppressed for COOLDOWN_H unless it gets materially
worse: its event count grows by >GROWTH_PCT since the last page, or its severity
escalates (severity is part of the state key, so P1→P0 pages as a new group). The old
flat 6h cooldown re-paged every long-lived open incident ~4x/day forever.

State is a small json file keyed by incident signature (component|event_type|severity),
holding the last-notified time and the event count at that time.

Cron: every 15 min.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE = Path.home() / ".local" / "state" / "siem_notified.json"
COOLDOWN_H = 24   # a still-open incident group re-pages at most once per day...
GROWTH_PCT = 0.5  # ...unless its event count grew by more than this since the last page
RECENT_H = 2      # only alert on incidents whose last event was within this window (not stale 14d history)


def _within(iso, hours):
    """True if the ISO timestamp is within `hours` of now."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(iso))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return (now - dt).total_seconds() <= hours * 3600
    except Exception:
        return False


def _load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s))


def _send(msg):
    try:
        from telegram_alert import send_telegram
        return send_telegram(msg)
    except Exception as e:
        print(f"[siem-notify] telegram error: {e}"); return False


def main():
    # load .env for TELEGRAM_* under cron
    envf = PROJECT_ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln and ln.split("=", 1)[0] not in os.environ:
                os.environ[ln.split("=", 1)[0]] = ln.split("=", 1)[1]

    try:
        with urllib.request.urlopen("http://localhost:7777/api/v2/system/siem", timeout=20) as r:
            data = json.load(r).get("data", {})
    except Exception as e:
        print(f"[siem-notify] could not read SIEM: {e}"); return 0

    incidents = [c for c in data.get("correlated", [])
                 if c.get("severity") in ("P0", "P1") and _within(c.get("last"), RECENT_H)]
    state = _load_state()
    # migrate legacy entries (bare float timestamp → dict; event baseline unknown)
    state = {k: (v if isinstance(v, dict) else {"t": v, "events": None})
             for k, v in state.items()}
    now = time.time()
    sent = 0
    for inc in incidents:
        # severity is part of the key: an escalation (P1→P0) is a NEW group and pages.
        key = f"{inc.get('component')}|{inc.get('event_type')}|{inc.get('severity')}"
        events = inc.get("events") or 0
        prev = state.get(key)
        why = ""
        if prev is not None:
            within_cooldown = now - (prev.get("t") or 0) < COOLDOWN_H * 3600
            prev_events = prev.get("events")
            if prev_events is None:
                # legacy/unknown baseline — record it, don't treat it as growth
                prev["events"] = events
                if within_cooldown:
                    continue
                why = f"\n(still open after {COOLDOWN_H}h)"
            elif events > prev_events * (1 + GROWTH_PCT):
                why = f"\n(escalating: {prev_events} → {events} events since last page)"
            elif within_cooldown:
                continue  # open but not getting worse — suppressed
            else:
                why = f"\n(still open after {COOLDOWN_H}h)"
        _send(f"🚨 SIEM {inc['severity']}: {inc.get('component')} — {inc.get('event_type')}\n"
              f"{events} events / {inc.get('groups')} group(s) in 14d. Check System → SIEM.{why}")
        state[key] = {"t": now, "events": events}
        sent += 1
    # prune state entries older than 7 days
    state = {k: v for k, v in state.items() if now - (v.get("t") or 0) < 7 * 86400}
    _save_state(state)
    print(f"[siem-notify] {len(incidents)} critical incident(s), {sent} new Telegram alert(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
