#!/usr/bin/env python3
"""CLI: one-way isolated cognition shadow projection.

SHADOW_ONLY. Never production :5432. Never mutates JSONL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# G2: root-only + scripts.lib — never also put scripts/ on path
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    # G2: after imports settle — refuse dual lib.X / scripts.lib.X identity
    from scripts.lib import assert_single_import_identity
    assert_single_import_identity()
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=str(ROOT))
    p.add_argument("--apply-schema", action="store_true")
    p.add_argument("--replay", action="store_true")
    p.add_argument("--parity", action="store_true")
    p.add_argument("--dark-read", action="store_true")
    p.add_argument("--rebuild", action="store_true")
    args = p.parse_args(argv)
    from scripts.lib.memory_shadow_projector import (
        apply_schema, connect, dark_read, health, parity, project,
    )
    conn = connect()
    if args.apply_schema or args.rebuild:
        apply_schema(conn)
    r1 = project(args.root, conn=conn)
    r2 = None
    if args.replay:
        r2 = project(args.root, conn=conn)
        r1["replay_new_rows"] = max(0, r2["versions_after"] - r1["versions_after"])
        r1["replay"] = r2
    if args.parity:
        r1["parity"] = parity(args.root, conn=conn, symbols=["SCHD", "SCHG", "CSCO", "ANET", "NOC", "PRSO"])
    if args.dark_read:
        r1["dark_read"] = dark_read(args.root, ["SCHD", "SCHG", "CSCO", "ANET", "NOC", "PRSO"])
    r1["health"] = health(conn)
    r1["production_sql_applied"] = False
    print(json.dumps(r1, indent=2, default=str))
    conn.close()
    return 0 if r1.get("canonical_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
