#!/usr/bin/env python3
"""Materialize one governed CIOPortfolioThesis@v1 from canonical read-only inputs.

Lane ``cio-portfolio-thesis`` (n8n dispatcher row, stage shadow; operator "yes rebuild 1417",
2026-10-21). Deterministic: no model, no provider, no send. Inputs are read-only
(``scripts/lib/cio_portfolio_thesis_inputs.py``: policy, holdings, cash evidence and canon files, and a
READ ONLY PostgreSQL session for the market context and seasonality).

    python scripts/materialize_cio_portfolio_thesis.py --dry-run   # report only, writes nothing
    python scripts/materialize_cio_portfolio_thesis.py              # publish if the delta is new

A real run appends at most one PORTFOLIO_THESIS_PUBLISHED record to the thesis store (none when the
delta is NO_NEW_INFO, so a second run is idempotent) and writes the LaneRunReceipt
``<state_root>/data/runtime/cio-portfolio-thesis_last.json`` (``produced_count`` = records published).
``--dry-run`` builds the same candidate and classifies it against the latest published thesis without
taking the store lock, creating a directory, appending or writing the receipt.

Exit codes: 0 = ran (NO_NEW_INFO is a success); 1 = the run failed (receipt ``failed``); 2 = usage.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_portfolio_thesis_inputs as inputs  # noqa: E402
from scripts.lib import lane_last_receipt as lr  # noqa: E402
from scripts.lib.cio_portfolio_thesis_v1 import (  # noqa: E402
    build_portfolio_thesis_candidate,
    classify_portfolio_thesis_delta,
    load_latest_portfolio_thesis,
    load_symbol_thesis_refs,
    reconcile_portfolio_thesis,
)

LANE_ID = "cio-portfolio-thesis"


def build_candidate(*, projection_path: Path) -> dict:
    portfolio = inputs.load_portfolio_state()
    held = {
        str(row.get("symbol") or "").upper()
        for row in portfolio.get("positions") or []
        if row.get("asset_class") != "CASH"
    }
    return build_portfolio_thesis_candidate(
        policy=inputs.load_policy(),
        portfolio_state=portfolio,
        market_context=inputs.load_market_context(),
        seasonality=inputs.load_seasonality(),
        symbol_theses=load_symbol_thesis_refs(projection_path, held),
        methodology_refs=inputs.ratified_methodology_refs(),
    )


def materialize(*, store_path: Path, projection_path: Path) -> dict:
    return reconcile_portfolio_thesis(build_candidate(projection_path=projection_path), store_path=str(store_path))


def preview(*, store_path: Path, projection_path: Path) -> dict:
    """Read-only: what a real run would publish. No lock file, no mkdir, no append."""
    candidate = build_candidate(projection_path=projection_path)
    prior = load_latest_portfolio_thesis(str(store_path)) if store_path.is_file() else None
    delta = classify_portfolio_thesis_delta(prior, candidate)
    return {"published": False, "would_publish": delta.get("classification") != "NO_NEW_INFO",
            "thesis": candidate, "prior_version": (prior or {}).get("thesis_version"), "delta": delta}


def _summary(result: dict) -> dict:
    thesis = result.get("thesis") or {}
    delta = result.get("delta") or {}
    return {
        "published": result.get("published"),
        "thesis_version": thesis.get("thesis_version"),
        "state": thesis.get("state"),
        "posture": thesis.get("current_posture"),
        "delta": delta.get("classification"),
        "reason_codes": delta.get("reason_codes"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=None, help="thesis store (default: CIO_PORTFOLIO_THESIS_JSONL or data/cio)")
    parser.add_argument("--symbol-projection", default=None,
                        help="symbol thesis projection (default: CIO_THESES_PROJECTION_JSON or data/cio)")
    parser.add_argument("--dry-run", action="store_true", help="report what would publish; write nothing")
    args = parser.parse_args(argv)
    store = Path(args.store) if args.store else inputs.portfolio_thesis_store()
    projection = Path(args.symbol_projection) if args.symbol_projection else inputs.symbol_thesis_projection_path()

    if args.dry_run:
        result = preview(store_path=store, projection_path=projection)
        summary = {**_summary(result), "would_publish": result["would_publish"],
                   "prior_version": result["prior_version"]}
        lr.dry_run_report(LANE_ID, summary, would_write=(
            [f"{store} PORTFOLIO_THESIS_PUBLISHED (append)"] if result["would_publish"] else []))
        return 0

    started = datetime.now(timezone.utc).isoformat()
    try:
        result = materialize(store_path=store, projection_path=projection)
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="materialize_cio_portfolio_thesis.py",
                              error=f"{type(exc).__name__}: {exc}")
        print(json.dumps({"ok": False, "error": type(exc).__name__}, sort_keys=True))
        return 1
    summary = _summary(result)
    published = 1 if result.get("published") else 0
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="materialize_cio_portfolio_thesis.py", summary=summary,
                          output={"produced_count": published, "attempted_count": 1,
                                  "empty_reason": None if published else "no_new_input"})
    print(json.dumps({"ok": True, **summary, "authority": result.get("authority")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
