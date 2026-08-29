#!/usr/bin/env python3
"""Dry identity coverage (slice 13) and register list (slice 14). No mint by default.

  python scripts/cio_identity_coverage.py                       # measure, dry
  python scripts/cio_identity_coverage.py --register            # dry would_register
  python scripts/cio_identity_coverage.py --register --apply    # writes, cap 30
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")


def main() -> int:
    ap = argparse.ArgumentParser(description="CIO identity coverage — read-only measure")
    ap.add_argument("--root", default=str(LIVE), help="data root (default: CURRENT)")
    ap.add_argument("--register", action="store_true", help="also dry the slice-14 register list")
    ap.add_argument("--apply", action="store_true", help="write the register list (cap 30)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    # Several collectors take no `root` and fall back to resolve_root(), which is
    # the checkout the code was imported from — empty in a build worktree. Point
    # it at the data root so a dry run measures CURRENT and not an empty tree.
    os.environ.setdefault("TRADEAI_ROOT", a.root)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from scripts.lib.cio_identity_coverage import (
        apply_registerable,
        collect_registerable,
        measure_identity_coverage,
    )
    from scripts.lib.cio_investment_product import build_product

    root = Path(a.root)
    product = build_product(root=root)
    out: dict = {"root": str(root), "coverage": measure_identity_coverage(product=product, root=root)}

    if a.register or a.apply:
        dry = collect_registerable(product=product, root=root)
        out["register_dry"] = {k: v for k, v in dry.items() if k != "would_register"}
        out["register_dry"]["would_register"] = [r["symbol"] for r in dry["would_register"]]
        if a.apply:
            out["register_apply"] = apply_registerable(dry, root=root, apply=True)

    text = json.dumps(out, indent=2, default=str)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
