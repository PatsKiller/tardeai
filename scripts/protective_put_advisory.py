#!/usr/bin/env python3
"""Print per-contract advisory economics over a snapshot; never select a quantity or place an order.

The default holdings path is owned by lib.portfolio_positions. Explicit fixture paths are
supported by --holdings; --events and --chains are optional injected JSON snapshots.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import portfolio_positions as pp  # noqa: E402
from lib.options_pipeline.protective_put_advisory import (  # noqa: E402
    SCHEMA,
    load_config,
    position_value,
    suggest_for_book,
)


def _load(path: str | None) -> object:
    """The sanctioned reader preserves missing/damaged/non-object evidence."""
    document, status = pp.read_store_document(Path(path) if path is not None else None)
    if status != "ok":
        raise ValueError(f"holdings snapshot is {status}")
    return document


def _positions(document: object) -> list[dict]:
    if not isinstance(document, dict):
        raise ValueError("holdings snapshot must be an object")
    rows = document.get("holdings") if "holdings" in document else document.get("positions")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("holdings snapshot must supply a list of position objects")
    return rows


def _load_json(path: str | None) -> dict:
    if path is None:
        return {}
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or any(not isinstance(value, dict) for value in document.values()):
        raise ValueError("events/chains snapshot must map symbols to objects")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", help="snapshot path (default: sanctioned position store)")
    parser.add_argument("--events", help="JSON {symbol: {event_date, days_to_event}}")
    parser.add_argument("--chains", help="JSON {symbol: {expirations:[...]}}")
    parser.add_argument(
        "--book-value", type=float, help="authoritative whole-book value; required if any snapshot position is unvalued"
    )
    parser.add_argument("--config", help="default: repository config/protective_put_advisory.json")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    source = "holdings"
    try:
        positions = _positions(_load(args.holdings))
        source = "config"
        cfg = load_config(args.config)
        source = "events/chains"
        events, chains = _load_json(args.events), _load_json(args.chains)
        source = "book_value"
        values = [position_value(row) for row in positions]
        if args.book_value is None:
            if any(value is None for value in values):
                raise ValueError("implicit book valuation is incomplete; supply an authoritative --book-value")
            try:
                book = round(math.fsum(values), 2)
            except OverflowError as exc:
                raise ValueError("implicit book valuation is not finite") from exc
            basis = "complete_snapshot_sum"
        else:
            book = args.book_value
            basis = "explicit"
        if not math.isfinite(book) or book < 0 or (book == 0 and any(v is not None and v > 0 for v in values)):
            raise ValueError("book value must be finite and positive when holdings have positive value")
    except (OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"schema": SCHEMA, "status": "unavailable", "input": source, "reason": str(exc)}))
        else:
            print(f"Advisory unavailable ({source}): {exc}", file=sys.stderr)
        return 2
    report = suggest_for_book(positions, book_value=book, events=events, chains=chains, cfg=cfg)
    report["book_value_basis"] = basis
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(
        f"{SCHEMA}: {len(report['suggestions'])} per-contract research result(s) for {report['examined']} position(s)"
    )
    print("ADVISORY ONLY — contract quantity is not selected; the operator alone chooses any coverage.")
    for row in report["suggestions"]:
        print(
            f"\n  {row['symbol']}: cost ${row['cost_per_contract_usd']:,.2f} per contract"
            + (" (LABELED ESTIMATE)" if row["cost_is_estimate"] else " (quoted ask)")
        )
        print(f"    Target: ${row['floor_target']:,.2f} ({row['floor_basis']})")
        if row["floor_price"] is not None:
            print(f"    Quoted put strike: ${row['floor_price']:,.2f}; expiry {row['expiry']}")
        if row["floor_per_covered_share_after_premium"] is not None:
            print(f"    Per covered share after premium: ${row['floor_per_covered_share_after_premium']:,.2f}")
        print("    No position-wide floor: coverage quantity is not selected.")
        print(f"    {row['cost_basis']}")
        if row.get("floor_warning"):
            print(f"    Warning: {row['floor_warning']}")
        if row.get("collar_per_contract"):
            collar = row["collar_per_contract"]
            print(
                f"    Collar unit: cap ${collar['cap_price']:,.2f}; net cost "
                f"${collar['net_cost_per_contract_usd']:,.2f} per contract; requires 100 owned shares per short call."
            )
        if row.get("collar_unavailable_reason"):
            print(f"    Collar unavailable: {row['collar_unavailable_reason']}")
    for row in report["skipped"]:
        print(f"  {row['symbol']}: {row['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
