#!/usr/bin/env python3
"""run_finviz_targeted_screeners.py — fetch a SPECIFIC list of registry Finviz screeners (by
screener_id or preset_id), dedupe across them, and tag every row with full source lineage.

This is the targeted alternative to `finviz_screener_runner.py --run` (which runs ALL active DB
screeners). The 5-minute momentum-scalp lane uses THIS with the registry `scalp_lane_screener_ids` so it
fetches only the 2-3 purpose-built scalp/gapper screens — never the 29 broad DB screeners.

Discovery only. No broker writes. Finviz alone never creates GO — strict downstream gates still apply.
Default DRY-RUN; --apply performs the throttle-safe fetch (reuses finviz_screener_runner's fetch).

    python3 scripts/run_finviz_targeted_screeners.py --screeners momentum_scalp_primary_gappers,... --dry-run --json
    python3 scripts/run_finviz_targeted_screeners.py --screeners <ids> --apply --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
REGISTRY = ROOT / "config" / "finviz_screeners.yaml"
ARTIFACT_DIR = ROOT / "data" / "runtime"


def _registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text())


def resolve(ids: list, reg: dict | None = None) -> list:
    """Resolve screener_id OR preset_id strings to registry preset entries (scalp/swing presets)."""
    reg = reg or _registry()
    presets = reg.get("screeners", [])
    by_sid = {p["screener_id"]: p for p in presets}
    by_pid = {p.get("preset_id"): p for p in presets if p.get("preset_id")}
    out = []
    for x in ids:
        x = x.strip()
        p = by_sid.get(x) or by_pid.get(x)
        if p and p not in out:
            out.append(p)
    return out


def _url_hash(url: str) -> str:
    return hashlib.sha1((url or "").encode()).hexdigest()[:12]


def _gen_trace_id(symbol: str, screener_id: str, now: datetime) -> str:
    return f"fvtgt-{now.strftime('%Y%m%d%H%M')}-{screener_id[:18]}-{symbol}"


def run(ids: list, dry_run: bool = True, limit_per_screen: int = 80) -> dict:
    now = datetime.now(timezone.utc)
    reg = _registry()
    presets = resolve(ids, reg)
    cookie = None
    if not dry_run:
        try:
            from finviz_screener_runner import _get_finviz_cookie
            cookie = _get_finviz_cookie()
        except Exception:
            cookie = None

    per_screen, all_rows, seen = [], [], {}
    for p in presets:
        sid, pid, url = p["screener_id"], p.get("preset_id"), p["url"]
        tickers, err = [], None
        if not dry_run:
            try:
                from finviz_screener_runner import _fetch_screener_tickers
                tickers = (_fetch_screener_tickers(url, cookie) or [])[:limit_per_screen]
            except Exception as e:
                err = str(e).splitlines()[0][:100]
        new_here = 0
        for sym in tickers:
            sym = str(sym).upper().strip()
            if not sym:
                continue
            row = {"symbol": sym, "screener_id": sid, "preset_id": pid,
                   "source_screen_name": p["name"], "source_url_hash": _url_hash(url),
                   "source_seen_at": now.isoformat(),
                   "discovery_trace_id": _gen_trace_id(sym, sid, now),
                   "strategy_family": p["strategy_family"], "time_sensitivity": p["time_sensitivity"]}
            if sym not in seen:           # dedupe across screens (first screen wins lineage)
                seen[sym] = row
                all_rows.append(row)
                new_here += 1
        per_screen.append({"screener_id": sid, "preset_id": pid, "fetched": len(tickers),
                           "new_unique": new_here, "error": err})

    if not dry_run and all_rows:
        try:
            ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            (ARTIFACT_DIR / "finviz_targeted_latest.json").write_text(
                json.dumps({"generated_at": now.isoformat(), "rows": all_rows}, indent=2))
        except Exception:
            pass

    return {
        "ok": True, "dry_run": dry_run, "generated_at": now.isoformat(),
        "requested": ids, "resolved_screeners": [p["screener_id"] for p in presets],
        "per_screen": per_screen,
        "unique_symbols": len(all_rows), "rows_sample": all_rows[:8],
        "uses_broad_runner": False,
        "note": "Targeted Finviz discovery (NOT finviz_screener_runner --run). Discovery only; Finviz "
                "alone never creates GO — strict momentum_scalp gates apply downstream. No broker writes.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screeners", required=True, help="comma-separated screener_id/preset_id list")
    ap.add_argument("--dry-run", action="store_true", help="resolve only, no fetch (default)")
    ap.add_argument("--apply", action="store_true", help="perform the throttle-safe fetch")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    ids = [s for s in args.screeners.split(",") if s.strip()]
    r = run(ids, dry_run=not args.apply)
    print(json.dumps(r, indent=2, default=str) if args.json else
          f"targeted: resolved={r['resolved_screeners']} unique={r['unique_symbols']} dry_run={r['dry_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
