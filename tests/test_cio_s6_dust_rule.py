"""S6 must not fire on a subject that is not a position.

S6_CONCENTRATION_OR_DISPOSITION asks a question that presupposes a position.
It fired forever on SRNE: a $0.90 residual against its cost basis is a 100% loss
held 36 months, so the disposition branch matched on every pass — and a residual
can never stop being a 100% loss. Twenty such plans were cancelled by hand on
2026-08-29 and a new one reappeared within twenty minutes.

The rule only ever SKIPS a fire. No threshold is loosened, no new fire is added,
and a real concentration must still fire.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_situation_detector import (
    SITUATION_CODES,
    eval_s6,
    eval_s6_skipped_subjects,
)

CFG = {"thresholds": {
    "concentration_weight_pct": 12.0,
    "disposition_loss_pct": 20.0,
    "disposition_hold_months": 6.0,
}}


def _evidence(rows, *, total=1_287_999.68, cost_basis=None, quotes=None):
    return {
        "holdings_detail": {"holdings": rows},
        "portfolio": {"total_value": total},
        "cost_basis": {"positions": cost_basis or []},
        "quotes": quotes or {},
    }


# The exact shape that was re-firing on CURRENT.
SRNE_ROW = {"symbol": "SRNE", "market_value": 0.90, "shares": 1000.0,
            "disposition_flag": True}
SRNE_BASIS = [{"symbol": "SRNE", "holding_months": 36.0, "avg_cost_per_share": 5.0}]
SRNE_QUOTE = {"SRNE": {"last": 0.0009}}
SCHD_ROW = {"symbol": "SCHD", "market_value": 365_694.75, "shares": 10_406.79}


def _symbols(cands):
    return sorted(c["symbols"][0] for c in cands)


# ── the regression ───────────────────────────────────────────────────────────

def test_a_dust_residual_no_longer_fires_the_disposition_rule():
    ev = _evidence([SRNE_ROW], cost_basis=SRNE_BASIS, quotes=SRNE_QUOTE)
    assert eval_s6(ev, CFG) == []
    assert eval_s6_skipped_subjects(ev, CFG) == [
        {"symbol": "SRNE", "reason": "dust_residual"},
    ]


def test_the_disposition_rule_would_otherwise_have_matched():
    """Guard the guard: without the residual, this exact shape does fire.

    If the underlying disposition branch ever stops matching, the test above
    would pass for the wrong reason and silently stop protecting anything.
    """
    real = {**SRNE_ROW, "symbol": "REAL", "market_value": 50_000.0}
    basis = [{"symbol": "REAL", "holding_months": 36.0, "avg_cost_per_share": 5.0}]
    ev = _evidence([real], cost_basis=basis, quotes={"REAL": {"last": 0.0009}})
    fired = eval_s6(ev, CFG)
    assert _symbols(fired) == ["REAL"]
    assert any("disposition" in r for r in fired[0]["fire_reasons"])


def test_a_real_concentration_still_fires():
    ev = _evidence([SCHD_ROW])
    fired = eval_s6(ev, CFG)
    assert _symbols(fired) == ["SCHD"]
    assert fired[0]["situation_type"] == SITUATION_CODES["S6"]
    assert any(r.startswith("weight_") for r in fired[0]["fire_reasons"])


def test_dust_and_a_real_position_together():
    ev = _evidence([SCHD_ROW, SRNE_ROW], cost_basis=SRNE_BASIS, quotes=SRNE_QUOTE)
    fired = eval_s6(ev, CFG)
    assert _symbols(fired) == ["SCHD"]
    assert fired[0]["s6_skipped_subjects"] == [{"symbol": "SRNE", "reason": "dust_residual"}]


# ── the other non-positions ──────────────────────────────────────────────────

def test_a_cusip_row_is_not_a_subject():
    row = {"symbol": "12507E201", "market_value": 0.0, "shares": 7.0}
    ev = _evidence([row])
    assert eval_s6(ev, CFG) == []
    assert eval_s6_skipped_subjects(ev, CFG) == [
        {"symbol": "12507E201", "reason": "not_a_ticker"},
    ]


def test_cash_is_still_excluded_before_the_new_rule():
    ev = _evidence([{"symbol": "CASH", "is_cash": True, "market_value": 585_917.80}])
    assert eval_s6(ev, CFG) == []
    assert eval_s6_skipped_subjects(ev, CFG) == []      # dropped as cash, not as dust


@pytest.mark.parametrize("mv,fires", [(49.99, False), (50.0, True), (0.90, False)])
def test_the_threshold_is_the_documented_one(mv, fires):
    from scripts.lib.holdings_universe import DUST_MAX_MARKET_VALUE_USD

    assert DUST_MAX_MARKET_VALUE_USD == 50.0
    row = {"symbol": "ZZZX", "market_value": mv, "shares": 1.0, "disposition_flag": True}
    basis = [{"symbol": "ZZZX", "holding_months": 36.0, "avg_cost_per_share": 500.0}]
    ev = _evidence([row], cost_basis=basis, quotes={"ZZZX": {"last": 0.01}})
    assert bool(eval_s6(ev, CFG)) is fires


# ── the two guards that carry over from the dust policy ──────────────────────

def test_value_is_aggregated_across_accounts():
    """A name held small in one account and large in another is not dust."""
    rows = [
        {"symbol": "SPCX", "market_value": 5.00, "account": "taxable",
         "disposition_flag": True},
        {"symbol": "SPCX", "market_value": 21_833.60, "account": "ira"},
    ]
    basis = [{"symbol": "SPCX", "holding_months": 36.0, "avg_cost_per_share": 500.0}]
    ev = _evidence(rows, cost_basis=basis, quotes={"SPCX": {"last": 1.0}})
    assert _symbols(eval_s6(ev, CFG)) == ["SPCX"]
    assert eval_s6_skipped_subjects(ev, CFG) == []


def test_an_unknown_market_value_is_never_dust():
    """A missing price must not silently suppress a real concentration."""
    rows = [{"symbol": "ZZZX", "shares": 100.0, "disposition_flag": True}]
    basis = [{"symbol": "ZZZX", "holding_months": 36.0, "avg_cost_per_share": 500.0}]
    ev = _evidence(rows, cost_basis=basis, quotes={"ZZZX": {"last": 1.0}})
    assert eval_s6_skipped_subjects(ev, CFG) == []
    assert _symbols(eval_s6(ev, CFG)) == ["ZZZX"]


def test_one_unpriced_leg_makes_the_whole_subject_unknown():
    """Summing a missing leg as 0.0 would mistake a real position for dust."""
    rows = [
        {"symbol": "ZZZX", "market_value": 10.0, "account": "a", "disposition_flag": True},
        {"symbol": "ZZZX", "account": "b"},                      # unpriced
    ]
    basis = [{"symbol": "ZZZX", "holding_months": 36.0, "avg_cost_per_share": 500.0}]
    ev = _evidence(rows, cost_basis=basis, quotes={"ZZZX": {"last": 1.0}})
    assert eval_s6_skipped_subjects(ev, CFG) == []
    assert _symbols(eval_s6(ev, CFG)) == ["ZZZX"]


# ── the rule only subtracts ──────────────────────────────────────────────────

def test_thresholds_are_untouched():
    """The rule skips subjects; it must never relax a threshold."""
    import inspect

    from scripts.lib import cio_situation_detector as det

    src = inspect.getsource(det.eval_s6)
    assert 'thr.get("concentration_weight_pct") or 12.0' in src
    assert 'thr.get("disposition_loss_pct") or 20.0' in src
    assert 'thr.get("disposition_hold_months") or 6.0' in src


def test_skipped_subjects_are_reported_not_silent():
    ev = _evidence([SCHD_ROW, SRNE_ROW], cost_basis=SRNE_BASIS, quotes=SRNE_QUOTE)
    assert eval_s6(ev, CFG)[0]["s6_skipped_subjects"]


def test_symbol_filter_still_works():
    ev = _evidence([SCHD_ROW, SRNE_ROW], cost_basis=SRNE_BASIS, quotes=SRNE_QUOTE)
    assert _symbols(eval_s6(ev, CFG, symbol="SCHD")) == ["SCHD"]
    assert eval_s6(ev, CFG, symbol="SRNE") == []


def test_the_skip_rule_fails_open_rather_than_disabling_s6(monkeypatch):
    """The caller swallows exceptions, so a raise here would silently kill S6.

    Losing every concentration alert to protect against a nuisance dust plan is
    the wrong trade. If the policy module cannot be read, the subject goes
    through and behaviour reverts to pre-rule.
    """
    import builtins

    real_import = builtins.__import__

    def _no_holdings_universe(name, *a, **k):
        if name == "scripts.lib.holdings_universe":
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_holdings_universe)

    ev = _evidence([SCHD_ROW, SRNE_ROW], cost_basis=SRNE_BASIS, quotes=SRNE_QUOTE)
    fired = eval_s6(ev, CFG)
    # SCHD — the alert that actually matters — still fires.
    assert "SCHD" in _symbols(fired)


# ── S1 shares the gate ───────────────────────────────────────────────────────

from scripts.lib.cio_situation_detector import eval_s1, eval_s1_skip_reason  # noqa: E402

S1_CFG = {"thresholds": {"basis_drawdown_pct": 25.0, "reclaim_eps_pct": 1.0,
                         "partial_recovery_pct": 15.0}}


def _s1_evidence(rows, quotes, basis):
    return {
        "holdings_detail": {"holdings": rows},
        "market_quote": quotes,
        "quotes": quotes,
        "cost_basis": {"positions": basis},
    }


def test_s1_no_longer_fires_deep_drawdown_on_a_residual():
    """35 open S1 plans had accumulated this way on JEPI, SRNE and LDOS."""
    ev = _s1_evidence(
        [{"symbol": "SRNE", "market_value": 0.90, "shares": 1000.0,
          "avg_cost": 5.0, "last": 0.0009, "basis": 5.0}],
        {"SRNE": {"last": 0.0009}},
        [{"symbol": "SRNE", "avg_cost": 5.0, "avg_cost_per_share": 5.0}],
    )
    assert eval_s1_skip_reason(ev, "SRNE") == "dust_residual"
    assert eval_s1(ev, S1_CFG, "SRNE") is None


def test_s1_still_fires_on_a_real_position_in_drawdown():
    """Guard the guard: the same shape at size must still fire."""
    ev = _s1_evidence(
        [{"symbol": "REAL", "market_value": 50_000.0, "shares": 1000.0,
          "avg_cost": 5.0, "last": 1.0, "basis": 5.0}],
        {"REAL": {"last": 1.0}},
        [{"symbol": "REAL", "avg_cost": 5.0, "avg_cost_per_share": 5.0}],
    )
    assert eval_s1_skip_reason(ev, "REAL") is None
    fired = eval_s1(ev, S1_CFG, "REAL")
    assert fired is not None
    assert any(r.startswith("deep_drawdown") for r in fired["fire_reasons"])


def test_s1_and_s6_share_one_gate():
    """One rule, not two drifting copies."""
    import inspect

    from scripts.lib import cio_situation_detector as det

    # S1 routes through eval_s1_skip_reason; S6 calls the gate directly. Both
    # end at the same function, and the S6-only name is gone.
    assert "eval_s1_skip_reason" in inspect.getsource(det.eval_s1)
    assert "_subject_skip_reason" in inspect.getsource(det.eval_s1_skip_reason)
    assert "_subject_skip_reason" in inspect.getsource(det.eval_s6)
    assert not hasattr(det, "_s6_subject_skip_reason")

    # and the one gate produces the same verdict for both callers
    assert det._subject_skip_reason(
        "SRNE", market_value=0.90, market_value_known=True) == "dust_residual"
    assert det._subject_skip_reason(
        "SCHD", market_value=365_694.75, market_value_known=True) is None


def test_s1_unknown_price_still_fires():
    ev = _s1_evidence(
        [{"symbol": "ZZZX", "shares": 1000.0, "avg_cost": 5.0, "last": 1.0,
          "basis": 5.0}],
        {"ZZZX": {"last": 1.0}},
        [{"symbol": "ZZZX", "avg_cost": 5.0, "avg_cost_per_share": 5.0}],
    )
    assert eval_s1_skip_reason(ev, "ZZZX") is None


def test_s1_aggregates_across_accounts():
    ev = _s1_evidence(
        [{"symbol": "SPCX", "market_value": 5.0, "account": "a", "shares": 1.0,
          "avg_cost": 500.0, "last": 1.0, "basis": 500.0},
         {"symbol": "SPCX", "market_value": 21_833.60, "account": "b", "shares": 100.0,
          "avg_cost": 500.0, "last": 1.0, "basis": 500.0}],
        {"SPCX": {"last": 1.0}},
        [{"symbol": "SPCX", "avg_cost": 500.0, "avg_cost_per_share": 500.0}],
    )
    assert eval_s1_skip_reason(ev, "SPCX") is None
