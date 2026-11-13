#!/usr/bin/env python3
"""n8n lane entrypoint for the ``cio.pages`` product builder (lane ``cio-pages-product``, LQ-20261107-2743).

The builder is ``scripts/lib/cc_products/cio_pages.py`` (LQ-2595). The run allowlist executes ``$PY <script>``
with the code root as cwd and has no ``-m`` form, so this file puts the code root on ``sys.path`` and hands the
argv to ``cio_pages.main`` with ``--lane cio-pages-product`` (the build log's lane column) unless one is given.

* ``--dry-run`` (the only argv the lane has at stage shadow): build in a forked child under RLIMIT_AS, measure,
  print the receipt JSON; writes nothing (no PG write, no hot tier, no lock).
* no flag (a live run, after promotion): try-lock, build, write ``cc_product_current`` + ``cc_product_build_log``
  in one transaction, then refresh the hot tier.

Never imports ``api_v2``. No broker, no order, no AI call (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cc_products import cio_pages  # noqa: E402

LANE_ID = "cio-pages-product"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], add_help=False)
    ap.add_argument("--dry-run", action="store_true", help="build and measure; write nothing (the shadow argv)")
    ap.add_argument("--lane", default=LANE_ID, help="build-log lane id (default %(default)s)")
    known, rest = ap.parse_known_args(list(sys.argv[1:] if argv is None else argv))
    # Every other flag (--root, --timeout, --rlimit-mb, --builder-sha, -h) is the builder's own and is passed on.
    return cio_pages.main((["--dry-run"] if known.dry_run else []) + rest + ["--lane", known.lane])


if __name__ == "__main__":
    sys.exit(main())
