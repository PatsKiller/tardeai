"""Packet D SHADOW_DSN guard: exact prod db match; lab URIs allowed.

Never uses real host DSNs or logs passwords.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD_PATH = ROOT / "scripts" / "operator_packets" / "packet_d_shadow_acceptance.py"


def _load():
    spec = importlib.util.spec_from_file_location("packet_d_shadow_acceptance", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()
ShadowGuardError = mod.ShadowGuardError
_shadow_dsn_guard = mod._shadow_dsn_guard
_parse_dsn_identity = mod._parse_dsn_identity
_is_production_dbname = mod._is_production_dbname


def test_parse_uri_lab_dbname():
    db, user = _parse_dsn_identity(
        "postgresql://agentic_runtime_shadow_rw:secret@127.0.0.1:5433/trade_ai_agentic_lab"
    )
    assert db == "trade_ai_agentic_lab"
    assert user == "agentic_runtime_shadow_rw"


def test_parse_key_value():
    db, user = _parse_dsn_identity(
        "host=127.0.0.1 port=5433 dbname=trade_ai_agentic_lab user=agentic_runtime_shadow_rw password=x"
    )
    assert db == "trade_ai_agentic_lab"
    assert user == "agentic_runtime_shadow_rw"


def test_lab_uri_with_trade_ai_prefix_allowed():
    """Regression: path /trade_ai_agentic_lab must NOT be treated as production."""
    _shadow_dsn_guard(
        "postgresql://agentic_runtime_shadow_rw:pw@localhost:5433/trade_ai_agentic_lab"
    )


def test_lab_key_value_allowed():
    _shadow_dsn_guard(
        "dbname=trade_ai_agentic_lab user=agentic_runtime_shadow_rw host=127.0.0.1"
    )


def test_shadow_named_db_allowed():
    _shadow_dsn_guard(
        "postgresql://agentic_runtime_shadow_rw:pw@localhost:5433/trade_ai_shadow"
    )


def test_exact_trade_ai_dbname_refused_uri():
    with pytest.raises(ShadowGuardError, match="production"):
        _shadow_dsn_guard(
            "postgresql://agentic_runtime_shadow_rw:pw@localhost:5432/trade_ai"
        )


def test_exact_trade_ai_dbname_refused_key_value():
    with pytest.raises(ShadowGuardError, match="production"):
        _shadow_dsn_guard(
            "dbname=trade_ai user=agentic_runtime_shadow_rw host=localhost"
        )


def test_missing_shadow_rw_user_refused():
    with pytest.raises(ShadowGuardError, match="agentic_runtime_shadow_rw"):
        _shadow_dsn_guard(
            "postgresql://agentic_runtime_lab_rw:pw@localhost:5433/trade_ai_agentic_lab"
        )


def test_reader_user_refused():
    with pytest.raises(ShadowGuardError, match="agentic_runtime_shadow_rw"):
        _shadow_dsn_guard(
            "postgresql://agentic_runtime_reader:pw@localhost:5433/trade_ai_agentic_lab"
        )


def test_production_marker_in_dbname_refused():
    with pytest.raises(ShadowGuardError, match="production"):
        _shadow_dsn_guard(
            "postgresql://agentic_runtime_shadow_rw:pw@localhost:5432/trade_ai_prod"
        )


def test_is_production_dbname_helpers():
    assert _is_production_dbname("trade_ai") is True
    assert _is_production_dbname("TRADE_AI") is True
    assert _is_production_dbname("trade_ai_agentic_lab") is False
    assert _is_production_dbname("trade_ai_shadow") is False
    assert _is_production_dbname("foo_lab") is False
