#!/usr/bin/env python3
"""The R:R backfill — arithmetic, void rule, and the comparison that kept leaking.

Three comparisons were tried before one held, and each earlier attempt silently
left rows behind:

  abs(stored - value) < 0.1   `abs(10.8 - 10.9)` is 0.09999999999999964 in binary
                              float, so 171 rows off by a full decimal place
                              counted as equal.
  round(stored, 1) == value   `round(1.25, 1)` is 1.2 under banker's rounding, so
                              a stored 1.25 matched a computed 1.2 and the
                              model's two-decimal number survived — true value
                              1.1667.
  float(stored) == value      holds.

The lesson is in the third: any rule about "close enough" needs its own rule, and
both of the ones tried leaked. The stored figure IS the computed figure.

Pure: no database. The arithmetic and the decision rule are exercised directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_entry_plan_rr as bf  # noqa: E402

SRC = (ROOT / "scripts" / "backfill_entry_plan_rr.py").read_text()


# ── the arithmetic ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("limit,stop,target,expected", [
    (203.5, 198.0, 225.0, 3.9),      # NVDA, stored 1.2
    (17.75, 16.94, 20.00, 2.8),      # BETA first plan, stored 1.5
    (18.00, 16.70, 20.50, 1.9),      # BETA second plan, stored 1.5 again
    (2.55, 2.40, 2.82, 1.8),         # ATOS, stored 2.0 — overstated
    (6.20, 5.50, 7.50, 1.9),
])
def test_recompute(limit, stop, target, expected):
    value, reason = bf._compute(limit, stop, target)
    assert value == expected and reason == "recomputed"


def test_a_poor_trade_is_allowed_to_look_poor():
    value, _ = bf._compute(10.0, 9.5, 10.25)
    assert value == 0.5


# ── the void rule ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("limit,stop", [(10.0, 10.0), (10.0, 11.0)])
def test_non_positive_risk_yields_no_rr(limit, stop):
    """A stop at or above the limit cannot produce a meaningful R:R. NULL beats
    a number nobody can reproduce."""
    value, reason = bf._compute(limit, stop, 12.0)
    assert value is None and reason == "inverted_or_zero_risk"


@pytest.mark.parametrize("levels", [
    (None, 9.0, 12.0), (10.0, None, 12.0), (10.0, 9.0, None),
])
def test_missing_levels_yield_no_rr(levels):
    value, reason = bf._compute(*levels)
    assert value is None and reason == "missing_levels"


# ── the comparison that decides whether a row is rewritten ────────────────────

def test_float_tolerance_would_have_missed_a_full_decimal():
    """The first attempt's actual failure, as arithmetic."""
    assert abs(10.8 - 10.9) < 0.1        # the bug: True in binary float
    assert 10.8 != 10.9                  # exact equality does not lie


def test_bankers_rounding_would_have_kept_a_two_decimal_claim():
    """The second attempt's actual failure."""
    assert round(1.25, 1) == 1.2         # banker's rounding
    true_value, _ = bf._compute(35.2, 33.5, 37.5)
    assert true_value == 1.4             # so a stored 1.25 must NOT be kept
    assert float(1.25) != true_value


def test_backfill_uses_exact_equality():
    assert "float(stored) == value" in SRC, \
        "the comparison regressed to a tolerance — earlier ones leaked rows"


# ── safety properties ─────────────────────────────────────────────────────────

def test_dry_run_is_the_default():
    assert 'ap.add_argument("--apply"' in SRC
    assert "def run(apply: bool = False)" in SRC


def test_levels_are_never_modified():
    """Only the DERIVED figure changes. The model's chosen levels stand."""
    assert "SET risk_reward = %s, plan = %s::jsonb" in SRC
    for col in ("limit_price =", "stop_price =", "target_price ="):
        assert col not in SRC, f"backfill must not rewrite {col.strip(' =')}"


def test_original_claim_is_preserved():
    assert 'risk_reward_model_claimed' in SRC


def test_idempotent_via_source_tag():
    assert 'plan.get("risk_reward_source") == SOURCE_TAG' in SRC


def test_single_transaction():
    assert "executemany" in SRC and SRC.count("conn.commit()") == 1


def test_void_records_its_reason():
    assert "risk_reward_void_reason" in SRC
