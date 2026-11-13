#!/usr/bin/env python3
"""n8n lane entrypoint for the generic product builder (DSN-20261112-PRECOMPUTE-CACHE; home-products, 13 Nov 2026).

``$PY scripts/cc_products_build.py --product <id> [--dry-run]``. Products: ``market_risk.latest``, ``risk``,
``reports.analyst_links``, ``home`` (``scripts/lib/cc_products/product_builder.py`` CATALOGUE).

* ``--dry-run`` (the only argv at stage shadow): host lock + slot, build in a forked child under RLIMIT_AS, measure,
  print the receipt JSON. Writes nothing (no PG row, no build-log row, no hot tier).
* no flag (after promotion): host lock + slot + PG try-lock, build, conditional publish of ``cc_product_current`` +
  a ``cc_product_build_log`` receipt in one transaction, then the hot tier.

Never imports ``api_v2``. No broker, no order, no AI call (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cc_products import product_builder  # noqa: E402

if __name__ == "__main__":
    sys.exit(product_builder.main())
