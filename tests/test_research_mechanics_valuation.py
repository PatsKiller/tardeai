"""R2 valuation / reverse-DCF goldens. Output is CONDITIONAL MODEL OUTPUT."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance.mechanics.common import Quantity, Unit  # noqa: E402
from scripts.lib.research_governance.mechanics.valuation import (  # noqa: E402
    dcf_value,
    gordon_tv,
    present_value_fcfs,
    reverse_dcf,
    sensitivity_matrix,
)


def test_pv_golden():
    # Independent: 100 / 1.1 + 100 / 1.1**2
    pv = present_value_fcfs([100.0, 100.0], 0.10)
    assert abs(pv - (100 / 1.1 + 100 / 1.21)) < 1e-12


def test_terminal_value_golden():
    # TV = 100 * 1.02 / (0.10-0.02) = 1275
    assert abs(gordon_tv(100.0, 0.10, 0.02) - 1275.0) < 1e-12


def test_wacc_le_g_invalid():
    r = dcf_value(
        instrument_id="X", fcfs=[100], wacc=0.05, terminal_growth=0.05, debt=0.0, cash=0.0,
    )
    assert r.status.value == "INVALID_INPUT"


def test_ev_to_equity_explicit_zeros():
    r = dcf_value(
        instrument_id="X", fcfs=[100.0], wacc=0.10, terminal_growth=0.02,
        debt=0.0, cash=0.0, shares=10.0,
    )
    assert r.status.value == "OK", r.reason
    tv = 100.0 * 1.02 / 0.08
    ev = (100.0 + tv) / 1.10
    assert abs(r.result["enterprise_value"] - ev) < 1e-8
    assert abs(r.result["equity_value"] - ev) < 1e-8
    assert abs(r.result["per_share_value"] - ev / 10.0) < 1e-8
    assert r.result["label"] == "CONDITIONAL_MODEL_OUTPUT"
    assert r.result["not"] == "FINANCIAL_TRUTH"


def test_missing_debt_unavailable():
    r = dcf_value(
        instrument_id="X", fcfs=[100], wacc=0.10, terminal_growth=0.02, debt=None, cash=0.0,
    )
    assert r.status.value == "UNAVAILABLE"


def test_missing_shares_per_share_unavailable():
    r = dcf_value(
        instrument_id="X", fcfs=[100], wacc=0.10, terminal_growth=0.02, debt=0.0, cash=0.0,
        shares=None,
    )
    assert r.status.value == "OK"
    assert r.result["per_share_value"] is None
    assert any("per-share" in w for w in r.warnings)


def test_negative_shares():
    r = dcf_value(
        instrument_id="X", fcfs=[100], wacc=0.10, terminal_growth=0.02,
        debt=0.0, cash=0.0, shares=-1,
    )
    assert r.status.value == "INVALID_INPUT"


def test_usd_millions_vs_usd():
    r = dcf_value(
        instrument_id="X", fcfs=[100.0], wacc=0.10, terminal_growth=0.02,
        debt=Quantity(1.0, Unit.USD_MILLIONS), cash=0.0, money_unit=Unit.USD,
    )
    assert r.status.value == "OK"
    # debt 1e6 reduces equity vs EV
    assert r.result["equity_value"] == r.result["enterprise_value"] - 1_000_000.0


def test_reverse_growth_golden():
    base = dcf_value(
        instrument_id="X", fcfs=[105.0], wacc=0.10, terminal_growth=0.02,
        debt=0.0, cash=0.0,
    )
    target = base.result["equity_value"]
    # starting_fcf=100, horizon=1, implied cagr such that 100*(1+g)=105 → g=0.05
    sol = reverse_dcf(
        instrument_id="X", solved_variable="implied_fcf_cagr",
        target_equity_value=target, starting_fcf=100.0, horizon=1,
        wacc=0.10, terminal_growth=0.02, debt=0.0, cash=0.0,
        domain=(0.0, 0.10),
    )
    assert sol.status.value == "OK", sol.reason
    assert abs(sol.result["solution"] - 0.05) < 1e-6
    assert sol.result["label"] == "CONDITIONAL_MODEL_OUTPUT"


def test_reverse_no_root():
    sol = reverse_dcf(
        instrument_id="X", solved_variable="implied_fcf_cagr",
        target_equity_value=1e18, starting_fcf=1.0, horizon=2,
        wacc=0.10, terminal_growth=0.02, debt=0.0, cash=0.0,
        domain=(0.0, 0.05),
    )
    assert sol.status.value == "UNAVAILABLE"


def test_sensitivity_monotone():
    s = sensitivity_matrix(
        instrument_id="X", fcfs=[100.0],
        wacc_grid=[0.08, 0.10, 0.12], g_grid=[0.01, 0.02],
        debt=0.0, cash=0.0,
    )
    assert s.status.value == "OK"
    assert s.result["higher_wacc_lowers_equity"] is True
    # WACC=g cell invalid
    bad_cells = [c for row in s.result["cells"] for c in row if c["status"] != "OK"]
    assert not bad_cells or all(c["wacc"] > c["g"] or c["status"] == "INVALID_INPUT" for c in
                                [c for row in s.result["cells"] for c in row])
