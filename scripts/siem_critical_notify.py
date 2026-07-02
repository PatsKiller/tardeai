#!/usr/bin/env python3
"""SIEM critical notifier — one deduped Telegram per new P0/P1 incident.

Reads the SIEM dashboard (/api/v2/system/siem), takes the critical (P0/P1) correlated
incidents, and Telegrams the operator — but only ONCE per incident per cooldown window
(so 43 repeats of the same failure = 1 ping, not 43). State is a small file keyed by
incident signature.

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
COOLDOWN_H = 6  # re-ping a still-active incident at most this often
RECENT_H = 2    # only alert on incidents whose last event was within this window (not stale 14d history)


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
    now = time.time()
    sent = 0
    for inc in incidents:
        key = f"{inc.get('component')}|{inc.get('event_type')}|{inc.get('severity')}"
        last = state.get(key, 0)
        if now - last < COOLDOWN_H * 3600:
            continue
        _send(f"🚨 SIEM {inc['severity']}: {inc.get('component')} — {inc.get('event_type')}\n"
              f"{inc.get('events')} events / {inc.get('groups')} group(s) in 14d. Check System → SIEM.")
        state[key] = now
        sent += 1
    # prune state entries older than 7 days
    state = {k: v for k, v in state.items() if now - v < 7 * 86400}
    _save_state(state)
    print(f"[siem-notify] {len(incidents)} critical incident(s), {sent} new Telegram alert(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
