#!/usr/bin/env python3
"""Mint durable entity identities for every symbol the system reasons about.

Phase A of the identity/memory advisory. Reads the symbols already flowing
through the system, resolves each once through the existing
`security_identity.resolve_identity_spine()`, and persists the result to the
`identity.registry` store so it can be read back instead of recomputed.

    python scripts/mint_identity_registry.py            # dry run (default)
    python scripts/mint_identity_registry.py --json
    python scripts/mint_identity_registry.py --apply    # write the registry

Scope is holdings and the watch universe — the symbols decisions are actually
made about. The 6,000+ symbols in `ticker_prices` are deliberately excluded:
minting an identity for a ticker nothing reasons about produces a registry that
is mostly noise, and the spine can always be resolved on demand for a symbol
that later becomes interesting.

Nothing here invents an identifier. A symbol with only a name resolves to a
CANDIDATE issuer identity; a symbol with a CUSIP/ISIN/FIGI resolves to a
CONFIRMED one; a symbol with neither is registered honestly as
UNRESOLVED_WITH_REASON against its ticker alias. Upgrades preserve the old GUID
as a superseded alias so history stays traversable — see `identity_registry`.

AUTHORITY: READ_ONLY_ADVISORY. Identity only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib.identity_registry import load, lookup_symbol, register_all  # noqa: E402
from scripts.lib.security_identity import normalize_symbol  # noqa: E402


def _holdings_rows() -> list[dict]:
    """Positions carry `name` for every row, which yields a CANDIDATE issuer."""
    try:
        from scripts.lib.canonical_store_registry import resolve_store
        path = Path(resolve_store("portfolio.holdings.current")["path"])
    except Exception:
        path = Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "portfolios" / "state" / "holdings.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    positions = doc.get("holdings") or doc.get("positions") or []
    if isinstance(positions, dict):
        positions = list(positions.values())
    rows = []
    for p in positions:
        if not isinstance(p, dict) or p.get("is_cash"):
            continue
        sym = normalize_symbol(p.get("symbol"))
        if not sym:
            continue
        ids = {k: p[k] for k in ("cusip", "isin", "figi") if p.get(k)}
        rows.append({
            "symbol": sym,
            "company": p.get("company") or p.get("name"),
            "cik": p.get("cik"),
            "exchange": p.get("exchange"),
            "identifiers": ids,
            "source": "holdings",
        })
    return rows


def _watchlist_rows() -> list[dict]:
    """Active watch universe. Absent Postgres this simply contributes none.

    Scoped to `status = 'active'` deliberately. The table holds 11,729 distinct
    symbols, of which 7,197 are `removed` and 5,113 `researched` -- registering
    all of them mints ~11,700 entities that carry nothing but a ticker alias and
    buries the few hundred the system actually reasons about. A symbol that
    becomes active later is picked up on the next run; registration is
    incremental and idempotent, so nothing is lost by waiting.
    """
    try:
        from price_db_sync import _get_conn  # type: ignore
        conn = _get_conn()
    except Exception:
        return []
    rows = []
    try:
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT symbol FROM watchlist_items
                       WHERE symbol IS NOT NULL AND symbol <> ''
                         AND status = 'active'""")
        for (sym,) in cur.fetchall():
            s = normalize_symbol(sym)
            if s:
                rows.append({"symbol": s, "source": "watchlist"})
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return rows


def _identifier_rows() -> list[dict]:
    """Durable identifiers the brokers already gave us and nothing consumed.

    Schwab e-confirms carry a real CUSIP per traded symbol. That is exactly what
    lifts an entity from a name-derived CANDIDATE identity to a CONFIRMED one, and
    it has been sitting in `econfirm_evidence` unused. Read it rather than ask a
    vendor for something we already hold.
    """
    try:
        from price_db_sync import _get_conn  # type: ignore
        conn = _get_conn()
    except Exception:
        return []
    rows = []
    try:
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT UPPER(symbol), cusip FROM econfirm_evidence
                       WHERE symbol IS NOT NULL AND symbol <> ''
                         AND cusip IS NOT NULL AND cusip <> ''""")
        for sym, cusip in cur.fetchall():
            rows.append({"symbol": sym, "identifiers": {"cusip": str(cusip).strip()},
                         "source": "econfirm"})
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return rows


def collect_rows() -> list[dict]:
    """Holdings first: a held position's richer row should win the merge."""
    merged: dict[str, dict] = {}
    for row in _holdings_rows() + _watchlist_rows() + _identifier_rows():
        sym = row["symbol"]
        if sym in merged:
            for k, v in row.items():
                if k == "identifiers" and isinstance(v, dict):
                    # Union, never replace: holdings supply the name, e-confirms
                    # supply the CUSIP, and an entity needs both to reach CONFIRMED.
                    merged[sym].setdefault("identifiers", {}).update(
                        {ik: iv for ik, iv in v.items() if iv}
                    )
                elif v and not merged[sym].get(k):
                    merged[sym][k] = v
        else:
            merged[sym] = dict(row)
    return list(merged.values())


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint the durable identity registry (Phase A)")
    ap.add_argument("--apply", action="store_true", help="write the registry (default: dry run)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--symbol", default=None, help="show the registered identity for one symbol")
    args = ap.parse_args()

    if args.symbol:
        ent = lookup_symbol(load(), args.symbol)
        print(json.dumps(ent, indent=2, sort_keys=True) if ent
              else f"{normalize_symbol(args.symbol)}: not registered")
        return 0

    rows = collect_rows()
    summary = register_all(rows, apply=args.apply)

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"{'APPLY' if args.apply else 'DRY RUN'} — {summary['rows_seen']} symbol(s)")
        print(f"  entities   {summary['entities_before']} → {summary['entities_after']}"
              f"  (+{summary['entities_added']})")
        print(f"  by status  {summary['by_identity_status']}")
        print(f"  symbols    {summary['symbols_indexed']} indexed")
        print(f"  registry   {summary['path']}")
        if not args.apply:
            print("\nnothing written. re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
