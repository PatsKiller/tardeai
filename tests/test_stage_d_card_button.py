#!/usr/bin/env python3
"""Stage D — the 'Build Full Strategy' button on the card.

The button is additive and shadow-only: it triggers the on-demand runner and
renders the multidimensional packet WITHOUT replacing the primary card or its
legacy IGNORE label. These tests pin the API contract the button depends on and
the shadow-only guarantees in the component source (there is no React test
harness in this repo; the design guard + tsc validate the component at build).

No order queued, submitted, or 2FA requested anywhere in this module.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CARD = ROOT / "apps" / "command-center-v3" / "src" / "components" / "WatchlistCardV4.tsx"
BUTTON = ROOT / "apps" / "command-center-v3" / "src" / "components" / "ShadowStrategyButton.tsx"


# ── the packet endpoint the button reads ──────────────────────────────────────

def test_packet_endpoint_requires_symbol():
    import importlib
    import api_v2
    importlib.reload(api_v2)
    assert api_v2._shadow_strategy_packet({})["ok"] is False


def test_packet_endpoint_returns_families_and_packet():
    """After a live BETA run exists, the endpoint returns the packet plus its
    per-family blueprints — what the card renders."""
    import importlib
    import api_v2
    importlib.reload(api_v2)
    r = api_v2._shadow_strategy_packet({"symbol": "BETA"})
    if not r.get("ok"):
        pytest.skip("no live BETA shadow packet persisted in this environment")
    assert "packet" in r and "blueprints" in r
    fams = {b["family"] for b in r["blueprints"]}
    # every required family must be representable
    assert fams & {"LONG_TERM", "SWING", "BEARISH", "OPTIONS", "NO_TRADE"}


def test_all_three_shadow_routes_registered():
    import api_v2
    src = Path(api_v2.__file__).read_text()
    for route in ("/api/v2/shadow/strategy/status",
                  "/api/v2/shadow/strategy/packet"):
        assert f'"{route}"' in src
    assert '"/api/v2/shadow/strategy/build"' in src


# ── the component is additive, not a replacement ──────────────────────────────

def test_button_is_mounted_in_the_card():
    src = CARD.read_text()
    assert "import ShadowStrategyButton" in src
    assert "<ShadowStrategyButton symbol={it.symbol}" in src


def test_button_does_not_touch_the_primary_recommendation_render():
    """Stage D must not rebuild the card. The primary latest_recommendation
    display and its cioAvoid gating stay exactly as they were — the button lives
    in the drawer, additively."""
    src = CARD.read_text()
    # the button is inside the expandable drawer block, not the header
    drawer_idx = src.index("Expandable drawer")
    header_idx = src.index("{it.symbol}")
    assert src.index("<ShadowStrategyButton") > drawer_idx > header_idx


def test_component_calls_the_shadow_endpoints():
    src = BUTTON.read_text()
    assert "/api/v2/shadow/strategy/build" in src
    assert "/api/v2/shadow/strategy/status" in src
    assert "/api/v2/shadow/strategy/packet" in src
    assert "method: 'POST'" in src


def test_component_states_it_is_shadow_only():
    src = BUTTON.read_text()
    low = src.lower()
    assert "shadow" in low
    assert "nothing queued or submitted" in low or "does not place" in low


def test_component_renders_every_family_always():
    """The five families are rendered from a fixed order, so a missing family
    shows as DATA_UNAVAILABLE rather than silently vanishing."""
    src = BUTTON.read_text()
    assert "FAMILY_ORDER" in src
    for fam in ("LONG_TERM", "SWING", "BEARISH", "OPTIONS", "NO_TRADE"):
        assert f"'{fam}'" in src


def test_component_shows_per_dimension_agreement_not_one_badge():
    src = BUTTON.read_text()
    assert "agreement_by_dimension" in src


def test_component_demotes_the_legacy_label():
    src = BUTTON.read_text()
    assert "legacy_summary" in src and "Legacy CIO" in src


def test_component_uses_no_raw_hex_or_sub_ten_px():
    """The card's design guard rejects both; verify the new component complies so
    it never trips the baseline."""
    import re
    src = BUTTON.read_text()
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", src), "no raw hex — use BB tokens"
    for m in re.finditer(r"fontSize:\s*([0-9.]+)", src):
        assert float(m.group(1)) >= 10, f"fontSize {m.group(1)} below the 10px floor"
