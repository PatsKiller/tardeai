#!/usr/bin/env python3
"""Backfill stored Ticker Prospectuses into the CIO memory (operator 2026-10-26: "I need to ensure that this is
also in the CIO memory. Very important.").

New versions are written by ``prospectus_build.py --apply`` right after they are stored. This command lands the
versions that already exist. Dry run is the default: it reads the private prospectus store and the spine, and
prints what would be written; nothing is written.

    python3 scripts/prospectus_cio_memory.py                       # dry run, every stored version
    python3 scripts/prospectus_cio_memory.py --symbols AAA,BBB     # dry run, named symbols
    python3 scripts/prospectus_cio_memory.py --apply               # write (idempotent by symbol + version)
    python3 scripts/prospectus_cio_memory.py --apply --latest-only # newest version per symbol only

Writes go only through ``security_research_spine.upsert_research_memory`` (CIO-owned, registry GUID required)
plus a ``research_write_path`` receipt (lane ``prospectus-writer``). READ_ONLY_ADVISORY (MBI_BEHAVIOR=0).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import load_config, store  # noqa: E402
from scripts.lib.prospectus.cio_memory import backfill  # noqa: E402


def state_root() -> Path:
    from scripts.lib.anthropic_routing import state_root as resolve
    return Path(resolve())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill stored prospectuses into the CIO memory (dry run by default).")
    ap.add_argument("--apply", action="store_true", help="write to the CIO memory (default: dry run)")
    ap.add_argument("--symbols", default="", help="comma-separated symbols (default: every stored symbol)")
    ap.add_argument("--latest-only", action="store_true", help="only the newest version per symbol")
    ap.add_argument("--verbose", action="store_true", help="print every row")
    args = ap.parse_args(argv)
    root = state_root()
    base = store.base_dir(root, load_config())
    symbols = [s for s in args.symbols.split(",") if s.strip()] or None
    out = backfill(base, root=root, apply=args.apply, symbols=symbols, latest_only=args.latest_only)
    if not args.verbose:
        out["rows"] = [r for r in out["rows"] if r["outcome"] not in ("written", "would_write", "exists")] \
            + out["rows"][:3]
    out["state_root"] = str(root)
    print(json.dumps(out, indent=2, default=str))
    bad = sum(v for k, v in out["counts"].items() if k in ("error",))
    return 1 if bad else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
