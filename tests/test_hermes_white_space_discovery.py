#!/usr/bin/env python3
"""White-Space Discovery Stage 2 — coverage-diff gap engine + gap dashboard.

Covers: gap candidates decoupled from holdings (synthetic coverage vs
demand), the closed MISSING_* gap_type taxonomy, dedupe against the covered
set, recurrence/cross-source gates, the required meta contract, the
worker-pool lane-runner registration + contract (dry runs write nothing),
the /api/v2/hermes/discovery-gaps route shape, the all-areas-down fail-closed
guard, and the no-broker-imports guarantee.

TRADE_AI_CI-safe: everything runs against synthetic rows via the
white_space._execute seam — no DB required.

    .venv/bin/python -m pytest tests/test_hermes_white_space_discovery.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import (dedupe, subjects, white_space,  # noqa: E402
                                  worker_pool)


# ── synthetic world ──────────────────────────────────────────────────────────
# COVERED: holdings {AAPL}, watchlist {NVDA}, topic "AI datacenter buildout",
# directive "uranium supply squeeze" (+ keyword "uranium"), strategy
# momentum_scalp, source semianalysis.com.
# DEMAND: quantum networking hardware (recurs, cross-source, UNCOVERED →
# gap), AAPL + AI datacenter buildout (covered), single-source and
# single-mention subjects (gated out).

def _fake_execute_factory(demand_topics=None, entity_rows=None):
    demand_topics = demand_topics if demand_topics is not None else [
        {"subject": "quantum networking hardware", "n": 3, "n_sources": 2,
         "sources": ["arxiv", "reuters"], "sample": "quantum interconnect races"},
        {"subject": "AI datacenter buildout trend", "n": 5, "n_sources": 3,
         "sources": ["wsj", "ft", "reuters"], "sample": "capex supercycle"},
        {"subject": "one source wonder", "n": 4, "n_sources": 1,
         "sources": ["blogspot"], "sample": "unconfirmed"},
        {"subject": "single mention", "n": 1, "n_sources": 2,
         "sources": ["a", "b"], "sample": "once"},
    ]
    entity_rows = entity_rows if entity_rows is not None else [
        {"entity_type": "ticker", "subject": "AAPL", "n": 9, "n_sources": 4,
         "sources": ["wsj", "cnbc", "ft", "reuters"], "sample": "apple everywhere"},
    ]

    def fake_execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if "from watchlist_items" in s:
            return [{"symbol": "NVDA"}]
        if "from topic_monitor" in s:
            return [{"display_name": "AI datacenter buildout"}]
        if "from watch_directives" in s:
            return [{"label": "uranium supply squeeze",
                     "spec": json.dumps({"keywords": ["uranium"]})}]
        if "from strategy_registry" in s:
            return [{"strategy_id": "momentum_scalp",
                     "strategy_type": "momentum_scalp"}]
        if "from research_sources" in s:
            return [{"source_name": "semianalysis.com",
                     "source_url": "https://www.semianalysis.com/feed"}]
        if "from hermes_research_intelligence" in s:
            return [{"subject": t["subject"], "n": t["n"],
                     "n_sources": t["n_sources"], "sources": t["sources"],
                     "sample": t["sample"]} for t in demand_topics]
        if "from content_entity_links" in s:
            return [dict(r) for r in entity_rows]
        if "from hermes_discovery_candidates" in s:
            return []
        return []

    return fake_execute


@pytest.fixture
def synthetic_world(monkeypatch, tmp_path):
    monkeypatch.setattr(white_space, "_execute", _fake_execute_factory())
    monkeypatch.setattr(subjects, "held_symbols", lambda: {"AAPL"})
    monkeypatch.setattr(white_space, "BUS_PATH", tmp_path / "no_bus.json")


# ── gaps are demand-vs-coverage, not holdings-driven ─────────────────────────

def test_gap_candidates_not_tied_to_holdings(synthetic_world):
    report = white_space.run_discovery(dry_run=True)
    assert report["dry_run"] is True and not report.get("error")
    labels = [c["label"] for c in report["candidates"]]
    # the uncovered cross-source recurring subject IS a gap
    assert any("quantum networking hardware" in x for x in labels)
    # held symbol AAPL and covered topic never become gaps
    assert not any("AAPL" in x for x in labels)
    assert not any("datacenter" in x.lower() for x in labels)
    # dry run reports would_upsert, writes nothing
    assert report["upserted"] == 0
    assert report["would_upsert"] == len(report["candidates"]) > 0


def test_recurrence_and_cross_source_gates(synthetic_world):
    report = white_space.run_discovery(dry_run=True)
    labels = [c["label"] for c in report["candidates"]]
    assert not any("one source wonder" in x for x in labels)
    assert not any("single mention" in x for x in labels)
    assert report["skipped_reasons"].get("low_cross_source", 0) >= 1
    assert report["skipped_reasons"].get("low_recurrence", 0) >= 1


# ── dedupe vs the covered set ────────────────────────────────────────────────

def test_dedupe_vs_covered_set(synthetic_world):
    covered = white_space.build_covered_set()
    # normalize_key drops the stopword 'trend' → collides with the monitor
    assert dedupe.normalize_key("AI datacenter buildout trend") in covered["keys"]
    demand = white_space.aggregate_demand(white_space.collect_demand_mentions())
    skipped: dict[str, int] = {}
    gaps = white_space.compute_gaps(demand, covered["keys"], skipped=skipped)
    assert skipped.get("already_covered", 0) >= 2  # AAPL + datacenter topic
    assert all(g["key"] not in covered["keys"] for g in gaps)
    # every covered surface contributed
    assert all(covered["areas"][a] is not None
               for a in white_space.COVERAGE_AREAS)


def test_all_coverage_areas_down_fails_closed(monkeypatch, tmp_path):
    def boom(sql, params=None, fetch=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(white_space, "_execute", boom)
    monkeypatch.setattr(subjects, "held_symbols",
                        lambda: (_ for _ in ()).throw(RuntimeError("no file")))
    monkeypatch.setattr(white_space, "BUS_PATH", tmp_path / "no_bus.json")
    report = white_space.run_discovery(dry_run=True)
    assert "refusing" in report["error"]
    assert report["candidates"] == [] and report["upserted"] == 0
    assert white_space.lane_runner({"max_candidates_per_run": 5},
                                   dry_run=True) == []


# ── gap_type taxonomy ────────────────────────────────────────────────────────

@pytest.mark.parametrize("subject,kwargs,expected", [
    ("wash sale rule changes", {}, "MISSING_TAX_TOPIC"),
    ("irmaa bracket thresholds", {}, "MISSING_RETIREMENT_TOPIC"),
    ("sec enforcement wave against exchanges", {}, "MISSING_LEGAL_TOPIC"),
    ("overnight gap mean reversion strategy", {}, "MISSING_STRATEGY"),
    ("utilities sector rerating", {}, "MISSING_SECTOR"),
    ("Utilities", {"entity_types": ["sector"]}, "MISSING_SECTOR"),
    ("stratechery.com", {}, "MISSING_SOURCE"),
    ("IONQ", {"entity_types": ["ticker"]}, "MISSING_COMPANY"),
    ("sodium-ion battery storage", {}, "MISSING_PRODUCT_VERTICAL"),
    ("labor market cooling narrative", {}, "MISSING_THEME"),
])
def test_classify_gap_type(subject, kwargs, expected):
    assert white_space.classify_gap_type(subject, **kwargs) == expected


def test_gap_type_taxonomy_enforced(synthetic_world):
    payloads = white_space.lane_runner({"max_candidates_per_run": 8},
                                       dry_run=True)
    assert payloads
    for p in payloads:
        assert p["candidate_type"] == "GAP_CANDIDATE"
        assert p["meta"]["gap_type"] in white_space.GAP_TYPES
    # the taxonomy is closed and Stage-4's proxy type is NOT in it
    assert "MISSING_PRIVATE_COMPANY_PROXY" not in white_space.GAP_TYPES
    assert len(white_space.GAP_TYPES) == 9
    # unmatched junk classification falls back inside the taxonomy
    assert white_space.classify_gap_type("zzz qqq xxx") in white_space.GAP_TYPES


def test_required_meta_contract_and_safe_action(synthetic_world):
    payloads = white_space.lane_runner({"max_candidates_per_run": 8},
                                       dry_run=True)
    required = ("gap_type", "why_missing", "why_it_matters",
                "current_system_coverage", "proposed_coverage",
                "evidence_refs", "source_count", "recurrence_count")
    for p in payloads:
        assert p["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
        for key in required:
            assert p["meta"].get(key) not in (None, "", []), \
                f"missing meta.{key} in {p['label']}"
        assert p["meta"]["recurrence_count"] >= white_space.MIN_RECURRENCE
        assert p["meta"]["source_count"] >= white_space.MIN_SOURCES
        assert p["evidence"], "gap payloads must carry evidence refs"
        # stable label → idempotent upserts across runs
        assert p["label"].startswith("Coverage gap: ")


# ── worker-pool lane-runner contract ─────────────────────────────────────────

def test_white_space_lane_runner_registered():
    assert worker_pool.get_lane_runner("white_space") is white_space.lane_runner


def test_lane_runner_respects_lane_cap(synthetic_world, monkeypatch):
    many = [{"subject": f"unseen theme number {i} alpha", "n": 3, "n_sources": 2,
             "sources": ["s1", "s2"], "sample": "x"} for i in range(10)]
    monkeypatch.setattr(white_space, "_execute",
                        _fake_execute_factory(demand_topics=many, entity_rows=[]))
    payloads = white_space.lane_runner({"max_candidates_per_run": 3},
                                       dry_run=True)
    assert len(payloads) == 3


def test_lane_dry_run_through_pool_writes_nothing(synthetic_world, tmp_path,
                                                  monkeypatch):
    """run_lane('white_space', dry_run=True) exercises the registered runner
    through the pool machinery and never writes candidates/state."""
    def no_write(*a, **k):
        raise AssertionError("dry run must never reach upsert_candidate")
    from lib.hermes_discovery import inbox
    monkeypatch.setattr(inbox, "upsert_candidate", no_write)
    state = tmp_path / "state.json"
    report = worker_pool.run_lane("white_space", dry_run=True, force=True,
                                  lock_dir=tmp_path / "locks", state_path=state)
    assert not report.get("error"), report
    assert report["dry_run"] is True and report["scanned"] > 0
    assert report["upserted"] == 0
    assert not state.exists()  # dry runs never mark cadence state


# ── route shape (handler called directly, no server restart needed) ──────────

def _fake_gap_row(i=1, gap_type="MISSING_THEME", status="DISCOVERED",
                  ctype="GAP_CANDIDATE"):
    return {
        "id": i, "candidate_type": ctype,
        "label": f"Coverage gap: subject {i}", "summary": "s",
        "status": status, "safe_action_level": "OPERATOR_REVIEW_REQUIRED",
        "seen_count": 3, "discovery_score": 41.5,
        "created_at": "2026-07-04T00:00:00+00:00",
        "last_seen_at": "2026-07-05T00:00:00+00:00",
        "evidence_json": [{"source_domain": "reuters", "note": "n"}],
        "meta_json": {"gap_type": gap_type, "why_missing": "wm",
                      "why_it_matters": "wim",
                      "current_system_coverage": "covered surfaces checked: ...",
                      "proposed_coverage": "Operator review: consider a topic.",
                      "source_count": 2, "recurrence_count": 3,
                      "research_domain": "custom", "workspace_id": "trade_ai"},
    }


def test_discovery_gaps_route_shape(monkeypatch):
    import api_v2
    import db_adapter
    rows = [_fake_gap_row(1, "MISSING_THEME"),
            _fake_gap_row(2, "MISSING_SOURCE"),
            _fake_gap_row(3, "MISSING_THEME", status="REJECTED"),
            _fake_gap_row(4, "MISSING_COMPANY", ctype="TOPIC_CANDIDATE")]
    monkeypatch.setattr(db_adapter, "_execute",
                        lambda sql, params=None, fetch=None:
                        rows if fetch == "all" else None)
    st, body = api_v2.handle("/api/v2/hermes/discovery-gaps", method="GET",
                             query={"limit": ["100"]})
    assert st == 200 and body["ok"] is True
    data = body["data"]
    assert data["advisory_only"] is True
    # closed row excluded by default; meta-stamped TOPIC included
    assert data["total"] == 3
    assert set(data["gap_types"]) == {"MISSING_THEME", "MISSING_SOURCE",
                                      "MISSING_COMPANY"}
    gap = data["gap_types"]["MISSING_THEME"]["gaps"][0]
    for key in ("id", "label", "gap_type", "thesis", "evidence_count",
                "domain", "workspace", "safe_action",
                "recommended_next_action", "status", "source_count",
                "recurrence_count"):
        assert key in gap
    assert gap["thesis"] == "wm wim"
    assert gap["evidence_count"] == 1
    assert gap["workspace"] == "trade_ai"
    assert gap["safe_action"] == "OPERATOR_REVIEW_REQUIRED"

    # gap_type filter narrows; include_closed restores the rejected row
    st, body = api_v2.handle("/api/v2/hermes/discovery-gaps", method="GET",
                             query={"gap_type": ["MISSING_SOURCE"]})
    assert st == 200 and set(body["data"]["gap_types"]) == {"MISSING_SOURCE"}
    st, body = api_v2.handle("/api/v2/hermes/discovery-gaps", method="GET",
                             query={"include_closed": ["1"]})
    assert st == 200 and body["data"]["total"] == 4


# ── advisory-only guarantee ──────────────────────────────────────────────────

def test_no_broker_imports_in_white_space_files():
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?(brokers\b|schwab\w*|"
        r"alpaca\w*)", re.MULTILINE)
    targets = [
        ROOT / "scripts" / "lib" / "hermes_discovery" / "white_space.py",
        ROOT / "scripts" / "hermes_white_space_discovery.py",
    ]
    offenders = [p.name for p in targets if forbidden.search(p.read_text())]
    assert not offenders, f"broker imports in advisory-only files: {offenders}"
    # the engine never imports promotion either — gaps are review-only
    src = (ROOT / "scripts" / "lib" / "hermes_discovery" / "white_space.py").read_text()
    assert "promotion" not in re.findall(r"^\s*from \. import (.+)$", src,
                                         re.MULTILINE)[0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
