"""CADI-011 / CADI-012 — producer + consumer hooks for SecurityResearchSpine.

Hermetic: library wiring only. Organic OBSERVED requires promote + CROSS_ASSET_SPINE=1
plus a live Hermes complete that lands a spine row desks then read.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cross_asset.hooks import (
    notify_hermes_result_completed,
    overlay_thesis_fields_from_spine,
    spine_rows_for_root,
)
from scripts.lib.cross_asset.security_research_spine import default_path, upsert_from_hermes

REG = "ecb5ba89-96c6-536c-ba76-89e468a81bf1"


@pytest.fixture()
def spine_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CROSS_ASSET_SPINE", "1")
    monkeypatch.delenv("CROSS_ASSET_SHADOW", raising=False)
    (tmp_path / "data" / "cio").mkdir(parents=True)

    def _resolve(symbol, *, root=None):
        return {
            "symbol": str(symbol or "").upper(),
            "subject_guid": REG,
            "issuer_guid": None,
            "security_guid": REG,
            "identity_status": "CONFIRMED",
            "identity_lookup": "RESOLVED",
        }

    monkeypatch.setattr("scripts.lib.identity_carriage.resolve_security_identity", _resolve)
    return tmp_path


def test_cadi011_hermes_notify_upserts_when_flag_on(spine_env: Path):
    result = {
        "symbol": "NFLX",
        "result_id": "rr_hook_1",
        "research_id": "res_hook_1",
        "status": "completed",
        "summary": "Hooked Hermes thesis for all desks.",
        "confidence": 0.71,
        "subject_guid": REG,
    }
    out = notify_hermes_result_completed(result, root=spine_env)
    assert out.get("ok") is True
    assert not out.get("skipped")
    ledger = default_path(spine_env)
    assert ledger.exists()
    text = ledger.read_text(encoding="utf-8")
    assert "Hooked Hermes thesis" in text
    assert "NFLX" in text
    assert REG in text


def test_cadi011_skipped_when_spine_flag_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CROSS_ASSET_SPINE", "0")
    monkeypatch.delenv("CROSS_ASSET_SHADOW", raising=False)
    out = notify_hermes_result_completed(
        {"symbol": "NFLX", "summary": "x", "result_id": "rr"},
        root=tmp_path,
    )
    assert out.get("skipped") is True
    assert out.get("reason") == "CROSS_ASSET_SPINE_off"


def test_cadi012_overlay_prefers_spine_summary(spine_env: Path):
    upsert_from_hermes(
        "NFLX",
        {
            "result_id": "rr_ov",
            "research_id": "res_ov",
            "status": "completed",
            "summary": "Shared spine summary wins.",
            "thesis_stance": "HOLD",
            "confidence": 0.55,
            "subject_guid": REG,
        },
        root=spine_env,
    )
    local = {
        "symbol": "NFLX",
        "thesis_summary": "Stale silo-local copy",
        "thesis_stance": "BUY",
        "thesis_state": "THIN",
    }
    out = overlay_thesis_fields_from_spine(local, "NFLX", root=spine_env, silo="watchlist")
    assert out["thesis_summary"] == "Shared spine summary wins."
    assert out["thesis_stance"] == "HOLD"
    assert out["security_research_spine"] is True
    assert out["spine_silo"] == "watchlist"


def test_cadi012_spine_rows_for_options(spine_env: Path):
    upsert_from_hermes(
        "NFLX",
        {
            "result_id": "rr_opt",
            "research_id": "res_opt",
            "status": "completed",
            "summary": "Options desk shared thesis.",
            "subject_guid": REG,
        },
        root=spine_env,
    )
    rows = spine_rows_for_root(spine_env)
    assert any(r.get("symbol") == "NFLX" for r in rows)
    nflx = next(r for r in rows if r.get("symbol") == "NFLX")
    assert "cio_research" in nflx["source_lanes"]
    assert "security_research_spine" in nflx["source_lanes"]
    assert nflx["summary"] == "Options desk shared thesis."


def test_wiring_grep_gate_producers_consumers():
    """CI gate: CADI-011/012 must stay hooked outside scripts/lib/cross_asset/."""
    root = Path(__file__).resolve().parents[1]
    hermes = (root / "scripts/lib/cio_hermes_research.py").read_text(encoding="utf-8")
    attach = (root / "scripts/lib/symbol_thesis_attach.py").read_text(encoding="utf-8")
    opts = (root / "scripts/options_engine.py").read_text(encoding="utf-8")
    assert "notify_hermes_result_completed" in hermes
    assert "overlay_thesis_fields_from_spine" in attach
    assert "spine_rows_for_root" in opts
    assert "overlay_thesis_fields_from_spine" in opts
