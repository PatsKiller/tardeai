"""Small JSON-boundary helpers for values written to PostgreSQL JSON columns."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from decimal import Decimal
from numbers import Real
from typing import Any, Callable


def normalize_nonfinite_json(value: Any) -> Any:
    """Return JSON-compatible containers with NaN and infinities represented as null.

    Python's JSON encoder emits the non-standard tokens ``NaN`` and ``Infinity`` by
    default. PostgreSQL's JSON parser rejects those tokens. Real values are checked
    without coercion so the existing ``default=str`` output retains their type and
    precision (for example Fraction and NumPy scalar representations).
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Real):
        # Compare in the value's own numeric domain. Coercing to float would round
        # Fractions, change NumPy integer output, and overflow finite longdouble.
        try:
            nonfinite = bool(value != value or value == math.inf or value == -math.inf)
        except (TypeError, ValueError, OverflowError) as exc:
            raise TypeError(f"could not determine whether {type(value).__name__} is finite") from exc
        return None if nonfinite else value
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, Mapping):
        return {normalize_nonfinite_json(key): normalize_nonfinite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_nonfinite_json(item) for item in value]
    # NumPy scalar types that do not register as Real expose item(); recurse on the
    # native scalar when available, and leave other unsupported objects to json's
    # configured default handler.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            native = item()
        except (TypeError, ValueError):
            native = value
        if native is not value:
            return normalize_nonfinite_json(native)
    return value


def json_dumps_for_postgres(value: Any, *, default: Callable[[Any], Any] | None = None) -> str:
    """Serialize strict JSON after normalizing non-finite numeric values."""
    return json.dumps(normalize_nonfinite_json(value), default=default, allow_nan=False)


def indicator_cache_scalar_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize numeric scalar columns alongside the indicator cache JSON fields."""
    defaults = {
        "confluence_score": 0,
        "signals_bullish": 0,
        "signals_bearish": 0,
        "signals_neutral": 0,
        "stop_price": None,
        "target_price": None,
        "atr": None,
        "entry_quality": None,
    }
    return {name: normalize_nonfinite_json(result.get(name, default)) for name, default in defaults.items()}


def indicator_cache_json_fields(result: Mapping[str, Any]) -> tuple[str, str]:
    """Serialize the ``key_levels`` and full-result JSON columns for indicator cache writers."""
    return (
        json_dumps_for_postgres(result.get("key_levels", {})),
        json_dumps_for_postgres(result, default=str),
    )
