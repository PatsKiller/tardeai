#!/usr/bin/env python3
"""Options pipeline Stage A — deep-ITM call paper strategy + winner scanner.

Covers: strategy YAML loads + registers through the standard loader (registry
entry path), generator config gates (delta / DTE / spread / OI / volume /
earnings / capital-vs-shares) on synthetic deep_itm_call_analysis fixtures,
paper/manual flags on every proposal (and the absence of ANY auto-execute
surface), queue-write shape parity with the existing options_approval_queue
writer, scanner dry-run writing nothing, underlying eligibility logic, and a
forbidden-imports sweep (no broker submit / order pilot / 2FA modules).

    .venv/bin/python -m pytest tests/test_options_pipeline_deep_itm.py -q
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import deep_itm_generator as gen  # noqa: E402
import options_strategy_scanner as scanner  # noqa: E402

SPOT = 200.0


# ── synthetic deep_itm_call_analysis fixtures ────────────────────────────────

def _candidate(strike=150.0, mid=55.0, *, delta=0.88, oi=500, volume=20,
               spread_pct=2.0, earnings_before=False, no_quote=False):
    intrinsic = max(SPOT - strike, 0.0)
    return {
        "strike": strike, "exp": "2026-10-16", "dte": 89,
        "bid": mid - 0.5, "ask": mid + 0.5, "mid": None if no_quote else mid,
        "delta": delta, "iv": 0.30, "volume": volume, "oi": oi,
        "spread_pct": None if no_quote else spread_pct,
        "liquidity_score": 70,
        "flags": {"wide_spread": (spread_pct or 99) > 10.0, "low_oi": oi < 100,
                  "no_volume": volume < 1, "no_quote": no_quote,
                  "earnings_before_expiry": earnings_before},
        "intrinsic_value": intrinsic,
        "extrinsic_value": None if no_quote else round(mid - intrinsic, 4),
        "breakeven": None if no_quote else round(strike + mid, 4),
        "breakeven_move_pct": None if no_quote else round(((strike + mid) / SPOT - 1) * 100, 2),
        "max_loss": None if no_quote else round(mid * 100, 2),
        "capital_required": None if no_quote else round(mid * 100, 2),
        "capital_vs_100_shares": None if no_quote else {
            "contract_debit": round(mid * 100, 2),
            "100_shares": round(SPOT * 100, 2),
            "capital_ratio_pct": round(mid * 100 / (SPOT * 100) * 100, 2),
        },
    }


def _bucket(target_dte=90, candidates=None, selection_mode="delta"):
    cands = candidates if candidates is not None else [_candidate()]
    return {"target_dte": target_dte, "exp": "2026-10-16", "dte": 89,
            "selection_mode": selection_mode, "available": True,
            "selected": cands[0] if cands else None, "candidates": cands}


def _analysis(sym="NVDA", buckets=None, *, feas_score=80, earnings=None):
    return {
        "strategy": "deep_itm_call", "symbol": sym, "available": True,
        "educational_only": True, "banner": "EDUCATIONAL_ONLY — test fixture",
        "source": "fixture", "generated_at": "2026-07-05T00:00:00+00:00",
        "underlying_price": SPOT, "delta_range": [0.80, 0.95],
        "selection_modes_used": ["delta"], "next_earnings_date": earnings,
        "dte_buckets": buckets if buckets is not None else [_bucket()],
        "chain_liquidity_score": 70,
        "feasibility": {"feasible": True, "score": feas_score,
                        "reason": "ITM calls with >=25 DTE: fixture"},
    }


def _underlying(sym="NVDA", conviction=0.85):
    return {"symbol": sym, "conviction": conviction,
            "conviction_source": "watchlist_strong_buy", "verdict": "strong_buy",
            "held_shares": None}


def _gen(underlyings=None, analysis=None, config=None):
    return gen.generate_deep_itm_proposals(
        underlyings or [_underlying()],
        config or gen.load_pipeline_config(),
        analysis_fn=lambda sym, **kw: (analysis or _analysis(sym)),
    )


# ── (1) strategy config loads + registry entry path ──────────────────────────

def test_config_loads_and_validates():
    from strategy_config_loader import load_strategy_config, validate_strategy_config
    cfg = load_strategy_config("deep_itm_call")
    assert validate_strategy_config(cfg) == []
    assert cfg["strategy_id"] == "deep_itm_call"
    assert cfg["status"] == "UNVALIDATED"          # lifecycle entry path
    assert cfg["family"] == "stock_replacement"
    assert cfg["paper_only"] is True
    assert cfg["execution_mode"] == "manual_review_only"
    assert cfg["execution"]["paper_allowed"] is True
    assert cfg["execution"]["live_allowed"] is False
    vg = cfg["validation_gate"]
    assert vg["min_closed_paper_trades"] == 30
    assert vg["min_profit_factor"] == 1.3
    assert vg["min_win_rate"] == 0.55
    assert vg["human_approval_required"] is True
    assert cfg["discovery_ref"]["candidate_id"] == 339


def test_config_selection_policy_matches_spec():
    cfg = gen.load_pipeline_config()
    pol = cfg["selection_policy"]
    assert pol["delta_range"] == [0.80, 0.95]
    assert pol["dte_buckets"] == [60, 90, 180]
    assert pol["max_capital_pct_vs_shares"] == 0.35
    # Operator-ratified 2026-07-05 (Stage B): stock-replacement holds through
    # earnings like shares — earnings becomes a disclosed card flag, not a reject.
    assert pol["allow_earnings_before_expiry"] is True
    assert pol["max_underlyings_per_run"] == 15
    assert pol["max_proposals_per_run"] == 5
    q = cfg["underlying_quality_gate"]
    assert set(q["watchlist_verdicts"]) == {"strong_buy", "buy"}
    assert q["include_current_holdings"] is True


def test_registry_entry_path_picks_up_strategy():
    """The standard sync path (load_all_strategy_configs → strategy_registry upsert)
    must see deep_itm_call like every other strategy YAML."""
    from strategy_config_loader import load_all_strategy_configs
    configs = load_all_strategy_configs()
    assert "deep_itm_call" in configs
    assert configs["deep_itm_call"]["_config_hash"]


# ── (2) generator gates on synthetic fixtures ────────────────────────────────

def test_happy_path_generates_proposal():
    out = _gen()
    assert out["count"] == 1
    p = out["proposals"][0]
    assert p["strategy"] == "deep_itm_call"
    assert p["symbol"] == "NVDA"
    assert p["side"] == "BUY" and p["option_type"] == "call"
    assert p["premium_total"] == 5500.0
    assert p["max_loss"] == 5500.0            # long premium: max loss = debit
    assert p["breakeven"] == 205.0
    # score = feasibility×conviction blend: (80+70)/2 × 0.85
    assert p["edge_score"] == round(75 * 0.85, 1)
    assert p["id"].startswith("opt_deep_itm_call_NVDA_")


def test_gate_delta_out_of_band_rejected():
    a = _analysis(buckets=[_bucket(candidates=[_candidate(delta=0.75)])])
    out = _gen(analysis=a)
    assert out["count"] == 0
    assert "delta_0.75" in json.dumps(out["per_underlying"])


def test_gate_dte_bucket_not_configured_rejected():
    a = _analysis(buckets=[_bucket(target_dte=30)])   # 30 not in [60, 90, 180]
    out = _gen(analysis=a)
    assert out["count"] == 0


def test_gate_wide_spread_rejected():
    a = _analysis(buckets=[_bucket(candidates=[_candidate(spread_pct=14.0)])])
    assert _gen(analysis=a)["count"] == 0


def test_gate_low_oi_and_volume_rejected():
    a = _analysis(buckets=[_bucket(candidates=[_candidate(oi=40)])])
    assert _gen(analysis=a)["count"] == 0
    a = _analysis(buckets=[_bucket(candidates=[_candidate(volume=0)])])
    assert _gen(analysis=a)["count"] == 0


def test_gate_earnings_before_expiry_rejected_unless_flagged():
    a = _analysis(buckets=[_bucket(candidates=[_candidate(earnings_before=True)])],
                  earnings="2026-09-01")
    # Strict mode (allow flag off) still rejects — the gate machinery is intact.
    strict = gen.load_pipeline_config()
    strict["selection_policy"]["allow_earnings_before_expiry"] = False
    strict["selection_policy"]["earnings_flag_override"] = False
    assert _gen(analysis=a, config=strict)["count"] == 0
    # Ratified config default (operator 2026-07-05): earnings passes as a
    # disclosed flag — stock replacement holds through earnings like shares.
    out = _gen(analysis=a)
    assert out["count"] == 1
    assert "earnings_before_expiry_operator_flagged" in out["proposals"][0]["meta"]["gate_flags"]


def test_gate_earnings_unknown_is_flag_not_reject():
    a = _analysis(buckets=[_bucket(candidates=[_candidate(earnings_before=None)])])
    out = _gen(analysis=a)
    assert out["count"] == 1
    assert "earnings_unknown" in out["proposals"][0]["meta"]["gate_flags"]


def test_gate_capital_ratio_rejected():
    # debit 75×100 = 37.5% of 100-share capital > 35% cap
    a = _analysis(buckets=[_bucket(candidates=[_candidate(strike=150.0, mid=75.0)])])
    assert _gen(analysis=a)["count"] == 0


def test_gate_no_quote_rejected():
    a = _analysis(buckets=[_bucket(candidates=[_candidate(no_quote=True)])])
    assert _gen(analysis=a)["count"] == 0


def test_delta_proxy_mode_allowed_but_flagged():
    a = _analysis(buckets=[_bucket(candidates=[_candidate(delta=None)],
                                   selection_mode="itm_pct_proxy")])
    out = _gen(analysis=a)
    assert out["count"] == 1
    p = out["proposals"][0]
    assert "delta_proxy_itm_depth" in p["meta"]["gate_flags"]
    assert p["pop_pct"] is None               # never fabricated from a missing delta


def test_conviction_floor_skips_weak_underlyings():
    out = _gen(underlyings=[_underlying(conviction=0.40)])
    assert out["count"] == 0
    assert out["per_underlying"][0]["status"] == "skipped"


def test_degraded_chain_reports_honestly():
    out = gen.generate_deep_itm_proposals(
        [_underlying()], gen.load_pipeline_config(),
        analysis_fn=lambda sym, **kw: {"available": False,
                                       "reason": "weekend — no chain"})
    assert out["count"] == 0
    pu = out["per_underlying"][0]
    assert pu["status"] == "degraded" and "weekend" in pu["reason"]


def test_first_passing_candidate_per_bucket_only():
    a = _analysis(buckets=[_bucket(candidates=[_candidate(strike=140.0),
                                               _candidate(strike=160.0)])])
    out = _gen(analysis=a)
    assert out["count"] == 1
    assert out["proposals"][0]["strike"] == 140.0


# ── (3) paper/manual flags — and NO auto-execution surface, ever ─────────────

def test_proposals_carry_paper_manual_flags_and_discovery_ref():
    p = _gen()["proposals"][0]
    assert p["educational_paper_model"] is True
    assert p["requires_manual_review"] is True
    assert p["paper_only"] is True
    assert p["execution_mode"] == "manual_review_only"
    assert p["auto_eligible"] is False
    assert p["enterprise"]["live_eligible"] is False
    assert p["enterprise"]["paper_model"] is True
    assert p["enterprise"]["approval_required"] is True
    assert any("no live execution path" in b for b in p["enterprise"]["blocks"])
    ref = p["meta"]["discovery_ref"]
    assert ref["candidate_id"] == 339
    assert ref["source"] == "hermes_discovery_candidates"
    assert ref["candidate_status"] == "APPROVED_RESEARCH_ONLY"
    assert p["meta"]["analysis"]["candidate"]["strike"] == p["strike"]


def test_proposals_never_carry_auto_execute_fields():
    p = _gen()["proposals"][0]
    dumped = json.dumps(p).lower()
    for forbidden in ("auto_execute", "submit_order", "place_order",
                      "order_id", "occ_symbol_to_submit"):
        assert forbidden not in dumped
    assert p.get("auto_eligible") is False
    assert p.get("execution_mode") != "auto"
    assert p.get("broker") == "paper_model"    # never a live broker routing key


# ── (4) queue-write shape matches the existing options desk queue ────────────

def test_queue_write_uses_desk_sync_and_shape(monkeypatch):
    captured = {}
    import options_desk_enterprise as ode

    def fake_sync(rows, **kw):
        captured["rows"] = rows
        return {"ok": True, "upserted": len(rows)}

    monkeypatch.setattr(ode, "sync_approval_queue", fake_sync)
    props = _gen()["proposals"]
    res = gen.submit_to_desk_queue(props)
    assert res == {"ok": True, "upserted": 1}
    row = captured["rows"][0]
    # exactly the fields options_desk_enterprise.sync_approval_queue reads for
    # its INSERT INTO options_approval_queue (proposal_id, symbol, strategy,
    # desk_tier, edge_score, status←enterprise_blocked, live_eligible,
    # blocks_json, proposal_json)
    for key in ("id", "symbol", "strategy", "desk_tier", "edge_score", "enterprise"):
        assert key in row, f"queue row missing {key}"
    assert row["enterprise"]["live_eligible"] is False
    assert row.get("enterprise_blocked") is not True   # stays in 'pending' review lane
    json.dumps(row, default=str)                       # proposal_json serializable


def test_queue_write_fails_closed_without_paper_flags(monkeypatch):
    import options_desk_enterprise as ode
    monkeypatch.setattr(ode, "sync_approval_queue",
                        lambda rows, **kw: pytest.fail("queue write must not happen"))
    p = _gen()["proposals"][0]

    stripped = dict(p, educational_paper_model=False)
    assert gen.submit_to_desk_queue([stripped])["ok"] is False

    live = dict(p, enterprise=dict(p["enterprise"], live_eligible=True))
    assert gen.submit_to_desk_queue([live])["ok"] is False

    auto = dict(p, auto_eligible=True)
    assert gen.submit_to_desk_queue([auto])["ok"] is False


# ── (5) scanner: dry-run writes nothing; run queues top-N winners ────────────

def _many_underlyings(n=8):
    return [_underlying(f"SY{i}", conviction=0.60 + i * 0.04) for i in range(n)]


def test_scanner_dry_run_writes_nothing():
    res = scanner.run_scan(
        dry_run=True,
        underlyings=[_underlying()],
        analysis_fn=lambda sym, **kw: _analysis(sym),
        queue_writer=lambda rows: pytest.fail("dry-run must never write"),
    )
    assert res["ok"] is True and res["dry_run"] is True
    assert res["queue_result"]["skipped"] is True
    assert res["candidates_passed_gates"] == 1
    assert res["winner_summary"][0]["discovery_ref"] == 339
    assert "options_approval_queue" in res["queue_target"]


def test_scanner_run_queues_top_five_only():
    written = {}

    def writer(rows):
        written["rows"] = rows
        return {"ok": True, "upserted": len(rows)}

    res = scanner.run_scan(
        dry_run=False,
        underlyings=_many_underlyings(8),
        analysis_fn=lambda sym, **kw: _analysis(sym),
        queue_writer=writer,
    )
    assert res["ok"] is True
    assert len(written["rows"]) == 5          # max_proposals_per_run cap
    scores = [r["edge_score"] for r in written["rows"]]
    assert scores == sorted(scores, reverse=True)   # winners ranked
    assert all(r["educational_paper_model"] for r in written["rows"])


def test_scanner_default_is_dry_run_and_rejects_unknown_strategy(capsys):
    assert scanner.run_scan(strategy="covered_call")["ok"] is False
    rc = scanner.main(["--dry-run", "--strategy", "nope"])
    assert rc != 0


def test_scanner_refuses_config_without_paper_guarantees(monkeypatch):
    bad = gen.load_pipeline_config()
    bad["execution_mode"] = "auto"
    monkeypatch.setattr(scanner, "load_pipeline_config", lambda: bad)
    res = scanner.run_scan(dry_run=False, underlyings=[_underlying()],
                           analysis_fn=lambda sym, **kw: _analysis(sym),
                           queue_writer=lambda rows: pytest.fail("must not write"))
    assert res["ok"] is False and "integrity" in res["error"]


def test_scanner_refuses_paused_or_killed_strategy(monkeypatch):
    paused = gen.load_pipeline_config()
    paused["status"] = "PAUSED"
    monkeypatch.setattr(scanner, "load_pipeline_config", lambda: paused)
    res = scanner.run_scan(dry_run=True, underlyings=[_underlying()],
                           analysis_fn=lambda sym, **kw: _analysis(sym))
    assert res["ok"] is False and "PAUSED" in res["error"]


def test_scanner_market_closed_note_present_when_closed(monkeypatch):
    import market_session
    monkeypatch.setattr(market_session, "current_market_session", lambda now=None: "weekend")
    res = scanner.run_scan(dry_run=True, underlyings=[_underlying()],
                           analysis_fn=lambda sym, **kw: {"available": False,
                                                          "reason": "weekend — no chain"})
    assert res["market_session"]["session"] == "weekend"
    assert "stale" in res["market_session"]["note"]
    assert res["per_underlying"][0]["status"] == "degraded"


# ── (6) underlying eligibility logic ─────────────────────────────────────────

def test_eligibility_holdings_plus_buy_watchlist():
    rows = [
        {"symbol": "NVDA", "card_rec": "STRONG BUY", "synth_rec": None},
        {"symbol": "PLTR", "card_rec": None, "synth_rec": "buy"},
        {"symbol": "XYZ", "card_rec": "hold", "synth_rec": None},
        {"symbol": "AVGO", "card_rec": "strong_buy", "synth_rec": None},
    ]
    held = {"NVDA": 120.0, "V": 300.0}
    out = scanner.resolve_eligible_underlyings(limit=15, holdings=held, watchlist_rows=rows)
    by_sym = {u["symbol"]: u for u in out}
    assert "XYZ" not in by_sym                        # hold never eligible
    assert by_sym["NVDA"]["conviction"] == 0.90       # strong_buy + held
    assert by_sym["NVDA"]["conviction_source"] == "watchlist_strong_buy+held"
    assert by_sym["AVGO"]["conviction"] == 0.85       # strong_buy
    assert by_sym["PLTR"]["conviction"] == 0.70       # buy
    assert by_sym["V"]["conviction"] == 0.60          # held only
    assert by_sym["V"]["conviction_source"] == "current_holding"
    convictions = [u["conviction"] for u in out]
    assert convictions == sorted(convictions, reverse=True)


def test_eligibility_dedupe_and_cap():
    rows = [{"symbol": f"S{i}", "card_rec": "buy", "synth_rec": None} for i in range(30)]
    rows.append({"symbol": "S0", "card_rec": "buy", "synth_rec": None})  # dupe
    out = scanner.resolve_eligible_underlyings(limit=15, holdings={}, watchlist_rows=rows)
    assert len(out) == 15
    assert len({u["symbol"] for u in out}) == 15


def test_eligibility_conviction_floor():
    out = scanner.resolve_eligible_underlyings(
        limit=15, holdings={"V": 100.0}, watchlist_rows=[], conviction_floor=0.65)
    assert out == []                                   # held-only 0.60 < 0.65 floor


# ── (7) forbidden imports — no broker submit / order / 2FA surface ───────────

NEW_FILES = [
    ROOT / "scripts" / "lib" / "options_pipeline" / "__init__.py",
    ROOT / "scripts" / "lib" / "options_pipeline" / "deep_itm_generator.py",
    ROOT / "scripts" / "options_strategy_scanner.py",
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
                mods.add(a.name)
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            mods.add(node.module.split(".")[0])
    return mods


def test_no_forbidden_imports_in_new_code():
    for path in NEW_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = _imports_of(tree) & FORBIDDEN_MODULES
        assert not bad, f"{path.name} imports forbidden broker/submit modules: {bad}"


def test_no_order_submit_calls_in_new_code():
    for path in NEW_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        bad = called & FORBIDDEN_CALL_ATTRS
        assert not bad, f"{path.name} calls forbidden order methods: {bad}"


def test_generator_only_touches_desk_sync_on_enterprise_module():
    """The only options_desk_enterprise surface the pipeline touches is the
    review-queue writer + tiering — never approval resolution or preflight."""
    src = (ROOT / "scripts" / "lib" / "options_pipeline" / "deep_itm_generator.py"
           ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    touched = {node.attr for node in ast.walk(tree)
               if isinstance(node, ast.Attribute)
               and isinstance(node.value, ast.Name)
               and node.value.id in ("ent", "ent_mod")}
    assert touched <= {"desk_tier", "sync_approval_queue"}
