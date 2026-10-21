"""Non-finite floats -> None, for anything bound for a Postgres json/jsonb column or a float column (2026-10-21).

``json.dumps`` defaults to ``allow_nan=True`` and emits the bare tokens ``NaN`` / ``Infinity``, which are not JSON:
Postgres rejects the row (``Token "NaN" is invalid``). pandas/numpy indicators produce NaN routinely (a weekly pivot
on a symbol with under a week of history), so the indicator_engine lane failed 2026-10-20 and 2026-10-21.

``json_safe`` walks dicts/lists/tuples/sets and numpy arrays, maps every non-finite float (numpy floats included) to
None, and unwraps numpy integer/bool/float scalars to the Python types. Everything else passes through unchanged
(strings, None, datetimes -- the caller's ``default=`` still handles those). Import-light: numpy is optional.
"""
from __future__ import annotations

import json
import math
from typing import Any


def finite_or_none(value: Any) -> Any:
    """A scalar float column value: non-finite -> None; numpy scalars unwrapped; anything else unchanged."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    item = getattr(value, "item", None)  # numpy scalar
    if callable(item) and getattr(value, "shape", None) == ():
        return finite_or_none(item())
    return value


def json_safe(value: Any) -> Any:
    """A copy of ``value`` that ``json.dumps(..., allow_nan=False)`` accepts as far as numbers go."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist) and getattr(value, "shape", None) not in (None, ()):  # numpy array / pandas Series
        return json_safe(tolist())
    return finite_or_none(value)


def dumps(value: Any, *, sanitize: bool = True, **kw: Any) -> str:
    """``json.dumps`` with ``allow_nan=False``: a non-finite float that reached here unsanitised raises ValueError."""
    kw["allow_nan"] = False
    return json.dumps(json_safe(value) if sanitize else value, **kw)
