#!/usr/bin/env python3
"""protective_put_advisory.py — print the D32 §5 advisory suggestions for a holdings snapshot.

Read-only by construction: it reads a holdings document and optional event/chain snapshots and
prints the suggestions. It never writes a store, never calls a broker, and there is no flag that
makes it place anything (AGENTS.md §0 rule 1, MBI_BEHAVIOR = 0).

    .venv/bin/python scripts/protective_put_advisory.py --holdings data/portfolios/state/holdings.json
    .venv/bin/python scripts/protective_put_advisory.py --holdings H --events E --chains C --json

Book value defaults to the summed position market values when the holdings document does not carry
an account-level total. ``--book-value`` overrides it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline.protective_put_advisory import (  # noqa: E402
    SCHEMA,
    load_config,
    position_value,
    suggest_for_book,
)

DEFAULT_HOLDINGS = ROOT / "data" / "portfolios" / "state" / "holdings.json"


def _load(path: str | None) -> object:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _positions(doc: object) -> list[dict]:
    if isinstance(doc, dict):
        rows = doc.get("holdings") if isinstance(doc.get("holdings"), list) else doc.get("positions")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    if isinstance(doc, list):
        return [row for row in doc if isinstance(row, dict)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--holdings", default=str(DEFAULT_HOLDINGS), help="holdings document (default: %(default)s)")
    parser.add_argument("--events", help="JSON {symbol: {event_date, days_to_event}}")
    parser.add_argument("--chains", help="JSON {symbol: {underlying_price, expirations:[...]}}")
    parser.add_argument("--book-value", type=float, help="whole-book value (default: sum of market values)")
    parser.add_argument("--config", help="advisory config JSON (default: config/protective_put_advisory.json)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    try:
        holdings_doc = _load(args.holdings)
    except (OSError, ValueError) as exc:
        print(f"cannot read holdings {args.holdings}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    positions = _positions(holdings_doc)
    book = args.book_value
    if book is None:
        values = [position_value(row) or 0.0 for row in positions]
        book = round(sum(values), 2) if values else 0.0

    try:
        events_doc = _load(args.events) if args.events else {}
        chains_doc = _load(args.chains) if args.chains else {}
    except (OSError, ValueError) as exc:
        print(f"cannot read events/chains: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    report = suggest_for_book(
        positions,
        book_value=book,
        events=events_doc if isinstance(events_doc, dict) else {},
        chains=chains_doc if isinstance(chains_doc, dict) else {},
        cfg=load_config(args.config),
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(f"{SCHEMA}: {len(report['suggestions'])} suggestion(s) for {report['examined']} position(s); "
          f"book ${report['book_value'] if 'book_value' in report else book:,.0f}")
    print("ADVISORY ONLY — the system never places, sizes, stops or cancels an order.")
    for row in report["suggestions"]:
        print(f"\n  {row['symbol']} ({row['account']}) — {row['pct_of_book']:.2f}% of book, "
              f"${row['position_value']:,.0f}")
        print(f"    Protective put: floor ${row['floor_price']:,.2f} ({row['floor_basis']}), "
              f"cost ${row['cost_usd']:,.2f}" + (" (LABELED ESTIMATE)" if row["cost_is_estimate"] else ""))
        if row.get("collar"):
            c = row["collar"]
            print(f"    Collar option: cap ${c['cap_price']:,.2f}, net cost ${c['net_cost_usd']:,.2f}"
                  + (" (net credit)" if c["net_is_credit"] else ""))
        print(f"    Event: {(row['event'] or {}).get('date')} ({(row['event'] or {}).get('days_to_event')} days)")
        print(f"    {row['operator_action']}")
    if report["skipped"]:
        print("\n  Not suggested:")
        for row in report["skipped"]:
            print(f"    {row['symbol']}: {row['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
