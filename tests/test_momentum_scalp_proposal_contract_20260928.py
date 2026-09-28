"""Momentum-scalp proposal contract (2026-09-28) — fail→pass.

Before: `auto_proposal_generator` forced a $3.00 floor on every momentum strategy, required
analyst coverage for every equity and applied the shared 5% spread ceiling, so every scalp GO
since 2026-07-13 was SKIPPED (STRATEGY_CRITERIA / NO_ANALYST / LIQUIDITY) and no proposal ever
carried a target_account (ATM deferred with account_resolution_missing).

Now `config/strategies/momentum_scalp.yaml::proposal_contract` adjusts those gates for THAT
strategy only, paper account only, with the analyst waiver recorded.

COVERS = ["scripts/auto_proposal_generator.py", "config/strategies/momentum_scalp.yaml"]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import auto_proposal_generator as apg  # noqa: E402

# CI has no psycopg2 (cio-hardening installs pytest+pyyaml only). The real market_quote_provider
# imports session13_db -> psycopg2 at module load, so the liquidity tests inject a stub module
# instead of importing it: _liquidity_prescreen does `from market_quote_provider import ...`
# lazily, which resolves through sys.modules.
import types  # noqa: E402

COVERS = ["scripts/auto_proposal_generator.py", "config/strategies/momentum_scalp.yaml"]

SCALP_CFG = yaml.safe_load((ROOT / "config/strategies/momentum_scalp.yaml").read_text())
SHARED = {"liquidity_prescreen": {"enabled": True, "max_spread_pct": 5.0,
                                  "min_day_volume_shares": 25000, "min_dollar_day_volume": 100000}}


def _scalp_signal(price: float, **kw) -> dict:
    sig = {"symbol": "TEST", "strategy_id": "momentum_scalp", "price": price, "rvol": 9.0,
           "float_m": 4.0, "gap_pct": 12.0, "change_pct": 20.0, "score": 44, "catalyst": "FDA nod"}
    sig.update(kw)
    return sig


# ------------------------------------------------------------------ price floor


def test_config_declares_the_contract():
    c = SCALP_CFG["proposal_contract"]
    assert c["hard_min_price"] == 1.0
    assert c["require_analyst_coverage"] is False
    assert c["require_catalyst"] is True
    assert c["target_account"] == "tradeai_automated"


def test_momentum_scalp_floor_is_one_dollar_from_config():
    assert apg._contract_hard_min_price("momentum_scalp", SCALP_CFG) == 1.0


def test_other_momentum_strategies_keep_the_three_dollar_floor():
    for sid in ("gap_and_go", "earnings_post_momentum", "speculative_growth"):
        assert apg._contract_hard_min_price(sid, {}) == 3.0
    assert apg._contract_hard_min_price("swing_breakout", {}) == 1.0


def test_contract_cannot_go_below_the_absolute_floor():
    assert apg._contract_hard_min_price("momentum_scalp", {"proposal_contract": {"hard_min_price": 0.25}}) == 1.0
    assert apg._contract_hard_min_price("momentum_scalp", {"proposal_contract": {"hard_min_price": "junk"}}) == 3.0


def test_one_fifty_scalp_signal_passes_strategy_criteria(monkeypatch):
    """The exact failure mode: `Price $1.50 outside $3.0-$25.0` — must no longer fire."""
    monkeypatch.setattr(apg, "_load_strategy_config", lambda sid: SCALP_CFG if sid == "momentum_scalp" else {})
    ok, reason, _ = apg._validate_against_strategy_criteria("momentum_scalp", _scalp_signal(1.50))
    assert ok, reason
    ok, reason, _ = apg._validate_against_strategy_criteria("momentum_scalp", _scalp_signal(0.80))
    # the deterministic evaluator (PRICE_RANGE) or the legacy floor may fire first — either is the $1 floor
    assert not ok and ("PRICE_RANGE" in reason or "Price $0.80 outside $1.0" in reason)


def test_two_fifty_signal_on_another_momentum_strategy_still_rejected(monkeypatch):
    cfg = {"screen_filters": {"min_price": 1.0, "max_price": 50.0}}
    monkeypatch.setattr(apg, "_load_strategy_config", lambda sid: cfg)
    sig = _scalp_signal(2.50, strategy_id="earnings_post_momentum")
    ok, reason, _ = apg._validate_against_strategy_criteria("earnings_post_momentum", sig)
    assert not ok and "outside $3.0" in reason


# ------------------------------------------------------------------ analyst + catalyst


def test_analyst_gate_waived_only_for_the_contract_strategy():
    assert apg._contract_requires_analyst(SCALP_CFG) is False
    assert apg._contract_requires_analyst({}) is True
    assert apg._contract_requires_analyst({"proposal_contract": {}}) is True


def test_waiver_is_recorded_not_silent():
    src = (ROOT / "scripts/auto_proposal_generator.py").read_text()
    assert 'ANALYST_WAIVED_BY_CONTRACT' in src
    assert '"decision": "ANALYST_WAIVED_BY_CONTRACT"' in src
    # the analyst gate still runs for strategies without a waiver
    assert "elif not force:\n                try:\n                    from analyst_coverage import check_analyst_gate" in src


def test_catalyst_required_by_contract():
    assert apg._contract_requires_catalyst(SCALP_CFG) is True
    assert apg._signal_has_catalyst(_scalp_signal(2.0))
    assert apg._signal_has_catalyst(_scalp_signal(2.0, catalyst="", catalyst_verified=True))
    assert not apg._signal_has_catalyst(_scalp_signal(2.0, catalyst="   ", catalyst_verified=False))
    src = (ROOT / "scripts/auto_proposal_generator.py").read_text()
    assert '"SKIPPED_NO_CATALYST"' in src


# ------------------------------------------------------------------ liquidity merge


def _patch_quotes(monkeypatch, spread):
    stub = types.ModuleType("market_quote_provider")
    stub.check_fresh_quote = lambda symbol, strategy_id=None: {"ok": True}
    stub.get_best_quote = lambda symbol: {"spread_pct": spread, "last_price": 2.0, "day_volume": 3_000_000}
    monkeypatch.setitem(sys.modules, "market_quote_provider", stub)


def test_seven_percent_spread_passes_scalp_contract_but_fails_shared_rules(monkeypatch):
    _patch_quotes(monkeypatch, 7.0)
    merged = apg._contract_liquidity_rules(SHARED, SCALP_CFG)
    assert merged["liquidity_prescreen"]["max_spread_pct"] == 8.0
    ok, reason = apg._liquidity_prescreen("TEST", merged, "momentum_scalp")
    assert ok, reason
    ok, reason = apg._liquidity_prescreen("TEST", SHARED, "momentum_scalp")
    assert not ok and "spread" in reason


def test_liquidity_merge_leaves_other_strategies_on_shared_rules():
    assert apg._contract_liquidity_rules(SHARED, {}) is SHARED or apg._contract_liquidity_rules(SHARED, {}) == SHARED


# ------------------------------------------------------------------ paper-only target account


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql = (sql, params)

    def fetchone(self):
        label = self.sql[1][0]
        return self.rows.get(label)


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cur(self.rows)


def test_target_account_bound_when_paper():
    conn = _Conn({"tradeai_automated": ("paper",)})
    acct, skip = apg.resolve_contract_target_account(conn, SCALP_CFG)
    assert acct == "tradeai_automated" and skip is None


def test_live_or_unknown_account_is_skipped_never_routed():
    conn = _Conn({"tradeai_automated": ("live",)})
    acct, skip = apg.resolve_contract_target_account(conn, SCALP_CFG)
    assert acct is None and skip.startswith("SKIPPED_ACCOUNT_NOT_PAPER") and "mode=live" in skip
    acct, skip = apg.resolve_contract_target_account(_Conn({}), SCALP_CFG)
    assert acct is None and "mode=unknown" in skip
    assert apg.resolve_contract_target_account(_Conn({}), {}) == (None, None)


def test_proposal_dict_carries_target_account_and_assigned_routing():
    src = (ROOT / "scripts/auto_proposal_generator.py").read_text()
    assert '"target_account": signal.get("_contract_target_account")' in src
    assert '"routing_state": "assigned" if signal.get("_contract_target_account") else "unassigned"' in src
    assert 'sig["_contract_target_account"] = _tgt_acct' in src
    assert '"SKIPPED_ACCOUNT_NOT_PAPER"' in src
