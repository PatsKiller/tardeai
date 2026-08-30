"""Rebalancer reads CIO product read-only (C1 / G-AUTH-01).

Drop (by default) suggestions that contradict AVOID on the same symbol from the
actionable list; annotate them and append refusal receipts. The job continues
for remaining non-contradicted orders. Never execute broker. Never notify-on.
READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
REFUSAL_SCHEMA = "CIOAvoidRefusal@v1"
REFUSAL_RELPATH = Path("data") / "cio" / "cio_avoid_refusals.jsonl"


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
        act = str(
            rec.get("recommended_action")
            or rec.get("decision")
            or rec.get("cio_decision")
            or rec.get("action")
            or ""
        ).upper()
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


def _annotate_order(order: dict[str, Any], avoid: set[str], *, dropping: bool) -> dict[str, Any]:
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
        if dropping:
            row["cio_avoid_note"] = (
                f"CIO AVOID on {', '.join(hit)} — dropped from actionable list; "
                "job continues for remaining; not executed"
            )
        else:
            row["cio_avoid_note"] = (
                f"CIO AVOID on {', '.join(hit)} — flag only; job continues; not executed"
            )
    row["cio_product_read"] = "read_only"
    row["authority"] = AUTHORITY
    row["memory_behavior_influence"] = MBI
    return row


def drop_orders_against_avoid(
    orders: list[dict[str, Any]],
    product: dict[str, Any] | None,
    *,
    drop_contradictions: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Annotate orders; optionally drop AVOID contradictions from actionable list.

    Returns (kept, dropped). When drop_contradictions is False, dropped is empty
    and kept contains every annotated order (flag-only). Never executes broker.
    """
    avoid = avoid_symbols_from_product(product)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for order in orders or []:
        row = _annotate_order(order, avoid, dropping=drop_contradictions)
        if drop_contradictions and row.get("cio_avoid_contradiction"):
            dropped.append(row)
        else:
            kept.append(row)
    return kept, dropped


def flag_orders_against_avoid(
    orders: list[dict[str, Any]],
    product: dict[str, Any] | None,
    *,
    drop_contradictions: bool = True,
) -> list[dict[str, Any]]:
    """Annotate orders; by default omit AVOID contradictions from actionable list.

    Set drop_contradictions=False for flag-only (legacy) behavior. Never executes.
    """
    kept, _dropped = drop_orders_against_avoid(
        orders, product, drop_contradictions=drop_contradictions
    )
    return kept


def _refusal_store_path(*, root: Path | str | None = None) -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root

        base = production_state_root(root)
    except Exception:
        base = Path(root) if root else Path(__file__).resolve().parents[2]
    return Path(base) / REFUSAL_RELPATH


def append_avoid_refusal_receipt(
    dropped: list[dict[str, Any]],
    *,
    root: Path | str | None = None,
) -> Path | None:
    """Append-only refusal receipt for dropped AVOID-contradicting orders.

    Writes under CIO persistent store (production_state_root) at
    data/cio/cio_avoid_refusals.jsonl. No-op when dropped is empty.
    """
    if not dropped:
        return None
    from scripts.lib.atomic_json_store import append_jsonl

    path = _refusal_store_path(root=root)
    symbols: list[str] = []
    seen: set[str] = set()
    for row in dropped:
        for sym in row.get("cio_avoid_symbols") or []:
            s = str(sym).upper()
            if s and s not in seen:
                seen.add(s)
                symbols.append(s)
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rec = {
        "schema": REFUSAL_SCHEMA,
        "ts": ts,
        "symbols": symbols,
        "authority": AUTHORITY,
        "mbi": MBI,
        "memory_behavior_influence": MBI,
        "dropped_count": len(dropped),
        "note": (
            "G-AUTH-01: AVOID-contradicting rebalance orders dropped from actionable "
            "list; job continues for remaining; never execute broker; no notify-on"
        ),
        "financial_action": False,
        "broker_write": False,
    }
    append_jsonl(path, rec)
    return path


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
