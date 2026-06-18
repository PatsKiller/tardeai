#!/usr/bin/env python3
"""refresh_symbol_cards.py — keep the unified symbol-card file fresh for the rotation engine + card layer.

(1) builds/refreshes symbol_profiles for watch-grade symbols (so new watchlist / research-candidate names
    get a description + sector + industry — build_symbol_profiles skips fresh ones unless --force), then
(2) materializes data/runtime/symbol_cards_latest.json from the live /api/v2/symbol-cards endpoint (atomic).

This file is read by the rotation engine (--cards) and the rotation summary; it previously had NO refresh
job and went stale, which is why newly-surfaced research candidates showed "sector/analyst pending". Run
daily from cron. Read-only re: trading — no broker, no orders.
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_FILE = ROOT / "data" / "runtime" / "symbol_cards_latest.json"
ENDPOINT = os.environ.get("SYMBOL_CARDS_URL", "http://localhost:7777/api/v2/symbol-cards")


def main():
    force = "--force" in sys.argv
    # 1. Enrich profiles for watch-grade symbols (new names get a profile; fresh ones are skipped).
    try:
        cmd = [sys.executable, str(ROOT / "scripts" / "build_symbol_profiles.py")] + (["--force"] if force else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, cwd=str(ROOT))
        print("profiles:", (r.stdout or r.stderr or "").strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else "ok")
    except Exception as e:
        print("profile build skipped (non-fatal):", str(e)[:120])
    # 2. Materialize the cards file from the live endpoint (atomic; refuse a clearly-broken payload).
    try:
        data = urllib.request.urlopen(ENDPOINT, timeout=60).read()
        d = json.loads(data)
        n = len((d.get("data") or {}).get("cards") or {})
        if n < 30:
            print(f"refused: only {n} cards (endpoint not ready) — kept existing file")
            return 1
        tmp = CARDS_FILE.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, CARDS_FILE)
        print(f"materialized {n} cards -> {CARDS_FILE.name}")
        return 0
    except Exception as e:
        print("materialize failed:", str(e)[:160])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
