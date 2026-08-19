"""Integration tests for symbol-thesis → CIO books / review / research / CC.

No live broker writes. Fixtures only where possible; live-root tests are opt-in.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def thesis_store(tmp_path):
    from scripts.lib.cio_theses import CIOThesisStore
    return CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "proj.json",
    )


def test_reconcile_no_churn_on_identical(thesis_store, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis

    publish_symbol_thesis(
        "SCHG",
        summary="SCHG is the primary large-cap growth sleeve for the book with clear invalidation.",
        stance="hold",
        portfolio_role="GROWTH",
        why_owned_or_watched="Growth exposure",
        store=thesis_store,
        notify=False,
    )
    r1 = reconcile_symbol_thesis(
        "SCHG",
        trigger="test",
        evidence={
            "summary": "SCHG is the primary large-cap growth sleeve for the book with clear invalidation.",
            "stance": "hold",
            "why_owned_or_watched": "Growth exposure",
            "portfolio_role": "GROWTH",
        },
        store=thesis_store,
        root=tmp_path,
        publish=True,
        notify=False,
    )
    assert r1["classification"] == "NO_MATERIAL_CHANGE"
    assert r1["version_published"] is False

    # Replay identical → still no churn
    r2 = reconcile_symbol_thesis(
        "SCHG",
        trigger="test_replay",
        evidence={
            "summary": "SCHG is the primary large-cap growth sleeve for the book with clear invalidation.",
            "stance": "hold",
            "why_owned_or_watched": "Growth exposure",
            "portfolio_role": "GROWTH",
        },
        store=thesis_store,
        root=tmp_path,
        publish=True,
        notify=False,
    )
    assert r2["classification"] == "NO_MATERIAL_CHANGE"
    assert r2["version_published"] is False


def test_reconcile_material_strengthen_and_broken(thesis_store, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis

    publish_symbol_thesis(
        "CSCO",
        summary="CSCO was a prior holding for networking exposure; thesis intact pending confirmation.",
        stance="watch",
        portfolio_role="CORE",
        why_exited="DATA_UNAVAILABLE",
        store=thesis_store,
        notify=False,
    )
    r = reconcile_symbol_thesis(
        "CSCO",
        trigger="research_completion",
        evidence={
            "summary": "CSCO thesis strengthened: durable cash flows and AI networking demand support re-entry study.",
            "stance": "add",
            "evidence_for": ["research:r1: AI networking demand"],
            "why_exited": "Trimmed for concentration; thesis not broken",
            "portfolio_role": "CORE",
        },
        store=thesis_store,
        root=tmp_path,
        notify=False,
    )
    assert r["classification"] == "THESIS_STRENGTHENED"
    assert r["version_published"] is True

    r2 = reconcile_symbol_thesis(
        "CSCO",
        trigger="contradiction",
        evidence={
            "summary": "CSCO thesis broken — competitive displacement invalidated prior networking thesis.",
            "stance": "avoid",
            "counter_evidence": ["competitive displacement"],
            "portfolio_role": "CORE",
        },
        store=thesis_store,
        root=tmp_path,
        notify=False,
    )
    assert r2["classification"] == "THESIS_BROKEN"
    assert r2["version_published"] is True


def test_specific_research_gap_not_vague(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_research import build_research_request

    fields = {
        "symbol_thesis_id": "symbol_schg",
        "symbol_thesis_version": None,
        "thesis_state": "RESEARCH_REQUIRED",
        "portfolio_role": "GROWTH",
        "memberships": ["HELD", "WATCHLIST"],
        "thesis_stance": None,
        "counter_evidence": [],
    }
    req = build_research_request(
        "SCHG",
        gap="Create living symbol thesis (role, why owned/exited, invalidation, research gaps)",
        thesis_fields=fields,
    )
    q = req["specific_question"].lower()
    assert "schg" in q
    assert q.strip() != "research schg."
    assert "research schg" != q.strip()
    assert req["priority"] == "P1"  # held gap
    assert req["enqueue"] is False
    assert "why is schg still held" in q or "still held" in q


def test_discovery_not_flooded(monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_research import propose_prioritized_research

    # Live read is OK for this gate — must not enqueue; must skip mass discovery
    prop = propose_prioritized_research(root=ROOT, limit=40, max_p3=5)
    assert prop["enqueued"] is False
    assert prop["counts"]["proposed"] <= 40
    # Must not propose thousands
    assert prop["counts"]["proposed"] < 500
    # Discovery skip should be recorded when universe is large
    if (prop.get("coverage_counts") or {}).get("rows", 0) > 1000:
        assert prop["counts"]["skipped_discovery_or_capped"] > 0


def test_opportunity_actionability_research_required():
    from scripts.lib.symbol_thesis_attach import opportunity_actionability
    row = {
        "thesis_state": "RESEARCH_REQUIRED",
        "status": "NEAR",
        "verdict": "ADD",
        "research_gap_count": 2,
    }
    assert opportunity_actionability(row) == "RESEARCH_REQUIRED"


def test_adjudicate_reentry_data_unavailable(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    from scripts.lib.cio_investment_product import adjudicate_reentry
    from scripts.lib.symbol_thesis_attach import clear_cache

    clear_cache()
    # Point product root at empty thesis store via _product_root
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/portfolios/state").mkdir(parents=True)
    (tmp_path / "data/portfolios/state/holdings.json").write_text(
        json.dumps({"accounts": []}), encoding="utf-8"
    )
    row = {
        "symbol": "ANET",
        "reentry_signal": "NEAR ENTRY",
        "pct_above_exit": 5,
        "reentry_zone_low": 100,
        "reentry_zone_high": 110,
        "last_exit_price": 105,
        "_product_root": str(ROOT),  # use real roles; thesis still missing for ANET typically
    }
    rec = adjudicate_reentry(
        row, qitems=[], lessons={}, fs_ok=False, infl={"lesson_enhanced": False}
    )
    assert "DATA_UNAVAILABLE" in str(rec.get("why_previously_owned") or "") or rec.get("why_previously_owned")
    assert rec.get("thesis_state") in {
        "RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE", "CONFLICTED", "CURRENT"
    }
    assert rec.get("governed_verdict") != "RE_ENTER"  # no queue RE_ENTER
    assert rec.get("status") in {"NEAR", "WAIT", "AVOID"}


def test_cc_symbol_card_schg_operator_role(monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_cc import build_symbol_thesis_card

    card = build_symbol_thesis_card("SCHG", root=ROOT)
    assert card["symbol"] == "SCHG"
    assert card["portfolio_role"] == "GROWTH"
    assert "operator" in str(card.get("portfolio_role_source") or "")
    assert card["thesis_state"] in {
        "RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE", "CONFLICTED", "CURRENT", "RETIRED"
    }
    assert card["authority"] == "READ_ONLY_ADVISORY"
    assert isinstance(card.get("thesis_history"), list)


def test_ask_cio_context_transparent(monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.symbol_thesis_cc import ask_cio_symbol_context

    ctx = ask_cio_symbol_context("SCHG", root=ROOT)
    assert ctx["trading_execution_authority"] is False
    assert ctx["portfolio_role"] == "GROWTH"
    if ctx.get("transparent_if_missing"):
        assert ctx["current_symbol_thesis"]["state"] in {
            "RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE", "CONFLICTED"
        }


def test_reassessment_hooks_thesis_review(tmp_path, monkeypatch):
    """research completion → thesis review → at most one material version (idempotent)."""
    monkeypatch.chdir(ROOT)
    from scripts.lib.cio_theses import CIOThesisStore
    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis

    store = CIOThesisStore(
        event_path=tmp_path / "t.jsonl",
        projection_path=tmp_path / "p.json",
    )
    evidence = {
        "summary": "ANET remains a high-quality networking compounder; watch for valuation stretch.",
        "stance": "watch",
        "evidence_for": ["research:r99: quality compounder"],
        "research_result_id": "r99",
    }
    a = reconcile_symbol_thesis(
        "ANET", trigger="research_completion", evidence=evidence,
        store=store, root=tmp_path, notify=False,
    )
    b = reconcile_symbol_thesis(
        "ANET", trigger="research_completion", evidence=evidence,
        store=store, root=tmp_path, notify=False,
    )
    assert a["version_published"] is True
    assert b["classification"] == "NO_MATERIAL_CHANGE"
    assert b["version_published"] is False


def test_api_helpers_importable():
    import api_v3_cio as cio
    assert callable(cio.get_universe_theses)
    assert callable(cio.get_symbol_thesis_card)
    assert callable(cio.get_thesis_research_proposal)
    assert callable(cio.get_ask_thesis_context)
