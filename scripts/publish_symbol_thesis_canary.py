#!/usr/bin/env python3
"""CLI: dry-run (default) canary publish for SCHG / CSCO / ANET.

  python scripts/publish_symbol_thesis_canary.py
  python scripts/publish_symbol_thesis_canary.py --symbols SCHG
  CANARY_THESIS_APPLY=1 python scripts/publish_symbol_thesis_canary.py --apply

Never run --apply against production from agent sessions unless the env/flag is set.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--symbols", nargs="*", default=None, help="Subset of SCHG CSCO ANET")
    ap.add_argument("--apply", action="store_true", help="Publish only if CANARY_THESIS_APPLY=1")
    args = ap.parse_args()
    from scripts.lib.symbol_thesis_canary import plan_canary_publish
    out = plan_canary_publish(
        args.symbols,
        root=Path(args.root),
        apply=bool(args.apply),
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if not out.get("apply_blocked") else 2


if __name__ == "__main__":
    raise SystemExit(main())
