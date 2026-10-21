"""Small JSON-boundary helpers for values written to PostgreSQL JSON columns."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from decimal import Decimal
from numbers import Integral, Real
from typing import Any, Callable


def normalize_nonfinite_json(value: Any) -> Any:
    """Return JSON-compatible containers with NaN and infinities represented as null.

    Python's JSON encoder emits the non-standard tokens ``NaN`` and ``Infinity`` by
    default. PostgreSQL's JSON parser rejects those tokens. NumPy scalar numbers are
    handled through their ``Real``/``Integral`` ABCs as well.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else None
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


def indicator_cache_json_fields(result: Mapping[str, Any]) -> tuple[str, str]:
    """Serialize the ``key_levels`` and full-result JSON columns for indicator cache writers."""
    return (
        json_dumps_for_postgres(result.get("key_levels", {})),
        json_dumps_for_postgres(result, default=str),
    )
