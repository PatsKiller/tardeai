#!/usr/bin/env python3
"""P2-WS4 / P2-WS5 identity confidence + position-state census (read-only).

  python scripts/cio_identity_confidence_census.py --json
  python scripts/cio_identity_confidence_census.py --json --root /path/to/CURRENT
  python scripts/cio_identity_confidence_census.py --json --identity-only

READ_ONLY_ADVISORY. MBI=0. Never mints. Never deletes lots. Never writes.
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
    ap = argparse.ArgumentParser(
        description="CIO identity confidence census — read-only measure"
    )
    ap.add_argument("--root", default=str(LIVE), help="data root (default: CURRENT)")
    ap.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="emit JSON (default; always on for this census)",
    )
    ap.add_argument(
        "--identity-only",
        action="store_true",
        help="skip position-state matrix (WS5)",
    )
    ap.add_argument("--out", default="", help="optional write path (still prints)")
    a = ap.parse_args()

    # Collectors that omit root fall back to resolve_root() = import checkout.
    # Point TRADEAI_ROOT at the live data root so dry runs measure CURRENT.
    os.environ.setdefault("TRADEAI_ROOT", a.root)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))

    from scripts.lib.cio_identity_confidence_census import run_census

    root = Path(a.root)
    out = run_census(root=root, include_position_state=not a.identity_only)
    text = json.dumps(out, indent=2, default=str)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
