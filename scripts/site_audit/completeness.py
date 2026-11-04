"""§6 completeness: a card must carry its evidence, and a top-list card missing it is P1.

The spec names the symbol detail card explicitly: price, RSI, MACD, 20/50/200-day averages, support/resistance 1 and
2, trend; a CIO thesis or stance with an as_of; and a *reason* for any missing field. A card in a TOP list (Best
opportunities, Home top 5) missing a technical or with no CIO thesis is P1.
"""

from __future__ import annotations

from typing import Any, Iterable

REQUIRED_SYMBOL_FIELDS = (
    "price", "rsi", "macd",
    "sma_20", "sma_50", "sma_200",
    "support_1", "support_2", "resistance_1", "resistance_2",
    "trend",
)
CIO_FIELDS = ("cio_stance", "cio_thesis")

P1 = "P1"
P2 = "P2"


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def _reason(card: dict[str, Any], name: str) -> str | None:
    """The card's own explanation for a missing field, if it gives one."""
    for key in (f"{name}_reason", "missing_reason", "why_missing"):
        value = card.get(key)
        if _present(value):
            return str(value)
    reasons = card.get("missing_reasons")
    if isinstance(reasons, dict) and _present(reasons.get(name)):
        return str(reasons[name])
    return None


def symbol_card_gaps(card: dict[str, Any]) -> list[dict[str, str]]:
    """Every required field that is absent, with the card's stated reason when it has one."""
    out: list[dict[str, str]] = []
    for name in REQUIRED_SYMBOL_FIELDS:
        if not _present(card.get(name)):
            out.append({"field": name, "reason": _reason(card, name) or ""})
    if not any(_present(card.get(k)) for k in CIO_FIELDS):
        out.append({"field": "cio_stance_or_thesis", "reason": _reason(card, "cio") or ""})
    return out


def card_severity(card: dict[str, Any], *, top_list: bool) -> tuple[str | None, list[dict[str, str]]]:
    """(severity, gaps) for one card. None means complete.

    Severity: a top-list card missing any technical field or the CIO thesis is P1; elsewhere a missing field is P2, and
    an unexplained one is P1 because the operator cannot tell a gap from a bug.
    """
    gaps = symbol_card_gaps(card)
    if not gaps:
        return None, []
    if top_list:
        return P1, gaps
    if any(not g["reason"] for g in gaps):
        return P1, gaps
    return P2, gaps


def thesis_as_of_missing(card: dict[str, Any]) -> bool:
    """A thesis/stance without an as_of is not evidence; it is a claim."""
    has_cio = any(_present(card.get(k)) for k in CIO_FIELDS)
    return has_cio and not _present(card.get("cio_as_of") or card.get("thesis_as_of"))
