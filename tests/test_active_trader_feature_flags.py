"""Active Trader (P5) audited feature flags — live_session hard-disabled."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.feature_flags import (  # noqa: E402
    MANDATE_DEFAULTS,
    Flags,
    automation_mode,
    is_live_session_enabled,
    load_flags,
)


def _write_config(tmp_path: Path, flags: dict) -> Path:
    p = tmp_path / "active_trader_flags.json"
    p.write_text(json.dumps({"flags": flags}), encoding="utf-8")
    return p


def test_defaults_match_mandate(tmp_path):
    """No config file -> hard-coded mandate defaults, verbatim."""
    flags = load_flags(tmp_path / "does_not_exist.json")
    assert flags.get("active_trader_live_data_enabled") is True
    assert flags.get("active_trader_session_builder_enabled") is True
    assert flags.get("active_trader_simulation_enabled") is True
    assert flags.get("active_trader_automation_engine_enabled") is True
    assert flags.get("active_trader_live_session_enabled") is False
    assert flags.get("active_trader_multi_account_enabled") is False
    assert flags.get("active_trader_fallback_enabled") is False
    # And exactly matches the published mandate defaults.
    assert dict(flags.values) == MANDATE_DEFAULTS


def test_live_session_disabled_by_default(tmp_path):
    flags = load_flags(tmp_path / "none.json")
    assert flags.active_trader_live_session_enabled is False
    assert flags.is_live_session_enabled() is False


def test_config_cannot_enable_live_session(tmp_path):
    """A config that TRIES to enable live_session is coerced to False + noted."""
    cfg = _write_config(tmp_path, {"active_trader_live_session_enabled": True})
    flags = load_flags(cfg)
    assert flags.active_trader_live_session_enabled is False
    assert flags.get("active_trader_live_session_enabled") is False
    assert flags.is_live_session_enabled() is False
    assert any("COERCED" in n for n in flags.notes)
    assert any("active_trader_live_session_enabled" in n for n in flags.notes)


def test_automation_mode_simulation_while_live_off(tmp_path):
    """automation_mode is SIMULATION while live session is off (always here)."""
    flags = load_flags(tmp_path / "none.json")
    assert flags.automation_mode() == "SIMULATION"
    assert automation_mode(flags) == "SIMULATION"

    # Even automation engine enabled + a config attempting live stays SIMULATION.
    cfg = _write_config(
        tmp_path,
        {
            "active_trader_automation_engine_enabled": True,
            "active_trader_live_session_enabled": True,
        },
    )
    flags2 = load_flags(cfg)
    assert flags2.get("active_trader_automation_engine_enabled") is True
    assert flags2.automation_mode() == "SIMULATION"


def test_non_live_flags_can_be_relaxed(tmp_path):
    """Non-live flags are freely toggleable via config."""
    cfg = _write_config(
        tmp_path,
        {
            "active_trader_multi_account_enabled": True,
            "active_trader_fallback_enabled": True,
            "active_trader_live_data_enabled": False,
        },
    )
    flags = load_flags(cfg)
    assert flags.get("active_trader_multi_account_enabled") is True
    assert flags.get("active_trader_fallback_enabled") is True
    assert flags.get("active_trader_live_data_enabled") is False
    # Live session remains hard-off regardless.
    assert flags.is_live_session_enabled() is False


def test_is_live_session_enabled_module_helper():
    assert is_live_session_enabled() is False


def test_source_and_audit_are_recorded(tmp_path):
    cfg = _write_config(tmp_path, {"active_trader_live_session_enabled": True})
    flags = load_flags(cfg)
    audit = flags.as_audit_dict()
    assert audit["live_session_enabled"] is False
    assert audit["automation_mode"] == "SIMULATION"
    assert str(cfg) in flags.source
    assert isinstance(flags, Flags)
