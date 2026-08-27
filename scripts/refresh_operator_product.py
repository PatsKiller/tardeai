#!/usr/bin/env python3
"""Persist the canonical operator product so its fallback stays fresh.

`cio.operator_product.current` is a DERIVED_CURRENT_PROJECTION of
`cio.product.current`. Every consumer -- command centre, aegis, morning, eod,
telegram -- rebuilds it in memory with `persist=False`, so nothing in
production ever wrote the file: on 2026-08-27 both copies still carried an
Aug-26 mtime left by a deploy simulation.

That matters for exactly one reason. When the investment brief is unparseable,
`build_operator_product` returns INVALID_SCHEMA / DEGRADED and recovers
`last_valid_product` FROM THIS FILE, so the operator sees the last good product
instead of "no product on disk" (tests/test_r18_data_operator_convergence.py::
test_invalid_schema_is_not_empty). A registry entry nothing writes made that
safety net as old as the last simulation.

Writing an unavailable product would destroy the very snapshot being preserved.
It cannot happen here: both `unavailable()` returns in build_operator_product
(lines 170, 178) precede the persist block (line 288), so only an AVAILABLE
product is ever written. This script additionally refuses to persist anything
that does not come back AVAILABLE, so the guarantee holds if that order changes.

    python3 scripts/refresh_operator_product.py            # persist
    python3 scripts/refresh_operator_product.py --dry-run  # build only

AUTHORITY: READ_ONLY_ADVISORY. Writes a rebuildable projection; no financial act.
"""
from __future__ import annotations

SCHEDULED_ENTRYPOINT = "cron: 5 */6 * * * -- every 6h (wired 2026-08-27)"

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and report, write nothing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from scripts.lib.cio_operator_product import build_operator_product

    probe = build_operator_product(persist=False)
    status = probe.get("status")
    available = bool(probe.get("available"))

    receipt = {
        "schema": "OperatorProductRefresh@v1",
        "authority": "READ_ONLY_ADVISORY",
        "status": status,
        "available": available,
        "product_id": probe.get("product_id"),
        "as_of": probe.get("as_of"),
        "persisted": False,
        "persisted_path": None,
    }

    if not available:
        # Refuse rather than overwrite the last good snapshot with a stub --
        # that snapshot is the whole reason this file is kept current.
        receipt["skipped_reason"] = (
            f"product not AVAILABLE (status={status}); "
            "preserving the existing last-valid snapshot"
        )
    elif args.dry_run:
        receipt["skipped_reason"] = "dry-run"
    else:
        written = build_operator_product(persist=True)
        receipt["persisted"] = True
        receipt["persisted_path"] = written.get("persisted_path")
        receipt["product_id"] = written.get("product_id")

    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        if receipt["persisted"]:
            print(f"[operator-product] wrote {receipt['persisted_path']} "
                  f"product_id={receipt['product_id']}")
        else:
            print(f"[operator-product] not written — {receipt['skipped_reason']}")
    # A brief that is legitimately unavailable is not a job failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
