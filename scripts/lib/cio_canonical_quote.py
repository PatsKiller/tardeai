"""cio_canonical_quote.py — named price lineage for holdings rows.

Phase 3 of CIO acceptance remediation v4: stop treating broker MV/shares
implied price and Finviz last as the same "current" field.

Named fields (never overload `price` / `current_price`):
  canonical_mark, canonical_mark_type, canonical_mark_source, canonical_mark_as_of
  broker_position_price, broker_position_as_of
  official_close, official_close_as_of
  implied_price_from_mv

`conflicted` is True only when TWO genuine marks disagree — not mark vs
implied-from-MV, and not mark vs a `price` field that is actually market_value.

Authority: READ_ONLY_ADVISORY. Pure. No broker / Telegram.
"""
from __future__ import annotations

from typing import Any, Optional

CANONICAL_QUOTE_VERSION = "cio_canonical_quote_1.0.0"

# price ≈ MV/shares → treat `price` as implied, not a second mark
IMPLIED_FROM_MV_REL_TOL = 0.0015  # 0.15%
# two genuine marks disagree
GENUINE_MARK_REL_TOL = 0.002  # 0.2%
# shares × canonical_mark vs broker MV (dollar floor matches FinancialTruthGate)
DOLLAR_FLOOR_TOL = 1.0
DOLLAR_PCT_TOL = 0.0001

MARK_TYPES = ("live", "after_hours", "close", "unknown")
MV_BASIS_BROKER = "broker"
MV_BASIS_SHARES_X_MARK = "shares_x_canonical_mark"

# Fields stamped onto a holdings row (repricer fail-soft annotation)
CANONICAL_QUOTE_OUTPUT_FIELDS = (
    "canonical_mark",
    "canonical_mark_type",
    "canonical_mark_source",
    "canonical_mark_as_of",
    "broker_position_price",
    "broker_position_as_of",
    "official_close",
    "official_close_as_of",
    "implied_price_from_mv",
    "mv_basis",
    "conflicted",
)

# Quote-like keys that can be genuine marks (never `close` — that is official_close)
_GENUINE_MARK_KEYS = ("current_price", "mark", "last", "price")


def _opt_fnum(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _positive(v: Any) -> Optional[float]:
    n = _opt_fnum(v)
    if n is None or n <= 0:
        return None
    return n


def _rel_close(a: Optional[float], b: Optional[float], rel: float = IMPLIED_FROM_MV_REL_TOL) -> bool:
    if a is None or b is None:
        return False
    if a == b:
        return True
    den = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / den <= rel


def _rel_far(a: Optional[float], b: Optional[float], rel: float = IMPLIED_FROM_MV_REL_TOL) -> bool:
    if a is None or b is None:
        return False
    return not _rel_close(a, b, rel)


def _dollar_tol(row_value: float) -> float:
    return max(DOLLAR_FLOOR_TOL, abs(row_value) * DOLLAR_PCT_TOL)


def _shares_of(row: dict[str, Any]) -> Optional[float]:
    if row.get("shares") is not None:
        return _opt_fnum(row.get("shares"))
    if row.get("quantity") is not None:
        return _opt_fnum(row.get("quantity"))
    if row.get("qty") is not None:
        return _opt_fnum(row.get("qty"))
    return None


def _market_value_of(row: dict[str, Any]) -> Optional[float]:
    if row.get("market_value") is not None:
        return _opt_fnum(row.get("market_value"))
    if row.get("value") is not None:
        return _opt_fnum(row.get("value"))
    return None


def implied_price_from_mv(row: dict[str, Any]) -> Optional[float]:
    """market_value / shares when both are present and shares ≠ 0."""
    shares = _shares_of(row)
    mv = _market_value_of(row)
    if shares is None or mv is None or shares == 0:
        return None
    return mv / shares


def _as_of_of(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = row.get(k)
        if v is not None and v != "":
            return v
    return None


def _infer_mark_type(row: dict[str, Any], *, source_key: Optional[str], as_of: Any) -> str:
    explicit = row.get("canonical_mark_type") or row.get("quote_type") or row.get("price_type")
    if explicit in MARK_TYPES:
        return str(explicit)
    src = str(row.get("price_source") or row.get("quote_source") or source_key or "").lower()
    session = str(
        row.get("session") or row.get("market_session") or row.get("quote_session") or ""
    ).lower()
    if any(tok in session for tok in ("after_hours", "afterhours", "after-hours", "extended")) or session == "ah":
        return "after_hours"
    if any(tok in src for tok in ("after_hours", "afterhours", "extended")):
        return "after_hours"
    if source_key in ("official_close", "close", "prev_close", "previous_close"):
        return "close"
    if session in ("closed", "close") or src in ("close", "official_close", "prev_close"):
        return "close"
    if source_key == "mark" or "live" in src:
        return "live"
    # Finviz last may be RTH or AH — do not guess without a session.
    return "unknown"


def _classify_price_field(
    *,
    price: Optional[float],
    implied: Optional[float],
    mv: Optional[float],
    quote_mark: Optional[float],
) -> str:
    """Role of the overloaded `price` column.

    Returns: mark | implied_from_mv | market_value | absent
    """
    if price is None:
        return "absent"
    if implied is not None and _rel_close(price, implied, IMPLIED_FROM_MV_REL_TOL):
        if quote_mark is not None and _rel_far(quote_mark, implied, IMPLIED_FROM_MV_REL_TOL):
            return "implied_from_mv"
        # price ≈ implied and quote is missing or agrees → still a usable mark
        return "mark"
    # Fractional / stuffed: price field holds market_value, not a per-share mark
    if mv is not None and _rel_close(price, mv, IMPLIED_FROM_MV_REL_TOL):
        if implied is None or _rel_far(price, implied, IMPLIED_FROM_MV_REL_TOL):
            return "market_value"
    return "mark"


def _collect_genuine_marks(
    row: dict[str, Any],
    *,
    price_role: str,
) -> dict[str, float]:
    marks: dict[str, float] = {}
    for key in _GENUINE_MARK_KEYS:
        if key == "price" and price_role != "mark":
            continue
        v = _positive(row.get(key))
        if v is not None:
            marks[key] = v
    return marks


def _pick_canonical_mark(
    marks: dict[str, float],
    *,
    implied: Optional[float],
    price_role: str,
    row: dict[str, Any],
) -> tuple[Optional[float], Optional[str]]:
    """Choose canonical_mark. Do not blindly prefer current_price.

    Hierarchy:
      a) price is implied-from-MV (or stuffed MV) and a quote is far → use the quote
      b) price ≈ current_price → that value
      c) one field missing → the other
      else prefer a quote key over a leftover `price` mark
    """
    current = marks.get("current_price")
    price = marks.get("price")
    last = marks.get("last")
    mark = marks.get("mark")
    quote = current if current is not None else (mark if mark is not None else last)

    if price_role in ("implied_from_mv", "market_value") and quote is not None:
        return quote, (
            "current_price" if current is not None else ("mark" if mark is not None else "last")
        )

    if price is not None and current is not None and _rel_close(price, current, IMPLIED_FROM_MV_REL_TOL):
        # Prefer the quote key when they agree so source is named honestly
        src = row.get("price_source")
        if src:
            return current, str(src)
        return current, "current_price"

    if len(marks) == 1:
        key = next(iter(marks))
        return marks[key], key

    if quote is not None and price is None:
        key = "current_price" if current is not None else ("mark" if mark is not None else "last")
        return quote, key

    if price is not None and quote is None:
        return price, "price"

    # Two-plus genuine marks: still pick a display mark (quote over price)
    if current is not None:
        src = row.get("price_source")
        return current, str(src) if src else "current_price"
    if mark is not None:
        return mark, "mark"
    if last is not None:
        return last, "last"
    if price is not None:
        return price, "price"
    return None, None


def _official_close_of(row: dict[str, Any]) -> tuple[Optional[float], Any]:
    for key in ("official_close", "previous_close", "prev_close", "close"):
        v = _positive(row.get(key))
        if v is not None:
            as_of = _as_of_of(
                row,
                "official_close_as_of",
                "close_as_of",
                "prev_close_as_of",
                "previous_close_as_of",
            )
            return v, as_of
    return None, None


def _broker_position_price(
    row: dict[str, Any],
    *,
    price_role: str,
    implied: Optional[float],
) -> tuple[Optional[float], Any]:
    dedicated = _positive(row.get("broker_price") or row.get("broker_position_price"))
    as_of = _as_of_of(
        row,
        "broker_position_as_of",
        "position_as_of",
        "broker_as_of",
        "as_of",
    )
    if dedicated is not None:
        return dedicated, as_of
    raw_price = _positive(row.get("price"))
    if price_role == "mark" and raw_price is not None:
        return raw_price, as_of
    if price_role == "implied_from_mv" and raw_price is not None:
        return raw_price, as_of
    if price_role == "market_value" and implied is not None and implied > 0:
        return implied, as_of
    if implied is not None and implied > 0:
        return implied, as_of
    return None, as_of


def apply_canonical_quote_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Return a row copy with named quote / MV lineage fields.

    Does not mutate `row`. Does not rewrite market_value.
    """
    out = dict(row)
    shares = _shares_of(row)
    mv = _market_value_of(row)
    implied = implied_price_from_mv(row)
    current = _positive(row.get("current_price"))
    last = _positive(row.get("last"))
    mark = _positive(row.get("mark"))
    raw_price = _positive(row.get("price"))
    quote_mark = current if current is not None else (mark if mark is not None else last)

    price_role = _classify_price_field(
        price=raw_price, implied=implied, mv=mv, quote_mark=quote_mark,
    )
    genuine = _collect_genuine_marks(row, price_role=price_role)
    canon, canon_key = _pick_canonical_mark(
        genuine, implied=implied, price_role=price_role, row=row,
    )
    # Only promote implied-from-MV to a mark when `price` is stuffed MV
    # (or recognized implied) and no quote exists. A row with shares+MV
    # and no price fields has an implied figure, not a mark.
    if (
        canon is None
        and implied is not None
        and implied > 0
        and price_role in ("implied_from_mv", "market_value")
    ):
        canon, canon_key = implied, "implied_from_mv"

    official_close, official_close_as_of = _official_close_of(row)
    if canon is None and official_close is not None:
        canon, canon_key = official_close, "official_close"

    broker_px, broker_as_of = _broker_position_price(
        row, price_role=price_role, implied=implied,
    )

    mark_as_of = _as_of_of(
        row, "canonical_mark_as_of", "price_as_of", "quote_time", "quote_as_of",
        "as_of", "updated_at",
    )
    mark_type = _infer_mark_type(out, source_key=canon_key, as_of=mark_as_of)

    # Dual genuine marks only (never mark vs implied / stuffed MV)
    genuine_values = list(genuine.values())
    dual = False
    if len(genuine) >= 2:
        ref = genuine_values[0]
        for v in genuine_values[1:]:
            if not _rel_close(v, ref, GENUINE_MARK_REL_TOL):
                dual = True
                break

    if mv is not None:
        mv_basis = MV_BASIS_BROKER
    elif shares is not None and canon is not None:
        mv_basis = MV_BASIS_SHARES_X_MARK
    else:
        mv_basis = None

    source = canon_key
    if canon_key in ("current_price", "last", "mark") and row.get("price_source"):
        source = str(row.get("price_source"))

    out["canonical_mark"] = canon
    out["canonical_mark_type"] = mark_type if canon is not None else "unknown"
    out["canonical_mark_source"] = source
    out["canonical_mark_as_of"] = mark_as_of
    out["broker_position_price"] = broker_px
    out["broker_position_as_of"] = broker_as_of
    out["official_close"] = official_close
    out["official_close_as_of"] = official_close_as_of
    out["implied_price_from_mv"] = implied
    out["mv_basis"] = mv_basis
    out["conflicted"] = dual
    out["price_field_role"] = price_role
    return out


def classify_row_conflicts(row: dict[str, Any]) -> dict[str, Any]:
    """Named-semantics conflict board for one holdings row."""
    named = apply_canonical_quote_fields(row)
    implied = named.get("implied_price_from_mv")
    price_role = named.get("price_field_role") or "absent"
    genuine = _collect_genuine_marks(named, price_role=str(price_role))
    dual = bool(named.get("conflicted"))

    shares = _shares_of(named)
    mv = _market_value_of(named)
    canon = _opt_fnum(named.get("canonical_mark"))
    broker_mv_diff = False
    abs_err = None
    tol = None
    if (
        shares is not None
        and shares > 0
        and canon is not None
        and canon > 0
        and mv is not None
    ):
        implied_mv = shares * canon
        tol = _dollar_tol(mv if mv else implied_mv)
        abs_err = abs(implied_mv - mv)
        broker_mv_diff = abs_err > tol

    implied_recognized = price_role in ("implied_from_mv", "market_value")
    exceptions: list[dict[str, Any]] = []
    if dual:
        exceptions.append({
            "type": "dual_price_conflict",
            "genuine_marks": genuine,
        })
    if broker_mv_diff:
        exceptions.append({
            "type": "shares_x_price_ne_mv",
            "label": "broker_mv_uses_different_mark",
            "canonical_mark": canon,
            "market_value": mv,
            "implied_mv": None if shares is None or canon is None else shares * canon,
            "abs_err": abs_err,
            "tol": tol,
        })

    return {
        "canonical_mark": canon,
        "canonical_mark_source": named.get("canonical_mark_source"),
        "canonical_mark_type": named.get("canonical_mark_type"),
        "implied_price_from_mv": implied,
        "price_field_role": price_role,
        "price_is_not_a_mark": price_role in ("implied_from_mv", "market_value"),
        "implied_from_mv_recognized": implied_recognized,
        "genuine_marks": genuine,
        "dual_price_conflict": dual,
        "broker_mv_uses_different_mark": broker_mv_diff,
        "conflicted": dual,  # only two genuine marks
        "mv_basis": named.get("mv_basis"),
        "exceptions": exceptions,
        "version": CANONICAL_QUOTE_VERSION,
    }
