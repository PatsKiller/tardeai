#!/usr/bin/env python3
"""cc-header-truth-v2 — API wiring pins.

These are structural assertions (AST) that the canonical contracts are actually
wired into the served endpoints, not merely defined and left unused — the
filing-cabinet defect AGENTS.md §13.5 names.

No network, broker, scheduler, Drive, database or production path is touched.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API_V2 = ROOT / "scripts" / "api_v2.py"


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(API_V2.read_bytes())


def _fn(tree, name):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    pytest.fail(f"{name}() not found in api_v2.py")


def _dict_keys(node: ast.AST) -> set:
    keys = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            for k in sub.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


# ── VIX names its source and observation time (Phase 2 D) ────────────────────


def test_vix_observation_returns_source_and_observation_time(tree):
    fn = _fn(tree, "_vix_observation")
    # A bare float hides which source answered; the contract is a 3-tuple.
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    assert any(isinstance(r.value, ast.Tuple) and len(r.value.elts) == 3 for r in returns), (
        "_vix_observation must return (value, source, observation_time)"
    )
    # the fallback path reads market_regime_indicators.vix_close by name
    src = ast.dump(fn)
    assert "market_regime_indicators.vix_close" in src


def test_compute_trade_ai_publishes_vix_source_and_observation_time(tree):
    fn = _fn(tree, "_compute_trade_ai")
    keys = _dict_keys(fn)
    assert "vix_source" in keys
    assert "vix_observation_time" in keys


# ── run-scoped GO/WAIT/NOGO contract is wired (Phase 2 C) ────────────────────


def test_compute_trade_ai_publishes_run_id_and_setup_run_summary(tree):
    fn = _fn(tree, "_compute_trade_ai")
    keys = _dict_keys(fn)
    assert "run_id" in keys
    assert "setup_run_summary" in keys


def test_summary_endpoint_serves_the_canonical_contract(tree):
    fn = _fn(tree, "trade_ai_summary")
    # the keys tuple must carry the canonical fields so the header reads them
    keys = {
        elt.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Tuple)
        for elt in node.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }
    assert {"run_id", "setup_run_summary", "vix_source", "vix_observation_time"} <= keys


# ── overview reads trade_ai from the same cached payload, not a raw file ─────


def test_overview_sources_trade_ai_from_the_cached_payload(tree):
    fn = _fn(tree, "overview")
    calls = [
        n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "trade_ai"
    ]
    assert calls, "overview must read trade_ai() (same payload as summary), not a divergent file"


def test_overview_trade_ai_block_carries_run_id_and_setup_summary(tree):
    fn = _fn(tree, "overview")
    keys = _dict_keys(fn)
    assert "setup_run_summary" in keys
    assert "run_id" in keys
    assert "vix_source" in keys
    assert "vix_observation_time" in keys


# ── portfolio aggregate names scope (Phase 2 A) ──────────────────────────────


def test_overview_publishes_an_all_accounts_aggregate(tree):
    fn = _fn(tree, "overview")
    keys = _dict_keys(fn)
    assert "portfolio_aggregate" in keys
    src = ast.dump(fn)
    assert "ALL_ACCOUNTS" in src, "the aggregate must name its scope explicitly"


def test_overview_publishes_a_quote_selection_envelope(tree):
    fn = _fn(tree, "overview")
    keys = _dict_keys(fn)
    assert "quote_selection" in keys, "the header must expose selected quote provider vs fallback"


# ── journal metrics state basis, window, scope (Phase 2 E) ───────────────────


def test_journal_block_states_basis_window_and_scope(tree):
    fn = _fn(tree, "overview")
    keys = _dict_keys(fn)
    assert "account_scope" in keys, "journal must name the account scope"
    assert "time_window" in keys, "journal must name the time window"
    assert "calculation_version" in keys, "journal must name its calculation version"
