#!/usr/bin/env python3
"""Executor CLI for lane advisory-desk-run-now (Wave C).

Rebuilds the advisory desk facts then Flash opinions + Pro synthesis.
Authority: READ_ONLY_ADVISORY. LLM stays on the governed bridge inside enrich.

Usage:
  $PY scripts/advisory_desk_run_now.py --dry-run
  $PY scripts/advisory_desk_run_now.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Advisory Desk run-now (READ_ONLY_ADVISORY)")
    ap.add_argument("--dry-run", action="store_true", help="build desk + enrich with dry_run (no paid LLM)")
    args = ap.parse_args(argv)

    from lib.advisory_desk_schedule import execute_run_now
    from lib.n8n_cc_wave_c import LANE_ADVISORY, write_lane_receipt

    live_llm = not args.dry_run
    if live_llm:
        os.environ.setdefault("ADVISORY_DESK_V1", "true")
    result = execute_run_now(live_llm=live_llm)
    ok = result.get("state") == "ok"
    mode = "dry_run" if args.dry_run else "live"
    write_lane_receipt(LANE_ADVISORY, ok=ok, mode=mode, detail={"result": result})
    print(json.dumps({"ok": ok, "mode": mode, "lane_id": LANE_ADVISORY, **result}, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
