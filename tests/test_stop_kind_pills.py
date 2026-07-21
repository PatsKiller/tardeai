#!/usr/bin/env python3
"""Stop KIND is preserved and shown as distinct labelled pills.

The stop-management row collapsed everything to a coarse stop_type
(TRAILING/MONITORED/HARD/PLANNED/NONE) that dropped the LIMIT distinction, so
fixed vs stop-limit vs trailing vs trailing-limit were not legible. The API now
emits a precise stop_kind (+ raw order_type) and the UI renders a colour-coded
pill on the row and the manage modal.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SM = ROOT / "apps" / "command-center-v3" / "src" / "components" / "StopManagement.tsx"
# The pill was lifted into a shared component so the Holdings table renders the identical one.
PILL = ROOT / "apps" / "command-center-v3" / "src" / "components" / "StopKindPill.tsx"
HOLD = ROOT / "apps" / "command-center-v3" / "src" / "components" / "HoldingsTableView.tsx"


def test_api_emits_stop_kind_and_order_type():
    import api_v2
    src = Path(api_v2.__file__).read_text()
    assert '"stop_kind": (' in src
    assert '"order_type": (str((ls or {}).get("order_type")' in src


def test_stop_kind_preserves_the_limit_distinction():
    """The coarse stop_type dropped LIMIT; stop_kind must keep it."""
    import api_v2
    src = Path(api_v2.__file__).read_text()
    blk = src[src.index('"stop_kind": ('):src.index('"stop_kind": (') + 700]
    for kind in ("TRAILING_LIMIT", "TRAILING", "STOP_LIMIT", "FIXED", "MONITORED", "PLANNED", "NONE"):
        assert kind in blk, f"stop_kind missing {kind}"
    # trailing-limit requires BOTH trailing AND limit
    assert 'is_trailing and "LIMIT" in' in blk


def test_pill_has_a_distinct_colour_per_kind():
    src = PILL.read_text()
    assert "STOP_KIND_PILL" in src
    # four principal kinds each mapped to a colour
    for kind in ("FIXED", "STOP_LIMIT", "TRAILING", "TRAILING_LIMIT"):
        assert kind in src[src.index("STOP_KIND_PILL"):src.index("STOP_KIND_PILL") + 700]


def test_pill_labels_are_human_readable():
    src = PILL.read_text()
    blk = src[src.index("STOP_KIND_PILL"):src.index("STOP_KIND_PILL") + 700]
    assert "'STOP LIMIT'" in blk and "'TRAILING LIMIT'" in blk


def test_pill_rendered_on_row_and_modal():
    src = SM.read_text()
    assert src.count("<StopKindPill") >= 2, "pill must show on the row AND the manage modal"


def test_pill_rendered_on_holdings_table():
    """The pill is the SAME shared component on the Portfolio > Holdings table."""
    src = HOLD.read_text()
    assert "<StopKindPill" in src and "from './StopKindPill'" in src


def test_trailing_pill_shows_the_trail_pct():
    src = PILL.read_text()
    blk = src[src.index("function StopKindPill"):src.index("function StopKindPill") + 900]
    assert "trailPct" in blk and "%" in blk
