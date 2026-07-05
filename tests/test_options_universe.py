#!/usr/bin/env python3
"""ALPACA-OPTIONS Stage 1 — options universe + strategy registry tests.

Covers: options_universe.yaml loads with all seven tiers (static seeds intact),
fail-closed yaml validation (missing/corrupt/invalid configs raise), tier
resolution with dedupe + precedence, defensive dynamic resolvers (holdings /
watchlist / hermes gap candidates — monkeypatched, outage ⇒ empty tier),
strategy registry contents + fail-closed live policy (live_enabled true
refuses to load unless TRADE_AI_OPTIONS_LIVE_POLICY=explicit, which is never
set), and a forbidden-imports sweep on the new module.

    .venv/bin/python -m pytest tests/test_options_universe.py -q
"""
from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import universe as uni  # noqa: E402

CORE_30 = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
           "TSLA", "AMD", "NFLX", "JPM", "BAC", "XOM", "CVX", "RTX", "LMT", "BA",
           "DIS", "KO", "PEP", "JNJ", "UNH", "V", "MA", "COST", "WMT", "SCHD", "DIA"]
SECTOR_13 = ["XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB",
             "XLRE", "XBI", "SMH", "ITA"]


def _write(tmp_path, doc, name="u.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


@pytest.fixture()
def ucfg():
    return uni.load_universe_config()


@pytest.fixture()
def reg():
    return uni.load_strategy_registry()


# ── (1) universe yaml loads with the spec'd tiers ────────────────────────────

def test_universe_config_has_all_tiers(ucfg):
    assert set(uni.REQUIRED_TIERS) <= set(ucfg["tiers"])
    assert sorted(ucfg["tier_precedence"]) == sorted(ucfg["tiers"])
    # precedence: holdings > watchlist > core > ... (dedupe order)
    prec = ucfg["tier_precedence"]
    assert prec.index("holdings") < prec.index("watchlist_buy_strong_buy") \
        < prec.index("liquid_options_core") < prec.index("sector_etfs") \
        < prec.index("discovery_missing_exposure")


def test_dynamic_tiers_are_markers_not_lists(ucfg):
    for tier in ("holdings", "watchlist_buy_strong_buy", "discovery_missing_exposure"):
        t = ucfg["tiers"][tier]
        assert t["dynamic"] is True and "symbols" not in t
        assert t["resolver"] in uni.KNOWN_RESOLVERS
        assert t["strategy_allowlist"]


def test_static_seed_tiers_contents(ucfg):
    core = [s["symbol"] for s in ucfg["tiers"]["liquid_options_core"]["symbols"]]
    assert sorted(core) == sorted(CORE_30) and len(core) == 30
    sect = [s["symbol"] for s in ucfg["tiers"]["sector_etfs"]["symbols"]]
    assert sorted(sect) == sorted(SECTOR_13) and len(sect) == 13
    for entry in ucfg["tiers"]["liquid_options_core"]["symbols"]:
        assert entry["reason_included"].strip()
        assert entry["liquidity_expectation"] == "high"
        assert entry["strategy_allowlist"] == ["deep_itm_call", "covered_call",
                                               "cash_secured_put", "protective_put",
                                               "credit_spread"]
        assert entry["enabled"] is True
        assert entry["max_scan_frequency"] == "daily"


def test_scaffold_tiers_empty(ucfg):
    assert ucfg["tiers"]["strategy_specific"]["symbols"] == []
    assert ucfg["tiers"]["operator_added"]["symbols"] == []
    # documented example must not leak into resolution
    entries = uni.resolve_universe(["strategy_specific", "operator_added"], config=ucfg)
    assert entries == []


# ── (2) fail-closed universe validation ──────────────────────────────────────

def test_missing_file_raises(tmp_path):
    with pytest.raises(uni.UniverseConfigError, match="missing"):
        uni.load_universe_config(tmp_path / "nope.yaml")


def test_corrupt_yaml_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("tiers: [unclosed", encoding="utf-8")
    with pytest.raises(uni.UniverseConfigError, match="unparsable"):
        uni.load_universe_config(p)


def test_missing_required_tier_raises(tmp_path, ucfg):
    doc = copy.deepcopy(ucfg)
    del doc["tiers"]["sector_etfs"]
    doc["tier_precedence"].remove("sector_etfs")
    with pytest.raises(uni.UniverseConfigError, match="required tiers"):
        uni.load_universe_config(_write(tmp_path, doc))


def test_bad_precedence_raises(tmp_path, ucfg):
    doc = copy.deepcopy(ucfg)
    doc["tier_precedence"] = doc["tier_precedence"][:-1]   # dropped a tier
    with pytest.raises(uni.UniverseConfigError, match="tier_precedence"):
        uni.load_universe_config(_write(tmp_path, doc))


def test_duplicate_symbol_in_tier_raises(tmp_path, ucfg):
    doc = copy.deepcopy(ucfg)
    syms = doc["tiers"]["liquid_options_core"]["symbols"]
    syms.append(dict(syms[0]))
    with pytest.raises(uni.UniverseConfigError, match="duplicate symbol"):
        uni.load_universe_config(_write(tmp_path, doc))


def test_unknown_strategy_in_allowlist_raises(tmp_path, ucfg):
    doc = copy.deepcopy(ucfg)
    doc["tiers"]["liquid_options_core"]["symbols"][0]["strategy_allowlist"] = ["yolo_calls"]
    with pytest.raises(uni.UniverseConfigError, match="unknown strategies"):
        uni.load_universe_config(_write(tmp_path, doc))


def test_missing_reason_included_raises(tmp_path, ucfg):
    doc = copy.deepcopy(ucfg)
    doc["tiers"]["operator_added"]["symbols"] = [
        {"symbol": "TLT", "strategy_allowlist": ["credit_spread"], "enabled": True}]
    with pytest.raises(uni.UniverseConfigError, match="reason_included"):
        uni.load_universe_config(_write(tmp_path, doc))


def test_dynamic_tier_with_static_symbols_raises(tmp_path, ucfg):
    doc = copy.deepcopy(ucfg)
    doc["tiers"]["holdings"]["symbols"] = [
        {"symbol": "SPY", "reason_included": "x", "strategy_allowlist": ["covered_call"],
         "enabled": True}]
    with pytest.raises(uni.UniverseConfigError, match="must not carry"):
        uni.load_universe_config(_write(tmp_path, doc))


def test_unknown_resolver_raises(tmp_path, ucfg):
    doc = copy.deepcopy(ucfg)
    doc["tiers"]["holdings"]["resolver"] = "crystal_ball"
    with pytest.raises(uni.UniverseConfigError, match="known resolver"):
        uni.load_universe_config(_write(tmp_path, doc))


# ── (3) tier resolution: dedupe + precedence + selectors ─────────────────────

HELD = {"NVDA": 120.0, "RTX": 50.0}
WL_ROWS = [
    {"symbol": "PLTR", "card_rec": "strong_buy", "synth_rec": None,
     "hermes_composite_score": 80},
    {"symbol": "SPY", "card_rec": None, "synth_rec": "buy",
     "hermes_composite_score": 60},
    {"symbol": "XYZ", "card_rec": "hold", "synth_rec": None,
     "hermes_composite_score": 90},
]
GAP_ROWS = [
    {"id": 501, "label": "ASML", "status": "READY_FOR_REVIEW",
     "seed_symbols": ["ASML"], "meta_json": {"gap_type": "MISSING_COMPANY"}},
    {"id": 502, "label": "utilities coverage gap", "status": "DISCOVERED",
     "seed_symbols": ["XLU"], "meta_json": {"gap_type": "MISSING_SECTOR"}},
]


def _resolve(selector="all", **kw):
    kw.setdefault("holdings", HELD)
    kw.setdefault("watchlist_rows", WL_ROWS)
    kw.setdefault("gap_rows", GAP_ROWS)
    kw.setdefault("gap_validator", lambda s: True)
    return uni.resolve_universe(selector, **kw)


def test_resolution_dedupes_with_tier_precedence():
    out = _resolve("all")
    by = {e["symbol"]: e for e in out}
    assert len(out) == len(by)                              # fully deduped
    # NVDA held AND a liquid_core seed → holdings tier wins
    assert by["NVDA"]["source_tier"] == "holdings"
    assert by["NVDA"]["held_shares"] == 120.0
    # SPY watchlist buy AND liquid_core seed → watchlist tier wins
    assert by["SPY"]["source_tier"] == "watchlist_buy_strong_buy"
    assert by["SPY"]["conviction"] == 0.70
    # XLU sector ETF AND a discovery gap → sector_etfs (higher precedence) wins
    assert by["XLU"]["source_tier"] == "sector_etfs"
    # untouched names keep their own tiers
    assert by["QQQ"]["source_tier"] == "liquid_options_core"
    assert by["PLTR"]["source_tier"] == "watchlist_buy_strong_buy"
    assert by["ASML"]["source_tier"] == "discovery_missing_exposure"
    assert by["ASML"]["discovery_gap"]["candidate_id"] == 501
    assert "XYZ" not in by                                  # hold never eligible


def test_every_entry_carries_contract_fields():
    for e in _resolve("all"):
        assert e["symbol"] and e["source_tier"] in uni.REQUIRED_TIERS
        assert e["reason_included"]
        assert isinstance(e["strategy_allowlist"], list) and e["strategy_allowlist"]
        assert e["conviction"] >= 0.55                      # clears the strategy floor


def test_selector_scoping():
    hw = {e["symbol"] for e in _resolve("holdings_watchlist")}
    assert hw == {"NVDA", "RTX", "PLTR", "SPY"}
    lc = {e["source_tier"] for e in _resolve("liquid_core")}
    assert lc == {"liquid_options_core", "sector_etfs"}
    disc = _resolve("discovery")
    assert {e["symbol"] for e in disc} == {"ASML", "XLU"}
    assert all(e["source_tier"] == "discovery_missing_exposure" for e in disc)


def test_unknown_selector_raises():
    with pytest.raises(uni.UniverseConfigError, match="unknown universe selector"):
        uni.resolve_universe("everything_and_the_moon")


def test_disabled_tier_is_skipped(ucfg):
    doc = copy.deepcopy(ucfg)
    doc["tiers"]["sector_etfs"]["enabled"] = False
    out = uni.resolve_universe("liquid_core", config=doc,
                               holdings={}, watchlist_rows=[], gap_rows=[])
    assert {e["source_tier"] for e in out} == {"liquid_options_core"}


# ── (4) dynamic resolvers are defensive ──────────────────────────────────────

def test_holdings_resolver_outage_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(uni, "_load_holdings_symbols",
                        lambda: (_ for _ in ()).throw(RuntimeError("disk gone")))
    out = uni.resolve_universe(["holdings"], watchlist_rows=[], gap_rows=[])
    assert out == []                                        # no raise, no fabrication


def test_watchlist_resolver_db_down_degrades(monkeypatch):
    monkeypatch.setattr(uni, "_fetch_watchlist_buy_rows",
                        lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert uni.resolve_universe(["watchlist_buy_strong_buy"],
                                holdings={}, gap_rows=[]) == []


def test_watchlist_resolver_filters_garbage_rows():
    rows = [{"symbol": "BAD SYM", "card_rec": "buy"},         # shape-invalid
            {"symbol": "", "card_rec": "strong_buy"},          # empty
            {"symbol": "OK", "card_rec": "sell"},              # not buy/strong_buy
            {"symbol": "GOOD", "card_rec": "Strong Buy"}]
    out = uni.resolve_universe(["watchlist_buy_strong_buy"],
                               holdings={}, watchlist_rows=rows, gap_rows=[])
    assert [e["symbol"] for e in out] == ["GOOD"]
    assert out[0]["conviction"] == 0.85


def test_gap_resolver_requires_validated_ticker():
    # validator says no → discovery tier stays empty (fail-closed, never guessed)
    out = uni.resolve_universe("discovery", holdings={}, watchlist_rows=[],
                               gap_rows=GAP_ROWS, gap_validator=lambda s: False)
    assert out == []
    # rows without any plausible ticker are skipped even with a permissive validator
    junk = [{"id": 9, "label": "vibes", "status": "DISCOVERED",
             "seed_symbols": [], "meta_json": {"gap_type": "MISSING_SECTOR"}}]
    assert uni.resolve_universe("discovery", holdings={}, watchlist_rows=[],
                                gap_rows=junk, gap_validator=lambda s: True) == []


def test_gap_resolver_handles_meta_json_string():
    rows = [{"id": 7, "label": "TSM", "status": "READY_FOR_REVIEW",
             "seed_symbols": ["TSM"],
             "meta_json": '{"gap_type": "MISSING_COMPANY"}'}]
    out = uni.resolve_universe("discovery", holdings={}, watchlist_rows=[],
                               gap_rows=rows, gap_validator=lambda s: True)
    assert len(out) == 1 and out[0]["symbol"] == "TSM"
    assert out[0]["discovery_gap"]["gap_type"] == "MISSING_COMPANY"


def test_gap_validator_default_fails_closed(monkeypatch):
    # validator import/DB failure → ticker does NOT pass
    assert uni._validate_gap_ticker("\x00notasymbol") is False


# ── (5) strategy registry: contents + fail-closed live policy ────────────────

def test_registry_contents_match_spec(reg):
    s = reg["strategies"]
    assert set(s) == {"deep_itm_call", "covered_call", "cash_secured_put",
                      "protective_put", "credit_spread"}
    assert s["deep_itm_call"]["status"] == "TESTING_PAPER"
    assert s["deep_itm_call"]["paper_enabled"] is True
    assert s["deep_itm_call"]["alpaca_paper_enabled"] is True
    for sid in ("cash_secured_put", "covered_call", "protective_put"):
        assert s[sid]["status"] == "MODELED"
        assert s[sid]["paper_enabled"] is True
        assert s[sid]["alpaca_paper_enabled"] is False
    assert s["credit_spread"]["status"] == "RESEARCH_ONLY"
    assert s["credit_spread"]["paper_enabled"] is False
    for sid, row in s.items():
        assert row["live_enabled"] is False, sid
        assert row["live_exception_allowed"] is False, sid
        assert row["live_exception_requires_2fa"] is True, sid
        assert row["required_permission_level"] == "operator"
        assert set(row["allowed_underlying_tiers"]) <= set(uni.REQUIRED_TIERS)
        gates = row["liquidity_gates"]
        assert gates["max_spread_pct"] > 0 and gates["min_oi"] >= 0 \
            and gates["min_volume"] >= 0
        assert row["max_contracts_paper"] == 1
        assert row["max_premium_paper"] == 5000


def test_registry_live_enabled_true_fails_closed(tmp_path, reg):
    doc = copy.deepcopy(reg)
    doc["strategies"]["deep_itm_call"]["live_enabled"] = True
    p = _write(tmp_path, doc, "r.yaml")
    with pytest.raises(uni.LivePolicyViolation):
        uni.load_strategy_registry(p, env={})
    # even a stray env value that isn't the exact policy string refuses
    with pytest.raises(uni.LivePolicyViolation):
        uni.load_strategy_registry(p, env={"TRADE_AI_OPTIONS_LIVE_POLICY": "yes"})
    # only the exact explicit policy env unlocks parsing (never set in deployment)
    out = uni.load_strategy_registry(p, env={"TRADE_AI_OPTIONS_LIVE_POLICY": "explicit"})
    assert out["strategies"]["deep_itm_call"]["live_enabled"] is True


def test_registry_live_exception_also_fails_closed(tmp_path, reg):
    doc = copy.deepcopy(reg)
    doc["strategies"]["credit_spread"]["live_exception_allowed"] = True
    with pytest.raises(uni.LivePolicyViolation):
        uni.load_strategy_registry(_write(tmp_path, doc, "r.yaml"), env={})


def test_registry_validation_fails_closed(tmp_path, reg):
    with pytest.raises(uni.RegistryConfigError, match="missing"):
        uni.load_strategy_registry(tmp_path / "absent.yaml")
    doc = copy.deepcopy(reg)
    del doc["strategies"]["covered_call"]["liquidity_gates"]
    with pytest.raises(uni.RegistryConfigError, match="missing fields"):
        uni.load_strategy_registry(_write(tmp_path, doc, "a.yaml"))
    doc = copy.deepcopy(reg)
    doc["strategies"]["covered_call"]["status"] = "SEND_IT"
    with pytest.raises(uni.RegistryConfigError, match="unknown status"):
        uni.load_strategy_registry(_write(tmp_path, doc, "b.yaml"))
    doc = copy.deepcopy(reg)
    doc["strategies"]["credit_spread"]["alpaca_paper_enabled"] = True  # paper_enabled false
    with pytest.raises(uni.RegistryConfigError, match="requires paper_enabled"):
        uni.load_strategy_registry(_write(tmp_path, doc, "c.yaml"))


def test_registry_entry_and_allowlist_helpers(reg):
    row = uni.registry_entry("deep_itm_call", registry=reg)
    assert row["alpaca_paper_enabled"] is True
    assert uni.registry_entry("iron_condor", registry=reg) is None
    assert uni.strategy_allowed_for_entry(
        {"strategy_allowlist": ["covered_call"]}, "deep_itm_call") is False
    assert uni.strategy_allowed_for_entry(
        {"strategy_allowlist": ["deep_itm_call"]}, "deep_itm_call") is True
    assert uni.strategy_allowed_for_entry({}, "deep_itm_call") is True  # legacy/injected


# ── (6) forbidden imports — universe module stays broker-free ────────────────

FORBIDDEN_MODULES = {
    "options_order_pilot", "options_pilot_arm", "brokers", "approval_service",
    "schwab_transport", "schwab_pilot_orders", "alpaca_trade_api", "alpaca",
    "trade_executor", "order_executor", "telegram_2fa", "two_factor",
    "options_execution_policy",
}


def test_universe_module_has_no_forbidden_imports():
    tree = ast.parse((ROOT / "scripts" / "lib" / "options_pipeline" / "universe.py"
                      ).read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.update({a.name, a.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.update({node.module, node.module.split(".")[0]})
    assert not mods & FORBIDDEN_MODULES
