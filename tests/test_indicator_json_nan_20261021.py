"""Regression coverage for non-standard numeric tokens at indicator JSON DB writes."""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from scripts.lib.indicator_universe_lane import upsert_params
from scripts.lib.json_safety import json_dumps_for_postgres, indicator_cache_json_fields


def _strict_loads(value: str):
    def reject_constant(token: str):
        raise AssertionError(f"non-standard JSON constant: {token}")

    return json.loads(value, parse_constant=reject_constant)


@pytest.mark.parametrize("bad_number", [float("nan"), float("inf"), float("-inf")])
def test_json_boundary_normalizes_nested_nonfinite_values(bad_number):
    payload = {
        "ema": {"value": bad_number},
        "bands": [1.25, bad_number, {"lower": float("-inf")}],
    }

    encoded = json_dumps_for_postgres(payload)

    assert _strict_loads(encoded) == {
        "ema": {"value": None},
        "bands": [1.25, None, {"lower": None}],
    }
    assert "NaN" not in encoded and "Infinity" not in encoded


def test_indicator_universe_writer_serializes_both_json_columns_strictly():
    result = {
        "ok": True,
        "key_levels": {"ema": {"value": float("nan")}},
        "nested": [float("inf"), {"atr": float("-inf")}],
    }

    params = upsert_params("TEST", "swing", result, ttl_minutes=60)

    assert _strict_loads(params[9]) == {"ema": {"value": None}}
    assert _strict_loads(params[15]) == {
        "ok": True,
        "key_levels": {"ema": {"value": None}},
        "nested": [None, {"atr": None}],
    }


def test_legacy_cache_writer_serialization_contract_handles_nested_nonfinite():
    # indicator_cache_refresh uses these same two serialization calls at its DB
    # boundary; keeping both fields strict prevents a partial fix of key_levels only.
    result = {
        "key_levels": {"ema": {"value": float("nan")}},
        "full_result": [float("inf"), {"signal": float("-inf")}],
    }

    key_levels, full_result = indicator_cache_json_fields(result)

    assert _strict_loads(key_levels) == {"ema": {"value": None}}
    assert _strict_loads(full_result) == {
        "key_levels": {"ema": {"value": None}},
        "full_result": [None, {"signal": None}],
    }


def test_numpy_nonfinite_scalars_are_normalized_when_numpy_is_available():
    np = pytest.importorskip("numpy")
    encoded = json_dumps_for_postgres({"nested": [np.float32("nan"), np.float64("inf")]})

    assert _strict_loads(encoded) == {"nested": [None, None]}


def test_finite_numeric_values_remain_finite():
    encoded = json_dumps_for_postgres({"integer": 2, "float": 1.5})

    assert _strict_loads(encoded) == {"integer": 2, "float": 1.5}
    assert math.isfinite(_strict_loads(encoded)["float"])


def test_decimal_normalization_preserves_finite_precision_and_nulls_nonfinite():
    precise = Decimal("12345678901234567890.12345678901234567890")
    result = {
        "key_levels": {},
        "precise_value": precise,
        "nonfinite_values": [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
    }

    _, full_result = indicator_cache_json_fields(result)

    assert _strict_loads(full_result) == {
        "key_levels": {},
        "precise_value": str(precise),
        "nonfinite_values": [None, None, None],
    }
