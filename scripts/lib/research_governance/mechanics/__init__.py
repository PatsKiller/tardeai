"""R2 deterministic mechanics — additive, unwired, READ_ONLY_ADVISORY.

Deterministic math is not financial truth. Every result carries status,
units, conventions, sources, and assumptions. Incomplete inputs fail closed.
"""
from __future__ import annotations

from .common import (  # noqa: F401
    AUTHORITY,
    CALCULATION_VERSION,
    AssumptionClass,
    InputDatum,
    MechanicStatus,
    Quantity,
    Unit,
    MechanicError,
    require_unit,
    convert_quantity,
    year_fraction,
    DayCount,
    CouponFrequency,
    parse_coupon_frequency,
)

AUTHORITY_LABEL = "READ_ONLY_ADVISORY"
