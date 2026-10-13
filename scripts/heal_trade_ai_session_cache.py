#!/usr/bin/env python3
"""heal_trade_ai_session_cache.py — record SETUPS calendar session context.

Session anchors do not establish a scanner run. Business dates, identity, counters,
timestamps and freshness stay as the scanner published them. Only warm_caches may
replace that business evidence with a newly computed package.

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
from datetime import datetime, timezone
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


def _write_json_if_changed(path: Path, value: dict) -> bool:
    if path.exists():
        try:
            if json.loads(path.read_text()) == value:
                return False
        except (OSError, ValueError):
            pass
    _atomic_write(path, json.dumps(value, indent=2, default=str))
    return True


def _heal_root(root: Path, today: str, dry_run: bool) -> dict:
    root = Path(root)
    out = {"root": str(root), "today": today}
    pkg_dir = root / "reports" / today / LABEL
    runtime_pkg = root / "data" / "runtime" / "run_summaries" / today
    cache_path = root / "data" / "runtime" / "trade_ai_cache.json"
    prev = {}
    if cache_path.exists():
        try:
            prev = json.loads(cache_path.read_text())
            if not isinstance(prev, dict):
                raise ValueError("cache is not an object")
        except (OSError, ValueError):
            # Never replace unreadable business evidence with a healthy empty cache.
            return {**out, "status": "CACHE_UNREADABLE", "changed": False, "dry_run": dry_run}

    old = prev.get("run_date") or prev.get("date")
    tickers = prev.get("tickers") if isinstance(prev.get("tickers"), list) else []
    contract = prev.get("setup_run_summary") if isinstance(prev.get("setup_run_summary"), dict) else {}
    business_date = contract.get("run_date") or old
    now = datetime.now(timezone.utc).isoformat()
    context = {
        "calendar_date": today,
        "timezone": "America/New_York",
        "by": "heal_trade_ai_session_cache",
        "action": "SESSION_ANCHOR_ONLY",
        "business_run_unchanged": True,
        "business_run_id": prev.get("run_id"),
        "business_run_date": business_date,
        "business_date_mismatch": bool(old and business_date and str(old)[:10] != str(business_date)[:10]),
        "preserved_tickers": len(tickers),
    }
    previous_context = prev.get("session_heal")
    if isinstance(previous_context, dict) and {k: v for k, v in previous_context.items() if k != "at"} == context:
        context["at"] = previous_context.get("at") or now
    else:
        context["at"] = now
    cache = dict(prev)
    cache.update({"session_date": today, "session_heal": context})
    if not prev:
        cache.update({"ok": False, "stale": True, "cache_error": "business_run_not_proven", "tickers": []})

    # Reserved zero-row calendar anchors stay excluded by the scanner run rank.
    summary = {
        "date": today,
        "run_date": today,
        "run_label": LABEL,
        "ok": True,
        "generated_at": now,
        "generated_at_utc": now,
        "generated_at_tz": "UTC",
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
    anchor = pkg_dir / "run_summary.json"
    if anchor.exists():
        try:
            existing = json.loads(anchor.read_text())
            if (
                existing.get("run_label") == LABEL
                and existing.get("date") == today
                and existing.get("session_heal") is True
            ):
                summary = existing
        except (AttributeError, OSError, ValueError):
            pass

    out.update(
        {
            "old": old,
            "new": today,
            "preserved_tickers": len(tickers),
            "business_run_changed": False,
            "changed": cache != prev,
            "status": "SESSION_CONTEXT_ONLY",
        }
    )

    if dry_run:
        out["dry_run"] = True
        return out

    _write_json_if_changed(anchor, summary)
    _write_json_if_changed(runtime_pkg / "run_summary.json", summary)
    _write_json_if_changed(cache_path, cache)
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
    ok = all(not r.get("error") and r.get("status") != "CACHE_UNREADABLE" for r in results)
    print(json.dumps({"ok": ok, "today_et": today, "business_run_proof": False, "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
