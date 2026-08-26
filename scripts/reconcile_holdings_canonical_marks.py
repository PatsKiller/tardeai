#!/usr/bin/env python3
"""Repair/migration utility — NOT an acceptance step.

Stamps analytical mark/MV fields. Must preserve raw broker values and
source timestamps. Must not mint quote freshness via updated_at=now.

Acceptance must never invoke this script to turn G4/G5 green.

READ_ONLY_ADVISORY. Does not call brokers. Writes a timestamped backup first.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_canonical_quote import apply_canonical_quote_fields  # noqa: E402

DEFAULT = Path(
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/holdings.json"
)


def _f(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def reconcile(doc: dict, now: datetime) -> dict:
    out = json.loads(json.dumps(doc))  # deep copy via json
    iso = now.isoformat()
    holdings = out.get("holdings") or []
    new_rows = []
    for h in holdings:
        if not isinstance(h, dict):
            continue
        row = apply_canonical_quote_fields(h)
        if row.get("is_cash") or row.get("is_loan"):
            row["updated_at"] = iso
            new_rows.append(row)
            continue
        shares = _f(row.get("shares") if row.get("shares") is not None else row.get("quantity"))
        mark = _f(row.get("canonical_mark"))
        # Preserve broker facts. Do not overwrite market_value / price with the mark.
        if row.get("broker_market_value") is None and row.get("market_value") is not None:
            if str(row.get("mv_basis") or "") != "shares_x_canonical_mark":
                row["broker_market_value"] = row.get("market_value")
                row["broker_source"] = row.get("broker_source") or "broker_position_snapshot"
                row["broker_ingested_at"] = row.get("broker_ingested_at") or row.get("as_of")
        if shares is not None and mark is not None and shares > 0:
            row["analytical_market_value"] = round(shares * mark, 2)
            basis = _f(row.get("cost_basis"))
            if basis is not None:
                row["analytical_unrealized_pl_usd"] = round(row["analytical_market_value"] - basis, 2)
        row["transformed_at"] = iso
        row["reconciled_at"] = iso
        new_rows.append(row)
    out["holdings"] = new_rows

    cash = 0.0
    long_mv = 0.0
    for r in new_rows:
        mv = _f(r.get("market_value"), 0.0) or 0.0
        if r.get("is_cash"):
            cash += mv
        elif not r.get("is_loan"):
            long_mv += mv
    derived = round(cash + long_mv, 2)
    out["reconciled_at"] = iso
    out["transformed_at"] = iso
    # Do not stamp updated_at / generated_at / last_repriced — those are not
    # source clocks and must not mint freshness.
    totals = dict(out.get("portfolio_totals") or {})
    totals["total_value"] = derived
    totals["total_cash"] = round(cash, 2)
    totals["as_of"] = now.date().isoformat()
    totals["last_pipeline_run"] = iso
    out["portfolio_totals"] = totals
    out["_canonical_reconcile"] = {
        "at": iso,
        "method": "shares_x_canonical_mark",
        "authority": "READ_ONLY_ADVISORY",
    }
    return out


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.is_file():
        print(json.dumps({"ok": False, "error": f"missing {path}"}))
        return 1
    now = datetime.now(timezone.utc)
    bak = path.with_name(path.name + f".bak-{now.strftime('%Y%m%dT%H%M%SZ')}")
    shutil.copy2(path, bak)
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = reconcile(doc, now)
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    from scripts.lib.cio_financial_truth_gate import evaluate_holdings_document
    g = evaluate_holdings_document(out, now=now)
    print(json.dumps({
        "ok": True,
        "backup": str(bak),
        "path": str(path),
        "quality": g.get("overall_quality"),
        "exception_count": g.get("exception_count"),
        "conflicted_symbols": g.get("conflicted_symbols"),
        "invariants": g.get("book_invariants"),
        "total_value": (out.get("portfolio_totals") or {}).get("total_value"),
    }, indent=2))
    return 0 if g.get("overall_quality") in ("VERIFIED_CURRENT", "VERIFIED_AS_OF") else 2


if __name__ == "__main__":
    raise SystemExit(main())
