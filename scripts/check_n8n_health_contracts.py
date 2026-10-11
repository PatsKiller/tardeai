#!/usr/bin/env python3
"""check_n8n_health_contracts.py — no lane enters n8n without a workflow health contract.

Gate for ``config/n8n_health_contracts.json`` (N8nHealthContract@v1; rules in
``scripts/lib/n8n_health_contracts.py``). It fails when:

* a lane at ``scheduler.stage`` shadow / canary / cutover, a ``dispatch`` block not ``off``, a staged ``r1_pending``
  row, a per-lane ``kind: n8n`` row, a host monitor of the n8n chain, or one of the six generic workflows has no
  contract (MISSING_CONTRACT);
* a contract has an empty purpose, owner, connects_to, healthy, degraded or failed list, no baseline basis, no
  review date for a provisional baseline, or no notifier priority (INVALID_CONTRACT);
* a DRAFT contract belongs to a lane that was not grandfathered on 2026-10-10 (DRAFT_NOT_GRANDFATHERED);
* a lane at canary or cutover has a contract that is not REVIEWED or still carries UNKNOWN (DRAFT_AT_LIVE_STAGE);
* a lane contract names no registry row (ORPHAN_CONTRACT).

    python3 scripts/check_n8n_health_contracts.py [--json] [--contracts PATH] [--registry PATH]

Exit 0 = pass, 1 = a rule failed, 2 = a file could not be read. Reads three files; writes nothing.
Procedure: docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md §3.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import n8n_health_contracts as H  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--contracts", default=str(H.CONTRACTS_PATH))
    ap.add_argument("--registry", default=str(H.REGISTRY_PATH))
    ap.add_argument("--index", default=str(H.GENERIC_INDEX_PATH))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        doc = H.load_json(Path(args.contracts))
        reg = H.load_json(Path(args.registry))
        idx = H.load_json(Path(args.index))
    except (OSError, ValueError) as exc:
        print(f"check_n8n_health_contracts: cannot read: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    res = H.check(doc, reg, idx)
    if args.json:
        print(json.dumps(res, indent=1))
    else:
        for e in res["errors"]:
            print(f"  ✗ {e}")
        for w in res["warnings"]:
            print(f"  ! {w}")
        print(f"n8n health contracts: {'FAILED' if res['errors'] else 'clean'} {json.dumps(res['counts'])}")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
