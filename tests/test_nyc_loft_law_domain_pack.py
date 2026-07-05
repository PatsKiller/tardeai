#!/usr/bin/env python3
"""WS Stage 5 — NYC Loft Law domain pack (spec Part G) test suite.

Covers: pack load + fail-closed validation (incl. the never-auto-publish hard
rule), domain registration into the registry, forced labels on every
candidate, source-policy classification (blocked skipped, primary ranked
first), candidate-type classification on synthetic texts, workspace isolation
(candidates stamped nyc_loft_law; assert_can_write blocks trade surfaces),
the 'legal_domain' lane-runner registration, the content_stage pipeline stub,
and the no-broker-imports guarantee.

Pure synthetic-data tests — the DB seam (loft_law._execute) is monkeypatched;
no PostgreSQL required.

    .venv/bin/python -m pytest tests/test_nyc_loft_law_domain_pack.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import (domains, inbox, loft_law,  # noqa: E402
                                  worker_pool, workspaces)

PACK_PATH = ROOT / "config" / "research_domains" / "nyc_loft_law.yaml"


@pytest.fixture(autouse=True)
def fresh_caches():
    loft_law._reset_pack_cache()
    domains._reset_cache()
    workspaces._reset_cache()
    yield
    loft_law._reset_pack_cache()
    domains._reset_cache()
    workspaces._reset_cache()


def _pack() -> dict:
    return loft_law.load_pack()


def _tampered(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(PACK_PATH.read_text(encoding="utf-8"))
    mutate(data)
    p = tmp_path / "pack.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _news_row(title, body="", source="news", source_url=None):
    return {"title": title, "body": body, "source": source,
            "source_url": source_url, "stream": "news_articles"}


# ── pack loads + validates ────────────────────────────────────────────────────

def test_pack_loads_and_validates():
    pack = _pack()
    assert pack["pack"] == "nyc_loft_law"
    assert pack["workspace"] == "nyc_loft_law"
    assert pack["domain_name"] == "legal_housing"
    assert pack["auto_publish"] is False
    assert pack["content_stage"] == "candidate"
    # spec Part G term list present (word-for-word spot checks)
    for term in ("Loft Law", "IMD", "Interim Multiple Dwelling",
                 "NYC Loft Board", "MDL Article 7-C", "legalization",
                 "protected occupant", "coverage application", "abandonment",
                 "fixture", "rent regulation", "certificate of occupancy",
                 "DOB violations", "fire safety", "residential conversion",
                 "zoning", "rent stabilization", "owner compliance"):
        assert loft_law.match_terms(term, pack["terms"]), f"term missing: {term}"
    # all five candidate types
    assert set(pack["candidate_types"]) == {
        "LEGAL_TOPIC_CANDIDATE", "SOURCE_CANDIDATE", "CASE_LAW_CANDIDATE",
        "STATUTE_UPDATE_CANDIDATE", "WEBSITE_CONTENT_CANDIDATE"}
    # source policy tiers all present
    for tier in ("primary", "secondary", "blocked"):
        assert pack["source_policy"][tier]


def test_pack_requires_all_four_labels(tmp_path):
    p = _tampered(tmp_path, lambda d: d["required_labels"].remove("Not legal advice."))
    with pytest.raises(loft_law.LoftLawPackError, match="required_labels"):
        loft_law.load_pack(p)


def test_pack_never_auto_publish_hard_rule(tmp_path):
    p = _tampered(tmp_path,
                  lambda d: d["publishing"].__setitem__("auto_publish", True))
    with pytest.raises(loft_law.LoftLawPackError, match="auto_publish"):
        loft_law.load_pack(p)
    # missing publishing stanza fails closed too
    p2 = _tampered(tmp_path, lambda d: d.pop("publishing"))
    with pytest.raises(loft_law.LoftLawPackError, match="auto_publish"):
        loft_law.load_pack(p2)


def test_pack_rejects_unknown_candidate_type(tmp_path):
    p = _tampered(tmp_path,
                  lambda d: d["candidate_types"].append("TRADE_SIGNAL_CANDIDATE"))
    with pytest.raises(loft_law.LoftLawPackError, match="candidate_types"):
        loft_law.load_pack(p)


def test_pack_rejects_wrong_workspace(tmp_path):
    p = _tampered(tmp_path, lambda d: d.__setitem__("workspace", "trade_ai"))
    with pytest.raises(loft_law.LoftLawPackError, match="workspace"):
        loft_law.load_pack(p)


def test_missing_pack_fails_closed(tmp_path):
    with pytest.raises(loft_law.LoftLawPackError, match="missing"):
        loft_law.load_pack(tmp_path / "nope.yaml")


# ── domain registration ───────────────────────────────────────────────────────

def test_domain_registers_into_registry():
    name = loft_law.ensure_domain_registered()
    assert name == "legal_housing"
    policy = domains.get_domain(name)
    assert policy["risk_level"] == "legal"
    assert policy["auto_promote"] is False  # registry hard rule survives
    assert policy["requires_professional_review_label"] is True
    assert "CASE_LAW_CANDIDATE" in policy["allowed_candidate_types"]
    # idempotent
    assert loft_law.ensure_domain_registered() == "legal_housing"


# ── source policy ─────────────────────────────────────────────────────────────

def test_source_classification_tiers():
    assert loft_law.classify_source("https://www.nyc.gov/site/loftboard/index.page") == "primary"
    assert loft_law.classify_source("https://iappscontent.courts.state.ny.us/x.pdf") == "primary"
    assert loft_law.classify_source("nycourts.gov") == "primary"
    assert loft_law.classify_source("https://legalaidnyc.org/get-help/housing") == "secondary"
    assert loft_law.classify_source("https://www.reddit.com/r/Loft_Law/") == "blocked"
    assert loft_law.classify_source("https://random-realty-blog.example.com/") == "unlisted"
    assert loft_law.classify_source(None) == "unlisted"


def test_blocked_source_skipped_entirely():
    rows = [
        _news_row("Loft Board coverage application backlog", source="nyc.gov",
                  source_url="https://www.nyc.gov/site/loftboard/news/1.page"),
        _news_row("Loft Law hot takes thread", source="reddit",
                  source_url="https://reddit.com/r/nyc/loft_law_thread"),
    ]
    skipped: dict[str, int] = {}
    payloads = loft_law.build_payloads(rows, skipped=skipped)
    assert skipped.get("blocked_source") == 1
    labels = " ".join(p["label"] for p in payloads)
    assert "hot takes" not in labels.lower()


def test_primary_preferred_source_quality_ranking():
    rows = [
        _news_row("Fixture fee dispute explained for tenants",
                  source_url="https://www.nolo.com/loft-fixture-fee"),   # secondary
        _news_row("Loft Board adopts rule change on coverage application",
                  source_url="https://www.nyc.gov/site/loftboard/rules/2.page"),  # primary
        _news_row("Protected occupant status overview",
                  source_url="https://some-blog.example.net/imd"),       # unlisted
    ]
    payloads = loft_law.build_payloads(rows)
    qualities = [p["meta"]["source_quality"] for p in payloads]
    assert qualities == sorted(qualities, reverse=True)
    assert payloads[0]["meta"]["source_policy_class"] == "primary"
    assert (loft_law.SOURCE_QUALITY["primary"]
            > loft_law.SOURCE_QUALITY["secondary"]
            > loft_law.SOURCE_QUALITY["unlisted"])


# ── candidate-type classification (synthetic texts) ───────────────────────────

def test_case_law_classification():
    assert loft_law.classify_candidate_type(
        "Chazon LLC v. NYC Loft Board — Appellate Division upholds coverage "
        "ruling for IMD tenants") == "CASE_LAW_CANDIDATE"
    assert loft_law.classify_candidate_type(
        "Housing court decision and order finds protected occupant status "
        "for loft tenant; respondent owner appeals") == "CASE_LAW_CANDIDATE"


def test_statute_update_classification():
    assert loft_law.classify_candidate_type(
        "Albany bill amends MDL Article 7-C: Loft Law coverage application "
        "deadline extended, signed into law") == "STATUTE_UPDATE_CANDIDATE"
    assert loft_law.classify_candidate_type(
        "Loft Board proposed rule on fixture fee calculations, effective date "
        "set for October") == "STATUTE_UPDATE_CANDIDATE"


def test_explainer_classification():
    assert loft_law.classify_candidate_type(
        "What is an Interim Multiple Dwelling? A guide to NYC Loft Law "
        "protections for residential tenants") == "WEBSITE_CONTENT_CANDIDATE"
    # a big recurring cluster is explainer-worthy even without explainer words
    assert loft_law.classify_candidate_type(
        "loft law rent regulation notes",
        cluster_size=loft_law.EXPLAINER_CLUSTER_MIN) == "WEBSITE_CONTENT_CANDIDATE"


def test_recurring_topic_default_classification():
    assert loft_law.classify_candidate_type(
        "Loft Board schedules hearings on legalization progress at Brooklyn "
        "IMD buildings") == "LEGAL_TOPIC_CANDIDATE"


def test_end_to_end_type_mix_in_payloads():
    rows = [
        _news_row("Tenant v. Owner: Appellate Division loft law ruling",
                  source_url="https://nycourts.gov/decision/123"),
        _news_row("Loft Law amendment enacted, new coverage application window",
                  source_url="https://www.nysenate.gov/legislation/bills/S1234"),
        _news_row("Loft Board posts legalization milestones",
                  source_url="https://www.nyc.gov/site/loftboard/index.page"),
    ]
    payloads = loft_law.build_payloads(rows)
    types = {p["candidate_type"] for p in payloads}
    assert "CASE_LAW_CANDIDATE" in types
    assert "STATUTE_UPDATE_CANDIDATE" in types
    assert types & {"LEGAL_TOPIC_CANDIDATE", "WEBSITE_CONTENT_CANDIDATE"}


# ── labels forced on every candidate + pipeline stub ──────────────────────────

def test_all_labels_forced_on_every_payload():
    rows = [
        _news_row("Loft Board coverage application ruling by the court",
                  source_url="https://nycourts.gov/x"),
        _news_row("Loft Law amendment enacted",
                  source_url="https://www.nysenate.gov/y"),
        _news_row("What is an IMD? A guide",
                  source_url="https://legalaidnyc.org/z"),
        _news_row("rent stabilization for lofts weekly notes"),
    ]
    payloads = loft_law.build_payloads(rows)
    assert payloads
    for p in payloads:
        assert p["meta"]["required_labels"] == list(_pack()["required_labels"])
        for lbl in loft_law.REQUIRED_LABELS:
            assert lbl in p["meta"]["required_labels"]
        assert p["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
        # content pipeline stub: candidate stage only, never published
        assert p["meta"]["content_stage"] == "candidate"
        assert p["meta"]["research_domain"] == "legal_housing"
        assert p["meta"]["workspace_id"] == "nyc_loft_law"


# ── workspace isolation ───────────────────────────────────────────────────────

def _enrich_view(payload: dict) -> dict:
    return {"candidate_type": payload["candidate_type"],
            "label": payload["label"], "summary": payload.get("summary"),
            "normalized_key": payload["label"].lower(), "source_domain":
            payload.get("source_domain"), "source_url": payload.get("source_url"),
            "evidence": payload.get("evidence") or [], "seed_symbols": [],
            "extracted_symbols": [], "meta": dict(payload["meta"]),
            "is_operator": False, "seen_count": 1}


def test_candidates_stamped_into_loft_law_workspace():
    loft_law.ensure_domain_registered()
    payloads = loft_law.build_payloads([
        _news_row("Loft Board legalization hearing schedule",
                  source_url="https://www.nyc.gov/site/loftboard/a.page")])
    assert payloads
    p = payloads[0]
    meta, level, domain = inbox._enrich_domain_meta(dict(p["meta"]),
                                                    _enrich_view(p),
                                                    p["safe_action_level"])
    assert domain == "legal_housing"
    assert meta["workspace_id"] == "nyc_loft_law"
    assert meta["workspace_domain"] == "legal_housing"
    # legal risk domain → professional-review label + forced operator review
    assert level == "OPERATOR_REVIEW_REQUIRED"
    assert meta["required_review_label"]
    assert meta["required_labels"] == list(_pack()["required_labels"])
    assert workspaces.workspace_for_domain("legal_housing") == "nyc_loft_law"


@pytest.mark.parametrize("surface", sorted(workspaces.TRADE_SURFACES))
def test_loft_law_workspace_blocks_trade_surfaces(surface):
    with pytest.raises(workspaces.WorkspaceIsolationError):
        workspaces.assert_can_write("nyc_loft_law", surface)


def test_loft_law_candidate_never_a_trading_signal():
    with pytest.raises(workspaces.WorkspaceIsolationError):
        workspaces.assert_tradeable_signal(
            {"meta_json": {"workspace_id": "nyc_loft_law",
                           "research_domain": "legal_housing"}})


# ── lane runner + scan seam ───────────────────────────────────────────────────

def test_legal_domain_lane_runner_registered():
    runner = worker_pool.get_lane_runner("legal_domain")
    assert runner is loft_law._lane_runner


def test_lane_runner_is_read_only_payload_producer(monkeypatch):
    rows = [_news_row("Loft Law amendment enacted for IMD buildings",
                      source_url="https://www.nysenate.gov/legislation/1")]

    def fake_execute(sql, params=None, fetch=None):
        if "information_schema" in sql:
            return {"ok": 1}
        return rows if "news_articles" in sql else []

    monkeypatch.setattr(loft_law, "_execute", fake_execute)
    writes = []
    monkeypatch.setattr(inbox, "upsert_candidate",
                        lambda *a, **k: writes.append(k) or {})
    payloads = loft_law._lane_runner({"max_candidates_per_run": 5}, dry_run=True)
    assert payloads and payloads[0]["candidate_type"] == "STATUTE_UPDATE_CANDIDATE"
    assert writes == []  # the runner NEVER writes; the pool owns writes


def test_run_discovery_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(
        loft_law, "_execute",
        lambda sql, params=None, fetch=None:
        ({"ok": 1} if "information_schema" in sql else []))
    writes = []
    monkeypatch.setattr(inbox, "upsert_candidate",
                        lambda *a, **k: writes.append(k) or {})
    report = loft_law.run_discovery(dry_run=True)
    assert report["dry_run"] is True
    assert report["scanned_rows"] == 0 and report["upserted"] == 0
    assert writes == []


# ── advisory-only guarantee ───────────────────────────────────────────────────

def test_no_broker_imports_in_loft_law_files():
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?(brokers\b|schwab\w*|"
        r"alpaca\w*)", re.MULTILINE)
    targets = [
        ROOT / "scripts" / "lib" / "hermes_discovery" / "loft_law.py",
        ROOT / "scripts" / "hermes_loft_law_discovery.py",
    ]
    offenders = [p.name for p in targets if forbidden.search(p.read_text())]
    assert not offenders, f"broker imports in advisory-only files: {offenders}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
