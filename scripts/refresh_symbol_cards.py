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
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_FILE = ROOT / "data" / "runtime" / "symbol_cards_latest.json"
ENDPOINT = os.environ.get("SYMBOL_CARDS_URL", "http://localhost:7777/api/v2/symbol-cards")
CONFIG_FILE = ROOT / "config" / "symbol_cards_refresh.yaml"
#: Used only when config/symbol_cards_refresh.yaml is missing or unreadable (the file is the source of truth).
_FALLBACK = {"materialize_timeout_s": 180.0, "materialize_retries": 1, "retry_backoff_s": 30.0, "min_cards": 30}


def load_policy(path: Path = CONFIG_FILE) -> dict:
    """Timeout / retry policy for step 2 (config/symbol_cards_refresh.yaml)."""
    pol = dict(_FALLBACK)
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for k in pol:
            if doc.get(k) is not None:
                pol[k] = type(pol[k])(doc[k])
    except Exception as e:  # noqa: BLE001 — a broken config must not stop the refresh
        print(f"policy: {path.name} unreadable ({type(e).__name__}); using fallback", file=sys.stderr)
    pol["materialize_retries"] = max(0, int(pol["materialize_retries"]))
    return pol


def _fetch_cards(timeout_s: float, min_cards: int) -> tuple[bytes, int]:
    """One attempt: the endpoint payload and its card count. Raises on timeout, bad JSON or too few cards."""
    data = urllib.request.urlopen(ENDPOINT, timeout=timeout_s).read()
    n = len((json.loads(data).get("data") or {}).get("cards") or {})
    if n < min_cards:
        raise ValueError(f"only {n} cards (endpoint not ready)")
    return data, n


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
    # Timeout and retry come from config/symbol_cards_refresh.yaml: at 06:42 the endpoint competes with
    # ~10 enrichment/DB crons and a cold build can exceed a minute (2026-10-08/09 "timed out").
    pol = load_policy()
    attempts = 1 + pol["materialize_retries"]
    for attempt in range(1, attempts + 1):
        try:
            data, n = _fetch_cards(pol["materialize_timeout_s"], pol["min_cards"])
        except Exception as e:  # noqa: BLE001
            print(f"materialize attempt {attempt}/{attempts} failed: {str(e)[:160]}")
            if attempt < attempts:
                time.sleep(pol["retry_backoff_s"])
                continue
            print("materialize failed: kept existing file")
            return 1
        tmp = CARDS_FILE.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, CARDS_FILE)
        print(f"materialized {n} cards -> {CARDS_FILE.name} (attempt {attempt}/{attempts})")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
