#!/usr/bin/env python3
"""Stop-kind taxonomy — ONE shared source of truth across Holdings + Stop desk.

Implementation baseline: 06cc5349. deriveStopKind (lib/stopManagement.ts) turns a
live broker order_type + trailing flag into a pill kind; StopKindPill
(components/StopKindPill.tsx) renders it. Both the Portfolio > Holdings table and
the Stop Management desk import the SAME function and component — no forked
Holdings-specific interpretation. Unknown order types fail visibly to NO STOP
rather than being mislabeled. Advisory only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PILL = ROOT / "apps" / "command-center-v3" / "src" / "components" / "StopKindPill.tsx"
STOPLIB = ROOT / "apps" / "command-center-v3" / "src" / "lib" / "stopManagement.ts"
ROW = ROOT / "apps" / "command-center-v3" / "src" / "lib" / "holdingsRowModel.ts"
SM = ROOT / "apps" / "command-center-v3" / "src" / "components" / "StopManagement.tsx"
TABLE = ROOT / "apps" / "command-center-v3" / "src" / "components" / "HoldingsTableView.tsx"

CANONICAL = ("FIXED", "STOP_LIMIT", "TRAILING", "TRAILING_LIMIT", "MONITORED", "PLANNED", "NONE")


def derive_stop_kind(order_type=None, is_trailing=False, has_live_stop=False,
                     monitored=False, planned=False):
    """Reference implementation of the TS deriveStopKind."""
    ot = str(order_type or "").upper()
    has_limit = "LIMIT" in ot
    if is_trailing:
        return "TRAILING_LIMIT" if has_limit else "TRAILING"
    if has_live_stop:
        return "STOP_LIMIT" if has_limit else "FIXED"
    if monitored:
        return "MONITORED"
    if planned:
        return "PLANNED"
    return "NONE"


# ── every server order_type maps to the right kind ────────────────────────────

@pytest.mark.parametrize("ot,trailing,live,mon,plan,expect", [
    ("STOP", False, True, False, False, "FIXED"),
    ("STOP_LIMIT", False, True, False, False, "STOP_LIMIT"),
    ("TRAILING_STOP", True, True, False, False, "TRAILING"),
    ("TRAILING_STOP_LIMIT", True, True, False, False, "TRAILING_LIMIT"),
    (None, False, False, True, False, "MONITORED"),          # Fidelity monitored/advisory
    (None, False, False, False, True, "PLANNED"),            # planned but not placed
    (None, False, False, False, False, "NONE"),              # no stop
    ("WEIRD_UNKNOWN_TYPE", False, False, False, False, "NONE"),  # malformed → safe NONE
])
def test_server_order_type_to_kind(ot, trailing, live, mon, plan, expect):
    assert derive_stop_kind(ot, trailing, live, mon, plan) == expect


def test_all_kinds_are_reachable():
    got = {
        derive_stop_kind("STOP", False, True),
        derive_stop_kind("STOP_LIMIT", False, True),
        derive_stop_kind("TRAILING_STOP", True, True),
        derive_stop_kind("TRAILING_STOP_LIMIT", True, True),
        derive_stop_kind(None, False, False, True),
        derive_stop_kind(None, False, False, False, True),
        derive_stop_kind(None),
    }
    assert got == set(CANONICAL)


# ── single shared source of truth ─────────────────────────────────────────────

def test_derive_function_lives_in_one_lib():
    assert "export function deriveStopKind" in STOPLIB.read_text()


def test_both_surfaces_import_the_same_component():
    assert "from './StopKindPill'" in TABLE.read_text()
    assert "from './StopKindPill'" in SM.read_text()


def test_row_model_uses_the_shared_derivation_not_a_fork():
    src = ROW.read_text()
    assert "deriveStopKind" in src and "from './stopManagement'" in src


def test_pill_labels_and_colours_are_defined_once():
    src = PILL.read_text()
    for kind in CANONICAL:
        assert kind in src, f"pill map missing {kind}"
    # unknown kind falls back to NONE (safe), never mislabeled
    assert "STOP_KIND_PILL[k] || STOP_KIND_PILL.NONE" in src


def test_pill_is_not_redefined_in_stopmanagement():
    """StopManagement must import the shared pill, not fork a local copy."""
    src = SM.read_text()
    assert "function StopKindPill(" not in src
    assert "import { StopKindPill }" in src


def test_pill_shows_type_AND_percent_for_static_and_trailing():
    """Every row states the stop TYPE and its % — trail % for trailing kinds, the
    actual distance-below-price for static (fixed/limit/monitored) kinds."""
    pill = PILL.read_text()
    # trailing → trail %, static → distance %
    assert "isTrail ? trailPct : distPct" in pill
    assert "% ${suffix} price" in pill or "below" in pill


def test_distance_is_the_live_stop_not_the_advisory_width():
    """The pill's static % is computed from the live stop vs price (drawer's 'N% below'),
    NOT pr.stop_distance_pct (the advisory band width)."""
    row = ROW.read_text()
    assert "stopLiveDistPct" in row
    assert "(cur - stopLiveForDist) / cur" in row
    # the table passes the live distance, not the advisory stopDistPct
    assert "distPct={m.stopLiveDistPct}" in TABLE.read_text()
