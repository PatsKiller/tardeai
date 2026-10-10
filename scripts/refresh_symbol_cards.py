#!/usr/bin/env python3
"""refresh_symbol_cards.py — keep the unified symbol-card file fresh for the rotation engine + card layer.

(1) builds/refreshes symbol_profiles for watch-grade symbols (so new watchlist / research-candidate names
    get a description + sector + industry — build_symbol_profiles skips fresh ones unless --force), then
(2) materializes data/runtime/symbol_cards_latest.json from the live /api/v2/symbol-cards endpoint (atomic).

This file is read by the rotation engine (--cards) and the rotation summary; it previously had NO refresh
job and went stale, which is why newly-surfaced research candidates showed "sector/analyst pending". Run
daily from cron. Read-only re: trading — no broker, no orders.

  --dry-run         fetch + validate the endpoint payload and report; no profile subprocess, no file write
  --skip-profiles   materialize only (step 2); build_symbol_profiles is owned by its own lane (L508)

Refactor wave 1 (2026-10-10): the no-flag cron form is unchanged (both steps). A real run writes
data/runtime/refresh_symbol_cards_last.json (LaneRunReceipt@v1, ok_at only on success).
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _runtime_dir() -> Path:
    """data/runtime on the persistent state root (the release symlinks it there), never a checkout copy."""
    try:
        from lib.persistent_state_root import resolve_durable_dir

        return resolve_durable_dir("data/runtime", ROOT)
    except Exception:  # noqa: BLE001 -- resolution layer unavailable: the code tree (old behaviour)
        return ROOT / "data" / "runtime"


CARDS_FILE = _runtime_dir() / "symbol_cards_latest.json"
RECEIPT_NAME = "refresh_symbol_cards"
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


def _python() -> str:
    """Interpreter for the profile step: release dirs ship no .venv (lib.live_project_root.venv_python)."""
    try:
        from lib.live_project_root import venv_python

        return venv_python(ROOT)
    except Exception:  # noqa: BLE001
        return sys.executable


def build_profiles(force: bool) -> None:
    # 1. Enrich profiles for watch-grade symbols (new names get a profile; fresh ones are skipped).
    try:
        cmd = [_python(), str(ROOT / "scripts" / "build_symbol_profiles.py")] + (["--force"] if force else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, cwd=str(ROOT))
        print(
            "profiles:",
            (r.stdout or r.stderr or "").strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else "ok",
        )
    except Exception as e:
        print("profile build skipped (non-fatal):", str(e)[:120])


def fetch_with_retry(pol: dict) -> tuple[bytes | None, int, int, str]:
    """(payload, card_count, attempt, last_error). payload None = every attempt failed."""
    attempts = 1 + pol["materialize_retries"]
    err = ""
    for attempt in range(1, attempts + 1):
        try:
            data, n = _fetch_cards(pol["materialize_timeout_s"], pol["min_cards"])
            return data, n, attempt, ""
        except Exception as e:  # noqa: BLE001
            err = str(e)[:160]
            print(f"materialize attempt {attempt}/{attempts} failed: {err}")
            if attempt < attempts:
                time.sleep(pol["retry_backoff_s"])
    return None, 0, attempts, err


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    force = "--force" in argv
    dry_run = "--dry-run" in argv
    skip_profiles = "--skip-profiles" in argv
    pol = load_policy()
    attempts = 1 + pol["materialize_retries"]
    if dry_run:
        # Fetch + validate only. The profile step is a subprocess that WRITES symbol_profiles, so a dry
        # run never starts it; the cards file and the receipt are never touched (AGENTS.md §6).
        data, n, attempt, err = fetch_with_retry(pol)
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "endpoint": ENDPOINT,
                    "valid": data is not None,
                    "cards": n,
                    "attempt": f"{attempt}/{attempts}",
                    "error": err or None,
                    "would_run_profiles": not skip_profiles,
                    "would_write": str(CARDS_FILE) if data is not None else None,
                }
            )
        )
        return 0 if data is not None else 1
    from lib.lane_last_receipt import now_iso, write_receipt

    started_at = now_iso()
    try:
        if not skip_profiles:
            build_profiles(force)
        # 2. Materialize the cards file from the live endpoint (atomic; refuse a clearly-broken payload).
        # Timeout and retry come from config/symbol_cards_refresh.yaml: at 06:42 the endpoint competes with
        # ~10 enrichment/DB crons and a cold build can exceed a minute (2026-10-08/09 "timed out").
        data, n, attempt, err = fetch_with_retry(pol)
        if data is None:
            print("materialize failed: kept existing file")
            write_receipt(
                RECEIPT_NAME,
                ok=False,
                started_at=started_at,
                error=f"materialize failed: {err}",
                summary={"attempts": attempts},
            )
            return 1
        tmp = CARDS_FILE.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, CARDS_FILE)
    except Exception as exc:
        write_receipt(RECEIPT_NAME, ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    print(f"materialized {n} cards -> {CARDS_FILE.name} (attempt {attempt}/{attempts})")
    write_receipt(
        RECEIPT_NAME,
        ok=True,
        started_at=started_at,
        summary={"cards": n, "attempt": attempt, "profiles_step": not skip_profiles},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
