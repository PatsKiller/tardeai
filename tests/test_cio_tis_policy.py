"""Unit tests for TIS policy + coverage SLA (Phase B)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.cio_tis_policy import (
    EMBEDDED_DEFAULTS,
    evaluate_coverage_sla,
    load_tis_policy,
    save_tis_policy,
    validate_tis_policy,
)


def test_embedded_defaults_validate():
    ok, errs = validate_tis_policy(EMBEDDED_DEFAULTS)
    assert ok, errs
    assert EMBEDDED_DEFAULTS["requirements"]["coverage_sla"]["holdings_current_pct"] == 100


def test_holdings_parity_note_in_layout():
    titles = {x["id"] for x in EMBEDDED_DEFAULTS["layout"]}
    assert "holdings_parity" in titles
    assert "telegram" in titles


def test_save_and_load_override(tmp_path: Path):
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)
    res = save_tis_policy(
        {
            "requirements": {
                "coverage_sla": {"watch_desk_current_pct": 75},
                "telegram": {"enabled": True},
            },
            "notes": "operator tweak",
        },
        root=tmp_path,
        updated_by="test",
    )
    assert res["ok"] is True
    pol = load_tis_policy(root=tmp_path)
    assert pol["requirements"]["coverage_sla"]["watch_desk_current_pct"] == 75
    assert pol["requirements"]["coverage_sla"]["holdings_current_pct"] == 100
    assert pol["updated_by"] == "test"
    assert pol["notes"] == "operator tweak"


def test_reject_impossible_sla(tmp_path: Path):
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)
    res = save_tis_policy(
        {"requirements": {"coverage_sla": {"holdings_current_pct": 10}}},
        root=tmp_path,
    )
    assert res["ok"] is False
    assert any("holdings_current_pct" in e for e in res["errors"])


def test_evaluate_sla_not_weight_gated():
    report = {
        "rows": [
            {"symbol": "V", "memberships": ["HELD"], "coverage_state": "RESEARCH_REQUIRED"},
            {"symbol": "DXCM", "memberships": ["HELD"], "coverage_state": "CURRENT"},
            {"symbol": "SCHD", "memberships": ["HELD"], "coverage_state": "CURRENT"},
            {"symbol": "AXTI", "memberships": ["REENTRY"], "reentry_state": "NEAR", "coverage_state": "RESEARCH_REQUIRED"},
        ]
    }
    sla = evaluate_coverage_sla(report)
    assert sla["buckets"]["holdings"]["n"] == 3
    assert sla["buckets"]["holdings"]["current_n"] == 2
    assert sla["sla_ok"] is False
    held_breach = next(b for b in sla["breaches"] if b["bucket"] == "holdings")
    assert "V" in held_breach["missing"]
    assert "concentration" in sla["note"].lower() or "not" in sla["note"].lower()


def test_digest_payload_builds(tmp_path: Path, monkeypatch):
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)
    # Minimal fake coverage so digest does not need live holdings
    from scripts import cio_tis_telegram_digest as dig

    def fake_report(**kwargs):
        return {
            "rows": [
                {"symbol": "V", "memberships": ["HELD"], "coverage_state": "RESEARCH_REQUIRED"},
                {"symbol": "AXTI", "memberships": ["REENTRY"], "reentry_state": "NEAR", "coverage_state": "RESEARCH_REQUIRED"},
            ]
        }

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_coverage.build_coverage_report",
        fake_report,
    )
    payload = dig.build_digest_payload(root=tmp_path)
    assert payload["should_send"] is True
    assert "V" in payload["body"] or "Held" in payload["body"]
