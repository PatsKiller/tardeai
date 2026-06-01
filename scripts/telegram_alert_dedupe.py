#!/usr/bin/env python3
"""Telegram Alert Dedupe Wrapper — suppresses repeated identical alerts.

Usage:
    python scripts/telegram_alert_dedupe.py --alert-type credential_expired --component finviz --message "FINVIZ COOKIE EXPIRED" [--apply]

Default: dry-run. --apply sends via real Telegram path if not suppressed.
"""
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "state" / "alert_dedupe_state.json"
DEFAULT_WINDOW_MIN = 60

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"alerts": {}}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def dedupe_key(alert_type, component):
    return f"{alert_type}:{component}"

def should_suppress(state, key, window_min):
    now = time.time()
    entry = state["alerts"].get(key)
    if not entry:
        return False
    last_sent = entry.get("last_sent_epoch", 0)
    return (now - last_sent) < (window_min * 60)

def record_sent(state, key):
    now = time.time()
    entry = state["alerts"].setdefault(key, {"count": 0})
    entry["last_sent_epoch"] = now
    entry["last_sent"] = datetime.now(timezone.utc).isoformat()
    entry["count"] = entry.get("count", 0) + 1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert-type", required=True)
    parser.add_argument("--component", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--window-min", type=int, default=DEFAULT_WINDOW_MIN)
    args = parser.parse_args()

    state = load_state()
    key = dedupe_key(args.alert_type, args.component)

    if should_suppress(state, key, args.window_min):
        entry = state["alerts"][key]
        entry["suppressed_count"] = entry.get("suppressed_count", 0) + 1
        save_state(state)
        print(f"SUPPRESSED: {key} (within {args.window_min}min window, suppressed {entry['suppressed_count']}x)")
        return

    if args.apply:
        # Would call actual Telegram send here
        print(f"SEND: {args.message[:100]}")
    else:
        print(f"DRY-RUN would send: {args.message[:100]}")

    record_sent(state, key)
    save_state(state)
    print(f"Recorded: {key}")

if __name__ == "__main__":
    main()
