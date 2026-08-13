#!/usr/bin/env python3
"""Backfill options_edge_score onto watchlist underlyings from options_paper_outcomes.

Advisory only. No-op when the table is empty. Safe to re-run.

  .venv/bin/python scripts/ops/fold_options_edge_backfill.py
  .venv/bin/python scripts/ops/fold_options_edge_backfill.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
os.chdir(ROOT)


def _load_env() -> None:
    env_file = Path(os.environ.get("TRADEAI_ENV_FILE", f"/run/user/{os.getuid()}/tradeai/env"))
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if not k or not (k[0].isalpha() or k[0] == "_") or not all(c.isalnum() or c == "_" for c in k):
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        os.environ.setdefault(k, v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    _load_env()

    from db_adapter import _execute
    from lib.options_pipeline.validation import fold_options_to_underlying

    rows = _execute(
        """SELECT DISTINCT UPPER(symbol) AS symbol
           FROM options_paper_outcomes
           WHERE symbol IS NOT NULL
           ORDER BY 1
           LIMIT %s""",
        (args.limit,),
        fetch="all",
    ) or []
    folded = 0
    skipped = 0
    errors = []
    for r in rows:
        sym = r["symbol"] if isinstance(r, dict) else r[0]
        try:
            res = fold_options_to_underlying(str(sym))
            if res.get("folded"):
                folded += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append({"symbol": sym, "error": str(exc)[:120]})
    out = {
        "ok": True,
        "symbols_seen": len(rows),
        "folded": folded,
        "skipped": skipped,
        "errors": errors[:10],
        "note": "zero symbols is normal if options_paper_outcomes is empty",
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
