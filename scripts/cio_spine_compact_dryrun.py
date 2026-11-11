#!/usr/bin/env python3
"""cio_spine_compact_dryrun.py — READ-ONLY report of what compacting the research spine would drop (LQ-1929).

``data/cio/security_research_spine.jsonl`` appends a full spine tip per write. Before the idempotent-write fix, an
Ask-the-CIO memory retry appended one more tip per attempt whose only change was one more copy of a contribution it
already held. This script NEVER writes: the file is opened 'rb', there is no apply mode, and nothing is created
unless ``--report`` names a new file. It reports the lines and bytes a compaction would drop.

A line is *redundant* (droppable) when, for its symbol, (1) every contribution key (kind, artifact_id, summary) in it
was already seen in an earlier line (so no information first appears there; items evicted from the 100-window are
still kept in the earlier lines that introduced them), and (2) every other tip field except the churn fields
(contributions, by_silo, as_of) equals the previous kept line's. The first and the LAST line of each symbol are
always kept (the last is the live tip ``load_latest`` serves).

Usage: python3 scripts/cio_spine_compact_dryrun.py [--path FILE] [--top N] [--report OUT.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

CHURN = ("contributions", "by_silo", "as_of")


def _fingerprint(tip: dict) -> str:
    return json.dumps({k: v for k, v in tip.items() if k not in CHURN}, sort_keys=True, separators=(",", ":"), default=str)


def analyse(path: Path, *, top: int = 10) -> dict[str, Any]:
    st = path.stat()
    per: dict[str, dict[str, Any]] = {}
    total_lines = total_bytes = bad_lines = 0
    with path.open("rb") as fh:                                   # read-only: no write mode exists in this script
        for raw in fh:
            total_lines += 1
            total_bytes += len(raw)
            try:
                tip = json.loads(raw)
            except ValueError:
                bad_lines += 1
                continue
            if not isinstance(tip, dict):
                bad_lines += 1
                continue
            sym = str(tip.get("symbol") or "").upper() or "?"
            s = per.setdefault(sym, {"seen": set(), "fp": None, "lines": 0, "drop_lines": 0, "drop_bytes": 0,
                                     "last_len": 0, "last_dropped": False})
            keys = {(c.get("kind"), c.get("artifact_id"), c.get("summary")) for c in tip.get("contributions") or []
                    if isinstance(c, dict)}
            fp = _fingerprint(tip)
            first = s["lines"] == 0
            redundant = (not first) and keys <= s["seen"] and fp == s["fp"]
            s["lines"] += 1
            s["last_len"], s["last_dropped"] = len(raw), redundant
            if redundant:
                s["drop_lines"] += 1
                s["drop_bytes"] += len(raw)
            else:
                s["fp"] = fp
            s["seen"] |= keys
    for s in per.values():                                         # the live tip (last line) is always kept
        if s["last_dropped"]:
            s["drop_lines"] -= 1
            s["drop_bytes"] -= s["last_len"]
    drop_lines = sum(s["drop_lines"] for s in per.values())
    drop_bytes = sum(s["drop_bytes"] for s in per.values())
    ranked = sorted(per.items(), key=lambda kv: -kv[1]["drop_bytes"])[:top]
    return {
        "schema": "SpineCompactionDryRun@v1",
        "dry_run": True,
        "at": datetime.now(timezone.utc).isoformat(),
        "path": str(path),
        "size_bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        "lines": total_lines,
        "unparseable_lines": bad_lines,
        "symbols": len(per),
        "would_drop_lines": drop_lines,
        "would_drop_bytes": drop_bytes,
        "would_keep_lines": total_lines - drop_lines,
        "would_keep_bytes": total_bytes - drop_bytes,
        "top_symbols": [{"symbol": k, "lines": v["lines"], "would_drop_lines": v["drop_lines"],
                         "would_drop_bytes": v["drop_bytes"]} for k, v in ranked],
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default=None)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--report", default=None, help="write the JSON report to this NEW file (never the spine)")
    a = ap.parse_args(argv)
    if a.path:
        path = Path(a.path)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts.lib.cross_asset.security_research_spine import default_path
        path = default_path()
    out = analyse(path, top=a.top)
    text = json.dumps(out, indent=1, sort_keys=True)
    if a.report:
        rp = Path(a.report)
        if rp.resolve() == path.resolve() or rp.exists():
            print("refusing: --report must be a new file, never the spine", file=sys.stderr)
            return 2
        rp.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
