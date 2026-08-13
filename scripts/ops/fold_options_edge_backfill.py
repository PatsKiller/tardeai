#!/usr/bin/env python3
"""Backfill options_edge_score onto watchlist underlyings.

Sources (priority):
  1) options_paper_outcomes (closed paper)
  2) options_approval_queue.edge_score (prime-rubric proposals)
  3) options_iv_history → IV rank vs peers

Advisory only. Safe to re-run.

  .venv/bin/python scripts/ops/fold_options_edge_backfill.py
  .venv/bin/python scripts/ops/fold_options_edge_backfill.py --limit 500
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
        env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if not k or not (k[0].isalpha() or k[0] == "_") or not all(
            c.isalnum() or c == "_" for c in k
        ):
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        os.environ.setdefault(k, v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    _load_env()

    from lib.options_pipeline.validation import backfill_options_edge_universe

    out = backfill_options_edge_universe(limit=args.limit)
    # Coverage snapshot
    try:
        from db_adapter import _execute
        cov = _execute(
            """SELECT count(*) FILTER (WHERE options_edge_score IS NOT NULL) AS with_edge,
                      count(*) AS active
               FROM watchlist_items WHERE status IN ('active','researched')""",
            fetch="one",
        )
        if cov:
            row = cov if isinstance(cov, dict) else {"with_edge": cov[0], "active": cov[1]}
            if isinstance(cov, (list, tuple)) and cov and isinstance(cov[0], dict):
                row = cov[0]
            out["coverage"] = {
                "with_options_edge": row.get("with_edge") if isinstance(row, dict) else None,
                "active_researched": row.get("active") if isinstance(row, dict) else None,
            }
    except Exception as exc:
        out["coverage_error"] = str(exc)[:120]
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
