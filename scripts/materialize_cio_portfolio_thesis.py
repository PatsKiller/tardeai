#!/usr/bin/env python3
"""Materialize one governed CIOPortfolioThesis@v1 from canonical read-only inputs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import api_v3_cio as cio_api  # noqa: E402
from scripts.lib.cio_portfolio_thesis_v1 import (  # noqa: E402
    build_portfolio_thesis_candidate,
    load_symbol_thesis_refs,
    reconcile_portfolio_thesis,
)


def materialize(*, store_path: Path, projection_path: Path) -> dict:
    policy = cio_api.get_operator_investment_policy()["policy"]
    portfolio = cio_api.get_portfolio_state_v1()["portfolio_state"]
    market = cio_api.get_market_context_state_v1()["market_context"]
    seasonality = cio_api.get_seasonality_state_v1()["seasonality"]
    held = {
        str(row.get("symbol") or "").upper()
        for row in portfolio.get("positions") or []
        if row.get("asset_class") != "CASH"
    }
    symbol_refs = load_symbol_thesis_refs(projection_path, held)
    candidate = build_portfolio_thesis_candidate(
        policy=policy,
        portfolio_state=portfolio,
        market_context=market,
        seasonality=seasonality,
        symbol_theses=symbol_refs,
    )
    return reconcile_portfolio_thesis(candidate, store_path=str(store_path))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--store",
        default=os.getenv("CIO_PORTFOLIO_THESIS_JSONL") or str(ROOT / "data/cio/cio_portfolio_theses.jsonl"),
    )
    parser.add_argument(
        "--symbol-projection",
        default=os.getenv("CIO_THESES_PROJECTION_JSON") or str(ROOT / "data/cio/cio_theses_projection.json"),
    )
    args = parser.parse_args()
    result = materialize(store_path=Path(args.store), projection_path=Path(args.symbol_projection))
    thesis = result.get("thesis") or {}
    delta = result.get("delta") or {}
    receipt = {
        "ok": True,
        "published": result.get("published"),
        "thesis_version": thesis.get("thesis_version"),
        "state": thesis.get("state"),
        "posture": thesis.get("current_posture"),
        "delta": delta.get("classification"),
        "reason_codes": delta.get("reason_codes"),
        "authority": result.get("authority"),
    }
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
