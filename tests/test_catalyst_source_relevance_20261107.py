"""A search result is a catalyst only when it is ABOUT this company and is CURRENT.

COVERS = ["scripts/lib/catalyst_source_relevance.py", "scripts/hermes_momentum_catalyst_researcher.py"]

Measured 2026-11-07 (audit78_result2, LQ-20261107-131) on the live 2026-11-06 run, 38 sources / 18 symbols:

    CIIT  "news_momentum high 0.6"  a 2020 Wikinews page (688 days old), a bank login page, a certification page
    VSA   "news_momentum 0.4"       a car warning-light article, by the whole-word ticker alone
    DFH   "news_momentum high 0.6"  a Forbes page 298 days old, a stock-chart page, an unrelated trading blog
    PMN   "analyst 0.6"             three pages that really are ProMIS Neurosciences, 8 and 129 days old

The writer took ``all_sources[0]`` as the catalyst and set ``confidence = 0.3 + 0.1 * len(all_sources)``, so the
more pages a query returned the more confident it became -- about nothing in particular. The gate below asks three
questions of every result before it can be evidence:

  * IDENTITY -- does the page's own text name the ticker as a whole word, or the company by name? (the read-side
    ``verify_identity`` matcher, reused, never re-implemented). A ticker that appears only in the URL path is a site
    section, not a story.
  * RECENCY -- a dated page older than :data:`FRESH_DAYS` is history. An undated page is weak evidence: accepted only
    when it names the COMPANY, because a page that carries just the ticker is exactly the search artefact VSA and
    SEGG were (a car warning light, a compensation disclosure).
  * SHAPE -- a quote/chart page is a market-data surface, never a story.

Fixtures are shaped after the live rows; hosts and dates are synthetic, no live page is captured.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import catalyst_source_relevance as G  # noqa: E402
from lib.hermes_scalp_catalyst_record import VERIFIED, verify_identity  # noqa: E402

COVERS = ["scripts/lib/catalyst_source_relevance.py", "scripts/hermes_momentum_catalyst_researcher.py"]

NOW = datetime(2026, 11, 6, 15, 25, tzinfo=timezone.utc)

NAMES = {
    "CIIT": ["Tianci International, Inc."],
    "VSA": ["VisionSys AI Inc"],
    "DFH": ["Dream Finders Homes, Inc."],
    "WEN": ["Wendy's Co"],
    "PMN": ["ProMIS Neurosciences Inc."],
    "CDT": ["CDT Equity Inc."],
    "SEGG": ["Sports Entertainment Gaming Global Corp"],
}


def src(title, url, *, published="", content="", engine="searxng"):
    return {"title": title, "url": url, "content": content, "published": published, "engine": engine}


def days_ago(n):
    return (NOW - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%S")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda _s: None)


def research(monkeypatch, symbol, sources, *, names=None, now=NOW):
    import hermes_momentum_catalyst_researcher as H

    monkeypatch.setattr(H, "search_catalyst", lambda *a, **k: [dict(s) for s in sources])
    monkeypatch.setattr(H, "_company_names", lambda _sym: list(names if names is not None else NAMES.get(symbol, [])))
    return H.research_ticker(symbol, now=now)


# ── the three named cases in the audit ──────────────────────────────────────

def test_a_car_warning_light_page_is_not_a_catalyst(monkeypatch):
    """"VSA" is VisionSys AI in the feed and a vehicle stability assist in a repair article."""
    out = research(monkeypatch, "VSA", [
        src("“Check VSA System” Light On? (8 Causes and Repair Costs)",
            "https://repair.example.com/check-vsa-system/",
            content="Below, you’ll find the most likely reasons for the VSA light."),
    ])
    assert out["catalyst_type"] == "no_clear_catalyst"
    assert out["confidence"] == 0.2
    assert out["source_count"] == 0
    assert out["sources_rejected"][0]["why"] == "undated, ticker only"


def test_a_2020_wikinews_page_and_a_bank_login_page_are_not_a_catalyst(monkeypatch):
    out = research(monkeypatch, "CIIT", [
        src("On the campaign trail in the USA, July 2020",
            "https://en.wikinews.example.org/wiki/On_the_campaign_trail"),
        src("Citibank Online", "https://online.bank.example.com/US/ag/mrc/"),
        src("Certified Investment Management Analyst (CIMA) Certification",
            "https://certify.example.org/certifications/cima-certification"),
    ])
    assert out["catalyst_type"] == "no_clear_catalyst"
    assert out["source_count"] == 0
    assert {r["why"] for r in out["sources_rejected"]} == {"unrelated"}
    assert "campaign trail" not in out["catalyst_summary"]


def test_a_ten_month_old_page_is_not_a_current_catalyst(monkeypatch):
    """"DFH Stock Jumps On White House Bond Purchase Announcement" is 298 days old; the chart page is not a story."""
    out = research(monkeypatch, "DFH", [
        src("DFH Stock Jumps On White House Bond Purchase Announcement, Justified?",
            "https://www.forbes.example.com/sites/greatspeculations/2026/01/12/dfh-stock-jumps",
            published=days_ago(298)),
        src("DFH Stock Chart Dream Finders Homes Class A",
            "https://charts.example.com/Overview/DFH/StockChart/"),
        src("How To Trade With The Gap And Go Strategy [2024]", "https://trading.example.com/trade-with-the-gap/"),
    ])
    assert out["catalyst_type"] == "no_clear_catalyst"
    assert out["source_count"] == 0
    whys = {r["why"].split(" (")[0] for r in out["sources_rejected"]}
    assert "stale" in whys and "quote/chart page" in whys and "unrelated" in whys


# ── the real catalyst must survive ──────────────────────────────────────────

def test_a_fresh_company_headline_still_sets_the_catalyst(monkeypatch):
    out = research(monkeypatch, "PMN", [
        src("Wall Street Analysts Believe Promis Neurosciences (PMN) Could Rally 292.95%",
            "https://news.example.com/promis-neurosciences-pmn", published=days_ago(8)),
    ])
    assert out["catalyst_type"] == "analyst"
    assert out["confidence"] == 0.4
    assert out["source_count"] == 1
    assert "Promis Neurosciences" in out["catalyst_summary"]


def test_confidence_counts_only_qualifying_sources(monkeypatch):
    """Two fresh pages, one stale and one unrelated: confidence is 0.5, not 0.7."""
    out = research(monkeypatch, "PMN", [
        src("Wall Street Analysts Believe Promis Neurosciences (PMN) Could Rally",
            "https://news.example.com/a", published=days_ago(8)),
        src("Promis Neurosciences (PMN) Announces Data", "https://news.example.com/b", published=days_ago(1)),
        src("Wall Street Analysts Believe Promis Neurosciences (PMN) Could Rally",
            "https://news.example.com/c", published=days_ago(129)),
        src("DraftKings Stock Tumbles on Guidance", "https://news.example.com/d", published=days_ago(1)),
    ])
    assert out["confidence"] == 0.5
    assert out["source_count"] == 2
    assert len(out["sources"]) == 2


def test_an_undated_page_that_names_the_company_is_still_evidence(monkeypatch):
    """"CDT Equity Inc. Announces Reverse Stock Split" has no date but names the company."""
    out = research(monkeypatch, "CDT", [
        src("CDT Equity Inc. Announces Reverse Stock Split",
            "https://news.example.com/cdt-equity-inc-reverse-split"),
    ])
    assert out["catalyst_type"] == "news_momentum"
    assert out["confidence"] == 0.3
    assert out["source_count"] == 1


def test_a_company_name_with_an_apostrophe_matches(monkeypatch):
    """"Wendy's Co" meets "How Wendy’s CEO plans ..." -- the curly apostrophe must not hide the company."""
    out = research(monkeypatch, "WEN", [
        src("How Wendy’s CEO plans to revive beleaguered burger chain",
            "https://restaurants.example.com/wendys-turnaround", published=days_ago(0)),
    ])
    assert out["catalyst_type"] != "no_clear_catalyst"
    assert out["source_count"] == 1


# ── the rules themselves (pure) ─────────────────────────────────────────────

def test_a_ticker_that_lives_only_in_the_url_is_not_a_story():
    out = G.select_evidence("SEGG", [
        src("Thesis", "https://media.example.com/SEGG/",
            content="Compass Live Media has been compensated $50,000.00"),
    ], NAMES["SEGG"], now=NOW)
    assert out["best"] is None
    assert out["rejected"][0]["why"] == "ticker only in the URL"


def test_fourteen_days_is_fresh_and_fifteen_is_stale():
    sym, names = "PMN", NAMES["PMN"]
    fresh = src("Promis Neurosciences announces data", "https://n.example.com/1", published=days_ago(14))
    stale = src("Promis Neurosciences announces data", "https://n.example.com/2", published=days_ago(15))
    assert G.select_evidence(sym, [fresh], names, now=NOW)["basis"] == "fresh"
    assert G.select_evidence(sym, [stale], names, now=NOW)["basis"] == "none"


def test_a_quote_page_is_never_evidence_even_when_it_names_the_company():
    out = G.select_evidence("DFH", [
        src("DFH Stock Price | Dream Finders Homes Inc. Stock Quote",
            "https://www.marketwatch.example.com/investing/stock/dfh"),
    ], NAMES["DFH"], now=NOW)
    assert out["best"] is None
    assert out["rejected"][0]["why"] == "quote/chart page"


def test_an_unparseable_date_is_treated_as_undated():
    out = G.select_evidence("PMN", [
        src("Promis Neurosciences announces data", "https://n.example.com/1", published="last tuesday"),
    ], NAMES["PMN"], now=NOW)
    assert out["basis"] == "company"
    assert G.publish_age_days("last tuesday", now=NOW) is None


def test_the_read_side_matcher_reports_what_it_matched():
    """The gate needs to know whether the COMPANY or only the TICKER was named."""
    rec = {"catalyst_summary": "Why is CDT equity stock surging?", "sources": []}
    out = verify_identity("CDT", rec, NAMES["CDT"])
    assert out["status"] == VERIFIED
    assert out["matched"] == "company"
    rec = {"catalyst_summary": "CDT time zone explained", "sources": []}
    assert verify_identity("CDT", rec, NAMES["CDT"])["matched"] == "ticker"
