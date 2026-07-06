#!/usr/bin/env python3
"""ALPACA-OPTIONS Stage 3 (Parts E/F) — prime rubric + desk API tests.

Covers: the 10 component scorers on fixtures (monotonicity + honest-neutral
degradation), weights summing to 1.0, verdict band boundaries, the
paper_fill_quality null-exclusion + weight renormalization, persist shape
(exactly ONE UPDATE merging meta.prime_json, never status), the no-order-path
invariant (grep + AST: the rubric never imports the alpaca_paper submit lane,
any broker/HTTP module, and never calls transition/submit), CLI flag
enforcement, and the Part-F API routes through api_v2.handle (mark-ready actor,
submit refused without confirm / without ALPACA_PAPER_BASE_URL as honest 4xx,
prime-rubric route, reconcile, record-outcome and promote guards, GET-list
meta.alpaca_json + prime_json exposure).

    .venv/bin/python -m pytest tests/test_options_prime_rubric.py -q
"""
from __future__ import annotations

import ast
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import prime_rubric as pr  # noqa: E402

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

# Fixture mirrors the real RTX deep-ITM queue row (values from the live scan).
RTX_PROPOSAL = {
    "id": "opt_deep_itm_call_RTX_paper_model_160p0000_20260918",
    "strategy": "deep_itm_call",
    "symbol": "RTX",
    "underlying": "RTX",
    "side": "BUY",
    "option_type": "call",
    "strike": 160.0,
    "expiration": "2026-09-18",
    "contracts": 1,
    "premium": 40.62,
    "premium_total": 4062.5,
    "underlying_price": 199.25,
    "delta": 0.93,
    "oi": 471,
    "volume": 15,
    "spread_pct": 6.77,
    "extrinsic_value": 1.375,
    "intrinsic_value": 39.25,
    "breakeven": 200.625,
    "breakeven_move_pct": 0.69,
    "iv_context": {"available": False, "reason": "insufficient history", "days": 1,
                   "required_days": 20},
    "educational_paper_model": True,
    "meta": {
        "gate_flags": [],
        "selection_policy": {"delta_range": [0.80, 0.95], "max_spread_pct": 10.0},
        "analysis": {"candidate": {"flags": {"earnings_before_expiry": False}}},
    },
}


def _row(status="pending", proposal=None, meta=None):
    p = copy.deepcopy(proposal or RTX_PROPOSAL)
    return {"id": 1, "proposal_id": p["id"], "symbol": p["symbol"],
            "strategy": p["strategy"], "status": status,
            "proposal_json": p, "meta": meta or {}}


def _score(row=None, **kw):
    kw.setdefault("max_premium_paper", 5000.0)
    kw.setdefault("portfolio_value", 1_258_645.0)
    kw.setdefault("latest_note_at", NOW - timedelta(days=1))
    kw.setdefault("now", NOW)
    return pr.score_proposal(row or _row(), **kw)


class FakeDB:
    """Executor double recording every statement."""

    def __init__(self, rows=()):
        self.rows = {r["proposal_id"]: r for r in rows}
        self.calls = []

    def __call__(self, sql, params=None, fetch=None):
        s = " ".join(sql.split())
        self.calls.append({"sql": s, "params": params, "fetch": fetch})
        if s.startswith("SELECT") and "WHERE proposal_id=%s" in s:
            r = self.rows.get(params[0])
            return copy.deepcopy(r) if r else None
        if s.startswith("SELECT") and "status = ANY(%s)" in s:
            return [copy.deepcopy(r) for r in self.rows.values()
                    if r["status"] in params[0]]
        if "GREATEST" in s:  # thesis-freshness lookup
            return {"latest_note_at": None}
        if s.startswith("UPDATE options_approval_queue SET meta ="):
            patch, pid = params
            r = self.rows.get(pid)
            if not r:
                return None
            r["meta"] = {**(r.get("meta") or {}), **json.loads(patch)}
            return True
        if s.startswith("UPDATE options_approval_queue SET status=%s"):
            to_status, patch_json, pid, from_status = params
            r = self.rows.get(pid)
            if not r or r["status"] != from_status:
                return None
            r["status"] = to_status
            r["meta"] = {**(r.get("meta") or {}), **json.loads(patch_json)}
            return {"id": r["id"]}
        return [] if fetch == "all" else None


# ── (1) component scorers ─────────────────────────────────────────────────────

def test_spread_tighter_is_higher():
    tight, _, _ = pr.spread_score(1.0)
    wide, _, _ = pr.spread_score(8.0)
    assert tight > wide
    assert pr.spread_score(0.0)[0] == 100.0
    assert pr.spread_score(10.0)[0] == 0.0
    assert pr.spread_score(25.0)[0] == 0.0          # clamped
    s, detail, _ = pr.spread_score(None)
    assert s == 0.0 and "unquotable" in detail       # fail-honest, not neutral


def test_oi_volume_monotonic():
    lo, _, _ = pr.oi_volume_score(100, 1)
    hi, _, _ = pr.oi_volume_score(2000, 200)
    assert hi > lo
    assert pr.oi_volume_score(0, 0)[0] == 0.0
    assert pr.oi_volume_score(None, None)[0] == 0.0


def test_delta_fit_window():
    assert pr.delta_fit_score(0.80)[0] == 100.0
    assert pr.delta_fit_score(0.93)[0] == 100.0
    assert pr.delta_fit_score(0.95)[0] == 100.0
    assert pr.delta_fit_score(-0.85)[0] == 100.0     # abs() — put-side symmetric
    assert pr.delta_fit_score(0.75)[0] == 50.0       # 0.05 outside → 50
    assert pr.delta_fit_score(0.60)[0] == 0.0        # 0.20 outside → floor
    s, detail, _ = pr.delta_fit_score(None)
    assert s == 50.0 and "proxy" in detail           # neutral + noted


def test_extrinsic_lower_is_higher():
    deep, _, _ = pr.extrinsic_score(1.0, 40.0)       # 2.5% extrinsic
    shallow, _, _ = pr.extrinsic_score(6.0, 40.0)    # 15% extrinsic
    assert deep > shallow
    assert pr.extrinsic_score(0.0, 40.0)[0] == 100.0
    assert pr.extrinsic_score(8.0, 40.0)[0] == 0.0   # 20% → 0
    assert pr.extrinsic_score(None, 40.0)[0] == 50.0
    assert pr.extrinsic_score(1.0, 0)[0] == 50.0     # bad premium → neutral


def test_breakeven_distance():
    assert pr.breakeven_distance_score(0.0)[0] == 100.0
    assert pr.breakeven_distance_score(-1.5)[0] == 100.0
    assert pr.breakeven_distance_score(5.0)[0] == 50.0
    assert pr.breakeven_distance_score(10.0)[0] == 0.0
    assert pr.breakeven_distance_score(None)[0] == 50.0


def test_iv_rank_cheap_is_high_and_unavailable_neutral():
    assert pr.iv_rank_score({"available": True, "iv_rank": 20.0})[0] == 80.0
    assert pr.iv_rank_score({"available": True, "iv_rank": 85.0})[0] == 15.0
    s, detail, inputs = pr.iv_rank_score({"available": False,
                                          "reason": "insufficient history", "days": 1})
    assert s == 50.0 and "unavailable" in detail and inputs["available"] is False
    assert pr.iv_rank_score(None)[0] == 50.0


def test_earnings_flag_present_is_low():
    s, detail, _ = pr.earnings_risk_score({"earnings_before_expiry": True}, [])
    assert s == pr.EARNINGS_FLAGGED_SCORE and "FLAGGED" in detail
    # gate-flag route (operator-flagged still an event risk)
    s2, _, _ = pr.earnings_risk_score({}, ["earnings_before_expiry_operator_flagged"])
    assert s2 == pr.EARNINGS_FLAGGED_SCORE
    assert pr.earnings_risk_score({"earnings_before_expiry": None}, [])[0] == 50.0
    assert pr.earnings_risk_score({}, ["earnings_unknown"])[0] == 50.0
    assert pr.earnings_risk_score({"earnings_before_expiry": False}, [])[0] == 100.0


def test_account_sizing():
    # small premium, big portfolio → near 100
    s, _, _ = pr.account_sizing_score(500.0, 5000.0, 1_000_000.0)
    assert s == 90.0
    # at the cap → 0 regardless of portfolio
    assert pr.account_sizing_score(5000.0, 5000.0, 1_000_000.0)[0] == 0.0
    assert pr.account_sizing_score(6000.0, 5000.0, 1_000_000.0)[0] == 0.0
    # portfolio-heavy: 3% of a small portfolio → floor wins (min taken)
    s2, _, inputs = pr.account_sizing_score(1500.0, 5000.0, 50_000.0)
    assert s2 == 0.0 and inputs["portfolio_score"] == 0.0
    # portfolio unavailable → cap-ratio only + honest detail
    s3, detail, inputs3 = pr.account_sizing_score(2500.0, 5000.0, None)
    assert s3 == 50.0 and "unavailable" in detail and inputs3["portfolio_value"] is None


def test_thesis_freshness():
    assert pr.thesis_freshness_score(NOW - timedelta(days=2), now=NOW)[0] == 100.0
    mid, _, _ = pr.thesis_freshness_score(NOW - timedelta(days=48.5), now=NOW)
    assert mid == 50.0
    assert pr.thesis_freshness_score(NOW - timedelta(days=120), now=NOW)[0] == 0.0
    s, detail, _ = pr.thesis_freshness_score(None, now=NOW)
    assert s == 50.0 and "no watchlist" in detail


def test_paper_fill_quality():
    # no fill → None (excluded)
    s, detail, _ = pr.paper_fill_quality_score({}, 40.62)
    assert s is None and "excluded" in detail
    # fill at/below mid → 100
    assert pr.paper_fill_quality_score({"fill": {"price": 40.62}}, 40.62)[0] == 100.0
    assert pr.paper_fill_quality_score({"fill": {"price": 40.00}}, 40.62)[0] == 100.0
    # 2% over mid → 50 (0 at 4%)
    s2, _, inputs = pr.paper_fill_quality_score({"fill": {"price": 40.62 * 1.02}}, 40.62)
    assert s2 == 50.0 and inputs["slippage_pct"] == pytest.approx(2.0, abs=0.01)
    assert pr.paper_fill_quality_score({"fill": {"price": 40.62 * 1.10}}, 40.62)[0] == 0.0


# ── (2) weights + overall score + verdict bands ───────────────────────────────

def test_weights_sum_to_one():
    assert sum(pr.WEIGHTS.values()) == pytest.approx(1.0)
    assert set(pr.WEIGHTS) == {
        "spread_score", "oi_volume_score", "delta_fit_score", "extrinsic_score",
        "breakeven_distance_score", "iv_rank_score", "earnings_risk_score",
        "account_sizing_score", "thesis_freshness_score", "paper_fill_quality_score"}


@pytest.mark.parametrize("score,verdict", [
    (0.0, "NOT_PRIME"), (49.9, "NOT_PRIME"),
    (50.0, "PAPER_WATCH"), (64.9, "PAPER_WATCH"),
    (65.0, "PRIME_FOR_PAPER"), (79.9, "PRIME_FOR_PAPER"),
    (80.0, "READY_FOR_LIVE_REVIEW_OPERATOR_ONLY"),
    (100.0, "READY_FOR_LIVE_REVIEW_OPERATOR_ONLY"),
])
def test_verdict_bands(score, verdict):
    assert pr.verdict_for_score(score) == verdict


def test_verdict_label_is_not_the_state_machine_string():
    # The >=80 verdict is a LABEL, deliberately distinct from the queue status.
    assert pr.VERDICT_LIVE_REVIEW_LABEL != "READY_FOR_LIVE_REVIEW"
    assert "OPERATOR_ONLY" in pr.VERDICT_LIVE_REVIEW_LABEL


def test_score_proposal_rtx_fixture_shape_and_math():
    prime = _score()
    assert prime["engine"] == pr.RUBRIC_ENGINE
    assert prime["verdict_is_label_only"] is True
    assert set(prime["components"]) == set(pr.WEIGHTS)
    # no fill on a pending row → fill component excluded, weights renormalized
    assert prime["excluded_components"] == ["paper_fill_quality_score"]
    assert prime["weight_used"] == pytest.approx(0.92)
    # manual re-computation over the returned components must match prime_score
    num = sum(c["score"] * c["weight"] for c in prime["components"].values()
              if c["score"] is not None)
    assert prime["prime_score"] == pytest.approx(num / 0.92, abs=0.06)
    assert prime["verdict"] == pr.verdict_for_score(prime["prime_score"])
    # RTX fixture: 100 delta-fit, tight extrinsic, near breakeven → prime band
    assert prime["components"]["delta_fit_score"]["score"] == 100.0
    assert 55.0 <= prime["prime_score"] <= 85.0


def test_null_fill_exclusion_vs_included():
    without = _score()
    with_fill = _score(_row(
        status="ALPACA_PAPER_FILLED",
        meta={"alpaca_json": {"fill": {"price": RTX_PROPOSAL["premium"]}}}))
    assert with_fill["excluded_components"] == []
    assert with_fill["weight_used"] == pytest.approx(1.0)
    fq = with_fill["components"]["paper_fill_quality_score"]
    assert fq["score"] == 100.0
    # a perfect at-mid fill can only help the renormalized score
    assert with_fill["prime_score"] >= without["prime_score"]


def test_degraded_row_scores_all_neutral_not_fabricated():
    bare = _row(proposal={"id": "x", "strategy": "deep_itm_call", "symbol": "X",
                          "premium": None, "educational_paper_model": True})
    prime = pr.score_proposal(bare, max_premium_paper=5000.0, portfolio_value=None,
                              latest_note_at=None, now=NOW)
    c = prime["components"]
    assert c["delta_fit_score"]["score"] == 50.0
    assert c["iv_rank_score"]["score"] == 50.0
    assert c["thesis_freshness_score"]["score"] == 50.0
    assert c["spread_score"]["score"] == 0.0          # unquotable is NOT neutral
    assert prime["notes"]                              # degradation disclosed


# ── (3) persist shape: ONE meta UPDATE, never status ─────────────────────────

def test_score_and_persist_one_update_meta_only():
    db = FakeDB([_row()])
    res = pr.score_and_persist(RTX_PROPOSAL["id"], executor=db)
    assert res["ok"] and res["persisted"]
    updates = [c for c in db.calls if c["sql"].startswith("UPDATE")]
    assert len(updates) == 1
    assert "SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb" in updates[0]["sql"]
    assert "status" not in updates[0]["sql"].lower().replace("updated_at", "")
    stored = db.rows[RTX_PROPOSAL["id"]]["meta"]["prime_json"]
    for key in ("prime_score", "verdict", "components", "verdict_is_label_only",
                "scored_at", "engine", "excluded_components", "weight_used"):
        assert key in stored, f"prime_json missing {key}"
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == "pending"  # untouched


def test_score_and_persist_dry_run_no_writes():
    db = FakeDB([_row()])
    res = pr.score_and_persist(RTX_PROPOSAL["id"], dry_run=True, executor=db)
    assert res["ok"] and res["persisted"] is False
    assert not any(c["sql"].startswith("UPDATE") for c in db.calls)


def test_score_and_persist_unknown_row():
    res = pr.score_and_persist("nope", executor=FakeDB([]))
    assert res["ok"] is False and "not in options_approval_queue" in res["error"]


# ── (4) no-order-path invariant (grep + AST) ─────────────────────────────────

RUBRIC_SOURCES = [
    ROOT / "scripts" / "lib" / "options_pipeline" / "prime_rubric.py",
    ROOT / "scripts" / "options_prime_rubric.py",
]

FORBIDDEN_IMPORTS = ("alpaca_paper", "requests", "urllib.request", "httpx",
                     "schwab", "brokers", "options_desk_enterprise",
                     "approval_service", "options_order_pilot")
FORBIDDEN_CALLS = ("transition", "submit_ready_proposal", "mark_ready",
                   "mark_live_review", "submit_option_limit_order",
                   "build_order_request", "build_order_payload")


def _imports_and_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports, calls = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
            imports += [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Call):
            f = node.func
            calls.append(f.attr if isinstance(f, ast.Attribute)
                         else f.id if isinstance(f, ast.Name) else "")
    return imports, calls


def test_rubric_never_imports_order_lane_or_http():
    for path in RUBRIC_SOURCES:
        imports, calls = _imports_and_calls(path)
        for imp in imports:
            for bad in FORBIDDEN_IMPORTS:
                assert bad not in imp, f"{path.name} imports forbidden module: {imp}"
        for call in calls:
            assert call not in FORBIDDEN_CALLS, \
                f"{path.name} calls order/state machinery: {call}()"


def test_rubric_sql_never_touches_status():
    src = RUBRIC_SOURCES[0].read_text(encoding="utf-8")
    assert "SET status" not in src
    assert src.count("UPDATE options_approval_queue") == 1  # the meta merge only
    # runtime double-check: scoring never mutates the row's status
    db = FakeDB([_row("ALPACA_PAPER_FILLED")])
    pr.score_and_persist(RTX_PROPOSAL["id"], executor=db)
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == "ALPACA_PAPER_FILLED"


# ── (5) CLI flags ─────────────────────────────────────────────────────────────

def test_cli_requires_exactly_one_selector(capsys):
    import options_prime_rubric as cli
    assert cli.main([]) == 2
    assert cli.main(["--proposal-id", "x", "--all-queued"]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_cli_scores_one_row(monkeypatch, capsys):
    import options_prime_rubric as cli
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    monkeypatch.setattr(pr, "_default_executor", lambda: FakeDB([_row()]))
    # dry-run json path
    assert cli.main(["--proposal-id", RTX_PROPOSAL["id"], "--json", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["results"][0]["prime_json"]["verdict"]
    assert out["results"][0]["persisted"] is False


# ── (6) Part F API routes through api_v2.handle ──────────────────────────────

@pytest.fixture(scope="module")
def api():
    import api_v2
    return api_v2


def _post(api, path, body):
    return api.handle(path, method="POST", body=body)


def test_api_mark_ready_requires_proposal_id(api):
    st, res = _post(api, "/api/v2/options/alpaca-paper/mark-ready", {})
    assert st == 400 and res["ok"] is False and "proposal_id" in res["reason"]


def test_api_mark_ready_uses_operator_ui_actor(api, monkeypatch):
    from lib.options_pipeline import alpaca_paper as ap
    seen = {}

    def fake_mark_ready(pid, *, operator_actor, executor=None):
        seen.update(pid=pid, actor=operator_actor)
        return {"ok": True, "proposal_id": pid, "from": "pending",
                "to": ap.STATE_READY}
    monkeypatch.setattr(ap, "mark_ready", fake_mark_ready)
    st, res = _post(api, "/api/v2/options/alpaca-paper/mark-ready",
                    {"proposal_id": "p1"})
    assert st == 200 and res["ok"]
    assert seen == {"pid": "p1", "actor": "operator:ui"}


def test_api_mark_ready_illegal_transition_is_409(api, monkeypatch):
    from lib.options_pipeline import alpaca_paper as ap

    def boom(pid, *, operator_actor, executor=None):
        raise ap.IllegalTransitionError("ALPACA_PAPER_FILLED → READY is illegal")
    monkeypatch.setattr(ap, "mark_ready", boom)
    st, res = _post(api, "/api/v2/options/alpaca-paper/mark-ready",
                    {"proposal_id": "p1"})
    assert st == 409 and res["ok"] is False and "illegal" in res["reason"]


def test_api_submit_refused_without_confirm(api, monkeypatch):
    from lib.options_pipeline import alpaca_paper as ap
    called = []
    monkeypatch.setattr(ap, "submit_ready_proposal",
                        lambda *a, **k: called.append(1))
    for body in ({"proposal_id": "p1"}, {"proposal_id": "p1", "confirm": False},
                 {"proposal_id": "p1", "confirm": "yes"}):
        st, res = _post(api, "/api/v2/options/alpaca-paper/submit", body)
        assert st == 400 and res["ok"] is False and "confirm" in res["reason"]
    assert not called  # never reached the lane


def test_api_submit_refused_without_paper_env(api, monkeypatch):
    """confirm:true + READY row but NO ALPACA_PAPER_BASE_URL → honest 4xx reason
    from the real paper-endpoint hard lock (no monkeypatched submit)."""
    from lib.options_pipeline import alpaca_paper as ap
    db = FakeDB([_row(ap.STATE_READY)])
    monkeypatch.setattr(ap, "_default_executor", lambda: db)
    for name in ("ALPACA_PAPER_BASE_URL", "ALPACA_MODE"):
        monkeypatch.delenv(name, raising=False)
    st, res = _post(api, "/api/v2/options/alpaca-paper/submit",
                    {"proposal_id": RTX_PROPOSAL["id"], "confirm": True})
    assert st == 409 and res["ok"] is False
    assert "ALPACA_PAPER_BASE_URL" in res["reason"]
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == ap.STATE_READY  # untouched


def test_api_reconcile_route(api, monkeypatch):
    from lib.options_pipeline import alpaca_paper as ap
    monkeypatch.setattr(ap, "reconcile_fills",
                        lambda **k: {"ok": True, "submitted_polled": 0,
                                     "transitions": [], "warnings": []})
    st, res = _post(api, "/api/v2/options/alpaca-paper/reconcile", {})
    assert st == 200 and res["ok"] and res["transitions"] == []


def test_api_prime_rubric_route(api, monkeypatch):
    db = FakeDB([_row()])
    monkeypatch.setattr(pr, "_default_executor", lambda: db)
    monkeypatch.setattr(pr, "read_portfolio_value", lambda: 1_258_645.0)
    st, res = _post(api, "/api/v2/options/prime-rubric",
                    {"proposal_id": RTX_PROPOSAL["id"]})
    assert st == 200 and res["ok"] and res["persisted"]
    assert res["prime_json"]["verdict"] in (
        "NOT_PRIME", "PAPER_WATCH", "PAPER_ONLY", "PRIME_FOR_PAPER",
        "READY_FOR_LIVE_REVIEW_OPERATOR_ONLY")
    assert db.rows[RTX_PROPOSAL["id"]]["meta"]["prime_json"]["prime_score"] >= 0
    # unknown row → 404
    st2, res2 = _post(api, "/api/v2/options/prime-rubric", {"proposal_id": "nope"})
    assert st2 == 404 and res2["ok"] is False


def test_api_record_outcome_guards(api, monkeypatch):
    from lib.options_pipeline import alpaca_paper as ap
    st, res = _post(api, "/api/v2/options/alpaca-paper/record-outcome",
                    {"proposal_id": "p1"})
    assert st == 400 and "exit_premium" in res["reason"]
    # wrong state → 409
    db = FakeDB([_row("pending")])
    monkeypatch.setattr(ap, "_default_executor", lambda: db)
    st2, res2 = _post(api, "/api/v2/options/alpaca-paper/record-outcome",
                      {"proposal_id": RTX_PROPOSAL["id"], "exit_premium": 42.0})
    assert st2 == 409 and "pending" in res2["reason"]
    # FILLED but no fill price in meta → honest refusal, no fabricated P/L
    db3 = FakeDB([_row(ap.STATE_FILLED, meta={"alpaca_json": {}})])
    monkeypatch.setattr(ap, "_default_executor", lambda: db3)
    st3, res3 = _post(api, "/api/v2/options/alpaca-paper/record-outcome",
                      {"proposal_id": RTX_PROPOSAL["id"], "exit_premium": 42.0})
    assert st3 == 409 and "fill" in res3["reason"]


def test_api_record_outcome_happy_path(api, monkeypatch):
    from lib.options_pipeline import alpaca_paper as ap
    import lib.options_pipeline.validation as val
    meta = {"alpaca_json": {
        "request": {"symbol": "RTX260918C00160000"},
        "response": {"id": "ord-42"},
        "fill": {"price": 40.10, "filled_at": "2026-07-06T14:31:00Z"}}}
    db = FakeDB([_row(ap.STATE_FILLED, meta=meta)])
    monkeypatch.setattr(ap, "_default_executor", lambda: db)
    recorded = {}

    def fake_record(pid, **kw):
        recorded.update(proposal_id=pid, **kw)
        return {"ok": True}
    monkeypatch.setattr(val, "record_outcome", fake_record)
    st, res = _post(api, "/api/v2/options/alpaca-paper/record-outcome",
                    {"proposal_id": RTX_PROPOSAL["id"], "exit_premium": 43.85})
    assert st == 200 and res["ok"]
    assert res["pnl"] == 375.0 and res["outcome"] == "win"  # (43.85-40.10)×100
    assert recorded["pnl"] == 375.0 and recorded["exit_reason"] == "manual"
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == ap.STATE_OUTCOME


def test_api_promote_requires_confirm_and_prime_verdict(api, monkeypatch):
    from lib.options_pipeline import alpaca_paper as ap
    st, res = _post(api, "/api/v2/options/alpaca-paper/promote-live-review",
                    {"proposal_id": "p1"})
    assert st == 400 and "confirm" in res["reason"]
    # OUTCOME_RECORDED but prime verdict below the live-review label → 409
    db = FakeDB([_row(ap.STATE_OUTCOME,
                      meta={"prime_json": {"verdict": "PRIME_FOR_PAPER"}})])
    monkeypatch.setattr(ap, "_default_executor", lambda: db)
    st2, res2 = _post(api, "/api/v2/options/alpaca-paper/promote-live-review",
                      {"proposal_id": RTX_PROPOSAL["id"], "confirm": True})
    assert st2 == 409 and "PRIME_FOR_PAPER" in res2["reason"]
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == ap.STATE_OUTCOME
    # verdict label present → operator-only state machine promote succeeds
    db3 = FakeDB([_row(ap.STATE_OUTCOME,
                       meta={"prime_json": {"verdict": pr.VERDICT_LIVE_REVIEW_LABEL}})])
    monkeypatch.setattr(ap, "_default_executor", lambda: db3)
    st3, res3 = _post(api, "/api/v2/options/alpaca-paper/promote-live-review",
                      {"proposal_id": RTX_PROPOSAL["id"], "confirm": True})
    assert st3 == 200 and res3["ok"]
    assert "no order was placed" in res3["note"]
    assert db3.rows[RTX_PROPOSAL["id"]]["status"] == ap.STATE_LIVE_REVIEW
    log = db3.rows[RTX_PROPOSAL["id"]]["meta"]["alpaca_state_log"]
    assert log[-1]["actor"] == "operator:ui"


def test_api_get_list_exposes_alpaca_and_prime_json(api, monkeypatch):
    """Paper-model queue rows in the proposals feed carry meta.alpaca_json +
    prime_json through to the frontend; flag-less rows stay fail-closed dropped."""
    import db_adapter
    good = _row("ALPACA_PAPER_FILLED", meta={
        "alpaca_json": {"fill": {"price": 40.10}},
        "prime_json": {"verdict": "PRIME_FOR_PAPER", "prime_score": 63.2}})
    stripped = _row("pending")
    stripped["proposal_id"] = "opt_stripped"
    stripped["proposal_json"] = {**copy.deepcopy(RTX_PROPOSAL),
                                 "id": "opt_stripped",
                                 "educational_paper_model": False}

    def fake_execute(sql, params=None, fetch=None):
        s = " ".join(sql.split())
        if "FROM options_approval_queue" in s and "strategy = 'deep_itm_call'" in s:
            return [{"proposal_id": r["proposal_id"],
                     "queue_status": r["status"],
                     "proposal_json": r["proposal_json"], "meta": r["meta"],
                     "created_at": None, "expires_at": None}
                    for r in (good, stripped)]
        return [] if fetch == "all" else None

    monkeypatch.setattr(db_adapter, "_execute", fake_execute)
    monkeypatch.setattr(db_adapter, "USE_DB", True)
    rows = api._fetch_paper_model_queue_proposals()
    assert len(rows) == 1                       # fail-closed guard still drops
    p = rows[0]
    assert p["queue_status"] == "ALPACA_PAPER_FILLED"
    assert p["alpaca_json"]["fill"]["price"] == 40.10
    assert p["prime_json"]["verdict"] == "PRIME_FOR_PAPER"
