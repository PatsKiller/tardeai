"""Non-finite floats at the two indicator_confluence_cache writers #1890 did not cover (2026-10-21, #1889 rework).

#1890 shipped ``scripts/lib/json_finite.py`` and fixed the indicator-engine lane writer. The ``/indicator-confluence``
API upserts in ``scripts/api_v2.py`` (single and batch handlers) and ``scripts/indicator_cache_refresh.py`` still did
``json.dumps(result)``, which emits the bare token ``NaN`` that Postgres rejects. Both now route through
``lib.json_finite`` (non-finite -> NULL / json null, ``allow_nan=False``). Ported from #1889's tests onto json_finite.

Hermetic: no DB (``_db_query``/``_db_write`` are recorders, psycopg2 is never imported), no network, no repo write.
"""

from __future__ import annotations

import ast
import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _strict_loads(value: str):
    def reject_constant(token: str):
        raise AssertionError(f"non-standard JSON constant: {token}")

    return json.loads(value, parse_constant=reject_constant)


def _api_module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    if "psycopg2" not in sys.modules:  # CI has no psycopg2; api_v2 must not need it for these handlers
        monkeypatch.setitem(sys.modules, "psycopg2", types.ModuleType("psycopg2"))
    import api_v2

    return api_v2


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
        "entry_quality": float("nan"),
        "metrics": {"outer": [float("-inf"), {"finite": 4}]},
        "signals": {
            "ema": {
                "signal": "BULLISH",
                "value": float("nan"),
                "details": {"score": float("nan"), "bands": [float("inf"), 0.75]},
            }
        },
    }


EXPECTED_FULL = {
    "ok": True,
    "confluence_score": None,
    "signals_bullish": None,
    "signals_bearish": None,
    "signals_neutral": None,
    "key_levels": {"ema": {"value": None}, "atr": [None, 12.5]},
    "stop_price": None,
    "target_price": 12.5,
    "atr": None,
    "entry_quality": None,
    "metrics": {"outer": [None, {"finite": 4}]},
    "signals": {"ema": {"signal": "BULLISH", "value": None, "details": {"score": None, "bands": [None, 0.75]}}},
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
    else:
        status, payload = api._indicator_batch_handler({"symbols": ["TEST"]})
    assert status == 200 and payload["ok"] is True

    cache_write = next(call for call in writes if "indicator_confluence_cache" in call[0])
    sql, params = cache_write[0], cache_write[1]
    assert sql.split("ON CONFLICT", 1)[0].count("%s") == len(params) == 16
    assert {i: params[i] for i in (2, 4, 5, 6, 10, 12, 14)} == {i: None for i in (2, 4, 5, 6, 10, 12, 14)}
    assert params[11] == 12.5
    assert _strict_loads(params[9]) == {"ema": {"value": None}, "atr": [None, 12.5]}
    assert _strict_loads(params[15]) == EXPECTED_FULL

    response = payload["data"] if handler_name == "_indicator_confluence_handler" else payload["results"]["TEST"]
    assert _strict_loads(json.dumps(response, allow_nan=False)) == EXPECTED_FULL

    if handler_name == "_indicator_confluence_handler":
        history = next(call for call in writes if "indicator_signal_history" in call[0])
        assert history[1][3] is None
        assert _strict_loads(history[1][4]) == {"score": None, "bands": [None, 0.75]}


def test_finite_values_pass_through_unchanged(monkeypatch):
    api = _api_module(monkeypatch)
    r = {"ok": True, "confluence_score": 3.5, "signals_bullish": 2, "stop_price": 9.75, "key_levels": {"s1": 1.5}}
    params = api._indicator_cache_params("TEST", "swing", r)
    assert params[2] == 3.5 and params[4] == 2 and params[10] == 9.75
    assert _strict_loads(params[9]) == {"s1": 1.5}
    assert _strict_loads(params[15]) == r


def test_api_writers_no_longer_dump_raw_results():
    """Static: no bare json.dumps(result|r|sig_data...) left in the indicator handlers."""
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {"_indicator_confluence_handler", "_indicator_batch_handler", "_indicator_cache_params"}
    seen = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            seen.add(node.name)
            body = ast.unparse(node)
            for bad in ("json.dumps(result", "json.dumps(r)", "json.dumps(r.get", "json.dumps(sig_data"):
                assert bad not in body, (node.name, bad)
    assert seen == names


def test_indicator_cache_refresh_routes_through_json_finite():
    """Static (the script connects to the DB at import, so it is not executed here)."""
    src = (ROOT / "scripts" / "indicator_cache_refresh.py").read_text(encoding="utf-8")
    assert "from lib.json_finite import dumps as _finite_dumps, finite_or_none as _f" in src
    insert = src.split("INSERT INTO indicator_confluence_cache", 1)[1]
    params = insert.split('""",', 1)[1].split("conn.commit()", 1)[0]
    assert "json.dumps" not in params
    assert "_finite_dumps(r.get('key_levels', {}))" in params
    assert "_finite_dumps(r, default=str)" in params
    for col in ("confluence_score", "stop_price", "target_price", "atr"):
        assert f"_f(r.get('{col}'" in params, col
    assert insert.split("ON CONFLICT", 1)[0].count("%s") == 16
    assert "json_safety" not in src


def test_json_finite_contract_used_by_both_writers():
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.json_finite import dumps, finite_or_none

    assert finite_or_none(float("nan")) is None and finite_or_none(1.5) == 1.5 and finite_or_none("A") == "A"
    assert _strict_loads(dumps({"a": [float("inf"), {"b": float("-inf")}]})) == {"a": [None, {"b": None}]}
    with pytest.raises(ValueError):
        dumps({"a": float("nan")}, sanitize=False)
