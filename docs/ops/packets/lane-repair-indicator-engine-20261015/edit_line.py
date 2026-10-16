#!/usr/bin/env python3
"""Exact one-line crontab edit for the indicator-engine lane repair (2026-10-15). Reads a crontab file, writes a
candidate. Never touches the live crontab; never expands a shell glob (the cron fields contain `*`).

  python3 edit_line.py apply    <crontab.live> <crontab.candidate>   # OLD line -> NEW line
  python3 edit_line.py rollback <crontab.live> <crontab.candidate>   # NEW line -> OLD line

Refuses (exit 2) unless the line to replace occurs exactly once and the other line does not occur at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD = "0 8 * * 1-5 cd $PROJ && $PY scripts/indicator_engine.py >> logs/indicator_engine.log 2>&1"
NEW = ("0 8 * * 1-5 cd $PROJ && flock -n /tmp/indicator_engine.lock $PY scripts/indicator_engine.py --universe >> "
       "logs/indicator_engine.log 2>&1  # lane indicator-engine: gap-fill indicator_confluence_cache over the "
       "indicator_cache_refresh universe (lane repair 2026-10-15)")


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("apply", "rollback"):
        print(__doc__, file=sys.stderr)
        return 2
    mode, src, dst = argv
    frm, to = (OLD, NEW) if mode == "apply" else (NEW, OLD)
    text = Path(src).read_text(encoding="utf-8")
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if line == frm]
    if len(hits) != 1 or to in lines:
        print(f"REFUSED: expected exactly one line to replace and none already replaced; found {len(hits)} "
              f"match(es), target present={to in lines}", file=sys.stderr)
        return 2
    lines[hits[0]] = to
    Path(dst).write_text("\n".join(lines), encoding="utf-8")
    print(f"{mode}: line {hits[0] + 1} replaced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
