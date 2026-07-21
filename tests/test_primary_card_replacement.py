#!/usr/bin/env python3
"""Primary-card replacement — the multidimensional packet leads; legacy demoted.

The one-word CIO label (IGNORE/AVOID/HOLD) no longer leads a card that has a
decision packet. The packet is attached INLINE to the watchlist item so the card
renders it as the primary surface with no per-card fetch, and the legacy verdict
band is dimmed and relabelled "prior" — present for history, not the source of
truth. Cards without a packet are unchanged (no regression).

No order queued, submitted, or 2FA requested anywhere in this module.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CARD = ROOT / "apps" / "command-center-v3" / "src" / "components" / "WatchlistCardV4.tsx"
BAND = ROOT / "apps" / "command-center-v3" / "src" / "components" / "DecisionPacketBand.tsx"


# ── backend: packet delivered inline on the item ──────────────────────────────

def test_items_query_joins_the_latest_live_packet():
    import api_v2
    src = Path(api_v2.__file__).read_text()
    assert "dpk.packet AS decision_packet" in src
    assert "dpk.generated_at AS decision_packet_at" in src
    # must join the LIVE (non-superseded) packet, newest first
    j = src[src.index("FROM decision_packets dpp"):]
    assert "superseded_by IS NULL" in j[:400]
    assert "ORDER BY dpp.generated_at DESC LIMIT 1" in j[:400]


def test_analysed_symbol_carries_a_packet_and_others_do_not():
    import importlib
    import api_v2
    importlib.reload(api_v2)
    r = api_v2._wl_items({"symbol": ["BETA"]})
    items = r.get("items") or []
    if not items or not items[0].get("decision_packet"):
        pytest.skip("no live BETA packet persisted in this environment")
    beta = items[0]
    assert beta["decision_packet"].get("headline")
    assert beta.get("decision_packet_at")


def test_inline_packet_does_not_blow_up_list_latency():
    """The lateral join must not turn the 200-card list into a slow query."""
    import importlib
    import api_v2
    importlib.reload(api_v2)
    t0 = time.time()
    r = api_v2._wl_items({"sort": ["hermes"]})
    dt = (time.time() - t0) * 1000
    assert len(r.get("items") or []) > 0
    assert dt < 6000, f"items list took {dt:.0f}ms — the packet join regressed it"


# ── frontend: the band leads, and degrades gracefully ─────────────────────────

def test_band_returns_nothing_without_a_packet():
    """A card for an un-analysed symbol keeps its legacy band unchanged."""
    src = BAND.read_text()
    assert "if (!packet || typeof packet !== 'object') return null" in src


def test_band_is_mounted_ABOVE_the_legacy_verdict_strip():
    src = CARD.read_text()
    band = src.index("<DecisionPacketBand")
    strip = src.index("Recommendation + status strip")
    assert band < strip, "the decision band must render before the legacy verdict strip"


def test_legacy_strip_is_demoted_when_a_packet_leads():
    src = CARD.read_text()
    assert "opacity: hasPacket ? 0.55 : 1" in src
    assert "hasPacket ? `prior ${cioLabel}`" in src


def test_anchored_agree_split_badge_hidden_when_packet_present():
    """The old models_agree badge is the anchored one the blind per-dimension
    agreement replaces; it must not show alongside the packet."""
    src = CARD.read_text()
    assert "!hasPacket && it.models_agree === true" in src
    assert "!hasPacket && it.models_agree === false" in src


def test_band_shows_every_family_and_demotes_legacy_label():
    src = BAND.read_text()
    assert "FAMILY_ORDER" in src
    for fam in ("LONG_TERM", "SWING", "BEARISH", "OPTIONS", "NO_TRADE"):
        assert f"'{fam}'" in src
    assert "prior CIO" in src
    assert "not the source of truth" in src


def test_band_shows_per_dimension_agreement_not_one_badge():
    src = BAND.read_text()
    assert "agreement_by_dimension" in src
    # and it warns when the mode is not a genuine blind consensus
    assert "not an independent consensus" in src


def test_band_reads_family_state_from_the_rollup_not_first_blueprint():
    """plan_families carries the authoritative family state; reading a blueprint
    row would mis-summarise OPTIONS (several structures)."""
    src = BAND.read_text()
    assert "plan_families" in src


def test_band_uses_no_raw_hex_or_sub_ten_px():
    import re
    src = BAND.read_text()
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", src), "no raw hex — BB tokens only"
    for m in re.finditer(r"fontSize:\s*([0-9.]+)", src):
        assert float(m.group(1)) >= 10, f"fontSize {m.group(1)} below the 10px floor"


def test_one_word_label_is_no_longer_the_primary_when_packet_exists():
    """The decisive property of this stage: with a packet, the legacy label is
    prefixed 'prior' and dimmed — it does not lead."""
    src = CARD.read_text()
    # the primary lead is the band; the legacy word is demoted text
    assert "the decision packet above is the source of truth" in src
