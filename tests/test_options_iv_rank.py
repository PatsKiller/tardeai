#!/usr/bin/env python3
"""IV-rank context layer (2026-07-06) — snapshot history + honest rank + bounded modifier.

Covers: ATM-IV extraction from a parsed chain snapshot (30-60 DTE near-the-money
average, defensive on missing/NaN greeks, IV unit normalization), snapshot upsert
idempotency (one row per symbol per day, ON CONFLICT), rank/percentile math on
synthetic history, the insufficient-history honesty contract (<20 days NEVER
fabricates a rank), cheap/normal/rich verdict bands, the bounded edge-score
modifier (×1.1 / ×0.9 / ×1.0 — informs ranking, NEVER a gate), iv_context in
deep_itm_call_analysis output, and a forbidden-imports sweep (no broker submit /
order / 2FA / direct schwab_transport surface in the new code).

    .venv/bin/python -m pytest tests/test_options_iv_rank.py -q
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.strategy_research import iv_history as ivh  # noqa: E402
from lib.strategy_research import options_chain as oc  # noqa: E402
from lib.options_pipeline import deep_itm_generator as gen  # noqa: E402

SPOT = 200.0


# ── synthetic chain snapshot (options desk normalize_option_chain shape) ─────

def _row(side, strike, bid, ask, *, iv=0.35, delta=0.6, oi=500, vol=50, dte=45):
    return {"exp": "x", "strike": strike, "side": side, "bid": bid, "ask": ask,
            "last": (bid + ask) / 2, "iv": iv, "delta": delta, "oi": oi,
            "volume": vol, "dte": dte}


def _raw_chain(*, iv=0.35, dte=45, include_far=True):
    strikes = [
        _row("call", 190.0, 14.0, 14.6, iv=iv, dte=dte),
        _row("call", 200.0, 8.0, 8.4, iv=iv, dte=dte),
        _row("put", 200.0, 7.6, 8.0, iv=iv, dte=dte),
        _row("call", 210.0, 4.0, 4.4, iv=iv, dte=dte),
        _row("call", 150.0, 51.0, 52.0, iv=(iv + 0.30 if iv else iv), dte=dte),  # far ITM, outside ±5%
    ]
    exps = [{"exp": "2026-08-21", "dte": dte, "contracts": len(strikes),
             "total_call_oi": 3000, "total_put_oi": 1000, "strikes": strikes}]
    if include_far:
        exps.append({"exp": "2027-07-16", "dte": 375, "contracts": 1,
                     "total_call_oi": 100, "total_put_oi": 0,
                     "strikes": [_row("call", 200.0, 30.0, 32.0, iv=0.90, dte=375)]})
    return {"status": "ok", "symbol": "TEAM", "underlying_price": SPOT,
            "expirations": exps}


def _snapshot(**kw):
    return oc.parse_chain(_raw_chain(**kw), "TEAM")


# ── ATM-IV extraction ────────────────────────────────────────────────────────

def test_extract_atm_iv_uses_near_the_money_30_60_dte():
    atm = ivh.extract_atm_iv(_snapshot())
    assert atm is not None
    # ±5% band at spot 200 = strikes 190-210 (call190, call200, put200, call210),
    # all iv 0.35 → 35.0%; the far-ITM 150 strike and the 375-DTE LEAPS are excluded.
    assert atm["atm_iv"] == 35.0
    assert atm["contracts_used"] == 4
    assert atm["atm_strike"] == 200.0
    assert atm["method"] == "dte_window"
    assert atm["dtes_used"] == [45]


def test_extract_atm_iv_normalizes_percent_style_iv():
    # Schwab sometimes carries IV as 35.0 instead of 0.35 — same result either way.
    assert ivh.extract_atm_iv(_snapshot(iv=35.0))["atm_iv"] == 35.0


def test_extract_atm_iv_defensive_on_missing_greeks():
    assert ivh.extract_atm_iv(_snapshot(iv=None, include_far=False)) is None
    assert ivh.extract_atm_iv(_snapshot(iv=0.0, include_far=False)) is None
    assert ivh.extract_atm_iv(None) is None
    assert ivh.extract_atm_iv({"available": False, "reason": "weekend"}) is None


def test_extract_atm_iv_falls_back_to_nearest_expiration():
    atm = ivh.extract_atm_iv(_snapshot(dte=150))  # nothing in 25-70 DTE
    assert atm is not None
    assert atm["method"].startswith("nearest_expiration_fallback")


# ── rank math + verdict bands ────────────────────────────────────────────────

def test_rank_math_on_synthetic_history():
    history = [20.0 + i for i in range(21)]  # 21 days, 20..40
    out = ivh.iv_rank("TEAM", current_iv=25.0, history=history)
    assert out["available"] is True
    assert out["iv_rank"] == 25.0            # (25-20)/(40-20)
    assert out["percentile"] == round(6 / 21 * 100, 1)  # 20..25 → 6 of 21 days
    assert out["iv_low"] == 20.0 and out["iv_high"] == 40.0
    assert out["days"] == 21
    assert out["verdict"] == "extrinsic_cheap"


def test_rank_includes_current_in_range_so_never_out_of_bounds():
    history = [30.0] * 19 + [40.0]
    hot = ivh.iv_rank("TEAM", current_iv=99.0, history=history)
    cold = ivh.iv_rank("TEAM", current_iv=1.0, history=history)
    assert hot["iv_rank"] == 100.0 and hot["verdict"] == "extrinsic_rich"
    assert cold["iv_rank"] == 0.0 and cold["verdict"] == "extrinsic_cheap"


def test_insufficient_history_is_honest_never_fabricated():
    out = ivh.iv_rank("TEAM", current_iv=35.0, history=[30.0] * 19)
    assert out["available"] is False
    assert out["reason"] == "insufficient history"
    assert out["days"] == 19 and out["required_days"] == 20
    assert "iv_rank" not in out and "percentile" not in out and "verdict" not in out
    # zero-range series is likewise refused, not ranked
    flat = ivh.iv_rank("TEAM", current_iv=30.0, history=[30.0] * 25)
    assert flat["available"] is False
    assert "degenerate" in flat["reason"]


def test_verdict_bands():
    assert ivh.verdict_for_rank(0)[0] == "extrinsic_cheap"
    assert ivh.verdict_for_rank(29.9) == ("extrinsic_cheap", "extrinsic cheap")
    assert ivh.verdict_for_rank(30.0)[0] == "normal"
    assert ivh.verdict_for_rank(70.0)[0] == "normal"
    assert ivh.verdict_for_rank(70.1)[0] == "extrinsic_rich"
    assert "pay-up" in ivh.verdict_for_rank(100)[1]


# ── snapshot upsert idempotency ──────────────────────────────────────────────

class _FakeDB:
    """Applies the upsert's (symbol, snapshot_date) semantics to a dict store."""

    def __init__(self):
        self.store = {}
        self.calls = []

    def __call__(self, sql, params):
        self.calls.append((sql, params))
        assert sql.count("INSERT") == 1 and ";" not in sql  # one statement
        assert "ON CONFLICT (symbol, snapshot_date) DO UPDATE" in sql
        self.store[(params[0], params[1])] = params
        return True


def test_snapshot_upsert_is_idempotent_per_day():
    db = _FakeDB()
    kw = dict(snapshot_date="2026-07-06",
              fetch_fn=lambda sym, **k: _snapshot(), execute_fn=db)
    r1 = ivh.snapshot_iv(["TEAM", "NVDA"], **kw)
    r2 = ivh.snapshot_iv(["TEAM", "NVDA"], **kw)  # re-run same day
    assert r1["rows_written"] == 2 and r2["rows_written"] == 2
    assert len(db.store) == 2                     # replaced, never duplicated
    assert set(db.store) == {("TEAM", "2026-07-06"), ("NVDA", "2026-07-06")}
    sym, day, iv_pct, strike, spot, source, meta = db.store[("TEAM", "2026-07-06")]
    assert iv_pct == 35.0 and strike == 200.0 and spot == SPOT
    assert source == ivh.IV_SOURCE
    assert json.loads(meta)["contracts_used"] == 4


def test_snapshot_skips_unavailable_chains_honestly():
    db = _FakeDB()
    r = ivh.snapshot_iv(
        ["TEAM"],
        fetch_fn=lambda sym, **k: {"available": False, "reason": "weekend — no chain"},
        execute_fn=db)
    assert r["rows_written"] == 0 and not db.store
    assert r["skipped"][0]["reason"] == "weekend — no chain"


def test_snapshot_dry_run_writes_nothing():
    db = _FakeDB()
    r = ivh.snapshot_iv(["TEAM"], dry_run=True,
                        fetch_fn=lambda sym, **k: _snapshot(), execute_fn=db)
    assert r["dry_run"] is True and r["rows_written"] == 0
    assert len(r["captured"]) == 1 and not db.calls


# ── analysis output shape (iv_context wired in) ──────────────────────────────

def _ctx(rank, verdict, label):
    return {"available": True, "atm_iv": 35.0, "iv_rank": rank, "percentile": rank,
            "days": 30, "required_days": 20, "verdict": verdict, "verdict_label": label}


CHEAP = _ctx(23.0, "extrinsic_cheap", "extrinsic cheap")
RICH = _ctx(84.0, "extrinsic_rich", "extrinsic rich — pay-up warning")
BUILDING = {"available": False, "reason": "insufficient history",
            "days": 7, "required_days": 20}


def test_deep_itm_analysis_carries_iv_context():
    out = oc.deep_itm_call_analysis("TEAM", snapshot=_snapshot(),
                                    dte_buckets=[45], iv_context=CHEAP)
    assert out["available"] is True
    assert out["iv_context"] == CHEAP


def test_deep_itm_analysis_iv_context_degrades_honestly(monkeypatch):
    monkeypatch.setattr(ivh, "iv_rank",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    out = oc.deep_itm_call_analysis("TEAM", snapshot=_snapshot(), dte_buckets=[45])
    assert out["iv_context"]["available"] is False
    assert "iv context error" in out["iv_context"]["reason"]


# ── edge modifier: bounded, advisory, never a gate ───────────────────────────

def test_edge_modifier_values_and_bounds():
    assert gen.apply_iv_edge_modifier(80.0, CHEAP) == (88.0, 1.1)
    assert gen.apply_iv_edge_modifier(80.0, RICH) == (72.0, 0.9)
    assert gen.apply_iv_edge_modifier(80.0, BUILDING) == (80.0, 1.0)
    assert gen.apply_iv_edge_modifier(80.0, None) == (80.0, 1.0)
    assert gen.apply_iv_edge_modifier(80.0, {"available": True, "verdict": "normal"}) == (80.0, 1.0)
    assert gen.apply_iv_edge_modifier(95.0, CHEAP) == (100.0, 1.1)   # capped
    assert gen.apply_iv_edge_modifier(0.0, RICH) == (0.0, 0.9)       # floored
    # a fabricated verdict on an unavailable context must NOT modify
    assert gen.apply_iv_edge_modifier(
        80.0, {"available": False, "verdict": "extrinsic_cheap"}) == (80.0, 1.0)


def _deep_itm_fixture(iv_context, sym="NVDA"):
    """Minimal deep_itm_call_analysis fixture (Stage A shape) + iv_context."""
    mid, strike = 55.0, 150.0
    cand = {
        "strike": strike, "exp": "2026-10-16", "dte": 89, "bid": mid - 0.5,
        "ask": mid + 0.5, "mid": mid, "delta": 0.88, "iv": 0.30, "volume": 20,
        "oi": 500, "spread_pct": 2.0, "liquidity_score": 70,
        "flags": {"wide_spread": False, "low_oi": False, "no_volume": False,
                  "no_quote": False, "earnings_before_expiry": False},
        "intrinsic_value": SPOT - strike, "extrinsic_value": round(mid - (SPOT - strike), 4),
        "breakeven": strike + mid, "breakeven_move_pct": round(((strike + mid) / SPOT - 1) * 100, 2),
        "max_loss": mid * 100, "capital_required": mid * 100,
        "capital_vs_100_shares": {"contract_debit": mid * 100, "100_shares": SPOT * 100,
                                  "capital_ratio_pct": round(mid / SPOT * 100, 2)},
    }
    return {
        "strategy": "deep_itm_call", "symbol": sym, "available": True,
        "educational_only": True, "banner": "EDUCATIONAL_ONLY — test fixture",
        "source": "fixture", "generated_at": "2026-07-06T00:00:00+00:00",
        "underlying_price": SPOT, "delta_range": [0.80, 0.95],
        "selection_modes_used": ["delta"], "next_earnings_date": None,
        "iv_context": iv_context,
        "dte_buckets": [{"target_dte": 90, "exp": "2026-10-16", "dte": 89,
                         "selection_mode": "delta", "available": True,
                         "selected": cand, "candidates": [cand]}],
        "chain_liquidity_score": 70,
        "feasibility": {"feasible": True, "score": 80, "reason": "fixture"},
    }


def _generate(iv_context):
    a = _deep_itm_fixture(iv_context)
    return gen.generate_deep_itm_proposals(
        [{"symbol": "NVDA", "conviction": 0.85,
          "conviction_source": "watchlist_strong_buy", "verdict": "strong_buy",
          "held_shares": None}],
        gen.load_pipeline_config(),
        analysis_fn=lambda sym, **kw: a)


def test_rich_iv_discloses_pay_up_warning_but_never_rejects():
    out = _generate(RICH)
    assert out["count"] == 1, "IV rich must inform, never gate"
    row = out["proposals"][0]
    assert gen.IV_RICH_FLAG in row["meta"]["gate_flags"]
    assert row["iv_context"] == RICH
    assert row["iv_rank"] == 84.0
    assert row["meta"]["iv_edge"]["modifier"] == 0.9
    assert row["edge_score"] == round(min(100.0, row["meta"]["iv_edge"]["base_edge"] * 0.9), 1)
    assert row["meta"]["analysis"]["iv_context"] == RICH
    # paper/manual safety flags untouched by the IV layer
    assert row["paper_only"] and row["requires_manual_review"]
    assert row["enterprise"]["live_eligible"] is False


def test_cheap_iv_boosts_edge_without_warning_flag():
    out = _generate(CHEAP)
    row = out["proposals"][0]
    assert gen.IV_RICH_FLAG not in row["meta"]["gate_flags"]
    assert row["meta"]["iv_edge"]["modifier"] == 1.1
    assert 0.0 <= row["edge_score"] <= 100.0
    assert "IV rank 23% — extrinsic cheap" in row["reasoning"]


def test_unavailable_iv_context_leaves_edge_untouched():
    out = _generate(BUILDING)
    row = out["proposals"][0]
    assert row["iv_rank"] is None
    assert row["iv_context"]["reason"] == "insufficient history"
    assert row["meta"]["iv_edge"]["modifier"] == 1.0
    assert row["edge_score"] == row["meta"]["iv_edge"]["base_edge"]
    assert gen.IV_RICH_FLAG not in row["meta"]["gate_flags"]


def test_scanner_winner_summary_includes_iv_context():
    import options_strategy_scanner as scanner
    a = _deep_itm_fixture(CHEAP)
    res = scanner.run_scan(
        dry_run=True,
        underlyings=[{"symbol": "NVDA", "conviction": 0.85,
                      "conviction_source": "watchlist_strong_buy",
                      "verdict": "strong_buy", "held_shares": None}],
        analysis_fn=lambda sym, **kw: a)
    assert res["ok"] is True
    assert res["winner_summary"][0]["iv_context"] == CHEAP


# ── forbidden imports — no broker/submit/2FA/direct-transport surface ────────

NEW_FILES = [
    ROOT / "scripts" / "lib" / "strategy_research" / "iv_history.py",
    ROOT / "scripts" / "options_iv_snapshot.py",
]
# schwab_transport is forbidden here too: chain reads must flow through the
# AST-proven read-only adapter (options_chain.fetch_chain_snapshot).
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


def test_no_forbidden_imports_in_iv_code():
    for path in NEW_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = _imports_of(tree) & FORBIDDEN_MODULES
        assert not bad, f"{path.name} imports forbidden broker/submit modules: {bad}"


def test_no_order_submit_calls_in_iv_code():
    for path in NEW_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        bad = called & FORBIDDEN_CALL_ATTRS
        assert not bad, f"{path.name} calls forbidden order methods: {bad}"


def test_iv_history_write_surface_is_single_upsert_to_own_table():
    import re
    assert ivh.UPSERT_SQL.startswith("INSERT INTO options_iv_history")
    assert "ON CONFLICT (symbol, snapshot_date) DO UPDATE" in ivh.UPSERT_SQL
    src = (ROOT / "scripts" / "lib" / "strategy_research" / "iv_history.py"
           ).read_text(encoding="utf-8")
    written = set(re.findall(
        r"(?:INSERT INTO|DELETE FROM|TRUNCATE|DROP TABLE)\s+([A-Za-z_]+)", src))
    assert written == {"options_iv_history"}, \
        f"iv_history must only write options_iv_history, found: {written}"
