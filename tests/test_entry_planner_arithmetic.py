#!/usr/bin/env python3
"""Entry-plan arithmetic must be computed, not accepted.

BETA's first plan (2026-07-20) stored risk_reward=1.5 against limit 17.75 /
stop 16.94 / target 20.00, where the arithmetic gives 2.78 — and 1.00 to its own
T1 rung. The stored number was not derivable from any level in the plan. The
prompt asked for (target-limit)/(limit-stop) and nothing checked the answer.

The same plan claimed urgency=near_entry with spot at 19.805 against an entry
zone topping out at 18.20 — 1.45 ATR away. The only server-side adjustment was
an UPGRADE, so an overstated urgency had no path back down. near_entry is one of
two values that unlock PROPOSE_ENTRY, so this lit a button that should have been
dark.

The model picks levels. The levels imply everything else.

Pure: no database, no LLM, no network.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SRC = (ROOT / "scripts" / "watchlist_entry_planner.py").read_text()


def _write_path() -> str:
    """The block between parsing the model output and the INSERT."""
    start = SRC.index("DETERMINISTIC R:R AND URGENCY")
    return SRC[start:SRC.index("INSERT INTO watchlist_entry_plans", start)]


# ── the values are recomputed at all ──────────────────────────────────────────

def test_risk_reward_is_recomputed_from_levels():
    blk = _write_path()
    assert 'p["risk_reward"] = round(' in blk, "risk_reward must be computed, not passed through"
    assert "float(_tgt) - float(_lim)" in blk and "float(_lim) - float(_stop)" in blk


def test_urgency_is_recomputed_from_atr_distance():
    blk = _write_path()
    assert 'p["urgency"] = urg' in blk
    assert "_atr" in blk and "near_entry" in blk


def test_model_claims_are_preserved_for_audit():
    """Silently overwriting a wrong number hides that the model produced one."""
    blk = _write_path()
    for k in ("risk_reward_model_claimed", "urgency_model_claimed"):
        assert k in blk, f"{k} must record what the model claimed"


# ── the arithmetic itself ─────────────────────────────────────────────────────

def _rr(limit, stop, target):
    return round((target - limit) / (limit - stop), 1)


def test_beta_stored_value_was_wrong():
    """The regression case, stated as arithmetic."""
    assert _rr(17.75, 16.94, 20.00) == 2.8
    assert _rr(17.75, 16.94, 20.00) != 1.5


@pytest.mark.parametrize("limit,stop,target,expected", [
    (17.75, 16.94, 20.00, 2.8),
    (100.0, 95.0, 115.0, 3.0),
    (50.0, 49.0, 51.0, 1.0),
    (10.0, 9.5, 10.25, 0.5),      # a poor trade must be allowed to look poor
])
def test_rr_arithmetic(limit, stop, target, expected):
    assert _rr(limit, stop, target) == expected


def _urgency(px, zlo, zhi, atr):
    if zlo <= px <= zhi:
        return "ready"
    dist = (zlo - px) if px < zlo else (px - zhi)
    return "near_entry" if dist <= atr else "watch"


@pytest.mark.parametrize("px,zlo,zhi,atr,expected", [
    (19.805, 17.08, 18.20, 1.11, "watch"),      # BETA: 1.45 ATR above the zone
    (17.50, 17.08, 18.20, 1.11, "ready"),       # inside
    (17.08, 17.08, 18.20, 1.11, "ready"),       # exactly the lower edge
    (18.20, 17.08, 18.20, 1.11, "ready"),       # exactly the upper edge
    (19.00, 17.08, 18.20, 1.11, "near_entry"),  # 0.72 ATR above
    (16.50, 17.08, 18.20, 1.11, "near_entry"),  # 0.52 ATR BELOW — proximity is symmetric
    (15.00, 17.08, 18.20, 1.11, "watch"),       # 1.87 ATR below
])
def test_urgency_from_distance(px, zlo, zhi, atr, expected):
    assert _urgency(px, zlo, zhi, atr) == expected


def test_urgency_is_measured_to_the_near_edge():
    """Measuring to the far edge would understate distance and overstate urgency."""
    # 19.00 is 0.80 above the TOP (18.20) but 1.92 above the BOTTOM (17.08).
    assert _urgency(19.00, 17.08, 18.20, 1.11) == "near_entry"
    assert (19.00 - 18.20) / 1.11 < 1.0 < (19.00 - 17.08) / 1.11


# ── failure modes ─────────────────────────────────────────────────────────────

def test_unverifiable_levels_carry_no_rr():
    """A stop at or above the limit gives a non-positive or inverted risk. Better
    to store nothing than a number nobody can reproduce."""
    blk = _write_path()
    assert 'p["risk_reward"] = None' in blk
    assert "rejected_unverifiable_levels" in blk


def test_missing_atr_fails_to_the_locked_state():
    """No ATR means the distance rule cannot run. It must fall to the value that
    does NOT unlock PROPOSE_ENTRY."""
    blk = _write_path()
    idx = blk.index("no_atr_failed_closed")
    window = blk[max(0, idx - 400):idx]
    assert '"watch"' in window, "no-ATR fallback must default to watch, not near_entry"


def test_ready_tag_can_be_demoted_but_never_promoted():
    """READY is a claim the model must make itself; arithmetic may only take it
    away. Promoting on arithmetic alone would manufacture conviction."""
    blk = SRC[SRC.index("prop = p.get(\"proposal\")"):SRC.index("p[\"scope\"] = scope")]
    assert '"NEEDS_CONFIRMATION"' in blk
    assert 'tag_model_claimed' in blk
    # Nothing in the block may assign READY.
    assert not re.search(r'tag"?\]?\s*=\s*"READY"', blk), "tag must never be promoted to READY"


def test_demotion_requires_both_urgency_and_confidence():
    blk = SRC[SRC.index("prop = p.get(\"proposal\")"):SRC.index("p[\"scope\"] = scope")]
    assert 'urg == "ready"' in blk and "0.7" in blk


# ── the alert and the button are downstream of urgency ────────────────────────

def test_alert_gate_still_reads_the_recomputed_urgency():
    """The alert fires on near_entry/ready. It must see the corrected value, so
    the recompute has to happen BEFORE the alert check."""
    recompute = SRC.index('p["urgency"] = urg')
    alert = SRC.index('if alert and urg in ("near_entry", "ready")')
    assert recompute < alert, "urgency must be recomputed before the alert gate reads it"


def test_recompute_happens_before_the_insert():
    recompute = SRC.index('p["urgency"] = urg')
    insert = SRC.index("INSERT INTO watchlist_entry_plans")
    assert recompute < insert


# ── proposals-branch regression (P0-1 + P1-7, 2026-08-03) ───────────────────

def test_proposals_candidates_returns_list_not_none():
    """The --scope proposals branch crashed every cron run since 2026-06-12
    because _candidates returned None (fell off the function end).
    The fix (line ~250) must return a list, not None."""
    # Find the proposals-scope return statement
    proposals_block = SRC[SRC.index('if scope == "proposals"'):]
    return_idx = proposals_block.index("return [dict")
    # The return must come BEFORE the else block that handles watchlist scope
    else_idx = proposals_block.index("else:")
    assert return_idx < else_idx, (
        "proposals scope must return a list BEFORE falling through to else. "
        "The None-return bug (2026-06-12) was: no return in the if-block, so "
        "the function fell off the end returning None."
    )


def test_analyst_function_uses_correct_column_name():
    """P0-1 (2026-08-03): deployed analyst_detail.py queried number_of_analysts
    but the column is number_of_analyst_opinions. Every cron died on UndefinedColumn.
    The merged-tree _analyst function must use the correct column name."""
    analyst_fn = SRC[SRC.index("def _analyst"):SRC.index("def ", SRC.index("def _analyst") + 1)]
    assert "number_of_analyst_opinions" in analyst_fn, (
        "P0-1 regression: _analyst must query number_of_analyst_opinions "
        "(NOT number_of_analysts — that column doesn't exist)"
    )


def test_proposals_sql_references_real_columns():
    """The proposals-branch SQL must only reference columns that exist in
    paper_trade_proposals. Verify the SELECT list is safe."""
    # Extract the proposals SQL
    proposals_block = SRC[SRC.index('if scope == "proposals"'):]
    sql_start = proposals_block.index('cur.execute("""')
    sql_end = proposals_block.index('""")', sql_start)
    sql = proposals_block[sql_start:sql_end]

    # These columns must exist in paper_trade_proposals
    required = ["symbol", "id", "proposed_entry", "proposed_stop",
                "proposed_target1", "strategy_id", "status", "created_at"]
    for col in required:
        assert col in sql, f"proposals SQL must reference column: {col}"

    # The SQL must reference paper_trade_proposals (not some other table)
    assert "paper_trade_proposals" in sql, "proposals scope must query paper_trade_proposals"
