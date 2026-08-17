#!/usr/bin/env python3
"""Export provider usage grouped by key when the source allows it.

  python scripts/provider_cost_export.py --start 2026-08-01 --end 2026-08-16 --group-by key --format json

Never prints raw API keys.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.provider_cost.export import export_by_key  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--group-by", default="key", choices=["key", "model", "day"])
    ap.add_argument("--format", default="json", choices=["json"])
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--operator-export", default=None, help="Optional CSV/JSON from the vendor console")
    args = ap.parse_args()
    result = export_by_key(
        start=args.start,
        end=args.end,
        provider=args.provider,
        operator_export=Path(args.operator_export) if args.operator_export else None,
    )
    print(json.dumps(result, indent=2, default=str))
    # KEY_ATTRIBUTION_UNAVAILABLE is a successful fail-closed result.
    if result.get("ok") or result.get("status") == "KEY_ATTRIBUTION_UNAVAILABLE":
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
