"""WAVE F1+F2 — web search callers census + bound to residual-web.

F1: every Brave/search caller is named with provider, schedule, volume class.
F2: news/catalyst callers re-pointed to RSS/Finviz; residual-web keeps
    ≤1 hop/subject/day and N=3. Never fail open. No cron. No secrets.

This file is on the hardening CI allowlist. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_residual_web as rw
from scripts.lib import search_budget as sb

REPO = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)

NEWS_CATALYST_CALLERS = {
    "portfolio_news",
    "catalyst_intelligence",
    "web_news_fetcher",
    "portfolio_weekly_report",
    "symbol_enrichment",
    "topic_ingestion",
}


# ── F1 census completeness ──────────────────────────────────────────────────

def test_f1_census_covers_named_news_catalyst_and_residual():
    names = {r["caller"] for r in rw.SEARCH_CALLER_CENSUS}
    assert "cio_residual_web" in names
    assert NEWS_CATALYST_CALLERS <= names
    for row in rw.SEARCH_CALLER_CENSUS:
        for key in (
            "caller", "provider", "trigger", "schedule",
            "calls_per_run", "class", "empty_result_behavior", "consumer",
        ):
            assert key in row and row[key] not in (None, ""), row


def test_f1_residual_web_class_and_rails():
    assert rw.DAILY_SUBJECT_BUDGET == 3
    assert rw.MAX_HOPS_PER_SUBJECT_PER_DAY == 1
    assert rw.LANE == "residual_web"
    assert rw.SEARCH_API_RESERVED_FOR == "residual_web"
    assert rw.NEWS_BELONGS_ON == ("rss", "finviz")
    residual = next(r for r in rw.SEARCH_CALLER_CENSUS if r["caller"] == "cio_residual_web")
    assert residual["class"] == "residual-web"
    assert residual["provider"] == "searxng"
    assert "no cron" in residual["schedule"].lower() or "none" in residual["schedule"].lower()


def test_f1_legacy_bulk_rows_name_a_consumer():
    """Only edit callers with a named consumer; census must carry that name."""
    for row in rw.SEARCH_CALLER_CENSUS:
        if row["class"] == "legacy-bulk":
            assert row["consumer"], row["caller"]


# ── F2 bound volume (dry-run arithmetic) ────────────────────────────────────

def test_f2_projected_volume_arithmetic_as_of():
    v = rw.projected_search_volume(weekdays_per_month=21, as_of=AS_OF)
    assert v["as_of"].startswith("2026-08-31T05:00:00")
    assert v["store_writes"] is False
    assert v["financial_action"] is False
    rw_block = v["residual_web"]
    assert rw_block["calls_per_day_cap"] == 3
    assert rw_block["monthly_projection"] == 63  # 3 × 1 × 21
    assert "3 subjects × 1 hop × 21 weekdays = 63" in rw_block["arithmetic"]
    assert rw_block["cost_usd_month"] == 0.0
    assert v["news_catalyst_brave_under_bound"]["monthly_projection"] == 0
    # aegis left on budgeted Brave: 10×2×21 + 12×21 = 420 + 252 = 672
    assert v["remaining_legacy_bulk_brave"]["monthly_projection"] == 672
    assert v["policy"]["never_fail_open"] is True
    assert v["policy"]["no_cron_for_residual_web"] is True


def test_f2_news_catalyst_bound_monthly_is_zero_in_census():
    for row in rw.SEARCH_CALLER_CENSUS:
        if row["caller"] in NEWS_CATALYST_CALLERS:
            assert row["bound_monthly"] == 0, row["caller"]


# ── F2 re-point: news callers must not call Brave search API ────────────────

def _source_of(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_f2_portfolio_news_uses_non_search_enrich_not_brave_api():
    src = _source_of("scripts/portfolio_news.py")
    assert "def _non_search_enrich" in src
    assert "api.search.brave.com" not in src
    assert "from brave_search import" not in src
    assert "finviz_news" in src and "yahoo_news" in src


def test_f2_catalyst_intelligence_no_brave_import():
    src = _source_of("scripts/catalyst_intelligence.py")
    assert "from brave_search import" not in src
    assert "api.search.brave.com" not in src
    assert "finviz_news" in src


def test_f2_web_news_fetcher_brave_stub_returns_empty():
    from scripts import web_news_fetcher as wnf
    assert wnf._brave_search("AAPL stock news", max_results=3) == []
    src = _source_of("scripts/web_news_fetcher.py")
    # Live Brave URL must not remain on the fetch path (stub may omit it).
    assert "api.search.brave.com" not in src
    assert "_finviz_yahoo_news" in src


def test_f2_symbol_enrichment_brave_tier_is_retired_noop(monkeypatch):
    from scripts import symbol_enrichment as se
    reported = []

    def _report(name, ok, error=None, **_kw):
        reported.append((name, ok, error))

    monkeypatch.setattr(se, "_report_source", _report)
    assert se.pull_brave_aplus("NOC", 80, conn=None) is False
    assert reported and reported[0][0] == "brave_search"
    assert reported[0][1] is False
    assert "rss_finviz" in (reported[0][2] or "")


def test_f2_portfolio_weekly_no_brave_url():
    src = _source_of("scripts/portfolio_weekly_report.py")
    # Function name retained for call-site compat; body must not hit Brave.
    assert "def _get_brave_analyst_commentary" in src
    assert "api.search.brave.com" not in src
    assert "finviz_news" in src


def test_f2_topic_ingestion_brave_stays_opt_in():
    """Named consumer (news_to_catalyst); already retired unless env flag."""
    src = _source_of("scripts/topic_ingestion.py")
    assert "TOPIC_BRAVE_ENABLED" in src


# ── never fail open (budget) + residual hop cap ─────────────────────────────

def test_f2_search_budget_never_fails_open(tmp_path):
    p = sb.budget_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", encoding="utf-8")
    verdict = sb.check("brave", root=tmp_path)
    assert verdict["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in verdict["reason"]


def test_f2_legality_enforces_one_hop_per_subject_per_day():
    rec = {
        "subject_key": "HELD:NOC",
        "kind": "HELD",
        "market_value": 50_000,
        "next_eligible_at": None,
    }
    gate = {"decision": rw.RESIDUAL_DECISION, "material": True}
    plan = {"material": True, "market_value": 50_000}
    ok = rw.legality(rec, gate_decision=gate, plan=plan, hops_today=0, now=AS_OF)
    assert ok["legal"] is True
    blocked = rw.legality(rec, gate_decision=gate, plan=plan, hops_today=1, now=AS_OF)
    assert blocked["legal"] is False
    assert "under_daily_subject_cap" in blocked["failed_checks"]


def test_f2_select_daily_respects_budget_n3():
    cands = []
    for sym in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        rec = {"subject_key": f"HELD:{sym}", "kind": "HELD", "market_value": 10_000}
        leg = {"legal": True, "hash_moved": None}
        cands.append({"record": rec, "legality": leg})
    out = rw.select_daily(cands, budget=rw.DAILY_SUBJECT_BUDGET, now=AS_OF)
    assert out["budget"] == 3
    assert len(out["selected"]) == 3


def test_f2_unnamed_aegis_callers_listed_not_deleted():
    """Do not delete unnamed/non-news consumers — census must still name them."""
    names = {r["caller"] for r in rw.SEARCH_CALLER_CENSUS}
    assert "aegis_social_sentiment" in names
    assert "aegis_transcript_discovery" in names
    social = next(r for r in rw.SEARCH_CALLER_CENSUS if r["caller"] == "aegis_social_sentiment")
    assert social["bound_monthly"] == 420  # 10 × 2 × 21 pre-budget-deny ceiling
