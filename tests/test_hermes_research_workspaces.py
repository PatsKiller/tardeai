#!/usr/bin/env python3
"""White-Space Discovery Stage 1 — workspaces: routing, isolation, stamping.

Covers: registry load + shape, domain→workspace routing, the isolation write
gate (nyc_loft_law can NEVER write a trading surface), the trading-signal
consumption block, fail-closed yaml validation, the meta_json workspace stamp
via inbox._enrich_domain_meta, the new candidate types mirror, the workspace
filter on inbox.list_candidates, and the no-broker-imports guarantee.

    .venv/bin/python -m pytest tests/test_hermes_research_workspaces.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db_adapter  # noqa: E402
from lib.hermes_discovery import inbox, workspaces  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_cache():
    workspaces._reset_cache()
    yield
    workspaces._reset_cache()


# ── registry load + routing ──────────────────────────────────────────────────

def test_registry_loads_both_workspaces():
    ws = workspaces.load_workspaces()
    assert set(ws) == {"trade_ai", "nyc_loft_law"}
    assert workspaces.default_workspace() == "trade_ai"
    assert ws["trade_ai"]["trading_related"] is True
    assert ws["nyc_loft_law"]["trading_related"] is False
    assert ws["nyc_loft_law"]["requires_professional_review_label"] is True
    assert ws["nyc_loft_law"]["no_legal_advice_label"] is True
    # auto_promote is hard-false everywhere
    assert all(spec["auto_promote"] is False for spec in ws.values())


def test_trade_ai_owns_market_domains():
    for domain in ("portfolio_holdings", "watchlist", "sectors", "macro",
                   "taxes", "retirement", "legal", "system_ops"):
        assert workspaces.workspace_for_domain(domain) == "trade_ai"


def test_loft_law_owns_housing_law_domains():
    for domain in ("legal_housing", "housing", "nyc_regulation", "case_law",
                   "tenant_rights", "landlord_compliance", "zoning"):
        assert workspaces.workspace_for_domain(domain) == "nyc_loft_law"


def test_unclaimed_domain_routes_to_default():
    assert workspaces.workspace_for_domain("some_future_domain") == "trade_ai"
    assert workspaces.workspace_for_domain("") == "trade_ai"


def test_get_workspace_unknown_fails_closed():
    with pytest.raises(workspaces.WorkspaceConfigError):
        workspaces.get_workspace("nope")


# ── isolation enforcement: writes ────────────────────────────────────────────

@pytest.mark.parametrize("surface", sorted(workspaces.TRADE_SURFACES))
def test_loft_law_can_never_write_trading_surfaces(surface):
    with pytest.raises(workspaces.WorkspaceIsolationError):
        workspaces.assert_can_write("nyc_loft_law", surface)


def test_loft_law_writes_only_its_own_surfaces():
    for surface in ("legal_research_topic_registry", "article_brief_queue",
                    "source_registry", "website_content_candidate_queue"):
        workspaces.assert_can_write("nyc_loft_law", surface)  # no raise
    with pytest.raises(workspaces.WorkspaceIsolationError):
        workspaces.assert_can_write("nyc_loft_law", "command_center")


def test_trade_ai_surfaces():
    for surface in ("command_center", "topic_monitor", "watch_directives",
                    "research_sources"):
        workspaces.assert_can_write("trade_ai", surface)  # no raise
    # not everything trading-shaped is declared — undeclared surfaces raise too
    with pytest.raises(workspaces.WorkspaceIsolationError):
        workspaces.assert_can_write("trade_ai", "article_brief_queue")
    with pytest.raises(workspaces.WorkspaceIsolationError):
        workspaces.assert_can_write("trade_ai", "proposals")


# ── isolation enforcement: trading-signal consumption ────────────────────────

def test_loft_law_candidates_never_tradeable():
    with pytest.raises(workspaces.WorkspaceIsolationError):
        workspaces.assert_tradeable_signal(
            {"meta_json": {"workspace_id": "nyc_loft_law"}})
    # workspace derived from a loft-law domain is blocked the same way
    with pytest.raises(workspaces.WorkspaceIsolationError):
        workspaces.assert_tradeable_signal(
            {"meta_json": {"research_domain": "case_law"}})


def test_trade_ai_candidates_are_tradeable_consumable():
    workspaces.assert_tradeable_signal(
        {"meta_json": {"workspace_id": "trade_ai"}})  # no raise
    workspaces.assert_tradeable_signal(
        {"meta_json": {"research_domain": "watchlist"}})  # no raise


# ── fail-closed yaml validation ──────────────────────────────────────────────

def _write(tmp_path, body: str) -> Path:
    p = tmp_path / "ws.yaml"
    p.write_text(body, encoding="utf-8")
    return p


_VALID_STANZA = """
version: 1
default_workspace: trade_ai
workspaces:
  trade_ai:
    trading_related: true
    domains: [watchlist]
    output_surfaces: [command_center]
"""


def test_missing_file_fails_closed(tmp_path):
    with pytest.raises(workspaces.WorkspaceConfigError):
        workspaces.load_workspaces(tmp_path / "absent.yaml")


def test_non_mapping_yaml_fails_closed(tmp_path):
    with pytest.raises(workspaces.WorkspaceConfigError):
        workspaces.load_workspaces(_write(tmp_path, "- just\n- a\n- list\n"))


def test_auto_promote_true_fails_closed(tmp_path):
    body = _VALID_STANZA.replace("trading_related: true",
                                 "trading_related: true\n    auto_promote: true")
    with pytest.raises(workspaces.WorkspaceConfigError, match="auto_promote"):
        workspaces.load_workspaces(_write(tmp_path, body))


def test_non_trading_workspace_listing_trade_surface_fails_closed(tmp_path):
    body = _VALID_STANZA + """
  sneaky:
    trading_related: false
    domains: [case_law]
    output_surfaces: [watch_directives]
"""
    with pytest.raises(workspaces.WorkspaceConfigError, match="trading"):
        workspaces.load_workspaces(_write(tmp_path, body))


def test_duplicate_domain_claim_fails_closed(tmp_path):
    body = _VALID_STANZA + """
  other:
    trading_related: false
    domains: [watchlist]
    output_surfaces: [source_registry]
"""
    with pytest.raises(workspaces.WorkspaceConfigError, match="claimed by both"):
        workspaces.load_workspaces(_write(tmp_path, body))


def test_unknown_default_fails_closed(tmp_path):
    body = _VALID_STANZA.replace("default_workspace: trade_ai",
                                 "default_workspace: ghost")
    with pytest.raises(workspaces.WorkspaceConfigError, match="default_workspace"):
        workspaces.load_workspaces(_write(tmp_path, body))


def test_missing_trading_related_fails_closed(tmp_path):
    body = _VALID_STANZA.replace("    trading_related: true\n", "")
    with pytest.raises(workspaces.WorkspaceConfigError, match="trading_related"):
        workspaces.load_workspaces(_write(tmp_path, body))


# ── inbox enrichment stamps the workspace onto every candidate ───────────────

def _enrich(meta: dict, label="CPI research topic", ctype="TOPIC_CANDIDATE"):
    view = {"candidate_type": ctype, "label": label, "summary": None,
            "normalized_key": label.lower(), "source_domain": None,
            "source_url": None, "evidence": [], "seed_symbols": [],
            "extracted_symbols": [], "meta": meta, "is_operator": False,
            "seen_count": 1}
    return inbox._enrich_domain_meta(dict(meta), view, "RESEARCH_ONLY")


def test_candidates_are_stamped_with_workspace():
    meta, _level, domain = _enrich({"research_domain": "macro"})
    assert domain == "macro"
    assert meta["workspace_id"] == "trade_ai"
    assert meta["workspace_domain"] == "macro"


def test_workspace_stamp_is_sticky_when_valid():
    meta, _level, _domain = _enrich({"research_domain": "macro",
                                     "workspace_id": "nyc_loft_law"})
    assert meta["workspace_id"] == "nyc_loft_law"  # explicit pin kept


def test_bogus_workspace_pin_is_rerouted_by_domain():
    meta, _level, _domain = _enrich({"research_domain": "macro",
                                     "workspace_id": "not_a_workspace"})
    assert meta["workspace_id"] == "trade_ai"


# ── new candidate types (migration mirror) ───────────────────────────────────

def test_white_space_types_mirrored_in_inbox():
    new_types = {"STRATEGY_CANDIDATE", "PRIVATE_COMPANY_PROXY_CANDIDATE",
                 "LEGAL_TOPIC_CANDIDATE", "CASE_LAW_CANDIDATE",
                 "STATUTE_UPDATE_CANDIDATE", "WEBSITE_CONTENT_CANDIDATE",
                 "GAP_CANDIDATE"}
    assert new_types <= inbox.CANDIDATE_TYPES
    # legacy types unchanged
    assert {"SOURCE_CANDIDATE", "TREND_CANDIDATE", "TICKER_CANDIDATE",
            "TOPIC_CANDIDATE", "CONNECTOR_CANDIDATE"} <= inbox.CANDIDATE_TYPES
    # the MISSING_* family must NOT exist as candidate types (meta.gap_type only)
    assert not any(t.startswith("MISSING_") for t in inbox.CANDIDATE_TYPES)


def test_migration_file_matches_inbox_types():
    sql = (ROOT / "migrations" / "2026_07_05_white_space_types.sql").read_text()
    for t in inbox.CANDIDATE_TYPES:
        assert f"'{t}'" in sql, f"{t} missing from the migration CHECK list"


def test_unknown_type_still_rejected():
    with pytest.raises(inbox.DiscoveryInboxError):
        inbox.upsert_candidate("MISSING_STOP_CANDIDATE", "x")


# ── list API workspace filter ────────────────────────────────────────────────

def test_list_candidates_filters_by_workspace(monkeypatch):
    seen: dict = {}

    def capture(sql, params=None, fetch=None):
        seen["sql"], seen["params"] = sql, params
        return []

    monkeypatch.setattr(db_adapter, "_execute", capture)
    inbox.list_candidates(workspace="nyc_loft_law", limit=5)
    assert "meta_json->>'workspace_id' = %s" in seen["sql"]
    assert "nyc_loft_law" in seen["params"]


# ── advisory-only guarantee ──────────────────────────────────────────────────

def test_no_broker_imports_in_stage1_white_space_files():
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?(brokers\b|schwab\w*|"
        r"alpaca\w*)", re.MULTILINE)
    targets = [
        ROOT / "scripts" / "lib" / "hermes_discovery" / "workspaces.py",
        ROOT / "scripts" / "lib" / "hermes_discovery" / "worker_pool.py",
        ROOT / "scripts" / "lib" / "hermes_discovery" / "inbox.py",
        ROOT / "scripts" / "hermes_research_worker_pool.py",
    ]
    offenders = [p.name for p in targets if forbidden.search(p.read_text())]
    assert not offenders, f"broker imports in advisory-only files: {offenders}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
