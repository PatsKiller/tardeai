"""WAVE E — catalyst pipeline (E1–E5).

E1 research-directive slugs never reach identity resolution.
E2 extractor constrained to known ticker universe (English/benefit acronyms out).
E3 deliberate one-at-a-time register; no rule widening.
E5 graph/momentum resolve via served state root, not cron cwd.
Identity guard unchanged: unregistered symbols are skipped, never guessed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.catalyst_graph import bind_catalyst, build_graph
from scripts.lib.hermes_discovery.symbol_validation import (
    DENYLIST,
    gate_catalyst_symbol,
    is_research_directive_slug,
    validate_ticker,
)
from scripts.lib.identity_registry import empty_registry, register
from scripts.mint_identity_registry import register_one_verified


# ── E1: research-directive slugs ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "slug",
    [
        "D124_EARNINGS_SEASON_OPTION_TRADING_FRAMEWORK",
        "D23_DEFENSE_AEROSPACE",
        "SU_INDUSTRY_INSURANCE_BROKERS",
        "SU_SECTOR_UTILITIES",
        "K_LEGAL_DOCUMENTS_AND_ELDER_LAW_PLANNING_F",
        "AI_DATACENTER_BUILDOUT",
        "BOND_RATES",
        "TAX_LOSS_HARVEST",
        "SSDI_CASH_SHIELD",
        "COVERED_CALL_INCOME",
    ],
)
def test_e1_research_directive_slugs_detected(slug):
    assert is_research_directive_slug(slug)


def test_e1_real_tickers_are_not_directive_slugs():
    for sym in ("NOC", "SCHD", "AAPL", "BRK.B", "LIVE", "SUGP", "EW"):
        assert not is_research_directive_slug(sym)


def test_e1_directive_slug_never_binds_to_identity():
    """Refuse before identity lookup — no wrong-company edge."""
    doc = empty_registry()
    # Even if somehow registered (must not happen), slug short-circuits first.
    register(doc, {"symbol": "NOC", "company": "Northrop Grumman"})
    row = {
        "id": 1,
        "symbol": "D124_EARNINGS_SEASON_OPTION_TRADING_FRAMEWORK",
        "catalyst_type": "other",
        "headline": "theme noise",
        "source": "topic_google_news_rss",
        "published_at": "2026-08-27T13:00:00+00:00",
    }
    assert bind_catalyst(row, doc) is None
    graph = build_graph([row], doc)
    assert graph["node_count"] == 0
    assert graph["skipped"].get("research_directive_slug") == 1
    # Must NOT be counted as symbol_not_registered (that path is identity resolution).
    assert "symbol_not_registered" not in graph["skipped"]


def test_e1_gate_catalyst_refuses_directive_slug():
    ok, reason = gate_catalyst_symbol("D107_ENERGY_TRANSITION_AND_TRADITIONAL_ENERGY")
    assert not ok
    assert "research-directive" in reason.lower() or "topic" in reason.lower()


# ── E2: known ticker universe / English junk ─────────────────────────────────

@pytest.mark.parametrize("token", ["SSDI", "IRMAA", "NEED", "FIND", "TO", "ASSET"])
def test_e2_english_benefit_acronyms_in_denylist(token):
    assert token in DENYLIST


def test_e2_validate_ticker_refuses_ssdi_without_profile(monkeypatch):
    import scripts.lib.hermes_discovery.symbol_validation as sv

    monkeypatch.setattr(sv, "_lookup_profile", lambda sym: None)
    result = validate_ticker("SSDI")
    assert result["verdict"] == "INVALID"
    assert result["valid"] is False


def test_e2_gate_refuses_unknown_english_word(monkeypatch):
    import scripts.lib.hermes_discovery.symbol_validation as sv

    monkeypatch.setattr(sv, "_lookup_profile", lambda sym: None)
    ok, reason = gate_catalyst_symbol("NEED")
    assert not ok
    assert "denylist" in reason.lower() or "not found" in reason.lower()


def test_e2_real_short_tickers_not_blocked_by_slug_rule():
    """Do not widen a rule: LIVE/GIFT/EW are listed names, not junk English."""
    assert not is_research_directive_slug("LIVE")
    assert not is_research_directive_slug("GIFT")
    assert not is_research_directive_slug("EW")


# ── E3: deliberate one-at-a-time; no silent mint ─────────────────────────────

def test_e3_register_refuses_directive_slug():
    report = register_one_verified("D124_EARNINGS_SEASON_OPTION_TRADING_FRAMEWORK", apply=False)
    assert report["ok"] is False
    assert "research-directive" in report["error"].lower() or "slug" in report["error"].lower()
    assert report["applied"] is False


def test_e3_register_refuses_absent_from_universe(monkeypatch):
    import scripts.mint_identity_registry as mir

    monkeypatch.setattr(mir, "_profile_row", lambda sym: None)
    report = register_one_verified("ZZZZNOTREAL", apply=False)
    assert report["ok"] is False
    assert "symbol_profiles" in report["error"]
    assert report["applied"] is False


def test_e3_register_dry_run_does_not_write(monkeypatch, tmp_path):
    import scripts.mint_identity_registry as mir
    from scripts.lib import identity_registry as ir

    monkeypatch.setattr(
        mir,
        "_profile_row",
        lambda sym: {"symbol": "FTRK", "description_1s": "Fat Truck Inc", "sector": "X"},
    )
    # Isolate registry to tmp so we never touch production.
    monkeypatch.setattr(ir, "registry_path", lambda root=None: tmp_path / "identity_registry.json")
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "identity_registry.json"))
    (tmp_path / "identity_registry.json").write_text(
        json.dumps(ir.empty_registry()), encoding="utf-8"
    )

    report = register_one_verified("FTRK", apply=False)
    assert report["ok"] is True
    assert report["applied"] is False
    assert report["would_register"] is True
    # Dry-run must leave registry empty.
    doc = json.loads((tmp_path / "identity_registry.json").read_text())
    assert doc.get("by_symbol") == {}


# ── identity guard unchanged ─────────────────────────────────────────────────

def test_identity_guard_still_skips_unregistered_real_ticker():
    """Refusing unrecognized symbols remains correct — do not widen."""
    doc = empty_registry()
    register(doc, {"symbol": "NOC", "company": "Northrop Grumman"})
    graph = build_graph(
        [{
            "id": 9,
            "symbol": "FTRK",
            "catalyst_type": "earnings",
            "headline": "beat",
            "source": "news",
            "published_at": "2026-08-27T13:00:00+00:00",
        }],
        doc,
    )
    assert graph["node_count"] == 0
    assert graph["skipped"]["symbol_not_registered"] == 1


# ── E5: served-path resolution ───────────────────────────────────────────────

def test_e5_projection_path_uses_state_root_not_checkout(monkeypatch, tmp_path):
    from scripts import build_catalyst_graph as bcg

    monkeypatch.setattr(bcg, "_state_root", lambda: tmp_path)
    path = bcg.projection_path()
    assert path == tmp_path / "data" / "cio" / "catalyst_graph_latest.json"
    assert "trade-ai-v12-rebuild" not in str(path)


def test_e5_diagnose_staleness_reports_schedule_gap(monkeypatch, tmp_path):
    from scripts import build_catalyst_graph as bcg

    monkeypatch.setattr(bcg, "_state_root", lambda: tmp_path)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "data" / "hermes" / "momentum_catalysts").mkdir(parents=True)
    report = bcg.diagnose_writer_staleness()
    assert report["graph"]["scheduled"] is False
    assert "NOT in crontab" in report["graph"]["schedule_note"]
    assert report["momentum_jsonl"]["path"].endswith("data/hermes/momentum_catalysts")


def test_e5_momentum_engine_last_run_relative_is_cio_served():
    # Import path helpers only — engine main() needs psycopg2 at runtime, not here.
    from scripts.catalyst_momentum_engine import LAST_RUN_RELATIVE

    assert LAST_RUN_RELATIVE == Path("data") / "cio" / "catalyst_momentum_last_run.json"
