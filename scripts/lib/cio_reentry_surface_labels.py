"""Scope labels for the two independent re-entry books.

They answer different questions and must not be merged (#584 / P9.3).
Labels are T (template). Precedence is not a winner — each surface is
authoritative only for its own question.

READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"

SURFACE_A: dict[str, Any] = {
    "surface": "A",
    "name": "former_holdings_reentry",
    "scope": "former holdings vs exit trigger",
    "question": "which former holdings are near their re-entry trigger?",
    "precedence": "answers former-holdings vs exit trigger only; not cash-stage R:R",
    "not_this_book": "candidates vs cash-stage R:R under desk thesis",
    "producer": "cio_investment_product.build_reentry_book",
    "class": "T",
    "authority": AUTHORITY,
}

SURFACE_B: dict[str, Any] = {
    "surface": "B",
    "name": "desk_cash_stage_reentry",
    "scope": "candidates vs cash-stage R:R under desk thesis",
    "question": "which candidates have acceptable risk-reward at the current cash stage?",
    "precedence": "answers cash-stage R:R under desk thesis only; not former-holdings vs exit trigger",
    "not_this_book": "former holdings vs exit trigger",
    "producer": "cio_desk_depth.build_reentry_book",
    "class": "T",
    "authority": AUTHORITY,
}


def stamp(book: dict[str, Any], surface: dict[str, Any]) -> dict[str, Any]:
    """Additive labels. Does not merge books or rewrite names/cards."""
    out = dict(book or {})
    out["surface"] = surface["surface"]
    out["scope"] = surface["scope"]
    out["question"] = surface["question"]
    out["precedence"] = surface["precedence"]
    out["not_this_book"] = surface["not_this_book"]
    out["surface_name"] = surface["name"]
    out["scope_class"] = surface["class"]
    return out


def banner(surface: dict[str, Any]) -> str:
    return (
        f"Surface {surface['surface']} · {surface['scope']} "
        f"(not {surface['not_this_book']})"
    )
