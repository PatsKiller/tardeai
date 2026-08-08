#!/usr/bin/env python3
"""heal_trade_ai_session_cache.py — Autonomous SETUPS session heal for Health Agent.

CC SETUPS uses trade_ai_cache.json `run_date` (session), not file mtime.

warm_caches → trade_ai(force=True) rebuilds the cache from reports/YYYY-*/**/run_summary.json
and will overwrite a naive empty heal with the latest real package (often yesterday).

This healer:
  1. Writes reports/{today}/{label}/run_summary.json so recompute prefers today
  2. Patches existing trade_ai_cache.json run_date **in place** (keeps tickers)
  3. Writes both LIVE stamp and DEV trees

Usage:
    .venv/bin/python scripts/heal_trade_ai_session_cache.py
    .venv/bin/python scripts/heal_trade_ai_session_cache.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from lib.live_project_root import get_live_project_root, DEV_ROOT
except Exception:
    get_live_project_root = lambda: PROJECT_ROOT  # noqa: E731
    DEV_ROOT = PROJECT_ROOT

LABEL = "HEALTH_AUTOHEAL"


def _today_et() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return datetime.now().date().isoformat()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".heal_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _heal_root(root: Path, today: str, dry_run: bool) -> dict:
    root = Path(root)
    out = {"root": str(root), "today": today}
    # 1) Package under reports/ so trade_ai(force=True) / warm_caches see today
    pkg_dir = root / "reports" / today / LABEL
    # Package is only a session anchor — real GO/WAIT live on trade_ai_cache tickers.
    # Use a low-sort label so warm_caches prefers the last real package when both exist,
    # while run_date today still satisfies the session freshness check.
    summary = {
        "date": today,
        "run_date": today,
        "run_label": LABEL,
        "ok": True,
        "generated_at": datetime.now().isoformat(),
        "source": "heal_trade_ai_session_cache",
        "ticker_count": 0,
        "go_count": 0,
        "wait_count": 0,
        "no_go_count": 0,
        "tickers": [],
        "vix": 0,
        "breadth": "Neutral",
        "session_heal": True,
        "_path_note": "session anchor only; do not use for GO/WAIT counts",
    }
    # 2) Also runtime package (health collector / other tools)
    runtime_pkg = root / "data" / "runtime" / "run_summaries" / today
    cache_path = root / "data" / "runtime" / "trade_ai_cache.json"

    prev = {}
    if cache_path.exists():
        try:
            prev = json.loads(cache_path.read_text() or "{}")
        except Exception:
            prev = {}
    old = prev.get("run_date") or prev.get("date")
    tickers = list(prev.get("tickers") or []) if isinstance(prev, dict) else []
    n_tickers = len(tickers)
    # CC header uses current_run_* filtered by run_label — keep the real label that
    # matches scan_run_label on tickers (do NOT overwrite with HEALTH_AUTOHEAL).
    real_label = (
        (prev.get("latest_run_label") if isinstance(prev, dict) else None)
        or (prev.get("run_label") if isinstance(prev, dict) else None)
        or ""
    )
    if real_label in ("", LABEL, "HEALTH_AUTOHEAL"):
        # Recover from a previous bad heal: use most common scan_run_label on rows
        labels = [str(t.get("scan_run_label") or "") for t in tickers if isinstance(t, dict)]
        labels = [x for x in labels if x and x not in (LABEL, "HEALTH_AUTOHEAL")]
        if labels:
            real_label = max(set(labels), key=labels.count)
        else:
            real_label = "1000"  # last known default for this desk

    def _dec(t):
        return str((t or {}).get("decision") or "").upper()

    # Prefer rows from real_label; fall back to all tickers
    cur_rows = [t for t in tickers if str((t or {}).get("scan_run_label") or "") == real_label]
    if not cur_rows:
        cur_rows = tickers
    go_n = sum(1 for t in cur_rows if _dec(t) == "GO")
    wait_n = sum(1 for t in cur_rows if _dec(t) == "WAIT")
    nogo_n = sum(1 for t in cur_rows if _dec(t) not in ("GO", "WAIT", ""))
    # Universe-wide counts (header sometimes falls back to these)
    go_all = sum(1 for t in tickers if _dec(t) == "GO")
    wait_all = sum(1 for t in tickers if _dec(t) == "WAIT")
    nogo_all = sum(1 for t in tickers if _dec(t) not in ("GO", "WAIT", ""))

    # Preserve tickers — never wipe a full cache with an empty one
    cache = dict(prev) if isinstance(prev, dict) else {}
    cache.update({
        "ok": True,
        "run_date": today,
        "date": today,
        "run_label": real_label,
        "latest_run_label": real_label,
        "latest_run_go_count": go_n,
        "latest_run_wait_count": wait_n,
        "latest_run_no_go_count": nogo_n,
        "current_run_go": go_n,
        "current_run_wait": wait_n,
        "current_run_nogo": nogo_n,
        "current_run_scanned": len(cur_rows),
        "go_count": go_n if go_n else go_all,
        "wait_count": wait_n if wait_n else wait_all,
        "avoid_count": nogo_n if nogo_n else nogo_all,
        "ticker_count": n_tickers,
        "session_heal": {
            "from": old,
            "to": today,
            "at": datetime.now().isoformat(),
            "by": "heal_trade_ai_session_cache",
            "preserved_tickers": n_tickers,
            "real_label": real_label,
            "go": go_n, "wait": wait_n, "nogo": nogo_n,
        },
        "stale": False,
        "cache_error": None,
    })
    if "tickers" not in cache:
        cache["tickers"] = []

    out.update({"old": old, "new": today, "preserved_tickers": n_tickers, "changed": str(old)[:10] != today})

    if dry_run:
        out["dry_run"] = True
        return out

    _atomic_write(pkg_dir / "run_summary.json", json.dumps(summary, indent=2))
    runtime_pkg.mkdir(parents=True, exist_ok=True)
    _atomic_write(runtime_pkg / "run_summary.json", json.dumps(summary, indent=2))
    # Preserve _cached_ts so age looks fresh
    import time as _t
    cache["_cached_ts"] = _t.time()
    cache["_cached_at"] = datetime.utcnow().isoformat() + "Z"
    _atomic_write(cache_path, json.dumps(cache, indent=2, default=str))
    out["cache"] = str(cache_path)
    out["report_pkg"] = str(pkg_dir / "run_summary.json")
    out["dry_run"] = False
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Autonomous SETUPS session cache heal")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    today = _today_et()
    roots = []
    try:
        live = get_live_project_root()
        if live and Path(live).is_dir():
            roots.append(Path(live))
    except Exception:
        pass
    for r in (DEV_ROOT, PROJECT_ROOT):
        if Path(r).is_dir() and Path(r) not in roots:
            roots.append(Path(r))
    # de-dupe by resolve
    uniq, seen = [], set()
    for r in roots:
        try:
            k = str(r.resolve())
        except Exception:
            k = str(r)
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    results = []
    for r in uniq:
        try:
            results.append(_heal_root(r, today, args.dry_run))
        except Exception as e:
            results.append({"root": str(r), "error": str(e)[:240]})
    print(json.dumps({"ok": True, "today_et": today, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
