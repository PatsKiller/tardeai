"""Opportunity view actions + CIO review coverage (operator 2026-10-09: "why no CIO review is on list and CIO memory,
still no way to flag or add to watch list").

Review requests into the symbol-thesis priority queue (API + curator top-ranked auto-requests), serving order
(operator flags, then CIO top-ranked, then the rest), watchlist state, the quote-page/option-listing news filter, and
the modal wiring. Fakes only: no database, no network, no real CIO memory (tmp roots).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import symbol_thesis_priority as stp  # noqa: E402

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)


def _req(root, sym, source, minutes_ago):
    stp.request(sym, reason="t", source=source, root=root, now=NOW - timedelta(minutes=minutes_ago))


def test_serving_order_operator_then_curator_then_rest(tmp_path):
    _req(tmp_path, "OLD1", "options_thesis_lifecycle", 600)
    _req(tmp_path, "OLD2", "sec_fundamentals_ingest", 500)
    _req(tmp_path, "TOPR", "cio_opportunity_curator", 30)
    _req(tmp_path, "MINE", "operator_opportunity_view", 5)
    _req(tmp_path, "OLD1", "operator_opportunity_view", 1)     # operator re-flag lifts an older request
    assert stp.open_requests(tmp_path, now=NOW) == ["OLD1", "OLD2", "TOPR", "MINE"]
    assert stp.open_requests_ranked(tmp_path, now=NOW) == ["OLD1", "MINE", "TOPR", "OLD2"]


def test_request_review_api_queues_once(tmp_path, monkeypatch):
    import api_v3_opportunities as api

    monkeypatch.setattr(stp, "_root", lambda root=None: tmp_path)
    monkeypatch.setattr(api, "_priority", lambda: stp)
    code, out = api.request_review("brcc", {"note": "rank 2, no thesis"})
    assert code == 200 and out["ok"] and out["already_open"] is False
    assert out["review"]["open"] is True and out["review"]["queue_position"] == 1
    rows = [json.loads(x) for x in (tmp_path / "data/cio/symbol_thesis_priority_queue.jsonl").read_text().splitlines()]
    assert rows[0]["symbol"] == "BRCC" and rows[0]["source"] == "operator_opportunity_view"
    assert "rank 2, no thesis" in rows[0]["reason"] and rows[0]["authority"] == "READ_ONLY_ADVISORY"
    code, out = api.request_review("BRCC", {})
    assert out["already_open"] is True
    assert len((tmp_path / "data/cio/symbol_thesis_priority_queue.jsonl").read_text().splitlines()) == 1
    assert api.request_review("bad sym!", {})[0] == 400


def test_curator_requests_top_ranked_without_thesis():
    import cio_opportunity_curator as c

    ranked = ["ANET", "BRCC", "AOSL", "FIGS", "QTEX", "DD"]
    has = {"ANET": True, "AOSL": True}
    got = c.review_candidates(ranked, {"enabled": True, "auto_top_n": 5}, has_thesis=lambda s: has.get(s, False),
                              open_requests=["QTEX"])
    assert got == ["BRCC", "FIGS"]                        # top 5 only, thesis-holders and open requests skipped
    assert c.review_candidates(ranked, {"enabled": False, "auto_top_n": 5}, has_thesis=lambda s: False,
                               open_requests=[]) == []


def test_curator_files_requests_only_on_apply():
    src = (ROOT / "scripts/cio_opportunity_curator.py").read_text(encoding="utf-8")
    apply_block = src.split("    if apply:", 1)[1]
    assert "file_review_requests(review, run_id)" in apply_block
    assert "file_review_requests" not in src.split("    if apply:", 1)[0].split("def run(", 1)[1]


def test_acquisition_and_monitor_serve_ranked_order():
    acq = (ROOT / "scripts/run_symbol_thesis_acquisition.py").read_text(encoding="utf-8")
    assert "open_requests_ranked(root)" in acq
    mon = (ROOT / "scripts/symbol_news_curation_monitor.py").read_text(encoding="utf-8")
    assert mon.count("import open_requests_ranked as open_requests") == 2


def test_quote_pages_and_option_listings_are_not_news():
    from lib.data_broker.catalyst_record import NOT_NEWS_PATTERNS, not_news_sql

    junk = ["BRCC Oct 2026 8.000 call (BRCC261016C00008000) stock price, news, quote and history - Yahoo Finance UK",
            "COHH Dec 2026 14.000 put (COHH261218P00014000) Stock Historical Prices & Data - Yahoo! Finance Canada",
            "GDS Holdings Limited (GDS) Stock Forecasts - Yahoo! Finance Canada",
            "GDS: GDS Holdings Latest Stock Price, Analysis, News and Trading Ideas - Stocktwits"]
    real = ["GDS Holdings (GDS) Upgraded to Buy: Here's Why",
            "Why Did Ceva (NASDAQ:CEVA) Rebound 6.92% Premarket Oct 9?",
            "Ceva, Inc. (NASDAQ:CEVA) Receives Consensus Recommendation of \"Moderate Buy\" from Brokerages"]
    hit = lambda t: any(re.search(p, t, re.I) for p in NOT_NEWS_PATTERNS)  # noqa: E731
    assert all(hit(t) for t in junk) and not any(hit(t) for t in real)
    sql = not_news_sql("headline")
    assert sql.count("COALESCE(headline, '') !~*") == len(NOT_NEWS_PATTERNS) and "%" not in sql


def test_modal_wiring():
    tsx = (ROOT / "apps/command-center-v3/src/components/opportunity/OpportunityModal.tsx").read_text(encoding="utf-8")
    for tid in ("opportunity-actions", "opp-add-watch", "opp-request-review", "opportunity-cio-memory"):
        assert f'data-testid="{tid}"' in tsx
    assert "'/api/v2/watch/directives'" in tsx and "/review-request" in tsx
    api = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    assert 'endswith("/review-request")' in api and "_opp.request_review(sym, body or {})" in api
