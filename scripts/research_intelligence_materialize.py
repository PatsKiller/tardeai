#!/usr/bin/env python3
"""RI v3.1 (WS-A): materialize feed snapshots out of the request path.

Builds the feed for each lane (+ the unfiltered desk) and writes versioned JSON
snapshots to data/runtime/ri_snapshots/{lane}.json. The GET route serves these
files with ETag/304 — request-time compute becomes the exception, not the rule.

Triggered by: the 16:45/02:40 queue drains (research_intelligence_queue calls
in-process), the 06:35 cron, and POST /api/v2/research-intelligence/rebuild
(operator; compute over existing rows, so RTH-allowed).

Usage:
  python scripts/research_intelligence_materialize.py            # all lanes
  python scripts/research_intelligence_materialize.py --lanes top,retirement
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# A caller/test may override SNAP_DIR; otherwise resolve durable state at execution time.
SNAP_DIR = None
_ENV_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_CONN_TRACE")


def _load_env():
    import os
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / ".env")
    for name in _ENV_KEYS:
        if values.get(name) is not None:
            os.environ.setdefault(name, values[name])


LOCK_PATH = "/tmp/ri_materialize.lock"
# "top" = the unfiltered desk; lane names must match LANE_CATEGORIES + the UI tabs
LANES = ("top", "retirement", "dividends", "macro_sector")
SLOW_WARN_S = 30.0
SNAPSHOT_LIMIT = 50  # matches the desk's server-side payload cap


def materialize(lanes: tuple[str, ...] = LANES, *, log=print) -> dict:
    """Build + atomically write one snapshot per lane. Returns per-lane stats."""
    from db_adapter import _execute

    def dbq(sql, params=None, fetch="all"):
        return _execute(sql, params, fetch=fetch)

    from lib.research_intelligence import build_feed
    try:
        from research_intelligence_qa_lint import lint_feed, known_symbol_universe
        known_syms = known_symbol_universe(dbq)
    except Exception:
        lint_feed, known_syms = None, set()

    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return {"ok": False, "error": "materialize already running (lock held)"}

    try:
        from lib.lane_last_receipt import runtime_dir
        snap_dir = SNAP_DIR or runtime_dir() / "ri_snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        out: dict = {"ok": True, "lanes": {}}
        for lane in lanes:
            t0 = time.perf_counter()
            try:
                feed = build_feed(
                    db_query=dbq,
                    limit=SNAPSHOT_LIMIT,
                    lane=None if lane == "top" else lane,
                )
            except Exception as e:  # a broken lane must not kill the others
                out["ok"] = False
                out["lanes"][lane] = {"ok": False, "error": str(e)[:200]}
                log(f"[ri-materialize] {lane}: BUILD FAILED — {e}")
                continue
            build_ms = int((time.perf_counter() - t0) * 1000)
            qa_counts = {}
            if lint_feed is not None:
                try:
                    qa_counts = lint_feed(feed.get("items") or [], known_symbols=known_syms)
                    feed.setdefault("stats", {})["qa_flag_counts"] = qa_counts
                except Exception as e:
                    log(f"[ri-materialize] {lane}: qa-lint failed (non-fatal) — {e}")
            body = json.dumps(feed, default=str, allow_nan=False)
            sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]
            snap = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "build_ms": build_ms,
                "item_count": len(feed.get("items") or []),
                "sha": sha,
                "lane": lane,
                "feed": feed,
            }
            path = snap_dir / f"{lane}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap, default=str, allow_nan=False), encoding="utf-8")
            tmp.replace(path)
            out["lanes"][lane] = {"ok": True, "build_ms": build_ms, "items": snap["item_count"], "sha": sha}
            msg = f"[ri-materialize] {lane}: {snap['item_count']} items in {build_ms}ms sha={sha}"
            if build_ms > SLOW_WARN_S * 1000:
                msg += f"  ⚠ SLOW (> {SLOW_WARN_S:.0f}s) — check hermes query / narrative enrichment phases"
            log(msg)
        return out
    finally:
        lock.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--lanes", default=",".join(LANES))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    lanes = tuple(x.strip() for x in args.lanes.split(",") if x.strip() in LANES) or LANES
    if args.dry_run:
        print(f"DRY-RUN research-intelligence-materialize: would build snapshots for {','.join(lanes)}; no DB, files or provider calls performed")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        _load_env()
        res = materialize(lanes)
    except Exception as exc:
        write_lane_receipt("research-intelligence-materialize", ok=False, exit_code=1,
                           started_at=started, script="research_intelligence_materialize.py",
                           error=f"{type(exc).__name__}: {exc}")
        raise
    if args.json:
        print(json.dumps(res, indent=2))
    rc = 0 if res.get("ok") else 1
    write_lane_receipt("research-intelligence-materialize", ok=rc == 0, exit_code=rc,
                       started_at=started, script="research_intelligence_materialize.py",
                       summary={"lanes_requested": len(lanes),
                                "lanes_completed": sum(bool(r.get("ok")) for r in res.get("lanes", {}).values()),
                                "lanes_failed": sum(not r.get("ok") for r in res.get("lanes", {}).values()),
                                "lock_skipped": "lock held" in str(res.get("error", ""))})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
