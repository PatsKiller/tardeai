#!/usr/bin/env python3
"""Registry and affiliation tests for OscillatorRegistry@v1.

The registry is the fail-closed boundary: an unregistered oscillator id, or a
state outside a given oscillator's declared set, must raise rather than emit an
affiliation nobody can trust (AGENTS.md §7: a control whose name asserts a
restriction must actually enforce it).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import oscillator_registry as oreg  # noqa: E402
from scripts.lib.oscillator_registry import OscillatorRegistryError  # noqa: E402

AS_OF = datetime(2026, 9, 11, 20, 0, tzinfo=timezone.utc)


def test_registry_schema_and_shape():
    raw = json.loads(oreg.registry_path().read_text(encoding="utf-8"))
    assert raw["schema"] == oreg.SCHEMA
    ids = [o["oscillator_id"] for o in raw["oscillators"]]
    assert ids == list(oreg.oscillator_ids())
    # No duplicate ids — the whole point is one name per oscillator.
    assert len(ids) == len(set(ids))


def test_every_registered_oscillator_names_producer_and_store():
    for o in oreg.all_entries():
        assert o.get("producer"), f"{o['oscillator_id']} missing producer"
        assert o.get("store"), f"{o['oscillator_id']} missing store"
        assert o.get("scope") in oreg.VALID_SCOPES, f"{o['oscillator_id']} bad scope"


def test_unregistered_id_raises():
    with pytest.raises(OscillatorRegistryError, match="unregistered"):
        oreg.affiliation_for("not_a_real_oscillator")


def test_invalid_state_raises():
    with pytest.raises(OscillatorRegistryError, match="not declared"):
        oreg.affiliation_for("sector_momentum_rs", state="TRENDING")


def test_prior_state_also_validated():
    with pytest.raises(OscillatorRegistryError):
        oreg.affiliation_for("sector_momentum_rs", state="LEADING", prior_state="BOGUS")


def test_valid_affiliation_carries_scope_and_name():
    tag = oreg.affiliation_for(
        "sector_momentum_rs",
        reading=-2.7,
        state="LAGGING",
        prior_state="IMPROVING",
        confirm_days=2,
        as_of=AS_OF,
    )
    assert tag["oscillator_id"] == "sector_momentum_rs"
    assert tag["display_name"] == "Sector Rotation"
    assert tag["scope"] == "sector"
    assert tag["reading_name"] == "RS20"
    assert tag["reading"] == -2.7
    assert tag["reading_is_numeric"] is True
    assert tag["prior_state"] == "IMPROVING"
    assert tag["confirm_days"] == 2
    assert tag["as_of"] == AS_OF.isoformat()


def test_numeric_reading_is_flagged_not_guessed():
    assert oreg.affiliation_for("sector_momentum_rs", reading=-2.7)["reading_is_numeric"] is True
    assert oreg.affiliation_for("sector_momentum_rs", reading="—")["reading_is_numeric"] is False
    # A boolean is not a measured number.
    assert oreg.affiliation_for("sector_momentum_rs", reading=True)["reading_is_numeric"] is False


def test_oscillator_without_named_states_accepts_any_label():
    # sector_breadth_20dma declares no states; a percent label is fine.
    tag = oreg.affiliation_for("sector_breadth_20dma", reading=24.0, state="24")
    assert tag["reading"] == 24.0


def test_evidence_item_names_oscillator_and_subject():
    item = oreg.evidence_item_for(
        "sector_momentum_rs", subject="XLF", reading=-2.7, state="LAGGING",
        prior_state="IMPROVING", as_of=AS_OF,
    )
    assert item["type"] == "oscillator_sector"
    assert item["oscillator_id"] == "sector_momentum_rs"
    assert "Sector Rotation" in item["title"]
    assert "XLF" in item["title"]
    assert item["value"] == -2.7
    assert item["state"] == "LAGGING"
    assert item["prior_state"] == "IMPROVING"


def test_evidence_item_scope_maps_to_type():
    assert oreg.evidence_item_for("confluence_v2", subject="NVDA")["type"] == "oscillator_symbol"
    assert oreg.evidence_item_for("industry_momentum_quadrant", subject="X")["type"] == "oscillator_industry"


def test_message_prefix_is_operator_label():
    assert oreg.message_prefix_for("sector_momentum_rs") == "SECTOR ROTATION"
    assert oreg.message_prefix_for("confluence_v2") == "INDICATOR CONFLUENCE"


def test_all_scopes_are_covered():
    scopes = {o["scope"] for o in oreg.all_entries()}
    assert "sector" in scopes and "industry" in scopes and "symbol" in scopes
    assert "style" in scopes and "market" in scopes


def test_negative_control_absent_registry_breaks_everything(monkeypatch):
    """The registry is a real dependency, not a nicety.

    If the registry file goes missing, affiliation_for must fail closed
    (raise), not silently return a tag with no name. Patching the path to a
    nonexistent file exercises that: the FileNotFoundError is the correct
    fail-closed behaviour.
    """
    monkeypatch.setattr(oreg, "_REGISTRY_PATH", ROOT / "config" / "does_not_exist.json")
    oreg._load.cache_clear()
    oreg._by_id.cache_clear()
    with pytest.raises(Exception):
        oreg.affiliation_for("sector_momentum_rs")
    # Restore for other tests.
    oreg._REGISTRY_PATH = ROOT / "config" / "oscillator_registry.json"
    oreg._load.cache_clear()
    oreg._by_id.cache_clear()
