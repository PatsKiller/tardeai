#!/usr/bin/env python3
"""Remediate Yahoo RSS mis-tagged news/catalyst on CIO-rated watchlist symbols (all verdict tiers).

Health agent auto_remediate calls this on `news_symbol_mismatch` findings.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PY = PROJECT_ROOT / ".venv/bin/python"
SCRIPTS = PROJECT_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))


def _run(script: str, args: list[str], *, timeout: int = 120) -> dict:
    try:
        proc = subprocess.run(
            [str(VENV_PY), str(SCRIPTS / script), *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-300:],
            "stderr_tail": (proc.stderr or "")[-300:],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def remediate(*, apply: bool = True, max_symbol_refresh: int = 10) -> dict:
    from db_adapter import get_connection
    from news_symbol_guard import (
        count_mismatched_watchlist,
        purge_mismatched_for_symbol,
        purge_mismatched_watchlist,
    )

    conn = get_connection()
    try:
        before = count_mismatched_watchlist(conn, limit=120)
        mismatch_syms = [m["symbol"] for m in (before.get("mismatches") or []) if m.get("symbol")]
        if int(before.get("mismatch_count") or 0) == 0:
            return {"ok": True, "action": "none", "mismatches_before": 0}

        purged_syms: set[str] = set()
        by_symbol: dict = {}

        for sym in mismatch_syms:
            r = purge_mismatched_for_symbol(conn, sym, apply=apply, auto_commit=False)
            if r.get("news_removed") or r.get("catalyst_removed"):
                purged_syms.add(sym)
                by_symbol[sym] = r

        if int(before.get("mismatch_count") or 0) >= 5:
            full = purge_mismatched_watchlist(conn, apply=apply)
            purged_syms.update((full.get("by_symbol") or {}).keys())
            by_symbol.update(full.get("by_symbol") or {})

        if apply and by_symbol:
            conn.commit()

        refresh_syms = sorted(purged_syms)[: max(1, max_symbol_refresh)]
        symbol_steps: dict[str, dict] = {}
        for sym in refresh_syms:
            symbol_steps[sym] = {
                "news": _run("news_ingestion.py", ["--symbol", sym, "--json"], timeout=90),
                "catalyst": _run("news_to_catalyst.py", ["--symbol", sym, "--json"], timeout=120),
            }

        priority = _run("news_ingestion.py", ["--priority"], timeout=150)

        after = count_mismatched_watchlist(conn, limit=120)
    finally:
        conn.close()

    out = {
        "ok": int(after.get("mismatch_count") or 0) == 0,
        "mismatches_before": int(before.get("mismatch_count") or 0),
        "mismatches_after": int(after.get("mismatch_count") or 0),
        "symbols_purged": len(purged_syms),
        "symbols_refreshed": len(refresh_syms),
        "by_symbol": by_symbol,
        "symbol_steps": symbol_steps,
        "priority_ingest": priority,
    }
    print(
        f"[remediate_watchlist_news_guard] before={out['mismatches_before']} "
        f"after={out['mismatches_after']} purged={out['symbols_purged']} "
        f"refreshed={out['symbols_refreshed']}",
        flush=True,
    )
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Delete mismatches and re-ingest")
    ap.add_argument("--dry-run", action="store_true", help="Audit only")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-symbol-refresh", type=int, default=10)
    args = ap.parse_args()
    result = remediate(apply=args.apply and not args.dry_run, max_symbol_refresh=args.max_symbol_refresh)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result.get("ok") else 1)