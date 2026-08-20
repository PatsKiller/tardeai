"""Fix #2: watch intelligence → CIO snapshot evidence for S7 (READ_ONLY_ADVISORY).

Notify stays off. No broker mutation. No reentry rewrite. No S7 spam from WAIT/MANAGING.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_notify(monkeypatch):
    monkeypatch.setenv("CIO_SITUATION_NOTIFY", "0")
    monkeypatch.setenv("CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY", "0")
    monkeypatch.setenv("CIO_LLM_ENRICH", "0")


@pytest.fixture
def cfg():
    from scripts.lib.cio_situation_detector import load_config

    return load_config("config/cio_situations.yaml")


def test_normalize_watch_s7_status_promotion_grade_only():
    from scripts.lib.data_broker.watch_intelligence import normalize_watch_s7_status

    st, score, meta = normalize_watch_s7_status(
        {"card": {"symbol": "A", "proposal_allowed": True, "rank_score": 88}}
    )
    assert st == "READY" and score == 88.0 and meta["reason"] == "proposal_allowed"

    st, _, meta = normalize_watch_s7_status(
        {"card": {"symbol": "B", "trade_ai_state": "GO", "rank_score": 90}}
    )
    assert st == "GO" and meta["reason"].startswith("trade_ai_state")

    st, score, meta = normalize_watch_s7_status(
        {
            "card": {
                "symbol": "C",
                "trade_ai_state": "WAIT",
                "is_near_trigger": True,
                "near_trigger": {"is_near": True},
                "rank_score": 72,
            }
        }
    )
    assert st == "NEAR" and score == 72.0 and meta["reason"] == "near_trigger"

    # Desk near without score → strong_near so eval_s7 can fire
    st, score, meta = normalize_watch_s7_status(
        {"card": {"symbol": "D", "is_near_trigger": True, "near_trigger": {"is_near": True}}}
    )
    assert st == "NEAR" and score is None and meta.get("strong_near") is True

    # Honesty: WAIT / MANAGING / street alone are BLOCK
    st, _, meta = normalize_watch_s7_status(
        {"card": {"symbol": "E", "trade_ai_state": "WAIT", "street_rating": "STRONG BUY"}}
    )
    assert st == "BLOCK" and meta["reason"] == "not_promotion_grade"

    st, _, _ = normalize_watch_s7_status(
        {"card": {"symbol": "F", "trade_ai_state": "MANAGING", "proposal_allowed": False}}
    )
    assert st == "BLOCK"

    st, _, _ = normalize_watch_s7_status({"status": "READY", "symbol": "G"})
    assert st == "READY"

    st, _, _ = normalize_watch_s7_status(None)
    assert st == "BLOCK"


def test_project_watch_intelligence_counts():
    from scripts.lib.data_broker.watch_intelligence import project_watch_intelligence_for_cio

    payload = {
        "ok": True,
        "generated_at": "2026-08-20T12:00:00+00:00",
        "items": [
            {"symbol": "AAA", "card": {"symbol": "AAA", "proposal_allowed": True, "rank_score": 80}},
            {"symbol": "BBB", "card": {"symbol": "BBB", "trade_ai_state": "GO"}},
            {
                "symbol": "CCC",
                "card": {
                    "symbol": "CCC",
                    "is_near_trigger": True,
                    "near_trigger": {"is_near": True},
                    "rank_score": 71,
                },
            },
            {"symbol": "DDD", "card": {"symbol": "DDD", "trade_ai_state": "MANAGING"}},
        ],
    }
    out = project_watch_intelligence_for_cio(payload)
    by = {r["symbol"]: r["status"] for r in out["items"]}
    assert by == {"AAA": "READY", "BBB": "GO", "CCC": "NEAR", "DDD": "BLOCK"}
    assert out["counts"]["ready"] == 1
    assert out["counts"]["go"] == 1
    assert out["counts"]["near"] == 1
    assert out["counts"]["block"] == 1
    assert out["counts"]["promotion_grade"] == 3
    assert out["candidates"] == out["items"]


def test_collect_candidates_s7_ready_go_near(cfg):
    from scripts.lib.cio_situation_detector import CIOSituationDetector

    ev = {
        "watch_intelligence": {
            "items": [
                {"symbol": "READY1", "status": "READY", "score": 90, "held": False},
                {"symbol": "GO1", "status": "GO", "score": 85, "held": False},
                {"symbol": "NEAR1", "status": "NEAR", "score": 75, "held": False},
                {"symbol": "BLOCK1", "status": "BLOCK", "held": False},
            ]
        }
    }
    cands = CIOSituationDetector().collect_candidates(ev)
    s7 = [c for c in cands if str(c.get("situation_type")).startswith("S7")]
    syms = {c["symbols"][0] for c in s7}
    assert syms == {"READY1", "GO1", "NEAR1"}
    assert "BLOCK1" not in syms
    ready = next(c for c in s7 if c["symbols"] == ["READY1"])
    assert "watch_READY" in (ready.get("fire_reasons") or [])


def test_collect_candidates_non_promotion_no_s7(cfg):
    from scripts.lib.cio_situation_detector import CIOSituationDetector

    ev = {
        "watch_intelligence": {
            "items": [
                {"symbol": "ANET", "status": "BLOCK", "trade_ai_state": "WAIT"},
                {"symbol": "DXCM", "status": "BLOCK", "trade_ai_state": "MANAGING"},
            ]
        }
    }
    s7 = [
        c
        for c in CIOSituationDetector().collect_candidates(ev)
        if str(c.get("situation_type")).startswith("S7")
    ]
    assert s7 == []


def test_project_none_fail_soft():
    from scripts.lib.data_broker.watch_intelligence import project_watch_intelligence_for_cio

    out = project_watch_intelligence_for_cio(None)
    assert out["items"] == []
    assert out["counts"]["total"] == 0
    assert out["counts"]["promotion_grade"] == 0


def test_domain_watch_intelligence_projects(monkeypatch):
    from scripts.lib.data_broker import cio_portfolio as cp
    from scripts.lib.cio_situation_detector import (
        CIOSituationDetector,
        build_evidence_from_snapshot,
    )

    fake = {
        "ok": True,
        "generated_at": "2026-08-20T19:00:00+00:00",
        "items": [
            {
                "symbol": "NEARX",
                "card": {
                    "symbol": "NEARX",
                    "trade_ai_state": "WAIT",
                    "proposal_allowed": False,
                    "is_near_trigger": True,
                    "near_trigger": {"is_near": True},
                    "rank_score": 74.0,
                    "held": False,
                },
            },
            {
                "symbol": "WAITX",
                "card": {
                    "symbol": "WAITX",
                    "trade_ai_state": "WAIT",
                    "proposal_allowed": False,
                    "street_rating": "STRONG BUY",
                    "held": False,
                },
            },
        ],
        "counts": {"proposal_eligible": 0, "near_trigger": 1},
    }

    def _fake_list(query=None):
        return fake

    monkeypatch.setattr(
        "lib.data_broker.watch_intelligence.list_watch_intelligence",
        _fake_list,
        raising=False,
    )
    # Also patch via scripts path import used inside collector
    import scripts.lib.data_broker.watch_intelligence as wi_mod

    monkeypatch.setattr(wi_mod, "list_watch_intelligence", _fake_list)

    domain = cp._domain_watch_intelligence()
    assert domain.quality_state == "AVAILABLE"
    data = domain.data or {}
    assert data.get("projection") == "cio_s7_status_v1"
    by = {r["symbol"]: r["status"] for r in data.get("items") or []}
    assert by["NEARX"] == "NEAR"
    assert by["WAITX"] == "BLOCK"

    snap = {"domains": {"watch_intelligence": domain.to_dict()}}
    ev = build_evidence_from_snapshot(snap)
    s7 = [
        c
        for c in CIOSituationDetector().collect_candidates(ev)
        if str(c.get("situation_type")).startswith("S7")
    ]
    assert len(s7) == 1
    assert s7[0]["symbols"] == ["NEARX"]


def test_domain_watch_intelligence_fail_soft(monkeypatch):
    from scripts.lib.data_broker import cio_portfolio as cp
    import lib.data_broker.watch_intelligence as wi_lib
    import scripts.lib.data_broker.watch_intelligence as wi_scripts

    def _boom(query=None):
        raise RuntimeError("broker_down")

    # Collector prefers `lib.` import when PYTHONPATH includes scripts/
    monkeypatch.setattr(wi_lib, "list_watch_intelligence", _boom)
    monkeypatch.setattr(wi_scripts, "list_watch_intelligence", _boom)

    domain = cp._domain_watch_intelligence()
    assert domain.quality_state == "DATA_UNAVAILABLE"
    assert "watch_intelligence_domain_error" in (domain.gap_reason or "")


def test_s3_fixture_unaffected_by_watch_shape(cfg):
    """Fix #1 regression guard: reentry READY still yields S3 with watch domain present."""
    from scripts.lib.cio_situation_detector import CIOSituationDetector

    ev = {
        "reentry_decision_desk": {
            "rows": [{"symbol": "IRDM", "status": "READY"}],
        },
        "watch_intelligence": {
            "items": [{"symbol": "ANET", "status": "BLOCK"}],
        },
    }
    cands = CIOSituationDetector().collect_candidates(ev)
    s3 = [c for c in cands if str(c.get("situation_type")).startswith("S3")]
    s7 = [c for c in cands if str(c.get("situation_type")).startswith("S7")]
    assert len(s3) == 1 and s3[0]["symbols"] == ["IRDM"]
    assert s7 == []
