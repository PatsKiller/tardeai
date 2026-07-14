#!/usr/bin/env python3
"""Phase 13 acceptance — gaps not covered by the capital-book / analytics /
phase-E / ui-token suites. Pure-function tests use fixtures; DB tests are
STRICTLY read-only (SELECT + rollback — the 2026-07-13 fixture pollution is
exactly what we guard against)."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LIB = ROOT / "scripts" / "lib"
API = ROOT / "scripts" / "api_v2.py"
PAGE = ROOT / "apps" / "command-center-v3" / "src" / "pages" / "RedeployDesk.tsx"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _db():
    try:
        from db_adapter import get_connection
    except Exception:
        return None
    return get_connection()


class _StubCur:
    """Read-nothing cursor for pure-function tests — never touches a DB."""

    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one
        self.executed: list[str] = []
        self.description = []

    def execute(self, sql, params=None):
        self.executed.append(" ".join(str(sql).split()))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


# ── duplicate-event prevention ────────────────────────────────────────────────

def test_event_key_duplicate_prevention_source():
    mig = (ROOT / "migrations" / "2026_07_14_deploy_redeploy_events.sql").read_text()
    assert "event_key TEXT NOT NULL UNIQUE" in mig, "deploy_events.event_key must be UNIQUE"
    src = (LIB / "deploy_events_db.py").read_text()
    # upsert must probe by event_key and UPDATE the existing row, never blind-insert
    assert "SELECT id FROM deploy_events WHERE event_key=%s" in src
    assert "WHERE event_key=%s RETURNING id" in src
    det = (LIB / "sale_event_detector.py").read_text()
    assert "def event_key_for_row" in det
    assert "dedupe_key" in det and "txn_id" in det, "event_key must derive from txn identity"


def test_event_key_no_duplicates_in_db():
    conn = _db()
    if not conn:
        return  # skip without DB
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT event_key, COUNT(*) FROM deploy_events GROUP BY event_key HAVING COUNT(*) > 1"
        )
        dupes = cur.fetchall()
        assert not dupes, f"duplicate deploy_events event_keys: {dupes}"
    finally:
        conn.rollback()


# ── settlement / proceeds reconciliation ─────────────────────────────────────

def test_reconciliation_fields_and_consistency():
    dt = _load("rdt13", "scripts/lib/redeploy_data_truth.py")
    required = {
        "net_proceeds_usd", "settled_available_cash_usd", "deployable_cash_usd",
        "reconciliation_status", "planned_not_actionable_usd", "source_account",
        "holdings_as_of", "sale_date", "reconciliation_reason",
    }
    # verified: cash covers proceeds
    r = dt.reconcile_proceeds(account="a1", proceeds_usd=10000.0, cash_visible_usd=12000.0)
    assert required <= set(r)
    assert r["reconciliation_status"] == "verified"
    assert r["deployable_cash_usd"] == 10000.0
    # partial: only some cash visible; deployable = min(net, cash)
    r = dt.reconcile_proceeds(account="a1", proceeds_usd=10000.0, cash_visible_usd=6000.0)
    assert r["reconciliation_status"] == "partial"
    assert r["deployable_cash_usd"] == 6000.0
    assert abs(r["planned_not_actionable_usd"] - 4000.0) < 0.01
    # unsettled: below 50% — deployable never exceeds visible cash
    r = dt.reconcile_proceeds(account="a1", proceeds_usd=10000.0, cash_visible_usd=1000.0)
    assert r["reconciliation_status"] == "unsettled"
    assert r["deployable_cash_usd"] == 1000.0
    assert r["reconciliation_reason"] == "cash_below_50pct_of_net_in_holdings"
    # operator attestation overrides
    r = dt.reconcile_proceeds(
        account="a1", proceeds_usd=10000.0, cash_visible_usd=0.0,
        operator_settlement={"verified": True, "settled_cash_usd": 10000.0},
    )
    assert r["reconciliation_status"] == "verified"
    assert r["reconciliation_reason"] == "operator_verified"
    # invariant across all cases: net = deployable + planned_not_actionable
    for cash in (0.0, 3000.0, 9999.0, 25000.0):
        r = dt.reconcile_proceeds(account="a1", proceeds_usd=10000.0, cash_visible_usd=cash)
        assert abs(r["net_proceeds_usd"] - r["deployable_cash_usd"] - r["planned_not_actionable_usd"]) < 0.01


def test_reconciliation_fields_consistent_in_db():
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id, proceeds_usd, net_proceeds_usd, deployable_cash_usd, reconciliation_status
               FROM deploy_events WHERE status='open'"""
        )
        allowed = {"verified", "partial", "unsettled", "holdings_stale", None}
        for eid, proceeds, net, deployable, status in cur.fetchall():
            assert status in allowed, f"event {eid}: unknown reconciliation_status {status!r}"
            if deployable is not None and (net or proceeds) is not None:
                cap = float(net if net is not None else proceeds)
                assert float(deployable) <= cap + 0.01, (
                    f"event {eid}: deployable {deployable} exceeds net proceeds {cap}"
                )
    finally:
        conn.rollback()


# ── exposure decomposition ───────────────────────────────────────────────────

_FIXTURE_LOOKTHROUGH = {
    "asset_class": "equity_fund",
    "fetched_date": "2026-07-10",
    "sector_weights": {"Technology": 40.0, "Healthcare": 30.0, "Financial Services": 22.5},
    "top_holdings": [{"ticker": "MSFT", "name": "Microsoft", "pct": 10.0}],
}


def test_exposure_decomposition_sums_to_100_with_residual():
    dt = _load("rdt13b", "scripts/lib/redeploy_data_truth.py")
    dt._fund_lookthrough = lambda sym: dict(_FIXTURE_LOOKTHROUGH)
    dt._income_for_symbol = lambda sym, p: {"income_status": "unknown", "income_annual_usd": None}
    out = dt.decompose_exposure_loss(symbol="FAKEFUND", proceeds_usd=10000.0)
    accounted = sum(s["weight_pct"] for s in out["sectors"])
    # weights covered 92.5% — the missing 7.5% must surface as an explicit residual
    assert abs(out["residual_sector_pct"] - 7.5) < 0.01
    assert abs(accounted + out["residual_sector_pct"] - 100.0) < 0.05, "sectors + residual must sum to 100%"
    usd = sum(s["usd_removed"] for s in out["sectors"]) + out["residual_sector_usd"]
    assert abs(usd - 10000.0) < 1.0, "sector USD + residual USD must reconcile to proceeds"
    assert out["sectors"][0]["sector"] == "Technology"  # sorted by weight


def test_unknown_never_silently_zero():
    dt = _load("rdt13c", "scripts/lib/redeploy_data_truth.py")
    # income unknown → None, never a fabricated $0
    dt._load_json = lambda path, default: {}  # no dividend calendar, no lookthrough
    income = dt._income_for_symbol("NOSUCHFUND", 50000.0)
    assert income["income_status"] == "unknown"
    assert income["income_annual_usd"] is None, "unknown income must be None, not 0"
    # no look-through row → explicit note + empty sectors, not zero-weight rows
    out = dt.decompose_exposure_loss(symbol="NOSUCHFUND", proceeds_usd=50000.0)
    assert out["sectors"] == []
    assert "unavailable" in out.get("note", "")


# ── candidate-universe breadth + dynamic plan generation ─────────────────────

def test_candidate_universe_breadth_source():
    src = (LIB / "redeploy_candidate_research.py").read_text()
    # every source class must feed assemble_universe
    for marker in ('"holding"', '"watchlist"', '"hermes_discovery"', '"cio_decision"', 'f"roster:{role}"'):
        assert marker in src, f"candidate universe missing source class {marker}"
    for table in ("watchlist_items", "hermes_discovery_candidates", "cio_decisions"):
        assert table in src, f"candidate universe must query {table}"
    assert "REFERENCE_ROSTER" in src
    for lane in ("sector_etf", "broad_etf", "factor_etf", "income_etf", "bond_cash"):
        assert f'"{lane}"' in src, f"reference roster missing {lane} lane"
    assert "def _source_breakdown" in src, "per-source provenance breakdown required"


def test_plan_generation_not_hardcoded_only():
    src = (LIB / "redeploy_plan_engine.py").read_text()
    # plan builder must accept dynamic inputs, not only static recipes
    assert "v1_targets" in src and "sleeve_gaps" in src
    assert 'exposure.get("sectors")' in src, "Plan B weights must derive from the event's removed sectors"
    # phase_b_2.0.0: legs are selected from the candidate universe per role with
    # competition evidence (replaces the old _sleeve_gap_etfs even-split helper);
    # Plan E consumes live sleeve gaps with gap-capped sizing
    assert "_select_for_role" in src, "legs must be selected from the candidate universe by role"
    assert "gap_usd" in src and "TACTICAL_SLEEVE_BUDGET_FRAC" in src, \
        "Plan E must consume live sleeve gaps with gap-capped sizing"
    api = API.read_text()
    assert "/api/v2/redeploy/candidates" in api
    assert "build_candidates" in api, "dynamic candidate research must be wired into the API"


# ── whole-share + residual-cash arithmetic ───────────────────────────────────

def test_whole_share_arithmetic_pure():
    epa = _load("epa13", "scripts/lib/entry_planner_adapter.py")
    for dollars, price in ((10000.0, 450.37), (2500.0, 61.01), (99.0, 100.0), (0.0, 50.0), (500.0, 0.0)):
        sh, filled = epa.whole_shares(dollars, price)
        assert isinstance(sh, int)
        assert sh == int(dollars // price) if price > 0 and dollars > 0 else sh == 0
        assert abs(filled - round(sh * price, 2)) < 0.005, "filled must be exactly shares × price"
        assert filled <= dollars + 0.005, "whole-share fill can never exceed the target dollars"
        if price > 0:
            assert dollars - filled < price + 0.005, "residual must be smaller than one share"


def test_pro_forma_three_state_fixture_arithmetic():
    pf = _load("rpf13", "scripts/lib/redeploy_pro_forma.py")
    pf._holdings = lambda: [
        {"symbol": "CASH", "market_value": 50000.0, "is_cash": True, "account": "acct1"},
        {"symbol": "ABC", "market_value": 100000.0, "is_cash": False, "account": "acct1"},
    ]
    event = {"symbol": "XYZ", "account": "acct1", "net_proceeds_usd": 20000.0}
    legs = [
        {"ticker": "QQQ", "target_dollars": 10000.0, "is_reserve": False},
        {"ticker": "NOPRICE", "target_dollars": 500.0, "is_reserve": False},
        {"ticker": "SPAXX", "target_dollars": 5000.0, "is_reserve": True},
    ]
    states = pf.build_states(event, legs, leg_prices={"QQQ": 450.0})

    modeled = {m["ticker"]: m for m in states["_modeled_legs"]}
    q = modeled["QQQ"]
    assert q["whole_shares"] == 22 and q["modeled_dollars"] == 9900.0
    assert abs(q["residual_vs_target"] - 100.0) < 0.005, "residual cash must be explicit"
    # a leg without a price is excluded WITH a reason — never modeled at $0
    assert modeled["NOPRICE"]["modeled"] is False and modeled["NOPRICE"]["reason"]
    assert states["_deployed"] == 9900.0

    pre, post_sale, post_plan = (states[k] for k in ("pre_sale", "post_sale", "post_plan"))
    # three states conserve total value: cash converts to positions, nothing created
    assert abs(pre.total() - post_sale.total()) < 0.01
    assert abs(post_plan.total() - post_sale.total()) < 0.01
    # post-plan cash reduced by exactly the whole-share deploy (residual stays in cash)
    cash_after = next(p["market_value"] for p in post_plan.positions if p["is_cash"])
    assert abs(cash_after - (50000.0 - 9900.0)) < 0.01
    # pre-sale re-adds the sold position and removes its proceeds from cash
    assert any(p["symbol"] == "XYZ" and p["market_value"] == 20000.0 for p in pre.positions)
    pre_cash = next(p["market_value"] for p in pre.positions if p["is_cash"])
    assert abs(pre_cash - 30000.0) < 0.01


# ── look-through / issuer overlap / fee-income honesty ───────────────────────

def test_issuer_overlap_pure():
    dt = _load("rdt13d", "scripts/lib/redeploy_data_truth.py")
    holdings = [
        {"symbol": "FUNDX", "market_value": 10000.0, "is_cash": False},
        {"symbol": "CASH", "market_value": 500.0, "is_cash": True},
    ]
    lookthrough = {
        "_meta": {"note": "must be skipped"},
        "FUNDX": {"top_holdings": [{"ticker": "MSFT", "pct": 10.0}, {"ticker": "AAPL", "pct": 5.0}]},
        "UNHELD": {"top_holdings": [{"ticker": "NVDA", "pct": 50.0}]},
    }
    rows = dt._issuer_overlap(holdings, lookthrough)
    by_issuer = {r["issuer"]: r for r in rows}
    assert by_issuer["MSFT"]["indirect_usd"] == 1000.0
    assert by_issuer["MSFT"]["indirect_via"] == "FUNDX"
    assert by_issuer["AAPL"]["indirect_usd"] == 500.0
    assert "NVDA" not in by_issuer, "unheld funds contribute no overlap"


def test_fee_income_honesty_none_when_unknown():
    pf = _load("rpf13b", "scripts/lib/redeploy_pro_forma.py")
    state = pf.PortfolioState("t", [
        {"symbol": "QQQ", "market_value": 10000.0, "is_cash": False, "account": "x"},
    ])
    out = pf.analyze_state(
        _StubCur(), state,
        facts_map={"QQQ": {"quote_type": "ETF"}},  # no yield, no ER cached
        lookthrough={}, sector_cache={}, manual_map={}, bench_closes=[],
    )
    assert out["weighted_expense_ratio_pct"] is None, "unknown ER must be None, never fabricated 0"
    assert out["weighted_beta_1y"] is None
    gaps = " ".join(out["data_gaps"])
    assert "no cached distribution yield" in gaps and "no cached expense ratio" in gaps
    # coverage percentages are first-class fields
    assert "expense_ratio_coverage_pct" in out and "beta_coverage_pct" in out
    assert out["expense_ratio_coverage_pct"] == 0.0
    # unmapped sector surfaces as explicit Unknown, not silently dropped
    sectors = {r["sector"]: r["pct"] for r in out["sectors"]}
    assert sectors.get("Unknown") == 100.0


# ── stale-quote export gate (fail-closed) ────────────────────────────────────

def test_export_gate_fail_closed_on_stale():
    epa = _load("epa13b", "scripts/lib/entry_planner_adapter.py")
    # a missing quote timestamp counts as stale — fail closed
    assert epa.is_quote_stale(None) is True
    ready = epa.assess_export_readiness([
        {"legs": [
            {"ticker": "QQQ", "price_stale": True},
            {"ticker": "SCHD", "price_stale": False},
            {"ticker": "SPAXX", "is_reserve": True, "price_stale": True},  # reserves exempt
        ]},
    ])
    assert ready["export_allowed"] is False
    assert ready["stale_symbols"] == ["QQQ"]
    fresh = epa.assess_export_readiness([{"legs": [{"ticker": "QQQ", "price_stale": False}]}])
    assert fresh["export_allowed"] is True
    # source: export refuses with the stale_quotes error unless force_stale
    src = (LIB / "entry_planner_adapter.py").read_text()
    assert '"stale_quotes"' in src or "'stale_quotes'" in src
    assert "force_stale" in src
    api = API.read_text()
    assert "export_trade_plan(event, plan, fmt=fmt, force_stale=force)" in api


# ── plan versioning + lock concurrency ───────────────────────────────────────

def test_plan_version_monotonic():
    src = (LIB / "redeploy_plan_db.py").read_text()
    assert "COALESCE(MAX(version), 0) + 1" in src, "next version must be MAX+1 (monotonic)"
    pdb = _load("rpdb13", "scripts/lib/redeploy_plan_db.py")
    cur = _StubCur(one=(6,))
    assert pdb._next_plan_version(cur, 42) == 6
    assert "COALESCE(MAX(version), 0) + 1" in cur.executed[0]
    assert "deploy_event_id" in cur.executed[0], "version counter is per-event"


def test_locked_plan_never_silently_overwritten():
    ov = (LIB / "redeploy_oversight.py").read_text()
    # locking is optimistic-concurrency guarded
    assert '"already_locked"' in ov
    assert '"version_conflict"' in ov
    assert "AND locked_at IS NULL" in ov, "lock update must be conditional (no silent relock)"
    assert '"plan_already_locked"' in ov
    pdb = (LIB / "redeploy_plan_db.py").read_text()
    # recompute persists a NEW version — deploy_plans rows are insert-only
    assert "INSERT INTO deploy_plans" in pdb
    assert "UPDATE deploy_plans" not in pdb, "plan_db must never mutate existing plan rows"
    die = (LIB / "deploy_intelligence_engine.py").read_text()
    assert "new_version_created" in die, "recompute of a locked event must report a new version"
    assert "lock_before" in die and "lock_after" in die


# ── fixture pollution: production DB must be clean ───────────────────────────

def test_no_test_fixture_rows_in_production():
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM redeploy_stage_fills WHERE environment='test'")
        test_rows = cur.fetchone()[0]
        assert test_rows == 0, f"{test_rows} environment='test' rows survive in redeploy_stage_fills"
        cur.execute("SELECT COUNT(*) FROM redeploy_stage_fills WHERE evidence_note ILIKE '%fixture%'")
        fixture_rows = cur.fetchone()[0]
        assert fixture_rows == 0, f"{fixture_rows} fixture-marked rows survive in redeploy_stage_fills"
    finally:
        conn.rollback()


def test_synthetic_markers_rejected_and_metrics_production_only():
    mon = _load("rmon13", "scripts/lib/redeploy_monitor.py")
    # synthetic/dummy/fake markers are flagged exactly like 'fixture' (pure fn)
    for note in ("synthetic row", "dummy fill", "fake evidence", "fixture data"):
        assert mon._fixture_marker_in({"evidence_note": note}) == "evidence_note", note
    assert mon._fixture_marker_in({"idempotency_key": "test-abc123"}) == "idempotency_key"
    assert mon._fixture_marker_in({"evidence_note": "operator statement row 4"}) is None
    # every fills query feeding metrics filters to environment='production'
    src = (LIB / "redeploy_monitor.py").read_text()
    assert src.count("environment='production'") >= 2, "fill readers must exclude non-production rows"


# ── NO broker execution path (hard invariant) ────────────────────────────────

def test_no_broker_execution_path():
    forbidden = (
        "schwab_transport", "place_order", "submit_fully_approved",
        "intent_submit_router", "alpaca", ".submit(",
    )
    for path in sorted(LIB.glob("redeploy_*.py")):
        src = path.read_text()
        for token in forbidden:
            assert token not in src, f"{path.name} references broker-execution token {token!r}"

    tsx = PAGE.read_text()
    for token in ("protective-stop", "submit_fully_approved", "intent_submit",
                  "place_order", "/api/v2/orders", "broker-orders"):
        assert token not in tsx, f"RedeployDesk.tsx references execution surface {token!r}"
    # every literal fetch target stays on advisory read/annotate endpoints
    allowed = ("/api/v2/deploy/", "/api/v2/redeploy/", "/api/v2/watchlist/")
    for m in re.finditer(r"fetch\((['\"`])([^'\"`\)]*)", tsx):
        url = m.group(2)
        if not url.startswith("/"):
            continue  # variable url (useJson hook) — sources checked above
        assert url.startswith(allowed), f"unexpected fetch target {url}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")
