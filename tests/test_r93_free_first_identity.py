"""R9.3 identity v2 + free-first gate. No paid provider calls."""
from __future__ import annotations

import pytest

from scripts.lib.evidence_freshness_policy import freshness_state, is_decision_fresh
from scripts.lib.free_first_refresh import classify_symbol, reject_paid_transition, run_free_first, summarize
from scripts.lib.librarian_assessment import assess_artifact
from scripts.lib.security_identity import (
    attach_identity_v2,
    classify_unresolved_symbol,
    issuer_guid,
    listing_guid,
    security_guid,
)
from scripts.lib.ticker_knowledge_graph import build_profile, entity_guid, seed_profiles


def test_ticker_guid_namespace_unchanged():
    p = build_profile("META", metadata={"company": "Meta Platforms"})
    assert p["ticker_guid"] == entity_guid("ticker", "META")
    assert p["ticker_id"] == p["ticker_guid"]


def test_security_not_equal_to_ticker_guid():
    p = build_profile("META", metadata={"company": "Meta Platforms"})
    assert p["security_guid"]
    assert p["listing_guid"]
    assert p["security_guid"] != p["ticker_guid"]
    assert p["listing_guid"] != p["ticker_guid"]
    assert security_guid(issuer=p["issuer_guid"], share_class="common", instrument="equity") == p["security_guid"]
    class_a = security_guid(issuer=p["issuer_guid"], share_class="A", instrument="equity")
    assert class_a != p["security_guid"]


def test_symbol_reuse_does_not_collapse_issuers():
    a = issuer_guid(company="Old Co META 2010")
    b = issuer_guid(company="Meta Platforms")
    assert a != b
    listing_a = listing_guid(security=security_guid(issuer=a), symbol="META")
    listing_b = listing_guid(security=security_guid(issuer=b), symbol="META")
    assert listing_a != listing_b
    assert entity_guid("ticker", "META") == entity_guid("ticker", "meta")  # alias still ticker-string


def test_unresolved_cusip_and_fund():
    assert classify_unresolved_symbol("12507E201")["kind"] == "cusip_or_fixed_income"
    assert classify_unresolved_symbol("AMAGX")["kind"] == "fund"
    assert classify_unresolved_symbol("NOC")["kind"] == "equity_unresolved"


def test_no_invented_cik():
    p = build_profile("GOVX")
    p = attach_identity_v2(p)
    assert p.get("cik") in (None, "")
    # No issuer/instrument identifiers → not a fabricated security identity from ticker text.
    assert p.get("security_guid") in (None, "")
    assert p["identity_status"] == "UNRESOLVED_WITH_REASON"
    assert p.get("ticker_guid_is_not_security") is True


def test_seed_profiles_still_idempotent(tmp_path):
    rows = [{"symbol": "SCHG"}, {"symbol": "SCHD"}]
    assert seed_profiles(tmp_path, rows)["profiles_created"] == 2
    assert seed_profiles(tmp_path, rows)["profiles_created"] == 0


def test_paid_transition_forbidden():
    with pytest.raises(RuntimeError, match="PAID_PROVIDER_FORBIDDEN"):
        reject_paid_transition("PLANNED", True, mode="FREE_FIRST_ONLY")
    reject_paid_transition("PLANNED", False, mode="FREE_FIRST_ONLY")


def test_free_first_no_new_info_when_fresh_hermes_and_thesis():
    profile = attach_identity_v2(build_profile("NOC", metadata={"company": "Northrop Grumman", "sector": "Industrials"}))
    hermes = [{"symbol": "NOC", "status": "promoted", "created_at": "2099-01-01T00:00:00+00:00", "source_urls": "https://example.com/a"}]
    row = classify_symbol(profile, hermes_rows=hermes, thesis={"thesis_version": "symbol_noc@v5"})
    assert row["no_new_info"] is True
    assert row["llm_eligible"] is None
    assert row["bucket"] in ("existing_Hermes_reuse", "no_refresh_needed")


def test_free_first_marks_flash_not_call(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "Northrop"}, {"symbol": "GOVX"}])
    report = run_free_first(tmp_path)
    assert report["paid_calls_attempted"] == 0
    assert report["paid_calls_completed"] == 0
    assert report["Pro_eligible_count"] == 0
    assert report["total_symbols"] == 2


def test_freshness_class_not_universal():
    now = None
    assert freshness_state("2020-01-01T00:00:00+00:00", evidence_class="news_catalyst") == "STALE"
    assert is_decision_fresh("2020-01-01T00:00:00+00:00", evidence_class="methodology_canon") is True


def test_librarian_duplicate_not_material():
    art = {"title": "x", "summary": "y", "source_url": "https://sec.gov/a", "content_hash": "abc"}
    a = assess_artifact(art, prior_hashes=set())
    b = assess_artifact(art, prior_hashes={a["content_hash"]})
    assert b["duplicate"] is True
    assert b["material"] is False


def test_summarize_never_implies_120_need_llm():
    rows = [
        classify_symbol(attach_identity_v2(build_profile("SCHD", metadata={"company": "Schwab", "sector": "ETF"}))),
        classify_symbol(attach_identity_v2(build_profile("12507E201"))),
    ]
    s = summarize(rows)
    assert s["total_symbols"] == 2
    assert s["Flash_eligible_count"] < 2
    assert s["paid_calls_attempted"] == 0
