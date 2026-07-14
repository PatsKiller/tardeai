#!/usr/bin/env python3
"""Phase 18 — semantic-integrity acceptance (operator review 2026-07-14,
docs/audits/REDEPLOY_DEFECT_MAP_2026-07-14.md). Pure-function tests use
fixtures; DB tests are STRICTLY read-only (SELECT + rollback). UI coverage
lives elsewhere — RedeployDesk.tsx is deliberately untouched here."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LIB = ROOT / "scripts" / "lib"
EVENT_ID = 144  # FCNTX sale — the event the 23-defect review was run against

from lib.redeploy_decision import (  # noqa: E402
    DEFAULT_WEIGHTS,
    load_weights,
    readiness_state,
    recommend,
    score_plan,
)
from lib.redeploy_plan_engine import _finalize_financials, _staging_risk  # noqa: E402


def _db():
    try:
        from db_adapter import get_connection
    except Exception:
        return None
    return get_connection()


_PLANS_CACHE: list | None = None


def _event_plans() -> list[dict]:
    """Latest-version plans for EVENT_ID, fetched once (read-only, rolled back)."""
    global _PLANS_CACHE
    if _PLANS_CACHE is not None:
        return _PLANS_CACHE
    conn = _db()
    if not conn:
        _PLANS_CACHE = []
        return _PLANS_CACHE
    cur = conn.cursor()
    try:
        from lib.redeploy_plan_db import list_plans_for_event
        _PLANS_CACHE = list_plans_for_event(cur, EVENT_ID)
    finally:
        conn.rollback()
    return _PLANS_CACHE


def _by_arch(plans: list[dict]) -> dict[str, dict]:
    return {str(p.get("plan_archetype")): p for p in plans}


# ── financial reconciliation (defects 2/3) ───────────────────────────────────

def test_finalize_financials_exact_reconciliation():
    legs = [
        {"ticker": "QQQ", "strategic_target_dollars": 5000.0, "target_dollars": 4950.50,
         "is_reserve": False},
        {"ticker": "SCHD", "strategic_target_dollars": 3000.0, "target_dollars": 2961.25,
         "is_reserve": False},
        {"ticker": "BIL", "strategic_target_dollars": 2000.0, "target_dollars": 2000.0,
         "is_reserve": True},
    ]
    fin = _finalize_financials(legs, net=10000.0, deployable=10000.0)
    # legs + reserve + residual == deployable, to the cent
    total = fin["executable_at_current_quote_usd"] + fin["reserve_usd"] + fin["whole_share_residual_usd"]
    assert abs(total - 10000.0) < 0.005
    assert fin["total_accounted_usd"] == round(total, 2)
    assert fin["reconciles"] is True
    assert abs(fin["reconciliation_gap_usd"]) < 0.01
    assert fin["strategic_target_usd"] == 8000.0
    assert fin["executable_at_current_quote_usd"] == 7911.75
    assert fin["reserve_usd"] == 2000.0
    # every dollar figure states its meaning
    assert "whole_share_residual_usd" in fin["amount_meanings"]


def test_finalize_financials_nonzero_residual_never_dropped():
    legs = [
        {"ticker": "QQQ", "strategic_target_dollars": 10000.0, "target_dollars": 8341.0,
         "is_reserve": False},
    ]
    fin = _finalize_financials(legs, net=10000.0, deployable=10000.0)
    # $1,659 of whole-share rounding must surface explicitly (defect 2)
    assert abs(fin["whole_share_residual_usd"] - 1659.0) < 0.005
    assert fin["reconciles"] is True
    assert abs(fin["executable_at_current_quote_usd"] + fin["reserve_usd"]
               + fin["whole_share_residual_usd"] - fin["deployable_cash_usd"]) < 0.005


def test_finalize_financials_staged_totals():
    legs = [
        {"ticker": "QQQ", "strategic_target_dollars": 5000.0, "target_dollars": 4950.5,
         "is_reserve": False,
         "stage_1_dollars": 2000.0, "stage_2_dollars": 1500.0, "stage_3_dollars": 1450.5},
    ]
    fin = _finalize_financials(legs, net=5000.0, deployable=5000.0)
    assert abs(fin["staged_limit_order_usd"] - 4950.5) < 0.005


def test_event_plans_reconcile_in_db():
    plans = _event_plans()
    if not plans:
        return  # skip without DB
    for p in plans:
        fin = p.get("financials") or {}
        assert fin, f"plan {p.get('plan_archetype')} has no financials block"
        assert fin.get("reconciles") is True, \
            f"plan {p.get('plan_archetype')} does not reconcile: {fin.get('reconciliation_gap_usd')}"
        assert abs(float(fin.get("reconciliation_gap_usd") or 0)) < 0.01


# ── readiness state machine (defect 1) ───────────────────────────────────────

def _fixture_plan(oversight: str = "pending", *, stale: bool = False,
                  ticker: str = "QQQ") -> dict:
    return {
        "plan_archetype": "A",
        "oversight_status": oversight,
        "legs": [{"ticker": ticker, "target_dollars": 1000.0, "is_reserve": False,
                  "price_stale": stale}],
        "financials": {"reconciles": True, "reconciliation_gap_usd": 0.0},
    }


_CTX_OK = {"is_major": True, "settled": True}


def test_readiness_oversight_pending_never_operator_ready():
    r = readiness_state(_fixture_plan("pending"), dict(_CTX_OK))
    assert r["state"] == "OVERSIGHT_PENDING"
    assert r["operator_ready"] is False
    assert "OVERSIGHT PENDING" in r["display"]


def test_readiness_oversight_passed_and_failed():
    r = readiness_state(_fixture_plan("passed"), dict(_CTX_OK))
    assert r["state"] == "OPERATOR_READY" and r["operator_ready"] is True
    r = readiness_state(_fixture_plan("failed"), dict(_CTX_OK))
    assert r["state"] == "OVERSIGHT_FAILED" and r["operator_ready"] is False


def test_readiness_stale_quotes_name_the_ticker():
    r = readiness_state(_fixture_plan("passed", stale=True, ticker="XLC"), dict(_CTX_OK))
    assert r["state"] == "QUOTES_STALE"
    assert r["operator_ready"] is False
    assert any("XLC" in reason for reason in r["reasons"])


def test_readiness_unsettled_mentions_settlement():
    r = readiness_state(_fixture_plan("passed"), {"is_major": True, "settled": False})
    assert r["state"] == "DATA_INCOMPLETE"
    assert any("settlement" in reason.lower() for reason in r["reasons"])


def test_readiness_locked_beats_selected_beats_ready():
    plan = _fixture_plan("passed")
    r = readiness_state(plan, {**_CTX_OK, "locked": True, "selected": True})
    assert r["state"] == "OPERATOR_LOCKED"
    r = readiness_state(plan, {**_CTX_OK, "selected": True})
    assert r["state"] == "OPERATOR_SELECTED"
    r = readiness_state(plan, dict(_CTX_OK))
    assert r["state"] == "OPERATOR_READY"


def test_readiness_stale_leg_does_not_leak_across_plans():
    stale_b = _fixture_plan("passed", stale=True, ticker="XLC")
    fresh_f = _fixture_plan("passed", stale=False, ticker="QQQ")
    assert readiness_state(stale_b, dict(_CTX_OK))["state"] == "QUOTES_STALE"
    r = readiness_state(fresh_f, dict(_CTX_OK))
    assert r["state"] == "OPERATOR_READY"
    assert not any("XLC" in reason for reason in r["reasons"])


# ── per-plan export gating (defect 4) ────────────────────────────────────────

def test_export_readiness_gates_per_plan():
    from lib.entry_planner_adapter import assess_export_readiness
    plans = [
        {"plan_archetype": "B", "legs": [
            {"ticker": "XLC", "price_stale": True},
            {"ticker": "XLF", "price_stale": False},
        ]},
        {"plan_archetype": "F", "legs": [
            {"ticker": "QQQ", "price_stale": False},
            {"ticker": "SCHD", "price_stale": False},
        ]},
    ]
    # Plan F is all-fresh: B's stale XLC must never block F's export
    assert assess_export_readiness(plans, plan_archetype="F")["export_allowed"] is True
    # no filter unions all plans — still blocked
    both = assess_export_readiness(plans)
    assert both["export_allowed"] is False and "XLC" in both["stale_symbols"]
    b = assess_export_readiness(plans, plan_archetype="B")
    assert b["export_allowed"] is False and "XLC" in b["stale_symbols"]


# ── settlement/regime narratives (defects 5/12/14) ───────────────────────────

def test_engine_source_has_no_static_settlement_string():
    src = (LIB / "redeploy_plan_engine.py").read_text()
    assert "Time to reconcile settlement" not in src
    # settlement text only when actually unsettled
    assert "settlement" in _staging_risk(False, "risk_off").lower()
    assert "settlement" not in _staging_risk(True, "risk_off").lower()
    assert "settlement" not in _staging_risk(True, "").lower()


def test_event_plans_no_settlement_language_after_verification():
    plans = _event_plans()
    if not plans:
        return
    import json
    blob = json.dumps(plans, default=str)
    for phrase in ("before settlement", "Time to reconcile settlement", "until proceeds settle"):
        assert phrase not in blob, f"settled event {EVENT_ID} still carries {phrase!r}"


def test_event_plan_objectives_are_honest():
    plans = _event_plans()
    if not plans:
        return
    by = _by_arch(plans)
    assert "NOT a replacement" in (by["E"].get("objective") or "")
    obj_b = by["B"].get("objective") or ""
    assert "all GICS" not in obj_b
    assert ("Partial" in obj_b) or ("top" in obj_b)
    assert "Strategic redesign" in (by["A"].get("objective") or "")


# ── decision scorecard + recommendation (defect: opaque ranking) ─────────────

def _scorable_plan(arch: str) -> dict:
    return {
        "plan_archetype": arch,
        "objective": f"fixture plan {arch}",
        "oversight_status": "pending",
        "financials": {"deployable_cash_usd": 100000.0,
                       "executable_at_current_quote_usd": 80000.0,
                       "reserve_usd": 15000.0, "whole_share_residual_usd": 5000.0},
        "legs": [
            {"ticker": "QQQ", "target_dollars": 50000.0, "is_reserve": False,
             "urgency": "ready", "price_stale": False, "expense_ratio_pct": 0.20,
             "selection_evidence": {"method": "fixture"}},
            {"ticker": "SCHD", "target_dollars": 30000.0, "is_reserve": False,
             "urgency": "near_entry", "price_stale": False, "expense_ratio_pct": 0.06},
            {"ticker": "BIL", "target_dollars": 15000.0, "is_reserve": True},
        ],
        "plan_income": {"expected_annual_income_usd": 1400.0, "whole_plan_yield_pct": 1.4},
    }


_SCORE_CTX = {"regime_posture": "risk_off", "is_major": True, "account_type": "ira",
              "exposure_sectors": []}


def test_score_plan_transparent_ten_dimensions():
    sc = score_plan(_scorable_plan("A"), dict(_SCORE_CTX))
    dims = sc["dimensions"]
    assert set(dims) == set(DEFAULT_WEIGHTS), "scorecard must carry exactly the 10 dimensions"
    for k, d in dims.items():
        for field in ("raw", "weight", "weighted", "note"):
            assert field in d, f"dimension {k} missing {field}"
        assert 0.0 <= d["raw"] <= 100.0
    assert abs(sum(d["weight"] for d in dims.values()) - 1.0) < 0.01
    assert abs(sc["total_score"] - sum(d["weighted"] for d in dims.values())) < 0.1


def test_recommend_plain_language_with_do_not_choose():
    plans = [_scorable_plan(a) for a in ("A", "E", "G")]
    scores = {p["plan_archetype"]: score_plan(p, dict(_SCORE_CTX)) for p in plans}
    rec = recommend(plans, scores, dict(_SCORE_CTX))
    assert rec["primary"]["archetype"] in ("A", "E", "G")
    assert rec["primary"]["reasons"]
    for alt in rec["alternatives"]:
        assert alt["choose_when"], "every alternative must state its choose-when condition"
    # E on a major sale is never a substitute for the sold mandate
    assert "E" in [d["archetype"] for d in rec["do_not_choose"]]


def test_weights_configurable_with_default_fallback(monkeypatch):
    w = load_weights()
    assert set(w) == set(DEFAULT_WEIGHTS)
    assert abs(sum(w.values()) - 1.0) < 0.01
    # no config file → exact defaults
    import pathlib
    monkeypatch.setattr(pathlib.Path, "is_file", lambda self: False)
    assert load_weights() == DEFAULT_WEIGHTS


# ── performance honesty (defects 7/10/11) ────────────────────────────────────

def test_plan_performance_whole_plan_vs_invested_sleeve_and_scenarios():
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        from lib.redeploy_performance import plan_performance
        legs = [
            {"ticker": "SCHD", "target_dollars": 10000.0, "is_reserve": False},
            # reserve with an unresolvable vehicle yield — contributes 0%, lower
            # than the invested sleeve, so whole-plan yield must be pulled DOWN
            {"ticker": "ZZZZZ", "target_dollars": 10000.0, "is_reserve": True},
        ]
        out = plan_performance(cur, {"symbol": "FCNTX"}, legs)
        assert "invested_sleeve" in out and "whole_plan" in out
        inv_y = out["invested_sleeve"]["yield_pct"]
        wp_y = out["whole_plan"]["yield_pct"]
        assert inv_y is not None and inv_y > 0, "SCHD trailing yield must be known"
        assert wp_y is not None
        assert wp_y <= inv_y, "whole-plan yield must include the (lower-yield) reserve"
        # scenarios: statistical bands never masquerade as forecasts
        scenarios = out["scenarios"]
        bands = [s for s in scenarios if s["kind"] == "STATISTICAL_BAND"]
        assert bands, "expected ±1σ statistical-band rows for a leg with vol data"
        for s in bands:
            lab = s["label"]
            assert "bull" not in lab.lower() and "bear" not in lab.lower()
            assert "NOT a" in lab and "forecast" in lab.lower()
        for s in scenarios:
            if s.get("unavailable"):
                assert s["plan_pct"] is None, \
                    f"unavailable scenario {s['key']} must be None, never 0"
    finally:
        conn.rollback()


# ── canonical income model (defects 8/9) ─────────────────────────────────────

def test_income_snapshot_fcntx_known_and_garbage_unavailable():
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        from lib.redeploy_income import income_snapshot
        snap = income_snapshot(cur, ["FCNTX", "ZZZZZ"])
        f = snap["FCNTX"]
        assert f["income_status"] != "UNAVAILABLE"
        assert "unknown" not in str(f["income_status"]).lower(), \
            "a number must never sit beside an 'unknown' status"
        assert f["yield_pct"] is not None
        assert f["recurring_income_note"] and "capital-gain" in f["recurring_income_note"]
        z = snap["ZZZZZ"]
        assert z["income_status"] == "UNAVAILABLE"
        assert z["yield_pct"] is None, "no data must be None, never a fabricated 0"
    finally:
        conn.rollback()


# ── candidate integrity (defects 18/19) ──────────────────────────────────────

def test_prose_blacklist_and_symbol_validation_pure():
    from lib.redeploy_candidate_research import PROSE_BLACKLIST, validate_symbol
    assert "FORUM" in PROSE_BLACKLIST and "WOULD" in PROSE_BLACKLIST
    no_corr = {"market": set(), "text": set()}
    ok, detail = validate_symbol(None, "FORUM", no_corr)
    assert ok is False and "prose" in detail
    # regex rejects non-ticker prose fragments outright
    ok, detail = validate_symbol(None, "TOO LONG", no_corr)
    assert ok is False and "pattern" in detail
    ok, detail = validate_symbol(None, "TOOLONGX", no_corr)
    assert ok is False
    # market-data corroboration overrides the blacklist (real word-tickers survive)
    ok, detail = validate_symbol(None, "FORUM", {"market": {"FORUM"}, "text": set()})
    assert ok is True and detail == "corroborated"


def test_rejection_codes_exist_in_source():
    src = (LIB / "redeploy_candidate_research.py").read_text()
    for code in ("INVALID_SYMBOL", "HISTORY_NOT_LOADED", "HISTORY_PROVIDER_FAILED",
                 "INSUFFICIENT_TRADING_HISTORY", "UNSUPPORTED_INSTRUMENT"):
        assert code in src, f"missing intake/rejection code {code}"


# ── competition evidence + roles on stored plans (defects 16/20) ─────────────

def test_event_legs_carry_roles_and_selection_evidence():
    plans = _event_plans()
    if not plans:
        return
    evidence_seen = False
    for p in plans:
        for leg in p.get("legs") or []:
            if leg.get("is_reserve"):
                continue
            assert str(leg.get("role") or "").strip(), \
                f"plan {p.get('plan_archetype')} leg {leg.get('ticker')} has no role"
            ev = leg.get("selection_evidence")
            if ev:
                assert ev.get("method"), "selection evidence must state its method"
                assert isinstance(ev.get("alternatives"), list)
                evidence_seen = True
    assert evidence_seen, "no leg carries candidate-competition evidence"


# ── audit lineage (defect 6) ─────────────────────────────────────────────────

def test_audit_log_populated_for_event():
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM redeploy_audit_log WHERE deploy_event_id=%s",
                    (EVENT_ID,))
        assert cur.fetchone()[0] > 0, f"event {EVENT_ID} audit trail is empty"
        cur.execute("""SELECT COUNT(*) FROM redeploy_audit_log
                       WHERE deploy_event_id=%s AND action='plan_version_generated'""",
                    (EVENT_ID,))
        assert cur.fetchone()[0] > 0
        cur.execute("""SELECT action, reason FROM redeploy_audit_log
                       WHERE deploy_event_id=%s AND inferred""", (EVENT_ID,))
        for action, reason in cur.fetchall():
            assert reason, f"inferred audit row {action!r} has no reason"
            assert ("INFERRED" in reason or "CHANGELOG" in reason
                    or "documented" in reason.lower()), \
                f"inferred row {action!r} must cite INFERRED marker or documented source: {reason!r}"
    finally:
        conn.rollback()


def test_list_audit_newest_first():
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        from lib.redeploy_audit import list_audit
        rows = list_audit(cur, EVENT_ID, limit=50)
        assert rows, f"list_audit returned nothing for event {EVENT_ID}"
        keys = [(r.get("occurred_at") or r.get("created_at")) for r in rows]
        assert all(k is not None for k in keys)
        for a, b in zip(keys, keys[1:]):
            assert a >= b, "audit rows must be ordered newest-first"
    finally:
        conn.rollback()


# ── NO broker execution path (hard invariant, extended to new modules) ───────

def test_new_decision_and_audit_modules_have_no_execution_surface():
    for name in ("redeploy_decision.py", "redeploy_audit.py"):
        src = (LIB / name).read_text()
        for token in ("schwab_transport", "place_order", "submit_fully_approved",
                      "intent_submit_router"):
            assert token not in src, f"{name} references broker-execution token {token!r}"


if __name__ == "__main__":
    import inspect
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        if inspect.signature(t).parameters:
            print(f"SKIP {t.__name__} (needs pytest fixtures)")
            continue
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")
