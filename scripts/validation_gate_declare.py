#!/usr/bin/env python3
"""validation-gate-declare: write the release's ValidationGateDecl@v1 files (LQ-20261107-2966).

Default is a DRY RUN: it prints what it would write and touches nothing. ``--apply`` writes the missing declaration
files into <state>/data/coordination/validation_gates/inbox/ (atomic rename); validation-gates-sync ingests them.
Run it once per release (a re-run is a no-op); a catalog edit of a declared gate is reported as DRIFT and exits 2.

AUTHORITY: files only. No DB, no broker, no credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from lib import validation_gate_producer as P  # noqa: E402

CATALOG_REL = "config/validation_gate_declarations.json"
QUERIES_REL = "config/validation_gate_queries.json"


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the missing declaration files (default: dry run)")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    root = state_root()
    try:
        catalog = json.loads((HERE.parent / CATALOG_REL).read_text(encoding="utf-8"))
        queries = json.loads((HERE.parent / QUERIES_REL).read_text(encoding="utf-8")).get("queries", {})
        decls = P.build_decls(catalog, queries=queries, now=now)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}))
        return 1
    rows = P.plan(decls, root=root)
    written = P.write_pending(decls, rows, root=root) if args.apply else []
    drift = [r for r in rows if r["action"] == "drift"]
    print(json.dumps({"mode": "apply" if args.apply else "dry_run", "state_root": str(root), "gates": rows,
                      "written": [str(p) for p in written], "drift": len(drift)}, indent=1))
    return 2 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
