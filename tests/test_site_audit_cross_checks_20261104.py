"""Site-audit cross-checks (spec piece 5) — the checks the crawl cannot make alone.

Why these exist: on 2026-11-04 the Risk card said SPCX **CONFIRMED** with `now —` while the same server held SPCX
132.99 @14:00:04Z, below the 134.50 invalidation. No single screen reading catches that; comparing two facts does.

§6 of the spec adds per-card completeness, and this module is where it lives so the deep crawl and the cross-checks use
one definition of "complete" rather than inventing two.

Hermetic: dicts in, findings out.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.site_audit import cross_checks as X  # noqa: E402

FULL = {"symbol": "SPCX", "price": 132.99, "rsi": 41.2, "macd": -0.31, "sma20": 140.1, "sma50": 145.0,
        "sma200": 138.0, "support1": 130.0, "support2": 126.5, "resistance1": 137.0, "resistance2": 141.0,
        "trend": "down", "cio_stance": "TRIM", "cio_thesis_as_of": "2026-11-04T14:00:04Z"}


def kinds(findings, check):
    return [f for f in findings if f["check"] == check]


# ── verdict vs price: the SPCX case ─────────────────────────────────────────────────────────────────────────────


def test_confirmed_below_invalidation_is_a_p1_contradiction():
    got = X.verdict_vs_price({**FULL, "verdict": "CONFIRMED", "invalidation_level": 134.50, "now_price": 132.99})
    assert len(got) == 1 and got[0]["severity"] == "P1"
    assert "below the invalidation" in got[0]["what"]


def test_confirmed_above_invalidation_is_quiet():
    assert X.verdict_vs_price({**FULL, "verdict": "CONFIRMED", "invalidation_level": 134.50, "now_price": 140.47}) == []


def test_a_verdict_with_no_price_is_not_judged():
    assert X.verdict_vs_price({**FULL, "verdict": "CONFIRMED", "invalidation_level": 134.50, "now_price": None}) == []


# ── now price ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_withheld_now_beside_a_live_quote_is_p1():
    got = X.now_price({"symbol": "SPCX", "now": "—"}, {"price": 132.99, "as_of": "2026-11-04T14:00:04Z"})
    assert len(got) == 1 and got[0]["severity"] == "P1" and "no now price" in got[0]["what"]


def test_a_different_price_from_the_server_is_p1():
    got = X.now_price({"symbol": "SPCX", "now": "$140.47"}, {"price": 132.99})
    assert len(got) == 1 and got[0]["evidence"]["server"] == 132.99


def test_a_cent_of_rounding_is_not_a_finding():
    assert X.now_price({"symbol": "SPCX", "now": "$132.99"}, {"price": 132.9901}) == []


def test_a_price_with_no_quote_to_trace_is_p2():
    got = X.now_price({"symbol": "SPCX", "now": "$132.99"}, None)
    assert len(got) == 1 and got[0]["severity"] == "P2"


# ── same figure everywhere ─────────────────────────────────────────────────────────────────────────────────────


def test_one_figure_two_values_is_p1():
    got = X.same_figure_everywhere("TODAY", [{"name": "header", "value": 2760.0}, {"name": "account row", "value": 3505.0}])
    assert len(got) == 1 and got[0]["severity"] == "P1"


def test_one_figure_one_value_is_quiet():
    assert X.same_figure_everywhere("TODAY", [{"name": "header", "value": 2760.0}, {"name": "account row", "value": 2760.0}]) == []


# ── §6 completeness: the definition the crawl and these checks share ─────────────────────────────────────────────


def test_a_top_list_card_missing_a_technical_is_p1():
    card = {**FULL, "list_kind": "best_opportunities"}
    card.pop("macd")
    got = kinds(X.card_completeness(card, list_kind="best_opportunities"), "card_completeness")
    assert any(f["severity"] == "P1" and "macd" in f["what"] for f in got)


def test_a_top_list_card_without_a_cio_thesis_is_p1():
    card = {**FULL, "list_kind": "home_top5"}
    card.pop("cio_stance")
    got = kinds(X.card_completeness(card, list_kind="home_top5"), "card_completeness")
    assert any(f["severity"] == "P1" and "no CIO thesis" in f["what"] for f in got)


def test_a_stance_with_no_as_of_is_p1_in_a_top_list():
    card = {**FULL, "list_kind": "cio_top_opportunities"}
    card.pop("cio_thesis_as_of")
    got = kinds(X.card_completeness(card, list_kind="cio_top_opportunities"), "card_completeness")
    assert any(f["severity"] == "P1" and "no as_of" in f["what"] for f in got)


def test_a_complete_top_card_is_quiet():
    assert X.card_completeness({**FULL, "list_kind": "best_opportunities"}, list_kind="best_opportunities") == []


def test_off_a_top_list_a_stated_reason_is_p2_and_an_unexplained_gap_is_p3():
    gap = {**FULL, "list_kind": "portfolio_holdings"}
    gap.pop("macd")
    stated = kinds(X.card_completeness({**gap, "missing_reason": "no intraday technicals for a delisted name"},
                                        list_kind="portfolio_holdings"), "card_completeness")
    assert stated and all(f["severity"] == "P2" for f in stated)
    silent = kinds(X.card_completeness(gap, list_kind="portfolio_holdings"), "card_completeness")
    assert silent and all(f["severity"] == "P3" for f in silent)


def test_the_crawler_and_the_checks_share_one_definition_of_complete():
    src = (ROOT / "scripts" / "lib" / "site_audit" / "cross_checks.py").read_text(encoding="utf-8")
    assert "REQUIRED_TECHNICAL" in src and "TOP_LISTS" in src
    assert X.top_list("Best Opportunities") and not X.top_list("portfolio_holdings")


# ── the report ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_run_sorts_p1_first_and_counts():
    rep = X.run([{**FULL, "list_kind": "home_top5", "verdict": "CONFIRMED", "invalidation_level": 134.5,
                  "now_price": 132.99}],
                quotes={"SPCX": {"price": 132.99}})
    assert rep["schema"] == "SiteAuditCrossChecks@v1" and rep["cards"] == 1
    assert rep["counts"]["P1"] >= 1 and rep["findings"][0]["severity"] == "P1"
    assert rep["authority"] == "READ_ONLY_ADVISORY"
