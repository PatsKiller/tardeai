"""Reviewer follow-up 2026-09-27: (a) a protective put / covered call reconciles the held shares
and cost basis to the holdings snapshot of record before an order exists; (b) every yield in the
CIO packet names its denominator and none is an expected return ("8.3% annualized" annualised the
$6.35 credit against the $520 short strike). Hermetic."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")]

import pytest  # noqa: E402
import options_desk_enterprise as ent  # noqa: E402
from scripts.lib import options_cio_review as ocr  # noqa: E402
from test_options_order_gates_20260927 import NOW, _gate, _proposal, _store, _iso, _row  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_earnings_calendar(monkeypatch):
    """LP-DEF-04 (live-proof 2026-09-28): a cached ``enterprise.earnings`` verdict without a gate_version is
    no longer trusted at preflight — it is recomputed against the live gate. This suite is hermetic and CI
    has no earnings provider (the recompute returned EARNINGS_TIMESTAMP_UNKNOWN there, run 36452009384), so
    the calendar answers "no scheduled event" for every symbol; a test that needs a blackout sets its own."""
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {str(s).upper(): "" for s in syms})

XAR_ROWS = [{"symbol": "XAR", "account": "rollover", "shares": 100.0, "cost_basis": 28238.0, "price": 239.86}]
META = {"data_as_of": _iso(NOW - timedelta(hours=20)), "generated_at": _iso(NOW - timedelta(hours=20))}


def _put(**over):
    p = _proposal(id="opt_protective_put_XAR_rollover_230p0000_20261120_d20260928", symbol="XAR", underlying="XAR",
                  strategy="protective_put", strike=230.0, premium=7.25, premium_total=725.0, max_profit="hedge",
                  max_loss=1671.0, underlying_price=239.46, shares_held=100.0, contracts=1,
                  legs_liquidity=[], enterprise={"tier": "A", "live_eligible": True, "blocks": [],
                                                 "earnings": {"in_blackout": False, "symbol": "XAR"},
                                                 "liquidity": {"pass": True, "issues": [], "legs": []}})
    p.pop("short_strike", None); p.pop("long_strike", None); p.pop("net_credit", None)
    p.update(over)
    return p


def test_hedge_reconciliation_passes_and_reports_basis(tmp_path):
    res = ent.preflight_desk_gate(_put()["id"], _put(), store=_store(tmp_path), now=NOW, row=_row(_put()),
                                  cfg=ent.load_desk_config(), holdings=(XAR_ROWS, META))
    h = res["hedge_reconciliation"]
    assert h["ok"] is True and h["shares_held"] == 100.0 and h["cost_basis_per_share"] == 282.38
    assert h["floor_per_share_after_premium"] == 222.75
    assert h["pl_vs_basis_at_floor"] == round((222.75 - 282.38) * 100, 2)      # the operator's loss to the floor
    assert h["pl_vs_basis_at_mark"] == round((239.46 - 282.38) * 100, 2)
    assert not [r for r in res["refusals"] if r["code"].startswith(("shares", "holdings", "cost_basis", "insufficient"))]


def _recon(rows, meta=META, **over):
    return ent.reconcile_hedge_holdings(_put(**over), now=NOW, cfg=ent.load_desk_config(), holdings=(rows, meta))


def test_hedge_reconciliation_fails_closed_on_every_gap():
    codes = lambda r: {x["code"] for x in r["refusals"]}
    assert "holdings_unavailable" in codes(_recon([]))
    assert "holdings_stale" in codes(_recon(XAR_ROWS, {"data_as_of": _iso(NOW - timedelta(hours=40))}))
    assert "holdings_age_unknown" in codes(_recon(XAR_ROWS, {}))
    assert "shares_not_held" in codes(_recon([dict(XAR_ROWS[0], account="taxable")]))
    assert "insufficient_shares" in codes(_recon([dict(XAR_ROWS[0], shares=60.0)]))
    assert "shares_changed" in codes(_recon([dict(XAR_ROWS[0], shares=150.0)]))
    assert "cost_basis_missing" in codes(_recon([dict(XAR_ROWS[0], cost_basis=None)]))
    # A card built without shares_held is unknown, not zero: no false "shares_changed".
    ok = _recon(XAR_ROWS, shares_held=None)
    assert "shares_changed" not in codes(ok) and ok["ok"] is True


def test_covered_call_reconciliation_reports_called_away_vs_basis():
    r = ent.reconcile_hedge_holdings(_put(strategy="covered_call", strike=250.0, premium=3.0), now=NOW,
                                     cfg=ent.load_desk_config(), holdings=(XAR_ROWS, META))
    assert r["called_away_per_share_incl_premium"] == 253.0
    assert r["pl_vs_basis_if_called"] == round((253.0 - 282.38) * 100, 2)


def test_spread_ideas_do_not_run_hedge_reconciliation(tmp_path):
    res = _gate(_proposal(), _store(tmp_path))
    assert res["hedge_reconciliation"] is None and res["ok"] is True


def test_yields_name_their_denominator_and_none_is_an_expected_return():
    d = ocr.build_facts({"symbol": "DELL", "strategy": "credit_spread", "underlying_price": 563.0, "strike": 520.0,
                         "short_strike": 520.0, "long_strike": 500.0, "dte": 54, "premium": 6.35,
                         "executable_credit": 6.35, "max_loss": 1365.0, "max_profit": 635.0, "contracts": 1},
                        disclosures_loader=lambda s: [])["derived"]
    assert d["annualized_yield_on_strike_pct"] == 8.3 == d["annualized_yield_pct"]
    assert d["annualized_yield_on_width_pct"] == round(100 * 6.35 / 20 * 365 / 54, 1)
    assert d["annualized_return_on_risk_pct"] == round(100 * 635 / 1365 * 365 / 54, 1)
    assert "short strike" in d["yield_denominators_note"] and "expected return" in d["yield_denominators_note"]
