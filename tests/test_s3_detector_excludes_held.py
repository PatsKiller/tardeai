"""S3 REENTRY_CANDIDATE must not propose re-entering a position already held.

Measured on CURRENT 433511415 (2026-09-01), the live desk carried:

    (held=False, READY)   1
    (held=False, NEAR)   24     -> the 25 emitted candidates
    (held=False, BLOCK)  71
    (held=True,  BLOCK)  10

Every held name was excluded, so the held-vs-candidate intersection was empty and
LITMUS_COVERAGE recorded it as "empty by design". It was not by design: nothing in
eval_s3 looked at `held`. All ten held names happened to carry status=BLOCK.

SCHG returned 0 for exactly that reason -- status=BLOCK, held=True -- and would
have been emitted as a re-entry candidate for a position already owned the moment
the desk moved it to NEAR. The empty intersection was luck that read like a rule.

These tests pin the rule so it stops depending on desk state.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

det = pytest.importorskip("scripts.lib.cio_situation_detector")


def _desk(rows):
    return {"reentry_decision_desk": {"candidates": rows}}


# ── the rule this PR adds ────────────────────────────────────────────────────

def test_a_held_name_is_never_a_reentry_candidate():
    """The load-bearing assertion. READY + held must still be excluded."""
    out = det.eval_s3(_desk([{"symbol": "SCHG", "status": "READY", "held": True}]), {})
    assert out == [], "a held position was emitted as a re-entry candidate"


def test_held_near_is_also_excluded():
    out = det.eval_s3(_desk([{"symbol": "SCHG", "status": "NEAR", "held": True}]), {})
    assert out == []


def test_the_same_symbol_unheld_IS_a_candidate():
    """Proves the guard keys on `held`, not on the symbol or on status."""
    out = det.eval_s3(_desk([{"symbol": "SCHG", "status": "READY", "held": False}]), {})
    assert len(out) == 1 and out[0]["symbols"] == ["SCHG"]


def test_held_absent_or_falsy_still_emits():
    """Only `held is True` excludes. A desk row without the field is unchanged
    behaviour -- this PR must not silently drop rows from older desk shapes."""
    for row in ({"symbol": "AAA", "status": "READY"},
                {"symbol": "BBB", "status": "READY", "held": False},
                {"symbol": "CCC", "status": "READY", "held": None},
                {"symbol": "DDD", "status": "READY", "held": 0}):
        assert len(det.eval_s3(_desk([row]), {})) == 1, f"{row} should still emit"


# ── behaviour that already existed and must not regress ──────────────────────

def test_block_is_excluded():
    """81 of 106 live rows are BLOCK. Widening the predicate would flood the
    surface with names the desk explicitly blocked."""
    out = det.eval_s3(_desk([{"symbol": "ZZZ", "status": "BLOCK", "held": False}]), {})
    assert out == []


def test_ready_and_near_are_the_admitted_set():
    rows = [{"symbol": "R", "status": "READY", "held": False},
            {"symbol": "N", "status": "NEAR", "held": False},
            {"symbol": "B", "status": "BLOCK", "held": False}]
    got = sorted(c["symbols"][0] for c in det.eval_s3(_desk(rows), {}))
    assert got == ["N", "R"]


def test_a_row_with_no_status_is_not_admitted():
    """The desk FILE carries market evidence with no status field; only the
    snapshot projection adds one. A statusless row must not default to admitted."""
    out = det.eval_s3(_desk([{"symbol": "ZZZ", "held": False, "rsi": 51.9}]), {})
    assert out == []


def test_symbol_filter_still_narrows():
    rows = [{"symbol": "AAA", "status": "READY", "held": False},
            {"symbol": "BBB", "status": "READY", "held": False}]
    out = det.eval_s3(_desk(rows), {}, symbol="BBB")
    assert len(out) == 1 and out[0]["symbols"] == ["BBB"]


def test_emitted_candidate_creates_no_order():
    """S3 is advisory. MBI_BEHAVIOR=0 -- the surface must never carry an order."""
    out = det.eval_s3(_desk([{"symbol": "AAA", "status": "READY", "held": False}]), {})
    c = out[0]
    assert "no broker order" in c["recommendation"].lower()
    assert all(o["id"] in {"watch_reentry", "staged_interest", "pass"} for o in c["options"])
