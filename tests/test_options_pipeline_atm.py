#!/usr/bin/env python3
"""MULTI-STRATEGY OPTIONS Stage 1 — ATM long-premium generator + registry extension.

Covers: registry rows for atm_call/atm_put (spec Part A gates, live locks intact
after the edit, LivePolicyViolation still fires), strategy YAMLs load + validate
through the standard loader, ATM call/put selection on synthetic chain snapshots
(delta window, DTE buckets, nearest-the-money proxy), gates (spread / OI /
volume / premium-pct-of-underlying / paper premium cap), earnings flag-vs-block
policy modes, paper/manual flags on every proposal row (live_eligible always
False), ranking, and a forbidden-imports sweep (grep + AST) over BOTH new
modules.

    .venv/bin/python -m pytest tests/test_options_pipeline_atm.py -q
"""
from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import atm_long_premium_generator as atm  # noqa: E402
from lib.options_pipeline import universe as uni  # noqa: E402

SPOT = 100.0
NO_IV = {"available": False, "reason": "iv context not computed (test)"}
NO_EARNINGS = "2099-01-01"   # after every fixture expiry → earnings flag False


# ── synthetic parse_chain-style snapshot fixtures ─────────────────────────────

def _contract(side="call", strike=100.0, mid=4.0, *, delta=0.52, oi=800,
              volume=50, spread_pct=3.0, dte=33, liquidity_score=75,
              no_quote=False):
    return {
        "side": side, "strike": strike,
        "bid": None if no_quote else round(mid - 0.10, 2),
        "ask": None if no_quote else round(mid + 0.10, 2),
        "mid": None if no_quote else mid,
        "spread_pct": None if no_quote else spread_pct,
        "volume": volume, "oi": oi, "delta": delta, "iv": 30.0,
        "dte": dte, "liquidity_score": liquidity_score,
    }


def _snapshot(expirations=None, spot=SPOT):
    exps = expirations if expirations is not None else [
        {"exp": "2026-08-07", "dte": 33,
         "contracts": [_contract(dte=33), _contract(side="put", delta=-0.52, dte=33)]},
    ]
    return {"available": True, "symbol": "TEST", "underlying_price": spot,
            "expirations": exps, "liquidity_score": 70,
            "source": "fixture", "generated_at": "2026-07-05T00:00:00+00:00"}


def _gen(side="call", snapshot=None, config=None, thesis_ctx=None,
         earnings=NO_EARNINGS, iv_context=NO_IV, sym="NVDA"):
    return atm.generate_atm_proposals(
        sym, side, config,
        thesis_ctx or {"conviction": 0.85, "conviction_source": "watchlist_strong_buy",
                       "verdict": "strong_buy"},
        snapshot=snapshot if snapshot is not None else _snapshot(),
        earnings_date=earnings, iv_context=iv_context)


# ── (1) registry extension (spec Part A) ─────────────────────────────────────

def test_registry_has_atm_rows_with_spec_gates():
    reg = uni.load_strategy_registry()
    s = reg["strategies"]
    assert "atm_call" in s and "atm_put" in s
    for sid in ("atm_call", "atm_put"):
        row = s[sid]
        assert row["family"] == "directional_long_premium"
        assert row["status"] == "TESTING_PAPER"    # spec 'research_paper' → loader enum
        assert row["paper_enabled"] is True
        assert row["alpaca_paper_enabled"] is False   # initially off
        assert row["live_enabled"] is False
        assert row["live_exception_allowed"] is False
        assert row["live_exception_requires_2fa"] is True
        assert row["required_permission_level"] == "operator"
        assert row["liquidity_gates"] == {"max_spread_pct": 8.0, "min_oi": 300,
                                          "min_volume": 10}
        sel = row["selection"]
        assert sel["dte_buckets"] == [30, 45, 60]
        assert sel["max_premium_pct_of_underlying"] == 8.0
        assert sel["earnings_policy"] == "flag"       # configurable to 'block'
        assert row["max_contracts_paper"] == 1        # live caps intact
        assert row["max_premium_paper"] == 5000
    assert s["atm_call"]["selection"]["delta_range"] == [0.45, 0.60]
    assert s["atm_put"]["selection"]["delta_range"] == [-0.60, -0.45]
    # deep_itm_call untouched (status enum has no 'active_paper' — stays TESTING_PAPER)
    assert s["deep_itm_call"]["status"] == "TESTING_PAPER"


def test_registry_live_locks_still_enforced_after_edit(tmp_path):
    reg = uni.load_strategy_registry()
    for sid, field in (("atm_call", "live_enabled"),
                       ("atm_put", "live_exception_allowed")):
        doc = copy.deepcopy(reg)
        doc["strategies"][sid][field] = True
        p = tmp_path / f"{sid}_{field}.yaml"
        p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        with pytest.raises(uni.LivePolicyViolation):
            uni.load_strategy_registry(p, env={})


# ── (2) strategy YAMLs load through the standard loader ─────────────────────

def test_atm_yamls_load_and_validate():
    from strategy_config_loader import load_strategy_config, validate_strategy_config
    for sid, band in (("atm_call", [0.45, 0.60]), ("atm_put", [-0.60, -0.45])):
        cfg = load_strategy_config(sid)
        assert validate_strategy_config(cfg) == []
        assert cfg["strategy_id"] == sid
        assert cfg["family"] == "directional_long_premium"
        assert cfg["paper_only"] is True
        assert cfg["execution_mode"] == "manual_review_only"
        assert cfg["execution"]["live_allowed"] is False
        pol = cfg["selection_policy"]
        assert pol["delta_range"] == band
        assert pol["dte_buckets"] == [30, 45, 60]
        assert pol["max_spread_pct"] == 8.0
        assert pol["min_open_interest"] == 300
        assert pol["min_volume"] == 10
        assert pol["max_premium_pct_of_underlying"] == 8.0
        assert pol["earnings_policy"] == "flag"
        vg = cfg["validation_gate"]
        assert vg["min_closed_paper_trades"] == 30
        assert vg["human_approval_required"] is True


def test_pipeline_config_merges_registry_gates():
    cfg = atm.load_pipeline_config("atm_call")
    pol = cfg["selection_policy"]
    assert pol["max_spread_pct"] == 8.0
    assert pol["min_open_interest"] == 300
    assert pol["min_volume"] == 10
    assert pol["max_premium_pct_of_underlying"] == 8.0
    assert pol["max_premium_paper"] == 5000.0
    assert pol["max_contracts_paper"] == 1
    with pytest.raises(ValueError):
        atm.load_pipeline_config("yolo_calls")


def test_pipeline_config_reraises_live_policy_violation(monkeypatch):
    def boom():
        raise uni.LivePolicyViolation("live flag without explicit policy env")
    monkeypatch.setattr(uni, "load_strategy_registry", boom)
    with pytest.raises(uni.LivePolicyViolation):
        atm.load_pipeline_config("atm_call")


# ── (3) selection: delta window, DTE buckets, proxy ──────────────────────────

def test_happy_path_call_selection_and_math():
    out = _gen("call")
    assert out["available"] is True and out["count"] == 1
    p = out["proposals"][0]
    assert p["strategy"] == "atm_call"
    assert p["strategy_family"] == "directional_long_premium"
    assert p["side"] == "BUY" and p["option_type"] == "call"
    assert p["contracts"] == 1
    assert p["premium"] == 4.0 and p["premium_total"] == 400.0
    assert p["max_loss"] == 400.0                    # long premium: max loss = debit
    assert p["breakeven"] == 104.0
    assert p["breakeven_move_pct"] == 4.0
    assert p["premium_pct_of_underlying"] == 4.0
    assert p["max_profit"] == "unlimited"
    # edge = mean(ATM fit 100, liq 75) × conviction 0.85 (IV modifier 1.0)
    assert p["edge_score"] == 74.4
    assert p["id"].startswith("opt_atm_call_NVDA_")
    assert p["recommended_action"] == "Review ATM Call (paper model)"


def test_happy_path_put_selection_and_math():
    out = _gen("put")
    assert out["count"] == 1
    p = out["proposals"][0]
    assert p["strategy"] == "atm_put"
    assert p["side"] == "BUY" and p["option_type"] == "put"
    assert p["breakeven"] == 96.0
    assert p["breakeven_move_pct"] == -4.0           # required move is DOWN, honest sign
    assert p["max_profit"] == 9600.0                 # (strike − premium) × 100
    assert p["max_loss"] == 400.0
    assert p["id"].startswith("opt_atm_put_NVDA_")
    assert p["recommended_action"] == "Review ATM Put (paper model)"


def test_delta_window_excludes_out_of_band():
    snap = _snapshot([{"exp": "2026-08-07", "dte": 33,
                       "contracts": [_contract(delta=0.30),
                                     _contract(strike=90.0, delta=0.75)]}])
    out = _gen("call", snapshot=snap)
    assert out["count"] == 0
    assert any("|delta| in [0.45, 0.6]" in (b.get("reason") or "")
               for b in out["buckets"])


def test_dte_buckets_selected_and_far_expiry_honest():
    snap = _snapshot([
        {"exp": "2026-08-07", "dte": 33, "contracts": [_contract(dte=33)]},
        {"exp": "2026-08-21", "dte": 47, "contracts": [_contract(strike=101.0, dte=47)]},
        {"exp": "2026-09-04", "dte": 61, "contracts": [_contract(strike=102.0, dte=61)]},
    ])
    out = _gen("call", snapshot=snap)
    assert out["count"] == 3                          # one winner per 30/45/60 bucket
    assert sorted(b["target_dte"] for b in out["buckets"]) == [30, 45, 60]
    # a lone far expiry must not masquerade as a near bucket
    far = _snapshot([{"exp": "2027-01-15", "dte": 194, "contracts": [_contract(dte=194)]}])
    out = _gen("call", snapshot=far)
    assert out["count"] == 0
    assert all("no expiration near this DTE bucket" in b["reason"]
               for b in out["buckets"])


def test_shared_expiration_not_double_proposed():
    # one 38-DTE expiry is within tolerance of BOTH the 30 and 45 buckets
    snap = _snapshot([{"exp": "2026-08-12", "dte": 38, "contracts": [_contract(dte=38)]}])
    out = _gen("call", snapshot=snap)
    assert out["count"] == 1                          # deduped on (strike, exp)
    ids = [p["id"] for p in out["proposals"]]
    assert len(ids) == len(set(ids))


def test_nearest_the_money_proxy_when_no_greeks():
    snap = _snapshot([{"exp": "2026-08-07", "dte": 33,
                       "contracts": [_contract(delta=None),
                                     _contract(strike=120.0, delta=None)]}])
    out = _gen("call", snapshot=snap)
    assert out["count"] == 1
    p = out["proposals"][0]
    assert p["strike"] == 100.0                       # 120 is outside the ±5% band
    assert p["meta"]["selection_mode"] == "atm_proxy"
    assert "delta_proxy_nearest_the_money" in p["meta"]["gate_flags"]
    assert p["pop_pct"] is None                       # never fabricated from missing delta


def test_proxy_disallowed_rejects_honestly():
    cfg = atm.load_pipeline_config("atm_call")
    cfg["selection_policy"]["allow_delta_proxy"] = False
    snap = _snapshot([{"exp": "2026-08-07", "dte": 33,
                       "contracts": [_contract(delta=None)]}])
    out = _gen("call", snapshot=snap, config=cfg)
    assert out["count"] == 0
    assert any("delta proxy is disallowed" in (b.get("reason") or "")
               for b in out["buckets"])


# ── (4) gates: spread / OI / volume / premium pct / paper cap / quote ────────

@pytest.mark.parametrize("kw,reject_bit", [
    ({"spread_pct": 9.0}, "spread_9.0pct_gt_8.0"),
    ({"oi": 200}, "oi_200_lt_300"),
    ({"volume": 5}, "volume_5_lt_10"),
    ({"mid": 9.0}, "premium_9.0pct_of_underlying_gt_8"),
    ({"no_quote": True}, "no_quotable_mid"),
])
def test_gate_rejections(kw, reject_bit):
    snap = _snapshot([{"exp": "2026-08-07", "dte": 33,
                       "contracts": [_contract(**kw)]}])
    out = _gen("call", snapshot=snap)
    assert out["count"] == 0
    assert reject_bit in json.dumps(out["buckets"])


def test_gate_paper_premium_cap():
    # spot 800: mid 60 → 7.5% of underlying (passes pct) but $6000 debit > $5000 cap
    snap = _snapshot(
        [{"exp": "2026-08-07", "dte": 33,
          "contracts": [_contract(strike=800.0, mid=60.0)]}], spot=800.0)
    out = _gen("call", snapshot=snap)
    assert out["count"] == 0
    assert "gt_max_premium_paper_5000" in json.dumps(out["buckets"])


def test_earnings_flag_mode_discloses_and_block_mode_rejects():
    snap = _snapshot()
    # default policy: flag — proposal queues with a disclosed flag
    out = _gen("call", snapshot=snap, earnings="2026-08-01")   # before 2026-08-07 expiry
    assert out["count"] == 1
    assert "earnings_before_expiry_flagged" in out["proposals"][0]["meta"]["gate_flags"]
    assert out["proposals"][0]["enterprise"]["earnings"]["in_blackout"] is True
    # block mode: same chain, hard reject
    cfg = atm.load_pipeline_config("atm_call")
    cfg["selection_policy"]["earnings_policy"] = "block"
    out = _gen("call", snapshot=snap, config=cfg, earnings="2026-08-01")
    assert out["count"] == 0
    assert "earnings_before_expiry" in json.dumps(out["buckets"])


def test_earnings_unknown_is_flag_not_reject():
    out = _gen("call", earnings="")                   # unknown, honest flag
    assert out["count"] == 1
    assert "earnings_unknown" in out["proposals"][0]["meta"]["gate_flags"]


def test_degraded_chain_reports_honestly():
    out = atm.generate_atm_proposals(
        "NVDA", "call", None, {"conviction": 0.85},
        snapshot={"available": False, "reason": "weekend — no chain"},
        earnings_date=NO_EARNINGS, iv_context=NO_IV)
    assert out["available"] is False and "weekend" in out["reason"]
    assert out["count"] == 0 and out["proposals"] == []


# ── (5) paper/manual flags — and NO auto-execution surface, ever ─────────────

def test_proposals_carry_all_paper_flags():
    for side in ("call", "put"):
        p = _gen(side)["proposals"][0]
        assert p["educational_paper_model"] is True
        assert p["paper_only"] is True
        assert p["requires_manual_review"] is True
        assert p["execution_mode"] == "manual_review_only"
        assert p["auto_eligible"] is False
        assert p["enterprise"]["live_eligible"] is False
        assert p["enterprise"]["paper_model"] is True
        assert p["enterprise"]["approval_required"] is True
        assert any("no live execution path" in b for b in p["enterprise"]["blocks"])
        assert p["broker"] == "paper_model"
        sj = p["meta"]["strategy_json"]
        assert sj["family"] == "directional_long_premium"
        assert sj["strategy_id"] == f"atm_{side}"
        assert p["meta"]["analysis"]["candidate"]["strike"] == p["strike"]
        dumped = json.dumps(p, default=str).lower()
        for forbidden in ("auto_execute", "submit_order", "place_order",
                          "order_id", "occ_symbol_to_submit"):
            assert forbidden not in dumped


def test_queue_writer_accepts_atm_rows_fail_closed_otherwise(monkeypatch):
    """Stage 2 reuses deep_itm_generator.submit_to_desk_queue — ATM rows must
    satisfy its fail-closed paper-flag wall (and be refused when stripped)."""
    from lib.options_pipeline import deep_itm_generator as gen
    import options_desk_enterprise as ode
    captured = {}
    monkeypatch.setattr(ode, "sync_approval_queue",
                        lambda rows, **kw: (captured.update(rows=rows)
                                            or {"ok": True, "upserted": len(rows)}))
    rows = _gen("call")["proposals"]
    assert gen.submit_to_desk_queue(rows)["ok"] is True
    assert captured["rows"][0]["strategy"] == "atm_call"
    stripped = dict(rows[0], paper_only=False)
    assert gen.submit_to_desk_queue([stripped])["ok"] is False


# ── (6) ranking ───────────────────────────────────────────────────────────────

def test_proposals_ranked_by_edge_score():
    snap = _snapshot([
        {"exp": "2026-08-07", "dte": 33, "contracts": [_contract(dte=33, liquidity_score=90)]},
        {"exp": "2026-08-21", "dte": 47, "contracts": [_contract(strike=101.0, dte=47, liquidity_score=40)]},
        {"exp": "2026-09-04", "dte": 61, "contracts": [_contract(strike=102.0, dte=61, liquidity_score=70)]},
    ])
    out = _gen("call", snapshot=snap)
    scores = [p["edge_score"] for p in out["proposals"]]
    assert len(scores) == 3
    assert scores == sorted(scores, reverse=True)


def test_iv_rich_context_applies_modifier_and_flag():
    rich = {"available": True, "iv_rank": 85.0, "verdict": "extrinsic_rich",
            "verdict_label": "extrinsic rich — pay-up warning"}
    p = _gen("call", iv_context=rich)["proposals"][0]
    assert p["meta"]["iv_edge"]["modifier"] == 0.90
    assert "iv_rich_pay_up_warning" in p["meta"]["gate_flags"]
    assert p["iv_rank"] == 85.0


# ── (7) forbidden imports — grep + AST over BOTH new modules ─────────────────

NEW_FILES = [
    ROOT / "scripts" / "lib" / "options_pipeline" / "atm_long_premium_generator.py",
    ROOT / "scripts" / "lib" / "options_pipeline" / "strategy_matcher.py",
]
FORBIDDEN_MODULES = {
    "options_order_pilot", "options_pilot_arm", "brokers", "approval_service",
    "schwab_transport", "schwab_pilot_orders", "alpaca_trade_api", "alpaca",
    "trade_executor", "order_executor", "telegram_2fa", "two_factor",
    "options_execution_policy",
}
FORBIDDEN_CALL_ATTRS = {"place_order", "submit_order", "cancel_order",
                        "submit", "place_option_order", "execute_order"}


def _imports_of(tree: ast.AST) -> set:
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.update({a.name, a.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.update({node.module, node.module.split(".")[0]})
    return mods


def test_no_forbidden_imports_in_new_modules():
    for path in NEW_FILES:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad = _imports_of(tree) & FORBIDDEN_MODULES
        assert not bad, f"{path.name} imports forbidden broker/submit modules: {bad}"
        # grep-level sweep: forbidden module names never appear in import lines
        for line in src.splitlines():
            ls = line.strip()
            if ls.startswith(("import ", "from ")):
                assert not any(m in ls for m in FORBIDDEN_MODULES), \
                    f"{path.name}: forbidden import line: {ls}"


def test_no_order_submit_calls_in_new_modules():
    for path in NEW_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        bad = called & FORBIDDEN_CALL_ATTRS
        assert not bad, f"{path.name} calls forbidden order methods: {bad}"
