#!/usr/bin/env python3
"""Scalp tier safety: config alone may not promote an event to T2."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGGER = ROOT / "scripts" / "scalp_shadow_logger.py"


def test_no_config_only_effective_data_tier_switch():
    source = LOGGER.read_text(encoding="utf-8")
    assert "def effective_data_tier" not in source
    assert "feeds_scoring" not in source


def test_persisted_ignition_rows_remain_t0_pending_per_symbol_proof():
    source = LOGGER.read_text(encoding="utf-8")
    # Both ordinary and FSM-trigger rows remain on the established T0 shadow contract.
    assert source.count("'T0'") >= 2
    assert "data_tier=\"T0\"" in source


def test_legacy_logger_does_not_construct_opend_context_directly():
    source = LOGGER.read_text(encoding="utf-8")
    assert "OpenQuoteContext(" not in source
    assert "FutuTransport(" not in source
