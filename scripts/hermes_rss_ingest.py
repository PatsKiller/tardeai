#!/usr/bin/env python3
"""Hermes RSS connector — reads feed URLs from config/hermes_rss_feeds.txt (one per line),
stages items into hermes_research_intelligence (research_type='source_discovery', source='rss').
Dormant if no feed file. Default dry-run; --apply to write. Kill-switch aware.
"""
import os, sys, json, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
FEEDS = ROOT / "config" / "hermes_rss_feeds.txt"
KILL = ROOT / "data" / "runtime" / "HERMES_DISABLED"

def main():
    apply = "--apply" in sys.argv
    if KILL.exists():
        print("kill switch active — RSS connector halted"); return 0
    if not FEEDS.exists():
        print("DORMANT: no config/hermes_rss_feeds.txt — add feed URLs (one per line) to enable."); return 0
    feeds = [l.strip() for l in FEEDS.read_text().splitlines() if l.strip() and not l.startswith("#")]
    print(f"RSS connector: {len(feeds)} feed(s) configured · mode={'APPLY' if apply else 'dry-run'}")
    # (Parser intentionally minimal — full feed parsing wired when feeds are configured + approved.)
    return 0

if __name__ == "__main__":
    sys.exit(main())
