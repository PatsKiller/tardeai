"""Fix #1: reentry desk → CIO snapshot evidence for S3 (READ_ONLY_ADVISORY).

Notify stays off. No broker mutation. No S7/watch changes.
"""
from __future__ import annotations

import json
from pathlib import Path

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


def test_normalize_reentry_s3_status_map():
    from scripts.lib.data_broker.reentry_decision_desk import normalize_reentry_s3_status

    assert normalize_reentry_s3_status({"intel": {"state": "READY TO REVIEW"}}) == "READY"
    assert normalize_reentry_s3_status({"intel": {"state": "NEAR ENTRY"}}) == "NEAR"
    assert normalize_reentry_s3_status({"intel": {"state": "OVERSOLD REVIEW"}}) == "NEAR"
    assert normalize_reentry_s3_status({"intel": {"state": "WAIT"}}) == "BLOCK"
    assert normalize_reentry_s3_status({"intel": {"state": "CURRENTLY HELD"}}) == "BLOCK"
    assert normalize_reentry_s3_status({"status": "READY"}) == "READY"
    assert normalize_reentry_s3_status({"status": "NEAR"}) == "NEAR"
    assert normalize_reentry_s3_status({"status": "BLOCK"}) == "BLOCK"
    assert normalize_reentry_s3_status(None) == "BLOCK"
    assert normalize_reentry_s3_status({}) == "BLOCK"


def test_project_reentry_desk_ready_near_block():
    from scripts.lib.data_broker.reentry_decision_desk import project_reentry_desk_for_cio

    desk = {
        "ok": True,
        "computed_at": "2026-08-20T12:00:00+00:00",
        "rows": [
            {"symbol": "IRDM", "held": False, "intel": {"state": "READY TO REVIEW"}},
            {"symbol": "AXTI", "held": False, "intel": {"state": "NEAR ENTRY"}},
            {"symbol": "SCHG", "held": True, "intel": {"state": "CURRENTLY HELD"}},
            {"symbol": "FATN", "held": False, "intel": {"state": "WAIT"}},
        ],
    }
    out = project_reentry_desk_for_cio(desk)
    by_sym = {r["symbol"]: r["status"] for r in out["rows"]}
    assert by_sym["IRDM"] == "READY"
    assert by_sym["AXTI"] == "NEAR"
    assert by_sym["SCHG"] == "BLOCK"
    assert by_sym["FATN"] == "BLOCK"
    assert out["counts"]["ready"] == 1
    assert out["counts"]["near"] == 1
    assert out["counts"]["block"] == 2
    assert out["candidates"] == out["rows"]


def test_collect_candidates_s3_ready_fixture(cfg):
    from scripts.lib.cio_situation_detector import CIOSituationDetector

    ev = {
        "reentry_decision_desk": {
            "rows": [
                {"symbol": "IRDM", "status": "READY"},
                {"symbol": "AXTI", "status": "NEAR"},
                {"symbol": "FATN", "status": "BLOCK"},
            ]
        }
    }
    cands = CIOSituationDetector().collect_candidates(ev)
    s3 = [c for c in cands if str(c.get("situation_type")).startswith("S3")]
    syms = {c["symbols"][0] for c in s3}
    assert "IRDM" in syms
    assert "AXTI" in syms
    assert "FATN" not in syms
    ready = next(c for c in s3 if c["symbols"] == ["IRDM"])
    assert "reentry_READY" in (ready.get("fire_reasons") or [])


def test_collect_candidates_block_only_no_s3(cfg):
    from scripts.lib.cio_situation_detector import CIOSituationDetector

    ev = {
        "reentry_decision_desk": {
            "rows": [
                {"symbol": "SCHG", "status": "BLOCK"},
                {"symbol": "FATN", "status": "BLOCK"},
            ]
        }
    }
    cands = CIOSituationDetector().collect_candidates(ev)
    s3 = [c for c in cands if str(c.get("situation_type")).startswith("S3")]
    assert s3 == []


def test_missing_desk_no_s3_no_raise(cfg, tmp_path, monkeypatch):
    from scripts.lib.data_broker import cio_portfolio as cp
    from scripts.lib.cio_situation_detector import (
        CIOSituationDetector,
        build_evidence_from_snapshot,
    )

    monkeypatch.setattr(cp, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(cp, "SNAPSHOT_DIR", tmp_path / "broker")
    monkeypatch.setattr(cp, "SNAPSHOT_PATH", tmp_path / "broker" / "cio_snapshot.json")

    domain = cp._domain_reentry()
    assert domain.quality_state == "DATA_UNAVAILABLE"

    # Snapshot path with only reentry collector result (empty evidence for S3)
    snap = {
        "domains": {
            "reentry_decision_desk": domain.to_dict(),
        }
    }
    ev = build_evidence_from_snapshot(snap)
    # Unavailable envelope has no usable rows
    cands = CIOSituationDetector().collect_candidates(ev)
    s3 = [c for c in cands if str(c.get("situation_type")).startswith("S3")]
    assert s3 == []


def test_domain_reentry_projects_latest_json(tmp_path, monkeypatch):
    from scripts.lib.data_broker import cio_portfolio as cp

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    desk = {
        "ok": True,
        "version": "reentry-decision-desk-v2-data-broker",
        "computed_at": "2026-08-20T19:00:00+00:00",
        "rows": [
            {"symbol": "MOGU", "held": False, "intel": {"state": "READY TO REVIEW"}, "price": 1.0},
            {"symbol": "WAITX", "held": False, "intel": {"state": "WAIT"}, "price": 2.0},
        ],
    }
    (runtime / "reentry_decision_desk_latest.json").write_text(json.dumps(desk), encoding="utf-8")
    monkeypatch.setattr(cp, "RUNTIME_DIR", runtime)

    domain = cp._domain_reentry()
    assert domain.quality_state == "AVAILABLE"
    data = domain.data or {}
    by_sym = {r["symbol"]: r["status"] for r in data.get("rows") or []}
    assert by_sym["MOGU"] == "READY"
    assert by_sym["WAITX"] == "BLOCK"

    # Evidence unwrap path used by build_evidence_from_broker
    from scripts.lib.cio_situation_detector import (
        CIOSituationDetector,
        build_evidence_from_snapshot,
    )

    snap = {"domains": {"reentry_decision_desk": domain.to_dict()}}
    ev = build_evidence_from_snapshot(snap)
    assert ev.get("reentry_decision_desk") is not None
    s3 = [
        c
        for c in CIOSituationDetector().collect_candidates(ev)
        if str(c.get("situation_type")).startswith("S3")
    ]
    assert len(s3) == 1
    assert s3[0]["symbols"] == ["MOGU"]
    assert "reentry_READY" in (s3[0].get("fire_reasons") or [])


def test_project_none_fail_soft():
    from scripts.lib.data_broker.reentry_decision_desk import project_reentry_desk_for_cio

    out = project_reentry_desk_for_cio(None)
    assert out["rows"] == []
    assert out["candidates"] == []
    assert out["counts"]["total"] == 0
