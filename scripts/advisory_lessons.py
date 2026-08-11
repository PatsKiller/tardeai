#!/usr/bin/env python3
"""Advisory KB lessons CLI — reflect / ratify / retire / list / inject-test.

Usage:
  .venv/bin/python scripts/advisory_lessons.py reflect
  .venv/bin/python scripts/advisory_lessons.py ratify-safe
  .venv/bin/python scripts/advisory_lessons.py ratify <id>
  .venv/bin/python scripts/advisory_lessons.py retire <id> [--reason ...]
  .venv/bin/python scripts/advisory_lessons.py list [--status ratified]
  .venv/bin/python scripts/advisory_lessons.py stats
  .venv/bin/python scripts/advisory_lessons.py auto-retire
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    from lib.advisory import kb_lessons as kb

    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("reflect")
    sub.add_parser("ratify-safe")
    pr = sub.add_parser("ratify")
    pr.add_argument("id")
    pr.add_argument("--by", default="iris")
    pret = sub.add_parser("retire")
    pret.add_argument("id")
    pret.add_argument("--reason", default="manual")
    pl = sub.add_parser("list")
    pl.add_argument("--status", default="ratified")
    sub.add_parser("stats")
    sub.add_parser("auto-retire")
    pi = sub.add_parser("retrieve")
    pi.add_argument("--symbol", default="")
    pi.add_argument("--verdict", default="")
    pi.add_argument("--query", default="")

    args = p.parse_args(argv)

    if args.cmd == "reflect":
        r = kb.nightly_reflection()
        print(json.dumps({k: r[k] for k in ("ok", "proposed", "ratified_n", "auto_retired")}, indent=2))
        return 0
    if args.cmd == "ratify-safe":
        rows = kb.iris_auto_ratify_safe(limit=15)
        print(json.dumps({"ratified": len(rows), "ids": [r["id"] for r in rows]}, indent=2))
        return 0
    if args.cmd == "ratify":
        r = kb.ratify_lesson(args.id, by=args.by)
        print(json.dumps({"id": r["id"], "status": r["status"], "title": r["title"]}, indent=2))
        return 0
    if args.cmd == "retire":
        r = kb.retire_lesson(args.id, reason=args.reason)
        print(json.dumps({"id": r["id"], "status": r["status"], "reason": r.get("retire_reason")}, indent=2))
        return 0
    if args.cmd == "list":
        status = None if args.status in ("all", "*") else args.status
        rows = kb.list_lessons(status=status)
        for r in rows:
            print(f"{r.get('id')}  {r.get('status'):10}  hits={r.get('hit_rate')}  n={r.get('applications')}  {r.get('title')}")
        print(f"total={len(rows)}")
        return 0
    if args.cmd == "stats":
        print(json.dumps(kb.stats(), indent=2))
        return 0
    if args.cmd == "auto-retire":
        rows = kb.auto_retire_sweep()
        print(json.dumps({"retired": len(rows), "ids": [r["id"] for r in rows]}, indent=2))
        return 0
    if args.cmd == "retrieve":
        rows = kb.retrieve_lessons_for_row(
            symbol=args.symbol, verdict=args.verdict, query_text=args.query,
        )
        print(json.dumps(kb.format_lessons_for_prompt(rows), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
