#!/usr/bin/env python3
"""ALPACA-OPTIONS Stage 1 — scanner universe-expansion tests.

Covers: --universe selection (holdings_watchlist default preserves the
original scope; liquid_core / discovery / all widen it), per-tier
resolved/scanned/winners/rejects stats, strategy_allowlist enforcement
(disallowed tiers are skipped, disclosed, never scanned), registry gating
(paper_enabled=false or an invalid registry refuses the scan), universe
config fail-closed refusal, limit/top defaults sourced from the universe
config, and dry-run writing nothing on every universe path.

MULTI-STRATEGY Stage 2 (operator spec Part D): --strategy atm_call|atm_put|all
routes through the per-symbol strategy matcher — per-strategy counts, matcher
fail reasons in the report + match_json cross-strategy context on queued rows,
paper-only ATM queue rows (live_eligible False, no auto-execute surface),
idempotent proposal ids across re-runs, the meta.alpaca_paper_enabled button
gating field, and deep_itm_call default full backward compatibility.

EARNINGS-SPREADS Stage 2 (operator spec Part E): --strategy
earnings_put_debit_spread scans through the matcher lane (real generator rows
queue paper-only with match_json + idempotent ids); earnings_put_credit_spread
refuses honestly while BLOCKED_INITIAL (and is disclosed-excluded in "all",
where its verdict still rides match_json); --event-window earnings /
--earnings-only filters underlyings to in-window earnings BEFORE any matcher
call (per-symbol skip reasons + filter stats, deep-ITM Stage-1 flow refuses
the flag).

Safety tests for the underlying pipeline live in
tests/test_options_pipeline_deep_itm.py (unchanged — its AST forbidden-import
sweep already covers this scanner file).

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


# ═══════════════════════════════════════════════════════════════════════════
# MULTI-STRATEGY Stage 2 (operator spec Part D) — matcher-driven scan
# ═══════════════════════════════════════════════════════════════════════════

from lib.options_pipeline.atm_long_premium_generator import generate_atm_proposals  # noqa: E402

NO_IV = {"available": False, "reason": "iv context not computed (test)"}
NO_EARNINGS = "2099-01-01"


def _atm_contract(side="call", strike=100.0, mid=4.0, *, delta=0.52, oi=800,
                  volume=50, spread_pct=3.0, dte=33, liquidity_score=75):
    return {"side": side, "strike": strike, "bid": mid - 0.1, "ask": mid + 0.1,
            "mid": mid, "spread_pct": spread_pct, "volume": volume, "oi": oi,
            "delta": delta, "iv": 30.0, "dte": dte,
            "liquidity_score": liquidity_score}


def _atm_snapshot(spot=100.0):
    return {"available": True, "symbol": "TEST", "underlying_price": spot,
            "expirations": [
                {"exp": "2026-08-07", "dte": 33,
                 "contracts": [_atm_contract(), _atm_contract(side="put", delta=-0.52)]},
                {"exp": "2026-09-04", "dte": 61,
                 "contracts": [_atm_contract(strike=101.0, dte=61),
                               _atm_contract(side="put", strike=101.0, delta=-0.55, dte=61)]},
            ],
            "liquidity_score": 70}


def _atm_proposals(sym, side="call"):
    gen = generate_atm_proposals(
        sym, side, None,
        {"conviction": 0.85, "conviction_source": "watchlist_strong_buy",
         "verdict": "strong_buy"},
        snapshot=_atm_snapshot(), earnings_date=NO_EARNINGS, iv_context=NO_IV)
    assert gen["available"] and gen["proposals"], "ATM fixture must generate"
    return gen["proposals"]


def _fake_matcher(record=None):
    """Deterministic per-symbol matcher: atm_call passes with real generator
    rows, atm_put fails on thesis, deep_itm_call degrades (weekend chain),
    the earnings pair reports honest not_applicable (no event / blocked)."""
    record = record if record is not None else {}

    def fake(symbol, context, strategies, **kw):
        record.setdefault("calls", []).append(
            {"symbol": symbol, "strategies": list(strategies),
             "context": dict(context or {}), "kw": sorted(kw)})
        results = {}
        for sid in strategies:
            if sid == "atm_call":
                results[sid] = {"status": "pass",
                                "reason": "2 proposal(s) passed gates",
                                "proposals": _atm_proposals(symbol, "call")}
            elif sid == "atm_put":
                results[sid] = {"status": "fail",
                                "reason": "bearish thesis missing (needs watchlist "
                                          "sell/avoid/deteriorating, an explicit "
                                          "bearish thesis, or a hedge-of-held flag)",
                                "proposals": []}
            elif sid == "earnings_put_debit_spread":
                results[sid] = {"status": "not_applicable",
                                "reason": "no earnings in window "
                                          "(days_to_earnings=None; window −2..10d)",
                                "proposals": []}
            elif sid == "earnings_put_credit_spread":
                results[sid] = {"status": "not_applicable",
                                "reason": "blocked initially (BLOCKED_INITIAL) — "
                                          "paper_enabled false in registry",
                                "proposals": []}
            else:
                results[sid] = {"status": "fail",
                                "reason": "chain unavailable: weekend — no chain",
                                "proposals": []}
        return {"symbol": symbol,
                "context": {"bullish_source": "watchlist_strong_buy",
                            "bearish_source": None},
                "strategy_results": results,
                "cross_strategy_summary": {}}

    fake.record = record
    return fake


def _multi_entry(sym, tier="holdings", conviction=0.90, held=120.0):
    # holdings tier: registry allowed_underlying_tiers admits all three strategies
    return _entry(sym, tier, conviction=conviction, held_shares=held,
                  allow=("deep_itm_call", "covered_call"))


# ── (7) strategy=all runs multiple matchers with per-strategy counts ─────────

def test_strategy_all_runs_matchers_and_reports_per_strategy_counts():
    fake = _fake_matcher()
    res = scanner.run_scan(dry_run=True, strategy="all",
                           underlyings=[_multi_entry("NVDA"), _multi_entry("RTX")],
                           matcher_fn=fake)
    assert res["ok"] is True and res["strategy"] == "all"
    assert set(res["strategies"]) == {"deep_itm_call", "atm_call", "atm_put",
                                      "earnings_put_debit_spread"}
    # the blocked credit lane is excluded + disclosed (never scanned)
    assert "BLOCKED_INITIAL" in res["strategy_notes"]["earnings_put_credit_spread"]
    # one matcher call per symbol, covering multiple strategies each; the
    # blocked credit id rides along VERDICT-ONLY (match_json visibility)
    assert [c["symbol"] for c in fake.record["calls"]] == ["NVDA", "RTX"]
    assert all(set(c["strategies"]) == {"deep_itm_call", "atm_call", "atm_put",
                                        "earnings_put_debit_spread",
                                        "earnings_put_credit_spread"}
               for c in fake.record["calls"])
    ps = res["per_strategy"]
    assert set(ps) == {"deep_itm_call", "atm_call", "atm_put",
                       "earnings_put_debit_spread"}
    for sid in ps:
        assert set(ps[sid]) >= {"scanned", "pass", "watch", "fail",
                                "not_applicable", "degraded", "queued",
                                "top_symbols"}
    assert ps["atm_call"] ["pass"] == 2 and ps["atm_call"]["queued"] >= 1
    assert ps["atm_put"]["fail"] == 2 and ps["atm_put"]["queued"] == 0
    assert ps["deep_itm_call"]["degraded"] == 2 and ps["deep_itm_call"]["fail"] == 0
    assert ps["earnings_put_debit_spread"]["not_applicable"] == 2
    assert ps["earnings_put_debit_spread"]["queued"] == 0
    assert ps["atm_call"]["top_symbols"]        # winners named
    json.dumps(res, default=str)                # --json payload stays serializable


def test_single_atm_strategy_runs_only_that_matcher():
    fake = _fake_matcher()
    res = scanner.run_scan(dry_run=True, strategy="atm_call",
                           underlyings=[_multi_entry("NVDA")], matcher_fn=fake)
    assert res["ok"] is True
    assert res["strategies"] == ["atm_call"]
    assert fake.record["calls"][0]["strategies"] == ["atm_call"]
    assert set(res["per_strategy"]) == {"atm_call"}


# ── (8) matcher fail reasons in the report + match_json context ──────────────

def test_fail_reasons_per_symbol_in_report_and_match_json():
    res = scanner.run_scan(dry_run=True, strategy="all",
                           underlyings=[_multi_entry("NVDA")],
                           matcher_fn=_fake_matcher())
    detail = {row["symbol"]: row for row in res["per_symbol"]}
    strat = detail["NVDA"]["strategies"]
    assert "bearish thesis missing" in strat["atm_put"]["reason"]
    assert "chain unavailable" in strat["deep_itm_call"]["reason"]
    # queued rows carry the cross-strategy context for the card — all FIVE
    # strategy verdicts now (the blocked credit id rides along verdict-only)
    for w in res["winners"]:
        mj = w["meta"]["match_json"]
        assert mj["strategy"] == "atm_call" and mj["status"] == "pass"
        assert "thesis: watchlist_strong_buy" in mj["why_matched"]
        others = mj["other_strategies"]
        assert set(others) == {"deep_itm_call", "atm_put",
                               "earnings_put_debit_spread",
                               "earnings_put_credit_spread"}
        assert "bearish thesis missing" in others["atm_put"]["reason"]
        assert others["deep_itm_call"]["status"] == "fail"
        assert others["earnings_put_debit_spread"]["status"] == "not_applicable"
        assert "no earnings in window" in \
            others["earnings_put_debit_spread"]["reason"]
        assert others["earnings_put_credit_spread"]["status"] == "not_applicable"
        assert "BLOCKED_INITIAL" in others["earnings_put_credit_spread"]["reason"]


# ── (9) ATM rows queue paper-only — auto-execution structurally impossible ───

def test_atm_rows_queue_paper_only_and_never_live_eligible():
    written = {}

    def writer(rows):
        written["rows"] = rows
        return {"ok": True, "upserted": len(rows)}

    res = scanner.run_scan(dry_run=False, strategy="all",
                           underlyings=[_multi_entry("NVDA")],
                           matcher_fn=_fake_matcher(), queue_writer=writer)
    assert res["ok"] is True and written["rows"]
    for row in written["rows"]:
        assert row["educational_paper_model"] is True
        assert row["requires_manual_review"] is True
        assert row["paper_only"] is True
        assert row["execution_mode"] == "manual_review_only"
        assert row["auto_eligible"] is False
        assert row["enterprise"]["live_eligible"] is False
        assert "auto_execute" not in row          # no such field exists, ever
        assert not any("auto" in str(b.get("action")) for b in row["action_buttons"])


def test_atm_rows_pass_the_fail_closed_desk_writer_guard(monkeypatch):
    """The real submit_to_desk_queue accepts well-formed ATM paper rows and the
    guard (not the DB) is what refuses a stripped row."""
    from lib.options_pipeline import deep_itm_generator as gen
    monkeypatch.setattr(
        "options_desk_enterprise.sync_approval_queue",
        lambda rows: {"ok": True, "upserted": len(rows)}, raising=False)
    rows = _atm_proposals("NVDA")
    ok = gen.submit_to_desk_queue(rows)
    assert ok.get("ok") is True
    bad = [dict(rows[0])]
    bad[0]["enterprise"] = dict(bad[0]["enterprise"], live_eligible=True)
    refused = gen.submit_to_desk_queue(bad)
    assert refused["ok"] is False and "fail-closed" in refused["error"]


# ── (10) idempotent re-run — deterministic ids, no dupes ─────────────────────

def test_rerun_produces_identical_ids_no_dupes():
    captured = []

    def writer(rows):
        captured.append([r["id"] for r in rows])
        return {"ok": True, "upserted": len(rows)}

    for _ in range(2):
        res = scanner.run_scan(dry_run=False, strategy="all",
                               underlyings=[_multi_entry("NVDA")],
                               matcher_fn=_fake_matcher(), queue_writer=writer)
        assert res["ok"] is True
    first, second = captured
    assert first == second                       # same ids → queue upsert dedupes
    assert len(set(first)) == len(first)         # no dupes within one run
    assert all(i.startswith("opt_atm_call_NVDA_paper_model_") for i in first)


# ── (11) alpaca_paper_enabled button-gating field (registry, scan time) ──────

def test_queued_rows_carry_alpaca_paper_enabled_from_registry():
    res = scanner.run_scan(dry_run=True, strategy="all",
                           underlyings=[_multi_entry("NVDA")],
                           matcher_fn=_fake_matcher())
    reg = scanner.load_strategy_registry()["strategies"]
    assert reg["atm_call"]["alpaca_paper_enabled"] is False    # spec Part A
    for w in res["winners"]:
        assert w["meta"]["alpaca_paper_enabled"] is False      # button must NOT show


def test_deep_itm_default_winners_carry_alpaca_paper_enabled_true():
    res = scanner.run_scan(dry_run=True,
                           underlyings=[_multi_entry("NVDA")],
                           analysis_fn=ANALYSIS_FN)
    assert res["ok"] is True and res["winners"]
    for w in res["winners"]:
        assert w["meta"]["alpaca_paper_enabled"] is True       # deep_itm registry row


# ── (12) registry gating for the multi path ──────────────────────────────────

def test_atm_paper_disabled_refuses_single_and_excludes_in_all(monkeypatch):
    reg = copy.deepcopy(scanner.load_strategy_registry())
    reg["strategies"]["atm_call"]["paper_enabled"] = False
    monkeypatch.setattr(scanner, "load_strategy_registry", lambda: reg)
    res = scanner.run_scan(dry_run=True, strategy="atm_call",
                           underlyings=[_multi_entry("NVDA")],
                           matcher_fn=_fake_matcher())
    assert res["ok"] is False and "paper_enabled=false" in res["error"]
    res_all = scanner.run_scan(dry_run=True, strategy="all",
                               underlyings=[_multi_entry("NVDA")],
                               matcher_fn=_fake_matcher())
    assert res_all["ok"] is True
    assert "atm_call" not in res_all["strategies"]
    assert "paper_enabled=false" in res_all["strategy_notes"]["atm_call"]


def test_registry_tier_gate_skips_atm_put_on_watchlist_tier():
    """atm_put's registry allowed_underlying_tiers excludes the watchlist tier —
    watchlist symbols skip atm_put (disclosed) while atm_call still scans."""
    fake = _fake_matcher()
    res = scanner.run_scan(dry_run=True, strategy="all",
                           underlyings=[_rich("PLTR")],       # watchlist tier
                           matcher_fn=fake)
    assert res["ok"] is True
    assert "atm_put" not in fake.record["calls"][0]["strategies"]
    assert "atm_call" in fake.record["calls"][0]["strategies"]
    assert res["per_strategy"]["atm_put"]["skipped"] == 1
    detail = {row["symbol"]: row for row in res["per_symbol"]}
    assert detail["PLTR"]["strategies"]["atm_put"]["status"] == "skipped"


# ── (13) dry-run never writes on the multi path; deep-ITM default unchanged ──

def test_multi_dry_run_never_writes():
    res = scanner.run_scan(
        dry_run=True, strategy="all",
        underlyings=[_multi_entry("NVDA")], matcher_fn=_fake_matcher(),
        queue_writer=lambda rows: pytest.fail("dry-run must never write"))
    assert res["ok"] is True and res["queue_result"]["skipped"] is True


def test_deep_itm_default_report_shape_is_backward_compatible():
    """Old flags → identical Stage-1 report shape: per_underlying (not
    per_symbol/per_strategy), discovery-linked winner summary, same keys."""
    res = scanner.run_scan(dry_run=True,
                           underlyings=[_multi_entry("NVDA")],
                           analysis_fn=ANALYSIS_FN)
    assert res["ok"] is True and res["strategy"] == "deep_itm_call"
    assert "per_underlying" in res and "per_strategy" not in res
    assert "per_symbol" not in res
    assert res["winner_summary"][0]["discovery_ref"] == 339


def test_cli_strategy_all_passes_through(monkeypatch):
    seen = {}

    def fake_run_scan(**kw):
        seen.update(kw)
        return {"ok": True, "dry_run": True, "universe": kw["universe"],
                "strategy": kw["strategy"], "strategies": ["atm_call"],
                "market_session": {"session": "test"}, "strategy_notes": {},
                "underlyings_considered": 0, "tier_stats": {}, "per_strategy": {},
                "per_symbol": [], "candidates_passed_gates": 0, "winners": [],
                "winner_summary": [], "queue_result": {"ok": True, "skipped": True},
                "queue_target": "x"}

    monkeypatch.setattr(scanner, "run_scan", fake_run_scan)
    assert scanner.main(["--dry-run", "--strategy", "all"]) == 0
    assert seen["strategy"] == "all" and seen["dry_run"] is True


# ═══════════════════════════════════════════════════════════════════════════
# EARNINGS-SPREADS Stage 2 (operator spec Part E) — earnings lane + filter
# ═══════════════════════════════════════════════════════════════════════════

from datetime import datetime, timedelta, timezone  # noqa: E402

from lib.options_pipeline import earnings_vertical_generator as evg  # noqa: E402


def _iso_in(days):
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def _earn_leg(side, strike, mid, *, delta=None, oi=600, volume=60):
    return {"side": side, "strike": float(strike), "bid": round(mid - 0.02, 4),
            "ask": round(mid + 0.02, 4), "mid": mid,
            "spread_pct": round(0.04 / mid * 100.0, 2), "volume": volume,
            "oi": oi, "delta": delta, "iv": 40.0, "dte": 12,
            "liquidity_score": 70}


EARN_EXP = "2026-07-17"


def _earn_event_json(sym):
    return {"symbol": sym, "days_to_earnings": 5,
            "earnings_date": {"date": "2026-07-15", "source": "test"},
            "event_window": {"days_before": 10, "days_after": 2,
                             "in_window": True},
            "nearest_expiration_after_earnings": {"available": True,
                                                  "exp": EARN_EXP, "dte": 12},
            "implied_move_pct": {"available": True, "pct": 5.0,
                                 "method": "atm_straddle_mid"},
            "historical_earnings_moves": {"available": False, "reason": "test"},
            "iv_context": {"available": False, "reason": "test"},
            "post_earnings_iv_crush_estimate": {"available": False,
                                                "reason": "test"},
            "event_thesis": "bearish", "event_thesis_source": "watchlist_sell",
            "event_confidence": 0.8, "risk_flags": [],
            "educational_only": True}


def _earn_snapshot(sym):
    return {"available": True, "symbol": sym, "underlying_price": 100.0,
            "expirations": [
                {"exp": EARN_EXP, "dte": 12, "liquidity_score": 70,
                 "contracts": [_earn_leg("call", 100.0, 1.0, delta=0.50),
                               _earn_leg("put", 100.0, 4.0, delta=-0.52),
                               _earn_leg("put", 95.0, 2.0, delta=-0.30),
                               _earn_leg("put", 90.0, 1.0, delta=-0.15)]},
            ],
            "liquidity_score": 70}


def _earn_proposals(sym):
    thesis = {"conviction": 0.70, "conviction_source": "watchlist_sell",
              "verdict": "sell", "held_shares": None, "hedge_of_held": False}
    gen = evg.generate_put_debit_spreads(sym, _earn_event_json(sym), None,
                                         thesis, snapshot=_earn_snapshot(sym))
    assert gen["available"] and gen["proposals"], "earnings fixture must generate"
    return gen["proposals"]


def _earn_matcher(record=None):
    """Per-symbol matcher: earnings debit passes with REAL generator rows."""
    record = record if record is not None else {}

    def fake(symbol, context, strategies, **kw):
        record.setdefault("calls", []).append(
            {"symbol": symbol, "strategies": list(strategies),
             "kw": dict(kw)})
        results = {}
        for sid in strategies:
            if sid == "earnings_put_debit_spread":
                results[sid] = {"status": "pass",
                                "reason": "2 proposal(s) passed gates",
                                "proposals": _earn_proposals(symbol)}
            elif sid == "earnings_put_credit_spread":
                results[sid] = {"status": "not_applicable",
                                "reason": "blocked initially (BLOCKED_INITIAL)",
                                "proposals": []}
            else:
                results[sid] = {"status": "fail",
                                "reason": "chain unavailable: weekend — no chain",
                                "proposals": []}
        return {"symbol": symbol,
                "context": {"bullish_source": None,
                            "bearish_source": "watchlist_sell"},
                "strategy_results": results, "cross_strategy_summary": {}}

    fake.record = record
    return fake


# ── (14) --strategy earnings_put_debit_spread single-strategy scan ───────────

def test_strategy_earnings_debit_single_scan_and_counts():
    fake = _earn_matcher()
    res = scanner.run_scan(dry_run=True, strategy="earnings_put_debit_spread",
                           underlyings=[_multi_entry("NVDA")], matcher_fn=fake)
    assert res["ok"] is True
    assert res["strategies"] == ["earnings_put_debit_spread"]
    # single-strategy runs get NO verdict-only rider
    assert fake.record["calls"][0]["strategies"] == ["earnings_put_debit_spread"]
    ps = res["per_strategy"]["earnings_put_debit_spread"]
    assert ps["scanned"] == 1 and ps["pass"] == 1 and ps["queued"] >= 1
    assert ps["top_symbols"] == ["NVDA"]
    json.dumps(res, default=str)


def test_earnings_rows_queue_paper_only_with_match_json():
    written = {}

    def writer(rows):
        written["rows"] = rows
        return {"ok": True, "upserted": len(rows)}

    res = scanner.run_scan(dry_run=False, strategy="earnings_put_debit_spread",
                           underlyings=[_multi_entry("NVDA")],
                           matcher_fn=_earn_matcher(), queue_writer=writer)
    assert res["ok"] is True and written["rows"]
    reg = scanner.load_strategy_registry()["strategies"]
    assert reg["earnings_put_debit_spread"]["alpaca_paper_enabled"] is False
    for row in written["rows"]:
        assert row["educational_paper_model"] is True
        assert row["paper_only"] is True
        assert row["enterprise"]["live_eligible"] is False
        assert row["meta"]["alpaca_paper_enabled"] is False   # button stays hidden
        mj = row["meta"]["match_json"]
        assert mj["strategy"] == "earnings_put_debit_spread"
        assert mj["status"] == "pass"
        assert "thesis: watchlist_sell" in mj["why_matched"]
        assert row["id"].startswith("opt_earnings_put_debit_spread_NVDA_paper_model_")


def test_earnings_rerun_produces_identical_ids():
    captured = []

    def writer(rows):
        captured.append([r["id"] for r in rows])
        return {"ok": True, "upserted": len(rows)}

    for _ in range(2):
        res = scanner.run_scan(dry_run=False,
                               strategy="earnings_put_debit_spread",
                               underlyings=[_multi_entry("NVDA")],
                               matcher_fn=_earn_matcher(), queue_writer=writer)
        assert res["ok"] is True
    assert captured[0] == captured[1]
    assert len(set(captured[0])) == len(captured[0])


# ── (15) credit lane: honest refusal while BLOCKED_INITIAL ───────────────────

def test_strategy_earnings_credit_refused_while_blocked():
    res = scanner.run_scan(dry_run=True, strategy="earnings_put_credit_spread",
                           underlyings=[_multi_entry("NVDA")],
                           matcher_fn=_earn_matcher())
    assert res["ok"] is False
    assert "paper_enabled=false" in res["error"]
    assert "BLOCKED_INITIAL" in res["error"]


def test_strategy_all_discloses_credit_exclusion():
    res = scanner.run_scan(dry_run=True, strategy="all",
                           underlyings=[_multi_entry("NVDA")],
                           matcher_fn=_earn_matcher())
    assert res["ok"] is True
    assert "earnings_put_credit_spread" not in res["strategies"]
    assert "earnings_put_debit_spread" in res["strategies"]
    note = res["strategy_notes"]["earnings_put_credit_spread"]
    assert "paper_enabled=false" in note and "BLOCKED_INITIAL" in note


# ── (16) --event-window earnings / --earnings-only pre-match filter ──────────

def test_earnings_filter_skips_out_of_window_before_matching():
    fake = _earn_matcher()
    underlyings = [
        dict(_multi_entry("NVDA"), earnings_date=_iso_in(3)),     # in window
        dict(_multi_entry("RTX"), earnings_date=_iso_in(40)),     # too far out
        dict(_multi_entry("OLD"), earnings_date=_iso_in(-10)),    # stale event
        _multi_entry("NODATE"),                                   # unknown date
    ]
    res = scanner.run_scan(dry_run=True, strategy="earnings_put_debit_spread",
                           underlyings=underlyings, matcher_fn=fake,
                           event_window="earnings")
    assert res["ok"] is True
    # the matcher (and therefore any chain read) ran ONLY for the in-window name
    assert [c["symbol"] for c in fake.record["calls"]] == ["NVDA"]
    # the enriched earnings date rides into the matcher call
    assert fake.record["calls"][0]["kw"].get("earnings_date") == _iso_in(3)
    ef = res["earnings_filter"]
    assert ef["applied"] is True
    assert ef["in_window"] == 1 and ef["filtered_out"] == 3
    assert ef["window_days_before"] == 10 and ef["window_days_after"] == 2
    detail = {row["symbol"]: row for row in res["per_symbol"]}
    for sym in ("RTX", "OLD", "NODATE"):
        assert detail[sym]["status"] == "skipped"
        assert "--event-window earnings" in detail[sym]["reason"]
    assert "no earnings date" in detail["NODATE"]["reason"]
    assert "outside window" in detail["RTX"]["reason"]
    json.dumps(res, default=str)


def test_event_window_all_applies_no_filter():
    fake = _earn_matcher()
    res = scanner.run_scan(dry_run=True, strategy="earnings_put_debit_spread",
                           underlyings=[_multi_entry("NVDA")], matcher_fn=fake)
    assert res["earnings_filter"]["applied"] is False
    assert [c["symbol"] for c in fake.record["calls"]] == ["NVDA"]


def test_event_window_refused_for_deep_itm_stage1_flow():
    res = scanner.run_scan(dry_run=True, event_window="earnings",
                           underlyings=[_multi_entry("NVDA")],
                           analysis_fn=ANALYSIS_FN)
    assert res["ok"] is False
    assert "matcher-driven strategy" in res["error"]


def test_unknown_event_window_refused():
    res = scanner.run_scan(dry_run=True, strategy="all",
                           event_window="lunar", underlyings=[])
    assert res["ok"] is False and "unknown event window" in res["error"]


def test_cli_earnings_only_flags(monkeypatch):
    seen = {}

    def fake_run_scan(**kw):
        seen.update(kw)
        return {"ok": True, "dry_run": True, "universe": kw["universe"],
                "strategy": kw["strategy"], "strategies": [],
                "market_session": {"session": "test"}, "strategy_notes": {},
                "underlyings_considered": 0, "tier_stats": {}, "per_strategy": {},
                "per_symbol": [], "candidates_passed_gates": 0, "winners": [],
                "winner_summary": [], "queue_result": {"ok": True, "skipped": True},
                "queue_target": "x"}

    monkeypatch.setattr(scanner, "run_scan", fake_run_scan)
    assert scanner.main(["--dry-run", "--strategy", "earnings_put_debit_spread",
                         "--earnings-only"]) == 0
    assert seen["event_window"] == "earnings"
    assert scanner.main(["--dry-run", "--strategy", "all",
                         "--event-window", "earnings"]) == 0
    assert seen["event_window"] == "earnings"
    assert scanner.main(["--dry-run"]) == 0
    assert seen["event_window"] == "all"
    with pytest.raises(SystemExit):               # argparse rejects bad choices
        scanner.main(["--dry-run", "--event-window", "bogus"])


def test_earnings_dry_run_never_writes():
    res = scanner.run_scan(
        dry_run=True, strategy="earnings_put_debit_spread",
        underlyings=[_multi_entry("NVDA")], matcher_fn=_earn_matcher(),
        queue_writer=lambda rows: pytest.fail("dry-run must never write"))
    assert res["ok"] is True and res["queue_result"]["skipped"] is True
