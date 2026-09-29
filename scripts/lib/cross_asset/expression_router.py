"""Shadow expression router — maps signal class → candidate families.

Uses options_strategy_matrix for known/absent honesty. Does not price chains.
READ_ONLY_ADVISORY / shadow_only=True always.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.lib.options_strategy_matrix import MATRIX, ABSENT
except ImportError:  # pragma: no cover
    from lib.options_strategy_matrix import MATRIX, ABSENT  # type: ignore

SIGNAL_EXPRESSIONS: dict[str, list[str]] = {
    "buy": ["shares", "long_call", "cash_secured_put", "debit_spread"],
    "hold": ["shares", "covered_call", "protective_put", "collar"],
    "reentry": ["shares", "cash_secured_put", "debit_spread"],
    "sell": ["sell_shares", "collar", "protective_put"],
}


def _candidate(family: str, *, position_state: dict[str, Any], rank: int) -> dict[str, Any]:
    blocks: list[str] = []
    status = "evaluable_shadow"

    if family == "shares":
        return {
            "family": "shares",
            "structure": "equity",
            "expected_value": None,
            "reward_to_risk": None,
            "max_loss": None,
            "pop": None,
            "blocks": blocks,
            "rank": rank,
            "status": status,
            "shadow_only": True,
            "note": "baseline equity expression; EV filled when ranking engine lands",
        }

    if family == "sell_shares":
        return {
            "family": "sell_shares",
            "structure": "equity_exit",
            "expected_value": None,
            "reward_to_risk": None,
            "max_loss": None,
            "pop": None,
            "blocks": blocks,
            "rank": rank,
            "status": status,
            "shadow_only": True,
            "note": "exit shares; compare to protective structures",
        }

    if family in ABSENT or (family not in MATRIX and family not in {"shares", "sell_shares"}):
        return {
            "family": family,
            "structure": family,
            "expected_value": None,
            "reward_to_risk": None,
            "max_loss": None,
            "pop": None,
            "blocks": ["family_absent_from_strategy_matrix"],
            "rank": rank,
            "status": "unavailable",
            "shadow_only": True,
            "note": "honest gap — not silently skipped",
        }

    # Matrix-backed option families — gate honesty without inventing prices
    if family == "covered_call" and not position_state.get("coverage_100"):
        blocks.append("fewer_than_100_shares")
    if family == "cash_secured_put" and position_state.get("cash_available") is not None:
        try:
            if float(position_state.get("cash_available") or 0) <= 0:
                blocks.append("insufficient_cash")
        except (TypeError, ValueError):
            blocks.append("cash_available_unreadable")
    if family == "protective_put" and float(position_state.get("held_shares") or 0) <= 0:
        blocks.append("no_held_exposure")

    status = "blocked_shadow" if blocks else "evaluable_shadow"
    return {
        "family": family,
        "structure": MATRIX.get(family, {}).get("family", family),
        "expected_value": None,
        "reward_to_risk": None,
        "max_loss": None,
        "pop": None,
        "blocks": blocks,
        "rank": rank,
        "status": status,
        "shadow_only": True,
        "note": "shadow candidate — no chain pricing in Phase 3 scaffold",
        "gates": list(MATRIX.get(family, {}).get("gates") or []),
    }


def route_expressions(
    signal_kind: str,
    *,
    position_state: dict[str, Any] | None = None,
    options_hints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return ranked ExpressionCandidate list (shadow)."""
    kind = str(signal_kind or "none").lower()
    families = SIGNAL_EXPRESSIONS.get(kind) or []
    pos = position_state or {}
    _ = options_hints  # reserved for chain freshness in later phase
    out: list[dict[str, Any]] = []
    for i, fam in enumerate(families, start=1):
        out.append(_candidate(fam, position_state=pos, rank=i))
    # Prefer evaluable over unavailable/blocked for top_family selection order
    out.sort(
        key=lambda c: (
            0 if c.get("status") == "evaluable_shadow" else 1 if c.get("status") == "blocked_shadow" else 2,
            int(c.get("rank") or 99),
        )
    )
    for i, c in enumerate(out, start=1):
        c["rank"] = i
    return out
