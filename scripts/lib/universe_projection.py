"""Canonical explicit-membership universe projection.

This module reads existing stores and emits denominators; it owns no security
master and performs no financial or broker mutation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.lib.holdings_universe import held_position_rows, is_cash_row, is_held_equity_ticker
from scripts.lib.symbol_universe import reconcile_universe

SCHEMA = "UniverseProjection@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MEMBERSHIPS = (
    "HELD", "FORMER_HOLDING", "REENTRY", "WATCH", "PROPOSAL",
    "INCUBATOR", "COLD", "NON_TICKER/BOND",
)


def _query(sql: str) -> list[dict[str, Any]]:
    try:
        from scripts.db_adapter import _execute
    except Exception:
        try:
            from db_adapter import _execute  # type: ignore
        except Exception:
            return []
    try:
        return [dict(row) for row in (_execute(sql, fetch="all") or [])]
    except Exception:
        return []


def _symbols(rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("symbol") or "").upper().strip()
        for row in rows
        if str(row.get("symbol") or "").strip()
    }


def build_universe_projection(
    *,
    root: Path,
    query: Callable[[str], list[dict[str, Any]]] = _query,
    reconciled: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = reconciled if reconciled is not None else reconcile_universe(root)
    base_symbols = base.get("symbols") or {}
    proposals = _symbols(query(
        "SELECT DISTINCT symbol FROM paper_trade_proposals "
        "WHERE status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST')"
    ))
    incubator = _symbols(query(
        "SELECT DISTINCT symbol FROM incubator_universe "
        "WHERE status='active' AND symbol IS NOT NULL"
    ))
    profiles = _symbols(query("SELECT DISTINCT symbol FROM symbol_profiles WHERE symbol IS NOT NULL"))

    holdings_rows = held_position_rows(root=root)
    held_symbols = {
        str(row.get("symbol") or "").upper().strip()
        for row in holdings_rows
        if not is_cash_row(row) and str(row.get("symbol") or "").strip()
    }
    non_ticker_or_bond = set()
    for row in holdings_rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        asset = str(row.get("asset_type") or row.get("security_type") or "").upper()
        if not symbol or is_cash_row(row):
            continue
        if not is_held_equity_ticker(symbol) or "BOND" in asset or symbol == "BND":
            non_ticker_or_bond.add(symbol)

    all_symbols = sorted(set(base_symbols) | proposals | incubator | profiles | held_symbols)
    records: dict[str, Any] = {}
    for symbol in all_symbols:
        existing = base_symbols.get(symbol) or {}
        source_memberships = set(existing.get("memberships") or [])
        memberships = []
        if symbol in held_symbols or "HELD" in source_memberships:
            memberships.append("HELD")
        if "FORMER_HOLDING" in source_memberships:
            memberships.append("FORMER_HOLDING")
        if "REENTRY" in source_memberships:
            memberships.append("REENTRY")
        if "WATCHLIST" in source_memberships:
            memberships.append("WATCH")
        if symbol in proposals or "OPPORTUNITY" in source_memberships:
            memberships.append("PROPOSAL")
        if symbol in incubator:
            memberships.append("INCUBATOR")
        if symbol in profiles and not memberships:
            memberships.append("COLD")
        if symbol in non_ticker_or_bond:
            memberships.append("NON_TICKER/BOND")
        records[symbol] = {
            "symbol": symbol,
            "memberships": memberships,
            "source_refs": sorted(set(existing.get("source_refs") or []) | {
                source for source, present in (
                    ("paper_trade_proposals", symbol in proposals),
                    ("incubator_universe", symbol in incubator),
                    ("symbol_profiles", symbol in profiles),
                ) if present
            }),
            "authority": AUTHORITY,
        }

    counts = {
        membership: sum(1 for row in records.values() if membership in row["memberships"])
        for membership in MEMBERSHIPS
    }
    held_unique = counts["HELD"]
    position_rows_non_cash = sum(1 for row in holdings_rows if not is_cash_row(row))
    material_union = sum(
        1 for row in records.values()
        if set(row["memberships"]) & {"HELD", "FORMER_HOLDING", "REENTRY", "WATCH", "PROPOSAL"}
    )
    return {
        "schema": SCHEMA,
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "authority": AUTHORITY,
        "financial_action": False,
        "memberships": list(MEMBERSHIPS),
        "counts": {
            **counts,
            "universe_union": len(records),
            "material_union": material_union,
            "holding_position_rows_non_cash": position_rows_non_cash,
            "held_unique_symbols": held_unique,
        },
        "denominators": {
            "held_thesis_coverage": {
                "value": held_unique,
                "membership_scope": "HELD unique symbols; cash excluded; bond ETFs retained",
                "formula": "count(distinct symbol where membership contains HELD)",
            },
            "material_thesis_coverage": {
                "value": material_union,
                "membership_scope": "union(HELD,FORMER_HOLDING,REENTRY,WATCH,PROPOSAL)",
                "formula": "count(distinct material symbol)",
            },
            "research_universe": {
                "value": len(records),
                "membership_scope": "union of all eight explicit memberships",
                "formula": "count(distinct projected symbol)",
            },
        },
        "source_errors": list(base.get("errors") or []),
        "symbols": records,
    }
