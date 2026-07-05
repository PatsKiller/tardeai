#!/usr/bin/env python3
"""ALPACA-OPTIONS Stage 1 — scanner universe-expansion tests.

Covers: --universe selection (holdings_watchlist default preserves the
original scope; liquid_core / discovery / all widen it), per-tier
resolved/scanned/winners/rejects stats, strategy_allowlist enforcement
(disallowed tiers are skipped, disclosed, never scanned), registry gating
(paper_enabled=false or an invalid registry refuses the scan), universe
config fail-closed refusal, limit/top defaults sourced from the universe
config, and dry-run writing nothing on every universe path.

Safety tests for the underlying pipeline live in
tests/test_options_pipeline_deep_itm.py (unchanged).

    .venv/bin/python -m pytest tests/test_options_strategy_scanner.py -q
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import options_strategy_scanner as scanner  # noqa: E402
from lib.options_pipeline.universe import (  # noqa: E402
    RegistryConfigError, UniverseConfigError, load_universe_config)

SPOT = 200.0


# ── compact synthetic deep_itm_call_analysis fixture ─────────────────────────

def _analysis(sym="NVDA"):
    mid, strike = 55.0, 150.0
    cand = {
        "strike": strike, "exp": "2026-10-16", "dte": 89,
        "bid": mid - 0.5, "ask": mid + 0.5, "mid": mid,
        "delta": 0.88, "iv": 0.30, "volume": 20, "oi": 500,
        "spread_pct": 2.0, "liquidity_score": 70,
        "flags": {"wide_spread": False, "low_oi": False, "no_volume": False,
                  "no_quote": False, "earnings_before_expiry": False},
        "intrinsic_value": SPOT - strike,
        "extrinsic_value": round(mid - (SPOT - strike), 4),
        "breakeven": strike + mid,
        "breakeven_move_pct": round(((strike + mid) / SPOT - 1) * 100, 2),
        "max_loss": mid * 100, "capital_required": mid * 100,
        "capital_vs_100_shares": {"contract_debit": mid * 100,
                                  "100_shares": SPOT * 100,
                                  "capital_ratio_pct": 27.5},
    }
    return {
        "strategy": "deep_itm_call", "symbol": sym, "available": True,
        "educational_only": True, "banner": "EDUCATIONAL_ONLY — test fixture",
        "source": "fixture", "generated_at": "2026-07-05T00:00:00+00:00",
        "underlying_price": SPOT, "delta_range": [0.80, 0.95],
        "selection_modes_used": ["delta"], "next_earnings_date": None,
        "dte_buckets": [{"target_dte": 90, "exp": "2026-10-16", "dte": 89,
                         "selection_mode": "delta", "available": True,
                         "selected": cand, "candidates": [cand]}],
        "chain_liquidity_score": 70,
        "feasibility": {"feasible": True, "score": 80, "reason": "fixture"},
    }


def _entry(sym, tier, conviction=0.70, allow=("deep_itm_call",), **kw):
    return dict({"symbol": sym, "source_tier": tier, "conviction": conviction,
                 "conviction_source": f"universe_{tier}",
                 "reason_included": f"test {tier}",
                 "strategy_allowlist": list(allow),
                 "verdict": None, "held_shares": kw.pop("held_shares", None),
                 "rank_score": 0.0}, **kw)


def _rich(sym, verdict="strong_buy", held=None):
    conviction = 0.85 if verdict == "strong_buy" else 0.70
    src = f"watchlist_{verdict}"
    if held:
        conviction = min(0.95, conviction + 0.05)
        src += "+held"
    return {"symbol": sym, "conviction": conviction, "conviction_source": src,
            "verdict": verdict, "held_shares": held, "rank_score": 50.0}


ANALYSIS_FN = lambda sym, **kw: _analysis(sym)  # noqa: E731


# ── (1) --universe selection ─────────────────────────────────────────────────

def test_default_universe_is_holdings_watchlist_and_preserves_behavior(monkeypatch):
    calls = {}

    def fake_eligible(*, limit, conviction_floor):
        calls["eligible"] = {"limit": limit, "floor": conviction_floor}
        return [_rich("NVDA"), _rich("V", verdict="buy", held=None)]

    monkeypatch.setattr(scanner, "resolve_eligible_underlyings", fake_eligible)
    monkeypatch.setattr(scanner, "resolve_universe",
                        lambda *a, **k: pytest.fail("static tiers must not resolve "
                                                    "on the default selector"))
    res = scanner.run_scan(dry_run=True, analysis_fn=ANALYSIS_FN)
    assert res["ok"] is True
    assert res["universe"] == "holdings_watchlist"
    assert calls["eligible"]["floor"] == 0.55
    assert {u["symbol"] for u in res["underlyings"]} == {"NVDA", "V"}
    assert {u["tier"] for u in res["underlyings"]} == {"watchlist_buy_strong_buy"}


def test_universe_liquid_core_scans_static_tiers_only(monkeypatch):
    monkeypatch.setattr(scanner, "resolve_eligible_underlyings",
                        lambda **k: pytest.fail("holdings/watchlist must not resolve"))
    monkeypatch.setattr(
        scanner, "resolve_universe",
        lambda tiers, config=None: [_entry("SPY", "liquid_options_core"),
                                    _entry("XLE", "sector_etfs")])
    res = scanner.run_scan(dry_run=True, universe="liquid_core", analysis_fn=ANALYSIS_FN)
    assert res["ok"] is True
    assert {u["symbol"] for u in res["underlyings"]} == {"SPY", "XLE"}
    assert set(res["tier_stats"]) == {"liquid_options_core", "sector_etfs"}


def test_universe_discovery_selector(monkeypatch):
    monkeypatch.setattr(scanner, "resolve_eligible_underlyings",
                        lambda **k: pytest.fail("holdings/watchlist must not resolve"))
    captured = {}

    def fake_resolve(tiers, config=None):
        captured["tiers"] = list(tiers)
        return [_entry("ASML", "discovery_missing_exposure", conviction=0.60)]

    monkeypatch.setattr(scanner, "resolve_universe", fake_resolve)
    res = scanner.run_scan(dry_run=True, universe="discovery", analysis_fn=ANALYSIS_FN)
    assert captured["tiers"] == ["discovery_missing_exposure"]
    assert res["tier_stats"]["discovery_missing_exposure"]["resolved"] == 1


def test_universe_all_merges_with_precedence(monkeypatch):
    monkeypatch.setattr(scanner, "resolve_eligible_underlyings",
                        lambda **k: [_rich("NVDA", held=120.0), _rich("PLTR", "buy")])
    monkeypatch.setattr(
        scanner, "resolve_universe",
        lambda tiers, config=None: [_entry("NVDA", "liquid_options_core"),  # dupe of held
                                    _entry("SPY", "liquid_options_core"),
                                    _entry("XLE", "sector_etfs")])
    res = scanner.run_scan(dry_run=True, universe="all", analysis_fn=ANALYSIS_FN)
    tiers = {u["symbol"]: u["tier"] for u in res["underlyings"]}
    # NVDA held + also a core seed → holdings tier wins the dedupe
    assert tiers == {"NVDA": "holdings", "PLTR": "watchlist_buy_strong_buy",
                     "SPY": "liquid_options_core", "XLE": "sector_etfs"}
    assert res["tier_stats"]["holdings"]["resolved"] == 1
    assert res["tier_stats"]["liquid_options_core"]["resolved"] == 1  # NVDA deduped away


def test_unknown_selector_refused():
    res = scanner.run_scan(dry_run=True, universe="metaverse",
                           underlyings=[], analysis_fn=ANALYSIS_FN)
    assert res["ok"] is False and "unknown universe selector" in res["error"]


def test_cli_universe_flag_passes_through(monkeypatch, capsys):
    seen = {}

    def fake_run_scan(**kw):
        seen.update(kw)
        return {"ok": True, "dry_run": True, "universe": kw["universe"],
                "strategy": kw["strategy"], "market_session": {"session": "test"},
                "underlyings_considered": 0, "tier_stats": {}, "per_underlying": [],
                "candidates_passed_gates": 0, "winners": [], "winner_summary": [],
                "queue_result": {"ok": True, "skipped": True}, "queue_target": "x"}

    monkeypatch.setattr(scanner, "run_scan", fake_run_scan)
    assert scanner.main(["--dry-run", "--universe", "all", "--json"]) == 0
    assert seen["universe"] == "all" and seen["dry_run"] is True
    with pytest.raises(SystemExit):                    # argparse rejects bad choices
        scanner.main(["--dry-run", "--universe", "bogus"])


# ── (2) per-tier stats ───────────────────────────────────────────────────────

def test_tier_stats_resolved_scanned_winners_rejects():
    underlyings = [
        _entry("NVDA", "holdings", conviction=0.90, held_shares=120.0),
        _entry("SPY", "liquid_options_core"),
        _entry("XLE", "sector_etfs"),
        _entry("WEAK", "sector_etfs", conviction=0.40),        # below floor → reject
        _entry("NOPE", "sector_etfs", allow=("covered_call",)),  # allowlist skip
    ]

    def analysis(sym, **kw):
        if sym == "XLE":
            return {"available": False, "reason": "weekend — no chain"}
        return _analysis(sym)

    res = scanner.run_scan(dry_run=True, underlyings=underlyings, analysis_fn=analysis)
    ts = res["tier_stats"]
    assert ts["holdings"] == {"resolved": 1, "scanned": 1, "winners": 1,
                              "rejects": 0, "allowlist_skipped": 0}
    assert ts["liquid_options_core"] == {"resolved": 1, "scanned": 1, "winners": 1,
                                         "rejects": 0, "allowlist_skipped": 0}
    assert ts["sector_etfs"]["resolved"] == 3
    assert ts["sector_etfs"]["scanned"] == 2               # NOPE never scanned
    assert ts["sector_etfs"]["winners"] == 0
    assert ts["sector_etfs"]["rejects"] == 2               # degraded XLE + weak floor
    assert ts["sector_etfs"]["allowlist_skipped"] == 1


def test_tier_stats_for_injected_legacy_underlyings():
    res = scanner.run_scan(
        dry_run=True,
        underlyings=[{"symbol": "NVDA", "conviction": 0.85,
                      "conviction_source": "watchlist_strong_buy",
                      "verdict": "strong_buy", "held_shares": None}],
        analysis_fn=ANALYSIS_FN)
    assert res["tier_stats"]["watchlist_buy_strong_buy"]["scanned"] == 1


# ── (3) strategy allowlist enforcement ───────────────────────────────────────

def test_allowlist_skips_symbol_before_analysis():
    def analysis(sym, **kw):
        assert sym != "SPY", "allowlist-skipped symbol must never reach the chain"
        return _analysis(sym)

    res = scanner.run_scan(
        dry_run=True,
        underlyings=[_entry("SPY", "sector_etfs", allow=("covered_call", "credit_spread")),
                     _entry("NVDA", "holdings", conviction=0.90)],
        analysis_fn=analysis)
    assert res["ok"] is True
    skipped = [pu for pu in res["per_underlying"] if pu["symbol"] == "SPY"]
    assert skipped and skipped[0]["status"] == "skipped"
    assert "not in sector_etfs tier strategy_allowlist" in skipped[0]["reason"]
    assert {u["symbol"] for u in res["underlyings"]} == {"NVDA"}
    assert res["candidates_passed_gates"] == 1


def test_entries_without_allowlist_are_allowed():
    res = scanner.run_scan(
        dry_run=True,
        underlyings=[{"symbol": "NVDA", "conviction": 0.85,
                      "conviction_source": "watchlist_strong_buy"}],
        analysis_fn=ANALYSIS_FN)
    assert res["candidates_passed_gates"] == 1


# ── (4) registry gating (fail-closed) ────────────────────────────────────────

def test_registry_paper_disabled_refuses_scan(monkeypatch):
    reg = copy.deepcopy(scanner.load_strategy_registry())
    reg["strategies"]["deep_itm_call"]["paper_enabled"] = False
    monkeypatch.setattr(scanner, "load_strategy_registry", lambda: reg)
    res = scanner.run_scan(dry_run=True, underlyings=[], analysis_fn=ANALYSIS_FN)
    assert res["ok"] is False and "paper_enabled=false" in res["error"]


def test_registry_invalid_refuses_scan(monkeypatch):
    def boom():
        raise RegistryConfigError("live_enabled true without explicit policy")
    monkeypatch.setattr(scanner, "load_strategy_registry", boom)
    res = scanner.run_scan(dry_run=True, underlyings=[], analysis_fn=ANALYSIS_FN)
    assert res["ok"] is False and "registry invalid" in res["error"]


def test_universe_config_invalid_refuses_scan(monkeypatch):
    def boom():
        raise UniverseConfigError("tiers mapping missing")
    monkeypatch.setattr(scanner, "load_universe_config", boom)
    res = scanner.run_scan(dry_run=True, underlyings=[], analysis_fn=ANALYSIS_FN)
    assert res["ok"] is False and "universe config invalid" in res["error"]


# ── (5) limits/top defaults come from the universe config ────────────────────

def test_limit_default_from_universe_config(monkeypatch):
    cfg = copy.deepcopy(load_universe_config())
    cfg["defaults"]["max_underlyings_per_run"] = 2
    cfg["defaults"]["max_proposals_per_run"] = 1
    monkeypatch.setattr(scanner, "load_universe_config", lambda: cfg)
    res = scanner.run_scan(
        dry_run=True,
        underlyings=[_entry(f"SY{i}", "liquid_options_core") for i in range(6)],
        analysis_fn=ANALYSIS_FN)
    assert res["underlyings_considered"] == 2              # capped by universe default
    ts = res["tier_stats"]["liquid_options_core"]
    assert ts["resolved"] == 6 and ts["scanned"] == 2


def test_cli_limit_overrides_universe_default():
    res = scanner.run_scan(
        dry_run=True, limit_underlyings=3, top_n=2,
        underlyings=[_entry(f"SY{i}", "liquid_options_core") for i in range(6)],
        analysis_fn=ANALYSIS_FN)
    assert res["underlyings_considered"] == 3
    assert len(res["winner_summary"]) == 2


# ── (6) dry-run writes nothing on every universe path ────────────────────────

@pytest.mark.parametrize("selector", ["holdings_watchlist", "liquid_core",
                                      "discovery", "all"])
def test_dry_run_never_writes_any_universe(monkeypatch, selector):
    monkeypatch.setattr(scanner, "resolve_eligible_underlyings",
                        lambda **k: [_rich("NVDA")])
    monkeypatch.setattr(scanner, "resolve_universe",
                        lambda tiers, config=None: [_entry("SPY", "liquid_options_core")])
    res = scanner.run_scan(
        dry_run=True, universe=selector, analysis_fn=ANALYSIS_FN,
        queue_writer=lambda rows: pytest.fail("dry-run must never write"))
    assert res["ok"] is True and res["dry_run"] is True
    assert res["queue_result"]["skipped"] is True
    json.dumps(res, default=str)                           # report stays serializable


def test_run_still_queues_winners_with_universe(monkeypatch):
    monkeypatch.setattr(scanner, "resolve_eligible_underlyings", lambda **k: [])
    monkeypatch.setattr(scanner, "resolve_universe",
                        lambda tiers, config=None: [_entry("SPY", "liquid_options_core")])
    written = {}

    def writer(rows):
        written["rows"] = rows
        return {"ok": True, "upserted": len(rows)}

    res = scanner.run_scan(dry_run=False, universe="liquid_core",
                           analysis_fn=ANALYSIS_FN, queue_writer=writer)
    assert res["ok"] is True
    assert len(written["rows"]) == 1
    assert written["rows"][0]["educational_paper_model"] is True
    assert res["tier_stats"]["liquid_options_core"]["winners"] == 1
