#!/usr/bin/env python3
"""Coverage adapters → Discovery Inbox (URDL Stage 4, Part H).

Pure/monkeypatched — no DB required (db_adapter._execute is monkeypatched with
synthetic rows). Covers: every adapter emits domain-correct TOPIC candidates,
sensitive domains pick up professional-review labels via the Stage-1
enrichment path, per-domain daily caps are honored, dry-run writes nothing,
system_ops findings target the escalation_candidate promotion path, and the
advisory-only no-broker-imports guarantee.

    .venv/bin/python -m pytest tests/test_hermes_discovery_coverage.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db_adapter  # noqa: E402
import hermes_discovery_coverage_adapters as cli  # noqa: E402
import hermes_discovery_ingestors as ing  # noqa: E402
from lib.hermes_discovery import coverage, domains, inbox, subjects  # noqa: E402


# ── synthetic DB dispatcher ──────────────────────────────────────────────────

@pytest.fixture
def fake_db(monkeypatch):
    """Register (sql_needle, rows) pairs; first needle found in the SQL wins.
    Unmatched SQL returns [] (adapters must skip cleanly what's absent)."""
    routes: list[tuple[str, list[dict]]] = []

    def dispatch(sql, params=None, fetch=None):
        for needle, rows in routes:
            if needle in sql:
                return rows
        return []

    monkeypatch.setattr(db_adapter, "_execute", dispatch)
    return routes


@pytest.fixture
def holdings_files(tmp_path, monkeypatch):
    """Synthetic holdings.json + risk_management.json snapshots."""
    holdings = tmp_path / "holdings.json"
    holdings.write_text(json.dumps({"holdings": [
        {"symbol": "NVDA", "shares": 100, "market_value": 50000,
         "account": "acct_a"},
        {"symbol": "T", "shares": 200, "market_value": 4000,
         "account": "acct_b"},
    ]}))
    monkeypatch.setattr(subjects, "HOLDINGS_PATH", holdings)
    monkeypatch.setattr(subjects, "_holdings_cache", None)

    rm = tmp_path / "risk_management.json"
    rm.write_text(json.dumps({"positions": [
        {"symbol": "NVDA", "status": "NO STOP", "market_value": 50000,
         "account": "acct_a"},
        {"symbol": "T", "status": "OK", "protected": True,
         "market_value": 4000, "account": "acct_b"},
    ]}))
    return rm


def _classes(payloads):
    return {p["meta"]["finding_class"] for p in payloads}


def _assert_domain(payloads, domain):
    assert payloads, f"expected candidates for domain {domain}"
    for p in payloads:
        assert p["candidate_type"] == "TOPIC_CANDIDATE"
        assert p["meta"]["research_domain"] == domain
        assert domains.classify_domain(
            {"candidate_type": p["candidate_type"], "label": p["label"],
             "summary": p["summary"], "meta": p["meta"]}) == domain


# ── holdings ─────────────────────────────────────────────────────────────────

def test_holdings_adapter_three_finding_classes(fake_db, holdings_files):
    fake_db.append(("symbol_profiles",
                    [{"symbol": "NVDA", "next_earnings_date": "2026-07-10"}]))
    fake_db.append(("ticker_dividend_data",
                    [{"symbol": "T", "annual_dividend_per_share": 1.11},
                     {"symbol": "NVDA", "annual_dividend_per_share": 0.04}]))
    payloads = coverage.holdings_findings(rm_path=holdings_files)
    _assert_domain(payloads, "portfolio_holdings")
    assert _classes(payloads) == {"stops_gap", "upcoming_earnings",
                                  "dividend_concentration"}
    stops = next(p for p in payloads
                 if p["meta"]["finding_class"] == "stops_gap")
    assert stops["seed_symbols"] == ["NVDA"]
    conc = next(p for p in payloads
                if p["meta"]["finding_class"] == "dividend_concentration")
    assert conc["meta"]["top_symbol"] == "T"  # 222/226 of estimated income
    assert conc["meta"]["top_income_share"] >= 0.9


def test_holdings_adapter_skips_absent_data_cleanly(fake_db, tmp_path,
                                                    monkeypatch):
    """No holdings file, no rm file, empty DB → no findings, no exception."""
    monkeypatch.setattr(subjects, "HOLDINGS_PATH", tmp_path / "none.json")
    monkeypatch.setattr(subjects, "_holdings_cache", None)
    assert coverage.holdings_findings(rm_path=tmp_path / "none_rm.json") == []


# ── watchlist ────────────────────────────────────────────────────────────────

def test_watchlist_adapter(fake_db):
    fake_db.append(("NOT EXISTS", [{"symbol": "AAA"}, {"symbol": "BBB"}]))
    fake_db.append(("COALESCE(hermes_scored_at",
                    [{"symbol": "CCC", "last_intel": "2026-06-01"}]))
    payloads = coverage.watchlist_findings()
    _assert_domain(payloads, "watchlist")
    assert _classes(payloads) == {"stale_intelligence", "missing_research"}
    stale = next(p for p in payloads
                 if p["meta"]["finding_class"] == "stale_intelligence")
    assert stale["seed_symbols"] == ["CCC"]
    missing = next(p for p in payloads
                   if p["meta"]["finding_class"] == "missing_research")
    assert missing["seed_symbols"] == ["AAA", "BBB"]


# ── sectors ──────────────────────────────────────────────────────────────────

def test_sectors_adapter(fake_db):
    fake_db.append(("GROUP BY sp.sector",
                    [{"sector": "Technology", "n": 7,
                      "symbols": ["AAA", "BBB", "CCC"]},
                     {"sector": "Industrials", "n": 4,
                      "symbols": ["DDD", "EEE"]}]))
    payloads = coverage.sector_cluster_findings()
    _assert_domain(payloads, "sectors")
    assert len(payloads) == 2
    assert payloads[0]["label"] == "Sector cluster: Technology"
    assert payloads[0]["seed_symbols"] == ["AAA", "BBB", "CCC"]
    assert payloads[0]["meta"]["sectors"] == ["Technology"]


# ── term-recurrence areas (taxes / retirement / legal / macro) ───────────────

# each headline matches exactly ONE term from its area's TERM_SETS list
TERM_CASES = [
    ("taxes", "wash sale", "Wash sale enforcement expands for brokerages"),
    ("retirement", "irmaa", "IRMAA surcharge brackets shift for 2027"),
    ("legal", "finra", "FINRA issues new arbitration decision"),
    ("macro", "cpi", "June CPI comes in hot at 3.1%"),
]


@pytest.mark.parametrize("area,term,headline", TERM_CASES)
def test_term_adapters_emit_domain_correct_topics(fake_db, area, term, headline):
    fake_db.append(("news_articles",
                    [{"text_a": headline, "text_b": "", "source": "reuters",
                      "source_url": "https://example.com/a"},
                     {"text_a": f"Follow-up: {headline}", "text_b": "",
                      "source": "wsj", "source_url": "https://example.com/b"}]))
    payloads = coverage.term_topic_findings(area, min_matches=2)
    _assert_domain(payloads, area)
    assert len(payloads) == 1
    p = payloads[0]
    assert p["meta"]["matched_term"] == term
    assert p["meta"]["match_count"] == 2
    assert p["meta"]["finding_class"] == "term_recurrence"
    assert term in p["label"].lower()
    assert len(p["evidence"]) == 2


def test_term_adapter_min_matches_floor(fake_db):
    fake_db.append(("news_articles",
                    [{"text_a": "one lonely cpi mention", "text_b": "",
                      "source": "x", "source_url": None}]))
    assert coverage.term_topic_findings("macro", min_matches=2) == []


def test_term_matching_uses_word_boundaries(fake_db):
    # "fed" must not match inside "federated"; "ira" not inside "airaware"
    fake_db.append(("news_articles",
                    [{"text_a": "Federated Hermes launches airaware fund",
                      "text_b": "", "source": "x", "source_url": None}] * 3))
    assert coverage.term_topic_findings("macro", min_matches=1) == []
    assert coverage.term_topic_findings("retirement", min_matches=1) == []


# ── system_ops ───────────────────────────────────────────────────────────────

def test_system_ops_adapter_escalation_path(fake_db):
    fake_db.append(("system_health_checks",
                    [{"component": "news_ingestion", "check_type": "cron_health",
                      "status": "STALE", "severity": "CRITICAL",
                      "failure_count": 3, "last_error": "no run in 6h",
                      "updated_at": "2026-07-04T12:00:00Z"}]))
    payloads = coverage.system_ops_findings()
    _assert_domain(payloads, "system_ops")
    p = payloads[0]
    assert p["meta"]["finding_class"] == "health_check_failure"
    assert p["meta"]["promotion_path_hint"] == "escalation_candidate"
    assert "news_ingestion" in p["label"]
    # the pinned domain actually allows the escalation promotion path
    assert "escalation_candidate" in \
        domains.domain_policy("system_ops")["promotion_paths"]


# ── Stage-1 enrichment: professional-review labels come free ─────────────────

def _enrich(payload):
    view = {
        "candidate_type": payload["candidate_type"], "label": payload["label"],
        "summary": payload["summary"], "evidence": payload["evidence"],
        "seed_symbols": payload["seed_symbols"], "extracted_symbols": [],
        "meta": dict(payload["meta"]), "is_operator": False, "seen_count": 1,
    }
    return inbox._enrich_domain_meta(dict(payload["meta"]), view,
                                     "RESEARCH_ONLY")


@pytest.mark.parametrize("area", ["taxes", "retirement", "legal"])
def test_sensitive_domains_carry_professional_review_labels(fake_db, area):
    term = TERM_SETS_SAMPLE[area]
    fake_db.append(("news_articles",
                    [{"text_a": f"headline about {term} rules", "text_b": "",
                      "source": "x", "source_url": None}] * 2))
    payloads = coverage.term_topic_findings(area, min_matches=2)
    assert payloads
    meta, level, domain = _enrich(payloads[0])
    assert domain == area
    assert level == "OPERATOR_REVIEW_REQUIRED"  # forced by Stage-1
    assert meta["required_review_label"]  # "consult a qualified professional"
    assert "professional" in meta["required_review_label"].lower()
    assert meta["advisory_label"]
    assert meta["subject_json"]["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"


TERM_SETS_SAMPLE = {"taxes": "wash sale", "retirement": "medicare",
                    "legal": "finra"}


def test_non_sensitive_domain_has_no_review_label(fake_db):
    fake_db.append(("news_articles",
                    [{"text_a": "cpi print and fed path", "text_b": "",
                      "source": "x", "source_url": None}] * 2))
    payloads = coverage.term_topic_findings("macro", min_matches=2)
    assert payloads
    meta, level, domain = _enrich(payloads[0])
    assert domain == "macro"
    assert level == "RESEARCH_ONLY"  # not forced upward
    assert "required_review_label" not in meta


# ── caps + dry-run through the shared intake machinery ───────────────────────

def _cfg():
    return json.loads((ROOT / "config" / "hermes_discovery_schedule.json")
                      .read_text(encoding="utf-8"))


def test_per_domain_daily_cap_honored():
    caps = ing.effective_caps(_cfg(), "steady")
    caps["max_candidates_per_domain_per_day"] = 1
    skipped: dict[str, int] = {}
    gate = ing.make_intake_gate(caps, {"by_domain": {}, "ticker": 0,
                                       "legal_tax": 0}, skipped)
    payloads = [coverage._topic_payload("macro", f"Macro research: cpi {i}",
                                        "s", finding_class="term_recurrence")
                for i in range(2)]
    out = ing._upsert_all(payloads, actor="pytest", dry_run=True, gate=gate)
    assert out["skipped"] == 1
    assert out["skipped_reasons"] == {"domain_cap:macro": 1}


def test_sensitive_daily_cap_honored():
    caps = ing.effective_caps(_cfg(), "steady")
    skipped: dict[str, int] = {}
    gate = ing.make_intake_gate(caps, {"by_domain": {}, "ticker": 0,
                                       "legal_tax": caps["max_legal_tax_candidates_per_day"]},
                                skipped)
    p = coverage._topic_payload("taxes", "Taxes research: wash sale", "s",
                                finding_class="term_recurrence")
    out = ing._upsert_all([p], actor="pytest", dry_run=True, gate=gate)
    assert out["skipped"] == 1 and out["skipped_reasons"] == {"legal_tax_cap": 1}


def test_dry_run_never_writes_inbox(fake_db, monkeypatch):
    monkeypatch.setattr(inbox, "upsert_candidate",
                        lambda *a, **k: pytest.fail("dry-run must not write"))
    monkeypatch.setattr(ing.inbox, "upsert_candidate",
                        lambda *a, **k: pytest.fail("dry-run must not write"))
    fake_db.append(("news_articles",
                    [{"text_a": "cpi and fed", "text_b": "", "source": "x",
                      "source_url": None}] * 2))
    report = cli.run_coverage(["macro"], dry_run=True,
                              scorecard_path=Path("/nonexistent"))
    assert report["results"]["macro"]["upserted"] == 0
    assert report["results"]["macro"]["scanned"] >= 1
    assert report["by_domain_counts"].get("macro", 0) >= 1


def test_run_coverage_fails_closed_on_broken_config(tmp_path):
    report = cli.run_coverage(["macro"], dry_run=True,
                              config_path=tmp_path / "missing.json")
    assert "error" in report and report["results"] == {}


def test_run_coverage_one_broken_adapter_never_blocks_others(fake_db,
                                                             monkeypatch):
    def boom(**kw):
        raise RuntimeError("adapter exploded")

    monkeypatch.setitem(cli.COVERAGE_ADAPTERS, "sectors", boom)
    fake_db.append(("news_articles",
                    [{"text_a": "cpi and fed", "text_b": "", "source": "x",
                      "source_url": None}] * 2))
    report = cli.run_coverage(["sectors", "macro"], dry_run=True,
                              scorecard_path=Path("/nonexistent"))
    assert "error" in report["results"]["sectors"]
    assert report["results"]["macro"]["scanned"] >= 1


# ── advisory-only guarantee ──────────────────────────────────────────────────

def test_no_broker_imports_in_stage4_files():
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?(brokers\b|schwab\w*|"
        r"alpaca\w*)", re.MULTILINE)
    targets = [
        ROOT / "scripts" / "lib" / "hermes_discovery" / "coverage.py",
        ROOT / "scripts" / "hermes_discovery_coverage_adapters.py",
        ROOT / "scripts" / "lib" / "hermes_outcome_bus" / "bus.py",
        ROOT / "scripts" / "hermes_outcome_feedback_agent.py",
    ]
    offenders = []
    for path in targets:
        m = forbidden.search(path.read_text(encoding="utf-8"))
        if m:
            offenders.append(f"{path.name}: {m.group(0).strip()}")
    assert not offenders, f"broker imports found in advisory-only files: {offenders}"


def test_every_coverage_area_has_a_registered_domain():
    registry = domains.load_domains()
    for area, domain in coverage.COVERAGE_DOMAINS.items():
        assert domain in registry, f"{area} pins unknown domain {domain!r}"
        assert area in coverage.COVERAGE_ADAPTERS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
