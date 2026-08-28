"""Rebalancer reads CIO product read-only (C1).

Flag suggestions that contradict AVOID on the same symbol. Do not stop the
job. Do not execute. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def avoid_symbols_from_product(product: dict[str, Any] | None) -> set[str]:
    out: set[str] = set()
    if not isinstance(product, dict):
        return out
    reentry = product.get("reentry_book") or product.get("reentry") or {}
    if isinstance(reentry, dict):
        for r in reentry.get("names") or []:
            if not isinstance(r, dict):
                continue
            status = str(r.get("status") or r.get("governed_verdict") or "").upper()
            if status == "AVOID" and r.get("symbol"):
                out.add(str(r["symbol"]).upper())
    for rec in product.get("recommendations") or product.get("decisions") or []:
        if not isinstance(rec, dict):
            continue
        act = str(rec.get("recommended_action") or rec.get("decision") or rec.get("cio_decision") or rec.get("action") or "").upper()
        if act == "AVOID" and (rec.get("symbol") or rec.get("entity")):
            out.add(str(rec.get("symbol") or rec.get("entity")).upper())
    book = product.get("action_book") or {}
    if isinstance(book, dict):
        for r in book.get("AVOID") or []:
            if isinstance(r, dict) and r.get("symbol"):
                out.add(str(r["symbol"]).upper())
    out.discard("")
    out.discard("PORTFOLIO")
    return out


def flag_orders_against_avoid(
    orders: list[dict[str, Any]],
    product: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Annotate orders. Never drops an order. Never executes."""
    avoid = avoid_symbols_from_product(product)
    out: list[dict[str, Any]] = []
    for order in orders or []:
        row = dict(order)
        tickers = [
            str(t).upper()
            for t in list(row.get("suggested_tickers") or []) + list(row.get("current_tickers") or [])
            if t
        ]
        hit = sorted({t for t in tickers if t in avoid})
        row["cio_avoid_contradiction"] = bool(hit)
        row["cio_avoid_symbols"] = hit
        if hit:
            row["cio_avoid_note"] = (
                f"CIO AVOID on {', '.join(hit)} — flag only; job continues; not executed"
            )
        row["cio_product_read"] = "read_only"
        row["authority"] = AUTHORITY
        row["memory_behavior_influence"] = MBI
        out.append(row)
    return out


def load_cio_product_readonly(root=None) -> dict[str, Any] | None:
    try:
        from scripts.lib.cio_operator_product import build_operator_product
        p = build_operator_product(root=root, persist=False)
        if isinstance(p, dict) and p.get("available"):
            return p
    except Exception:
        pass
    try:
        from scripts.lib.canonical_store_registry import load_json_store
        loc = load_json_store("cio.product.current", root=root)
        if loc.get("available") and isinstance(loc.get("data"), dict):
            return loc["data"]
    except Exception:
        pass
    return None
