"""Phase 2a: plan store, situation predicates, SpaceX-class fixture, fail-soft."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    """Detector unit tests use template enrichment only (no bridge hang)."""
    monkeypatch.setenv("CIO_LLM_ENRICH", "0")
    monkeypatch.setenv("CIO_SITUATION_NOTIFY", "0")


# ── Fixtures ────────────────────────────────────────────────────────────────


def spacex_evidence() -> dict:
    """SpaceX-class mock: basis 210, trough 108, last 138, target 200+, catalysts, no stop."""
    return {
        "as_of": "2026-08-11T12:00:00+00:00",
        "holdings_detail": {
            "as_of": "2026-08-11T12:00:00+00:00",
            "holdings": [
                {
                    "symbol": "SPACEX_TEST",
                    "shares": 100,
                    "avg_cost": 210.0,
                    "last": 138.0,
                    "trough": 108.0,
                    "weight_pct": 8.0,
                    "has_stop": False,
                    "stop_price": None,
                }
            ],
        },
        "cost_basis": {
            "as_of": "2026-08-11T12:00:00+00:00",
            "by_symbol": {"SPACEX_TEST": {"avg_cost": 210.0}},
        },
        "market_quote": {
            "as_of": "2026-08-11T12:00:00+00:00",
            "SPACEX_TEST": {"last": 138.0},
        },
        "analyst_rollup": {
            "as_of": "2026-08-11T12:00:00+00:00",
            "SPACEX_TEST": {"mean_target": 200.0},
        },
        "catalyst_record": {
            "as_of": "2026-08-11T12:00:00+00:00",
            "SPACEX_TEST": [
                {"type": "lockup", "name": "lockup expiry"},
                {"type": "earnings", "name": "Q earnings"},
            ],
        },
        "risk_snapshot": {
            "as_of": "2026-08-11T12:00:00+00:00",
            "stops": {},
            "no_stop_symbols": ["SPACEX_TEST"],
        },
        "path_context": {
            "SPACEX_TEST": {"trough": 108.0},
        },
    }


@pytest.fixture
def plan_store(tmp_path):
    from scripts.lib.cio_plans import CIOPlanStore
    return CIOPlanStore(
        event_path=tmp_path / "cio_plans.jsonl",
        projection_path=tmp_path / "cio_plans_projection.json",
    )


@pytest.fixture
def cfg():
    from scripts.lib.cio_situation_detector import load_config
    return load_config("config/cio_situations.yaml")


# ── Plan CRUD ───────────────────────────────────────────────────────────────


def test_plan_crud(plan_store):
    from scripts.lib.cio_plans import validate_plan_payload
    p = plan_store.create_plan(
        situation_type="S1_POSITION_LIFECYCLE",
        symbols=["ABC"],
        title="Test plan",
        summary="summary",
        options=[
            {"id": "hold", "label": "Hold", "pros": "a", "cons": "b"},
            {"id": "trim", "label": "Trim", "pros": "c", "cons": "d"},
        ],
        recommendation="Hold for now",
        risks=["r1"],
        evidence_refs=[{"domain": "holdings_detail", "as_of": "2026-08-11", "fields_used": ["last"]}],
        revisit_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        owner_agent="alex",
        cc_deep_links=["/v3/portfolio"],
    )
    assert p["plan_id"].startswith("plan_")
    assert p["status"] == "draft"
    assert p["authority"] == "READ_ONLY_ADVISORY"
    assert plan_store.get_plan(p["plan_id"])["title"] == "Test plan"
    open_p = plan_store.list_open_plans()
    assert any(x["plan_id"] == p["plan_id"] for x in open_p)
    plan_store.update_plan(p["plan_id"], summary="updated")
    assert plan_store.get_plan(p["plan_id"])["summary"] == "updated"
    plan_store.supersede_plan(p["plan_id"], reason="test")
    assert plan_store.get_plan(p["plan_id"])["status"] == "superseded"
    assert not any(x["plan_id"] == p["plan_id"] for x in plan_store.list_open_plans())


def test_plan_dedup(plan_store, cfg):
    from scripts.lib.cio_situation_detector import CIOSituationDetector
    det = CIOSituationDetector(plan_store=plan_store)
    det.cfg = cfg
    ev = spacex_evidence()
    r1 = det.run(ev)
    assert r1["plans_created"], r1
    r2 = det.run(ev)
    assert r2["dedup_skipped"] >= 1
    assert r2["plans_created"] == []


# ── Predicates ──────────────────────────────────────────────────────────────


def test_s1_s2_spacex_predicates(cfg):
    from scripts.lib.cio_situation_detector import eval_s1, eval_s2
    ev = spacex_evidence()
    s1 = eval_s1(ev, cfg, "SPACEX_TEST")
    s2 = eval_s2(ev, cfg, "SPACEX_TEST")
    assert s1 is not None, "S1 must fire on SpaceX fixture"
    assert s2 is not None, "S2 must fire on SpaceX fixture"
    assert s1["situation_type"] == "S1_POSITION_LIFECYCLE"
    assert s2["situation_type"] == "S2_STOP_GAP"


def test_s3_reentry_ready(cfg):
    from scripts.lib.cio_situation_detector import eval_s3
    ev = {
        "reentry_decision_desk": {
            "candidates": [{"symbol": "ZZZ", "status": "READY"}],
        }
    }
    out = eval_s3(ev, cfg)
    assert len(out) == 1
    assert out[0]["symbols"] == ["ZZZ"]


def test_s5_cash_partial(cfg):
    from scripts.lib.cio_situation_detector import eval_s5
    ev = {
        "cash": {"cash_pct": 40.0, "quality_state": "PARTIAL"},
        "watch_intelligence": {
            "items": [
                {"symbol": "A", "status": "READY"},
                {"symbol": "B", "status": "GO"},
            ]
        },
    }
    r = eval_s5(ev, cfg)
    assert r is not None
    assert "PARTIAL" in r["summary"]
    # must forbid execution language
    assert "never" in r["recommendation"].lower() and "buy now" in r["recommendation"].lower()
    assert "execution" in r["recommendation"].lower()


def test_s6_concentration(cfg):
    from scripts.lib.cio_situation_detector import eval_s6
    ev = {
        "holdings_detail": {
            "holdings": [
                {"symbol": "FAT", "weight_pct": 18.0, "avg_cost": 50, "last": 55},
            ]
        }
    }
    out = eval_s6(ev, cfg)
    assert out and out[0]["situation_type"] == "S6_CONCENTRATION_OR_DISPOSITION"


def test_s7_watch(cfg):
    from scripts.lib.cio_situation_detector import eval_s7
    ev = {
        "holdings_detail": {"holdings": []},
        "watch_intelligence": {"items": [{"symbol": "NEW", "status": "GO"}]},
    }
    out = eval_s7(ev, cfg)
    assert out and out[0]["symbols"] == ["NEW"]


def test_s8_regime(cfg):
    from scripts.lib.cio_situation_detector import eval_s8
    ev = {"risk_regime": {"label": "RISK_OFF"}}
    r = eval_s8(ev, cfg)
    assert r is not None


def test_s4_rotation(cfg):
    from scripts.lib.cio_situation_detector import eval_s4
    ev = {
        "rotation_ladders": {"material_change": True, "ladders": ["XLK"]},
        "holdings_detail": {"holdings": [{"symbol": "AAPL", "weight_pct": 5}]},
    }
    r = eval_s4(ev, cfg)
    assert r is not None


# ── SpaceX integration ─────────────────────────────────────────────────────


def _numbers_in_text(text: str) -> set[str]:
    # capture numeric tokens like 210, 138.0, 200
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", text or ""))


def test_spacex_integration_fixture(plan_store, cfg):
    from scripts.lib.cio_situation_detector import CIOSituationDetector
    det = CIOSituationDetector(plan_store=plan_store)
    det.cfg = {**cfg, "enabled": True, "shadow": True, "notify": False}
    ev = spacex_evidence()
    allowed_nums = {"210", "210.0", "138", "138.0", "108", "108.0", "200", "200.0", "100", "8", "8.0"}
    # also percentage-derived may appear — allow computed from fixture only
    # deep dd ~34.3, recovery ~29.4 — permit those as derived from fixture inputs
    result = det.run(ev)
    assert not any("broker" in str(e).lower() for e in result.get("errors") or [])
    plans = [plan_store.get_plan(pid) for pid in result["plans_created"]]
    plans = [p for p in plans if p]
    types = {p["situation_type"] for p in plans}
    assert types & {"S1_POSITION_LIFECYCLE", "S2_STOP_GAP"}, f"expected S1/S2, got {types}"

    for p in plans:
        if p["situation_type"] not in ("S1_POSITION_LIFECYCLE", "S2_STOP_GAP"):
            continue
        opt_blob = " ".join(
            f"{o.get('id','')} {o.get('label','')} {o.get('pros','')} {o.get('cons','')}"
            for o in (p.get("options") or [])
        ).lower()
        assert "hold" in opt_blob
        assert "stop" in opt_blob and ("break-even" in opt_blob or "be" in opt_blob or "above" in opt_blob)
        assert "trim" in opt_blob or p["situation_type"] == "S2_STOP_GAP"
        assert p.get("evidence_refs"), "evidence_refs required"
        for ref in p["evidence_refs"]:
            assert ref.get("domain")
            assert ref.get("as_of")
        # no invented numbers in detector/option core text; multi-domain synthesis may
        # append live Data Broker cash/portfolio facts after "Thesis alignment"/"Multi-domain"
        blob = f"{p.get('summary','')} {p.get('recommendation','')}"
        core = blob.split("Thesis alignment")[0].split("Multi-domain")[0]
        for num in _numbers_in_text(core):
            # allow small integers used in formatting / pct truncated
            if num in allowed_nums:
                continue
            f = float(num)
            # derived pct from fixture math is ok if between 0 and 100
            if 0 <= f <= 100 and ("pct" in core or "drawdown" in core or "recovery" in core or "reasons" in core):
                continue
            # hours revisit etc not in summary typically
            pytest.fail(f"unexpected number {num} in plan text: {core[:200]}")


def test_fail_soft_unavailable_domain(plan_store, cfg):
    from scripts.lib.cio_situation_detector import CIOSituationDetector, run_detector_safe
    det = CIOSituationDetector(plan_store=plan_store)
    det.cfg = cfg
    # missing holdings — should not crash
    r = det.run({"analyst_rollup": {"X": {"mean_target": 10}}})
    assert "plans_created" in r
    # run_detector_safe never raises
    r2 = run_detector_safe(evidence=None)
    assert "errors" in r2 or "plans_created" in r2


def test_run_detector_safe_no_raise():
    from scripts.lib.cio_situation_detector import run_detector_safe
    r = run_detector_safe(evidence={"broken": object()})  # type: ignore
    assert isinstance(r, dict)
