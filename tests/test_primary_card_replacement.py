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
# The band's decision/CTA logic moved into a presenter (operatorDecisionCard) in the
# 82415fa6 operator-card refactor; the operator CONTRACT is asserted semantically
# against it rather than against literal band copy.
PRES = ROOT / "apps" / "command-center-v3" / "src" / "lib" / "operatorDecisionCard.ts"


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
#
# SEMANTIC CONTRACT (survives the 82415fa6 operator-card refactor, which lifted the
# decision logic into buildOperatorPresentation and hides — rather than merely dims
# — the legacy strip when a packet leads). These assert the still-required operator
# behaviour, not literal copy.

def test_band_returns_nothing_without_a_packet():
    """No packet ⇒ the band renders nothing (guard now lives in the presenter)."""
    assert "if (!pres) return null" in BAND.read_text()
    assert "if (!packet || typeof packet !== 'object') return null" in PRES.read_text()


def test_band_leads_above_the_legacy_verdict_strip():
    """The decision band renders before the legacy strip, and the legacy strip is
    gated so it appears ONLY when there is no packet."""
    src = CARD.read_text()
    band = src.index("<DecisionPacketBand")
    legacy = src.index("Legacy verdict strip")
    assert band < legacy, "the decision band must render before the legacy verdict strip"
    # the legacy strip block is entirely conditional on NOT having a packet
    assert "ONLY when no packet" in src
    assert src.index("{hasPacket && (") < src.index("{!hasPacket && (")


def test_legacy_one_word_label_is_absent_from_the_primary_surface_when_a_packet_leads():
    """With a packet, the one-word CIO label / verdict strip does not render at all
    (stronger than the old opacity demotion) — it is gated behind !hasPacket."""
    src = CARD.read_text()
    gate = src.index("{!hasPacket && (")
    label = src.index("title={`CIO view: ${cioLabel}`}")
    assert gate < label, "the cioLabel must sit inside the !hasPacket-gated legacy strip"
    # there is no unconditional render of the one-word label as a primary element
    assert "hasPacket ? `prior ${cioLabel}`" not in src


def test_agree_split_badge_hidden_when_packet_present():
    """The anchored models_agree AGREE/SPLIT badge only shows on the legacy strip,
    which is itself hidden when a packet leads."""
    src = CARD.read_text()
    gate = src.index("{!hasPacket && (")
    agree = src.index("it.models_agree === true")
    assert gate < agree, "AGREE/SPLIT must sit inside the !hasPacket-gated legacy strip"


def test_only_ready_leads_to_a_proposal_cta_stale_leads_to_refresh():
    """The core operator-safety contract: a proposal CTA is reachable ONLY from a
    READY state; a stale packet routes to REFRESH, never a proposal."""
    pres = PRES.read_text()
    # READY is the only state that produces the proposal CTA
    assert "state = 'READY'" in pres and "Review Swing Proposal" in pres
    # stale / should_be_stale ⇒ REFRESH with a refresh CTA (not a proposal)
    assert "state = 'REFRESH'" in pres and "Refresh Strategy" in pres
    # the card only calls onPropose on READY — never on a stale/blocked/wait state
    card = CARD.read_text()
    assert "pres.state === 'READY' && onPropose" in card
    assert "never queue/approve/submit orders" in card


def test_held_symbol_uses_position_management_language():
    """A held symbol is framed as position management, not a fresh entry proposal."""
    pres = PRES.read_text()
    assert "MANAGE POSITION" in pres
    assert "Review Position" in pres


def test_audit_drawer_lists_all_families_and_demotes_legacy():
    """Every family remains available in the audit drawer, and the legacy verdict is
    explicitly demoted to 'not the operator decision'."""
    src = BAND.read_text()
    for fam in ("LONG_TERM", "SWING", "BEARISH", "OPTIONS", "NO_TRADE"):
        assert f"'{fam}'" in src, f"audit drawer missing family {fam}"
    assert "Legacy @ build" in src
    assert "not the operator decision" in src


def test_band_shows_per_dimension_agreement_not_one_badge():
    """Per-dimension model agreement is surfaced (audit), not collapsed to one badge."""
    assert "agreement_by_dimension" in BAND.read_text()
    assert "model_review" in PRES.read_text()


def test_family_state_reads_the_rollup_not_the_first_blueprint():
    """plan_families' rolled-up decision_state is authoritative; a raw blueprint row
    would mis-summarise OPTIONS (several structures)."""
    pres = PRES.read_text()
    assert "packet.plan_families" in pres
    assert "decision_state" in pres and "structures[0]" not in pres


def test_band_uses_no_raw_hex_or_sub_ten_px():
    import re
    src = BAND.read_text()
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", src), "no raw hex — BB tokens only"
    for m in re.finditer(r"fontSize:\s*([0-9.]+)", src):
        assert float(m.group(1)) >= 10, f"fontSize {m.group(1)} below the 10px floor"
