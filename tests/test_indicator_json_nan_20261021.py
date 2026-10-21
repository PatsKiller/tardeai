"""Regression coverage for non-standard numeric tokens at indicator JSON DB writes."""

from __future__ import annotations

import json
import math
import os
import sys
import time
import types
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from scripts.lib.indicator_universe_lane import upsert_params
from scripts.lib.json_safety import json_dumps_for_postgres, indicator_cache_json_fields

ROOT = Path(__file__).resolve().parent.parent


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


def test_indicator_universe_upsert_params_normalize_json_and_scalar_fields():
    result = {
        "ok": True,
        "confluence_score": float("nan"),
        "signals_bullish": float("inf"),
        "signals_bearish": float("-inf"),
        "signals_neutral": float("nan"),
        "stop_price": float("nan"),
        "target_price": 14.25,
        "atr": float("inf"),
        "key_levels": {"ema": {"value": float("nan")}},
        "nested": [float("inf"), {"atr": float("-inf")}],
    }

    params = upsert_params("TEST", "swing", result, ttl_minutes=60)

    assert {index: params[index] for index in (2, 4, 5, 6, 10, 12)} == {
        index: None for index in (2, 4, 5, 6, 10, 12)
    }
    assert params[11] == 14.25
    assert _strict_loads(params[9]) == {"ema": {"value": None}}
    assert _strict_loads(params[15]) == {
        "ok": True,
        "confluence_score": None,
        "signals_bullish": None,
        "signals_bearish": None,
        "signals_neutral": None,
        "stop_price": None,
        "target_price": 14.25,
        "atr": None,
        "key_levels": {"ema": {"value": None}},
        "nested": [None, {"atr": None}],
    }


def test_active_indicator_cache_refresh_uses_shared_writer_params():
    source = (ROOT / "scripts" / "indicator_cache_refresh.py").read_text(encoding="utf-8")
    assert "from lib.indicator_universe_lane import upsert_params" in source
    assert "upsert_params(s, 'swing', r, ttl_minutes=60)" in source
    insert = source.split("INSERT INTO indicator_confluence_cache", 1)[1].split("ON CONFLICT", 1)[0]
    assert insert.count("%s") == len(upsert_params("TEST", "swing", _indicator_result(), ttl_minutes=60)) == 17
    assert upsert_params("TEST", "swing", _indicator_result(), ttl_minutes=60)[-1] == 60


def test_legacy_cache_writer_serialization_contract_handles_nested_nonfinite():
    # Both refresh jobs route through the same serialization calls; keeping both
    # fields strict prevents a partial fix of key_levels only.
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
    encoded = json_dumps_for_postgres(
        {"nested": [np.float32("nan"), np.float64("inf"), np.longdouble("nan"), np.longdouble("inf")]}
    )

    assert _strict_loads(encoded) == {"nested": [None, None, None, None]}


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


def test_finite_fraction_and_numpy_scalars_match_legacy_default_str():
    np = pytest.importorskip("numpy")
    result = {
        "key_levels": {},
        "fraction": Fraction(1, 3),
        "numpy_int64": np.int64(1234567890123456789),
        "numpy_longdouble": np.longdouble("1.2345678901234567890123456789"),
        "large_finite_longdouble": np.longdouble("1e4000"),
    }

    _, full_result = indicator_cache_json_fields(result)

    assert full_result == json.dumps(result, default=str, allow_nan=False)
    decoded = _strict_loads(full_result)
    assert decoded["fraction"] == "1/3"
    assert decoded["numpy_int64"] == str(result["numpy_int64"])
    assert decoded["numpy_longdouble"] == str(result["numpy_longdouble"])
    assert decoded["large_finite_longdouble"] == str(result["large_finite_longdouble"])


def _api_module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import api_v2

    return api_v2


def _isolated_alert_database(dsn: str) -> str | None:
    """Accept only the repository's local throwaway PostgreSQL endpoint."""
    try:
        parsed = urlsplit(dsn)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or hostname != "127.0.0.1"
        or port != 55432
        or parsed.query
        or parsed.fragment
    ):
        return None
    from scripts.lib.m2_live_shadow_guard import dsn_database

    return dsn_database(dsn)


def _isolated_alert_connect_kwargs(database: str) -> dict[str, object]:
    """Pin libpq's effective destination even when PG* defaults are set."""
    return {
        "host": "127.0.0.1",
        "hostaddr": "127.0.0.1",
        "port": 55432,
        "dbname": database,
    }


def test_alert_test_dsn_must_use_local_isolated_endpoint():
    assert _isolated_alert_database("postgresql://user:secret@127.0.0.1:55432/m2_shadow_test") == "m2_shadow_test"
    for dsn in (
        "postgresql://user:secret@localhost:55432/m2_shadow_test",
        "postgresql://user:secret@192.0.2.10:55432/m2_shadow_test",
        "postgresql://user:secret@127.0.0.1:5432/m2_shadow_test",
        "postgresql://user:secret@127.0.0.1/m2_shadow_test",
        "postgresql://user:secret@[invalid:55432/m2_shadow_test",
        "postgresql://user:secret@127.0.0.1:55432/m2_shadow_test?host=192.0.2.10",
        "postgresql://user:secret@127.0.0.1:55432/m2_shadow_test?hostaddr=192.0.2.10",
        "postgresql://user:secret@127.0.0.1:55432/m2_shadow_test?port=5432",
        "postgresql://user:secret@127.0.0.1:55432/m2_shadow_test?dbname=trade_ai",
        "postgresql://user:secret@127.0.0.1:55432/m2_shadow_test?service=production",
        "postgresql://user:secret@127.0.0.1:55432/m2_shadow_test#host=192.0.2.10",
    ):
        assert _isolated_alert_database(dsn) is None


def test_alert_test_connection_pins_effective_libpq_destination():
    assert _isolated_alert_connect_kwargs("m2_shadow_test") == {
        "host": "127.0.0.1",
        "hostaddr": "127.0.0.1",
        "port": 55432,
        "dbname": "m2_shadow_test",
    }


def _indicator_result():
    return {
        "ok": True,
        "confluence_score": float("nan"),
        "signals_bullish": float("inf"),
        "signals_bearish": float("-inf"),
        "signals_neutral": float("nan"),
        "key_levels": {"ema": {"value": float("nan")}, "atr": [float("inf"), 12.5]},
        "stop_price": float("nan"),
        "target_price": 12.5,
        "atr": float("-inf"),
        "metrics": {"outer": [float("-inf"), {"finite": 4}]},
        "signals": {},
    }


@pytest.mark.parametrize("handler_name", ["_indicator_confluence_handler", "_indicator_batch_handler"])
def test_confluence_handlers_write_strict_cache_json(monkeypatch, handler_name):
    api = _api_module(monkeypatch)
    result = _indicator_result()
    engine = types.ModuleType("indicator_engine")
    engine.analyze_confluence = lambda *_args: result
    monkeypatch.setitem(sys.modules, "indicator_engine", engine)
    writes = []
    monkeypatch.setattr(api, "_db_query", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api, "_db_write", lambda *args, **_kwargs: writes.append(args))
    monkeypatch.setattr(time, "sleep", lambda *_args: None)

    if handler_name == "_indicator_confluence_handler":
        status, payload = api._indicator_confluence_handler({"symbol": "TEST", "force": "true"})
        assert status == 200 and payload["ok"] is True
    else:
        status, payload = api._indicator_batch_handler({"symbols": ["TEST"]})
        assert status == 200 and payload["ok"] is True

    cache_write = next(call for call in writes if "indicator_confluence_cache" in call[0])
    params = cache_write[1]
    assert {index: params[index] for index in (2, 4, 5, 6, 10, 12)} == {
        index: None for index in (2, 4, 5, 6, 10, 12)
    }
    assert params[11] == 12.5
    assert _strict_loads(params[9]) == {"ema": {"value": None}, "atr": [None, 12.5]}
    assert _strict_loads(params[15]) == {
        "ok": True,
        "confluence_score": None,
        "signals_bullish": None,
        "signals_bearish": None,
        "signals_neutral": None,
        "key_levels": {"ema": {"value": None}, "atr": [None, 12.5]},
        "stop_price": None,
        "target_price": 12.5,
        "atr": None,
        "metrics": {"outer": [None, {"finite": 4}]},
        "signals": {},
    }


def test_postgres_jsonb_round_trip_accepts_normalized_cache_fields():
    dsn = os.environ.get("ALERT_TEST_DSN", "").strip()
    if not dsn:
        pytest.skip("explicit ALERT_TEST_DSN integration fixture is absent; PostgreSQL proof is unmeasured")

    from scripts.lib.m2_live_shadow_guard import TEST_DATABASE_RE, refuse_live_shadow_under_pytest

    database = _isolated_alert_database(dsn)
    if database is None or not TEST_DATABASE_RE.fullmatch(database):
        pytest.fail("ALERT_TEST_DSN must use 127.0.0.1:55432 and name an isolated m2_shadow_test database")
    psycopg2 = pytest.importorskip("psycopg2")
    try:
        conn = psycopg2.connect(
            refuse_live_shadow_under_pytest(dsn),
            **_isolated_alert_connect_kwargs(database),
            connect_timeout=3,
        )
    except Exception:
        pytest.fail("explicit isolated ALERT_TEST_DSN could not be reached (connection details suppressed)")

    result = _indicator_result()
    key_levels, full_result = indicator_cache_json_fields(result)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "CREATE TEMP TABLE indicator_json_boundary_test "
                "(key_levels jsonb NOT NULL, full_result jsonb NOT NULL) ON COMMIT DROP"
            )
            cursor.execute(
                "INSERT INTO indicator_json_boundary_test (key_levels, full_result) VALUES (%s::jsonb, %s::jsonb)",
                (key_levels, full_result),
            )
            cursor.execute("SELECT key_levels, full_result FROM indicator_json_boundary_test")
            stored_levels, stored_result = cursor.fetchone()
        assert stored_levels == {"ema": {"value": None}, "atr": [None, 12.5]}
        assert stored_result["metrics"] == {"outer": [None, {"finite": 4}]}
        assert stored_result["confluence_score"] is None
        assert stored_result["target_price"] == 12.5
    finally:
        conn.rollback()
        conn.close()
