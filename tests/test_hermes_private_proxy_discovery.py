#!/usr/bin/env python3
"""White-Space Stage 4 — private-company / public-proxy discovery (spec Part C).

Covers: private detection (recurs + cross-source + FAILS symbol validation),
denylist/proper-noun filtering, proxy extraction from evidence phrases, the
no-invention rule (no evidence → nulls + research_only), the mandatory
no-direct-options sentence, the private_proxy_json schema, the worker-pool
lane contract (registered, read-only), targeted --company analysis honesty,
and the no-broker-imports guarantee.

    .venv/bin/python -m pytest tests/test_hermes_private_proxy_discovery.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import inbox, private_proxy, worker_pool  # noqa: E402
from lib.hermes_discovery.symbol_validation import (  # noqa: E402
    VERDICT_INVALID, VERDICT_NEEDS_VALIDATION, VERDICT_VALID)


# ── synthetic fixtures ───────────────────────────────────────────────────────

def _row(text, source="alpha-news", url="https://example.com/a", ref="news_articles:1"):
    return {"text": text, "source": source, "url": url, "ref": ref}


ACME_CORPUS = [
    _row("Defense startup Acme Robotics raised a new round on Monday.",
         source="alpha-news", ref="news_articles:1"),
    _row("Analysts say Acme Robotics is scaling drone output.",
         source="beta-wire", ref="news_articles:2"),
    _row("Suppliers cited demand from Acme Robotics for actuators.",
         source="beta-wire", ref="hermes_research_intelligence:9"),
]

LOOM_CORPUS = [
    _row("Video startup Loom was acquired by Atlassian (NASDAQ: TEAM) in a "
         "$975 million deal.", source="alpha-news", ref="news_articles:11"),
    _row("Enterprise teams keep adopting Loom for async video updates.",
         source="beta-wire", ref="news_articles:12"),
]


def _verdict(verdict, sym, valid=False):
    return {"valid": valid, "verdict": verdict, "reason": "test", "symbol": sym,
            "company_name": None, "exchange": None, "instrument_type": None,
            "sector": None}


@pytest.fixture
def offline(monkeypatch):
    """No real DB: every token fails symbol validation, no listed-name matches
    (i.e. everything capitalized+recurring looks private unless a test opts in)."""
    monkeypatch.setattr(private_proxy, "_ticker_verdict",
                        lambda sym: _verdict(VERDICT_INVALID, sym))
    monkeypatch.setattr(private_proxy, "_listed_symbols_for_name", lambda name: [])
    monkeypatch.setattr(
        private_proxy, "_execute",
        lambda sql, params=None, fetch=None: [] if fetch == "all" else None)


def _detect(corpus, skipped=None, limit=5):
    return private_proxy.detect_private_companies(corpus, limit=limit,
                                                  skipped=skipped)


# ── detection ────────────────────────────────────────────────────────────────

def test_detects_recurring_cross_source_unlisted_entity(offline):
    skipped = {}
    ents = _detect(ACME_CORPUS, skipped)
    names = [e["name"] for e in ents]
    assert "Acme Robotics" in names
    ent = next(e for e in ents if e["name"] == "Acme Robotics")
    assert ent["recurrence"] == 3
    assert ent["cross_source_count"] == 2
    # common words never surface as entities
    assert "Monday" not in names and "Analysts" not in names


def test_recurrence_and_cross_source_gates(offline):
    skipped = {}
    one_row = [ACME_CORPUS[0]]
    assert not _detect(one_row, skipped)
    assert skipped.get("low_recurrence", 0) >= 1

    same_source = [ACME_CORPUS[0],
                   _row("Acme Robotics again.", source="alpha-news",
                        ref="news_articles:3")]
    skipped2 = {}
    assert not any(e["name"] == "Acme Robotics"
                   for e in _detect(same_source, skipped2))
    assert skipped2.get("low_cross_source", 0) >= 1


def test_valid_ticker_entities_are_excluded(offline, monkeypatch):
    monkeypatch.setattr(
        private_proxy, "_ticker_verdict",
        lambda sym: _verdict(VERDICT_VALID, sym, valid=True)
        if sym == "ZORP" else _verdict(VERDICT_INVALID, sym))
    corpus = [_row("Investors piled into Zorp on Tuesday.", source="alpha-news"),
              _row("Buyers flocked to Zorp this quarter.", source="beta-wire")]
    skipped = {}
    assert not any(e["name"] == "Zorp" for e in _detect(corpus, skipped))
    assert skipped.get("directly_listed_ticker", 0) == 1


def test_ambiguous_ticker_shape_excluded(offline, monkeypatch):
    monkeypatch.setattr(
        private_proxy, "_ticker_verdict",
        lambda sym: _verdict(VERDICT_NEEDS_VALIDATION, sym))
    corpus = [_row("Demand for Zorp keeps growing.", source="alpha-news"),
              _row("Buyers liked what Zorp built.", source="beta-wire")]
    skipped = {}
    assert not any(e["name"] == "Zorp" for e in _detect(corpus, skipped))
    assert skipped.get("ambiguous_ticker_shape", 0) >= 1


def test_listed_company_name_excluded(offline, monkeypatch):
    monkeypatch.setattr(private_proxy, "_listed_symbols_for_name",
                        lambda name: ["TSLA"] if name == "Tesla" else [])
    corpus = [_row("Fans praised how Tesla builds cars.", source="alpha-news"),
              _row("Critics note that Tesla faces competition.", source="beta-wire")]
    skipped = {}
    assert not _detect(corpus, skipped)
    assert skipped.get("listed_company_name", 0) == 1


def test_sentence_start_only_single_words_excluded(offline):
    corpus = [_row("Shares rallied across the board today."),
              _row("Shares slipped after the report.", source="beta-wire")]
    assert not _detect(corpus)  # denylist or sentence-start-only, never detected


def test_acronym_shaped_allcaps_excluded(offline):
    corpus = [_row("Analysts flagged strong EBITX in the results.",
                   source="alpha-news"),
              _row("Guidance cited EBITX expansion again.", source="beta-wire")]
    skipped = {}
    assert not _detect(corpus, skipped)
    assert skipped.get("acronym_shaped", 0) == 1


def test_no_company_context_excluded(offline):
    corpus = [_row("Traders expect Volatility to persist.", source="alpha-news"),
              _row("Bets on Volatility rose again.", source="beta-wire")]
    skipped = {}
    assert not any(e["name"] == "Volatility" for e in _detect(corpus, skipped))
    assert skipped.get("no_company_context", 0) >= 1


def test_exchange_parenthetical_in_text_excludes_entity(offline):
    corpus = [
        _row("EV startup Polestar (NASDAQ: PSNY) cut its outlook.",
             source="alpha-news"),
        _row("Deliveries at EV maker Polestar fell again.", source="beta-wire")]
    skipped = {}
    assert not any(e["name"] == "Polestar" for e in _detect(corpus, skipped))
    assert skipped.get("exchange_listed_in_text", 0) == 1


def test_title_case_headline_words_not_detected(offline):
    corpus = [
        _row("3 Strong Growth Companies Momentum Traders Should Review Now",
             source="alpha-news"),
        _row("Top Growth Companies For Momentum Investors To Review Today",
             source="beta-wire")]
    assert not any(" " not in e["name"] for e in _detect(corpus))


# ── proxy extraction from evidence phrases ───────────────────────────────────

def test_acquired_by_with_exchange_parenthetical(offline, monkeypatch):
    monkeypatch.setattr(
        private_proxy, "_ticker_verdict",
        lambda sym: _verdict(VERDICT_VALID, sym, valid=True)
        if sym == "TEAM" else _verdict(VERDICT_INVALID, sym))
    proxies = private_proxy.extract_proxies(
        "Loom", [LOOM_CORPUS[0]["text"], LOOM_CORPUS[1]["text"]])
    assert len(proxies) == 1
    p = proxies[0]
    assert p["ticker"] == "TEAM"
    assert p["relationship"] == "acquirer"
    assert p["acquisition_status"] == "completed"
    assert p["confidence"] == pytest.approx(0.8)
    assert "acquired by Atlassian" in p["evidence"]


def test_subsidiary_of_resolves_via_profile_name(offline, monkeypatch):
    monkeypatch.setattr(private_proxy, "_listed_symbols_for_name",
                        lambda name: ["BIG"] if name.startswith("BigCo") else [])
    monkeypatch.setattr(
        private_proxy, "_ticker_verdict",
        lambda sym: _verdict(VERDICT_VALID, sym, valid=True)
        if sym == "BIG" else _verdict(VERDICT_INVALID, sym))
    proxies = private_proxy.extract_proxies(
        "Acme Robotics",
        ["Acme Robotics, a wholly-owned subsidiary of BigCo Industries, "
         "expanded output."])
    assert len(proxies) == 1
    assert proxies[0]["ticker"] == "BIG"
    assert proxies[0]["relationship"] == "parent"
    assert proxies[0]["confidence"] == pytest.approx(0.6)


def test_announced_acquisition_status(offline, monkeypatch):
    monkeypatch.setattr(
        private_proxy, "_ticker_verdict",
        lambda sym: _verdict(VERDICT_VALID, sym, valid=True)
        if sym == "IBM" else _verdict(VERDICT_INVALID, sym))
    proxies = private_proxy.extract_proxies(
        "HashiCloud", ["IBM has agreed to acquire HashiCloud for $6.4 billion."])
    assert proxies and proxies[0]["ticker"] == "IBM"
    assert proxies[0]["acquisition_status"] == "announced"
    assert proxies[0]["confidence"] == pytest.approx(0.7)


def test_unresolvable_public_side_yields_no_proxy(offline):
    # relationship phrase present, but the parent name can't resolve to a
    # validated ticker → NOTHING is invented
    proxies = private_proxy.extract_proxies(
        "Acme Robotics",
        ["Acme Robotics was acquired by Mystery Holdings last year."])
    assert proxies == []


# ── no-invention rule + mandatory sentence + schema ──────────────────────────

def _payload(corpus):
    ents = _detect(corpus)
    ent = next(e for e in ents if e["name"] == "Acme Robotics")
    texts = [corpus[i]["text"] for i in ent["row_idxs"]]
    return private_proxy.build_payload(
        ent, private_proxy.extract_proxies("Acme Robotics", texts))


def test_no_evidence_means_nulls_and_research_only(offline):
    ppj = _payload(ACME_CORPUS)["meta"]["private_proxy_json"]
    assert ppj["public_parent"] is None
    assert ppj["public_parent_ticker"] is None
    assert ppj["ownership_relationship"] is None
    assert ppj["ownership_percent_if_known"] is None
    assert ppj["acquisition_status"] == "unknown"
    assert ppj["materiality_to_parent"] == "unknown"
    assert ppj["proxy_underlyings"] == []
    assert ppj["options_possible_on"] == []
    assert ppj["recommended_action"] == "research_only"


def test_mandatory_no_direct_options_sentence(offline):
    required = ("No direct listed options found for the private company. "
                "Research must use a public parent/proxy/comparable/ETF if "
                "appropriate.")
    assert private_proxy.NO_DIRECT_OPTIONS_SENTENCE == required
    ppj = _payload(ACME_CORPUS)["meta"]["private_proxy_json"]
    assert required in ppj["no_direct_trade_reason"]


def test_private_proxy_json_schema_and_payload_contract(offline, monkeypatch):
    monkeypatch.setattr(
        private_proxy, "_ticker_verdict",
        lambda sym: _verdict(VERDICT_VALID, sym, valid=True)
        if sym == "HOLO" else _verdict(VERDICT_INVALID, sym))
    corpus = ACME_CORPUS + [_row(
        "Acme Robotics was acquired by HOLO in 2025, and HOLO owns 100% stake.",
        source="gamma-desk", ref="news_articles:44")]
    payload = _payload(corpus)

    assert payload["candidate_type"] == "PRIVATE_COMPANY_PROXY_CANDIDATE"
    assert payload["candidate_type"] in inbox.CANDIDATE_TYPES
    assert payload["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
    assert payload["evidence"], "evidence refs required"
    assert payload["meta"]["research_domain"] in private_proxy.ROUTING_DOMAINS

    ppj = payload["meta"]["private_proxy_json"]
    for key in ("private_company", "public_parent", "public_parent_ticker",
                "ownership_relationship", "ownership_percent_if_known",
                "acquisition_status", "materiality_to_parent",
                "direct_options_available", "proxy_underlyings",
                "options_possible_on", "no_direct_trade_reason",
                "evidence_refs", "recommended_action"):
        assert key in ppj, f"missing spec key {key}"
    assert ppj["direct_options_available"] is False
    assert ppj["recommended_action"] in private_proxy.RECOMMENDED_ACTIONS
    assert ppj["recommended_action"] == "proxy_analysis"
    assert ppj["public_parent_ticker"] == "HOLO"
    assert ppj["ownership_relationship"] == "acquirer"
    assert ppj["acquisition_status"] == "completed"
    assert ppj["ownership_percent_if_known"] == pytest.approx(100.0)
    for p in ppj["proxy_underlyings"]:
        assert set(p) == {"ticker", "relationship", "confidence"}
        assert p["relationship"] in private_proxy.RELATIONSHIPS
        assert 0.0 < p["confidence"] <= 1.0
    assert ppj["options_possible_on"] == [p["ticker"]
                                          for p in ppj["proxy_underlyings"]]
    assert payload["seed_symbols"] == ["HOLO"]


# ── lane contract ────────────────────────────────────────────────────────────

def test_private_proxy_lane_runner_registered():
    assert "private_proxy" in worker_pool.registered_lanes()
    assert worker_pool.get_lane_runner("private_proxy") is \
        private_proxy.private_proxy_lane_runner


def test_lane_runner_is_read_only_and_honors_cap(offline, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("lane runner must NEVER write candidates itself")
    monkeypatch.setattr(inbox, "upsert_candidate", _boom)
    monkeypatch.setattr(private_proxy, "collect_corpus",
                        lambda window_days=14, notes=None: ACME_CORPUS)
    payloads = private_proxy.private_proxy_lane_runner(
        {"max_candidates_per_run": 1}, dry_run=True)
    assert isinstance(payloads, list) and len(payloads) == 1
    assert payloads[0]["candidate_type"] == "PRIVATE_COMPANY_PROXY_CANDIDATE"


def test_lane_yaml_declares_private_proxy_lane():
    lanes = worker_pool.load_lanes()
    lane = lanes["private_proxy"]
    assert lane["promotion_allowed"] is False
    assert lane["promotion_requires_operator"] is True
    # every routing domain the module can pin is allowed by the lane fences
    for dom in private_proxy.ROUTING_DOMAINS:
        assert dom in lane["allowed_domains"]


def test_run_discovery_dry_run_writes_nothing(offline, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("dry run must not write")
    monkeypatch.setattr(inbox, "upsert_candidate", _boom)
    monkeypatch.setattr(private_proxy, "collect_corpus",
                        lambda window_days=14, notes=None: ACME_CORPUS)
    report = private_proxy.run_discovery(dry_run=True)
    assert report["dry_run"] is True
    assert report["upserted"] == 0
    assert report["would_upsert"] >= 1
    assert report["candidates"][0]["private_proxy_json"]["recommended_action"] \
        == "research_only"


# ── targeted --company analysis ──────────────────────────────────────────────

def test_analyze_company_no_evidence_reports_validate_first(offline):
    report = private_proxy.analyze_company("Levelable", corpus=[])
    assert report["status"] == "no_evidence"
    assert "Validate-first" in report["message"]
    assert report["candidate_payload"] is None
    assert report["proxies"] == []
    assert "report-only" in report["writes"]


def test_analyze_company_with_corpus_evidence(offline, monkeypatch):
    monkeypatch.setattr(
        private_proxy, "_ticker_verdict",
        lambda sym: _verdict(VERDICT_VALID, sym, valid=True)
        if sym == "TEAM" else _verdict(VERDICT_INVALID, sym))
    report = private_proxy.analyze_company("Loom", corpus=LOOM_CORPUS)
    assert report["status"] == "candidate"
    assert report["mentions"] == 2 and report["cross_source_count"] == 2
    assert report["proxies"] and report["proxies"][0]["ticker"] == "TEAM"
    ppj = report["candidate_payload"]["meta"]["private_proxy_json"]
    assert ppj["public_parent_ticker"] == "TEAM"
    assert ppj["recommended_action"] == "proxy_analysis"


def test_analyze_company_directly_listed(offline, monkeypatch):
    monkeypatch.setattr(private_proxy, "_ticker_verdict",
                        lambda sym: _verdict(VERDICT_VALID, sym, valid=True))
    report = private_proxy.analyze_company(
        "Zorp", corpus=[_row("Zorp is everywhere."), _row("More Zorp news.",
                                                          source="beta-wire")])
    assert report["status"] == "directly_listed"
    assert report["candidate_payload"] is None


# ── safety: no broker/execution imports ──────────────────────────────────────

def test_no_broker_or_execution_imports():
    forbidden = re.compile(
        r"^\s*(?:from|import)\s+[\w.]*(?:broker|execution|schwab|alpaca|"
        r"order|trade_exec)", re.IGNORECASE | re.MULTILINE)
    for rel in ("scripts/lib/hermes_discovery/private_proxy.py",
                "scripts/hermes_private_company_proxy_discovery.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not forbidden.search(src), f"forbidden import in {rel}"
