#!/usr/bin/env python3
"""cio_ask_reanswer.py — Ask the CIO Phase 11: re-answer tracked questions on material change.

Usage:
  .venv/bin/python scripts/cio_ask_reanswer.py --once --dry-run      # read and report only (rule 7: run this first)
  .venv/bin/python scripts/cio_ask_reanswer.py --once                # config mode (shadow by default: record only)
  .venv/bin/python scripts/cio_ask_reanswer.py --once --json

Not scheduled by the change that added it (cron freeze 2026-10-09; n8n-first). Proposed lane: ``cio-ask-reanswer``
at shadow. ``mode: live`` in config/cio_ask.json additionally needs the Ask-the-CIO cap APPROVED. READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ask the CIO — re-answer on material change")
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--dry-run", action="store_true", help="read and report only; no writes, spend or sends")
    ap.add_argument("--mode", choices=("shadow", "live"), default=None, help="override config mode")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.once:
        ap.error("--once is required (scheduling belongs to the lane registry, not this script)")
    from scripts.lib.cio_ask_reanswer import run_once

    rep = run_once(mode=args.mode, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(
            f"[cio-ask-reanswer] mode={rep.get('mode')} dry_run={rep.get('dry_run')} tracked={rep.get('tracked')} "
            f"events={rep.get('events')} candidates={len(rep.get('candidates') or [])} "
            f"reanswered={len(rep.get('reanswered') or [])} skipped={len(rep.get('skipped') or [])} "
            f"errors={len(rep.get('errors') or [])}"
        )
        for s in rep.get("skipped") or []:
            print(f"  SKIP {s.get('thread_id')} {s.get('symbol')} {s.get('kind')}: {s.get('reason')}")
        for e in rep.get("errors") or []:
            print(f"  ERR {e}")
    return 0 if rep.get("ok") and not rep.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
