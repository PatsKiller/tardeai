"""The ADR correction matches the registry and does not change the live model constant."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.llm_model_registry import (
    EXACT_DEEPSEEK_MODELS,
    LEGACY_DEEPSEEK_MODELS,
    RegistryError,
    reject_legacy_model_id,
)

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs/architecture/cio/ADR_LLM_GOVERNANCE_BOUNDARY.md"
FLASH = ROOT / "scripts/lib/agent_flash_governance.py"


def test_exact_id_is_deepseek_flash_and_v4_ids_are_rejected():
    assert EXACT_DEEPSEEK_MODELS == frozenset({"deepseek-flash"})
    assert "deepseek-v4-flash" in LEGACY_DEEPSEEK_MODELS
    assert "deepseek-v4-pro" in LEGACY_DEEPSEEK_MODELS
    with pytest.raises(RegistryError):
        reject_legacy_model_id("deepseek-v4-flash")
    with pytest.raises(RegistryError):
        reject_legacy_model_id("deepseek-v4-pro")


def test_adr_correction_names_the_running_id_without_editing_flash_model():
    text = ADR.read_text(encoding="utf-8")
    assert "## Correction 2026-10-07 (documentation only)" in text
    assert "EXACT_DEEPSEEK_MODELS` to `deepseek-flash` only" in text
    assert 'EXACT_DEEPSEEK_MODELS = {"deepseek-flash"}' in text
    assert 'EXACT_DEEPSEEK_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}' not in text
    assert "This correction does not edit that line." in text
    flash = FLASH.read_text(encoding="utf-8")
    assert 'FLASH_MODEL = deepseek_model_id("FAST")' in flash
    assert 'FLASH_MODEL = "deepseek-flash"' not in flash
    assert 'FLASH_MODEL = "deepseek-v4-flash"' not in flash
