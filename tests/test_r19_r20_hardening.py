"""R19 spine/registry and R20 provenance — no production activation."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.r19_evidence_spine import CHAIN_OBJECTS, project_joins
from scripts.lib.r19_experiment_registry import evaluate_registration, register_hypothesis
from scripts.lib.r19_learning_engine import attempt_historical_review_ready
from scripts.lib.r20_universe_propagation import (
    historical_propagation_traces,
    impact_candidates,
    propagate_from_canonical_root,
    sourced_economic_edge,
    universe_provenance_coverage,
)
from scripts.lib.transferson_universe import build_universe

CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
REPO = Path(__file__).resolve().parents[1]


def test_spine_does_not_fuzzy_join_observations_to_checkpoints() -> None:
    spine = project_joins(CURRENT)
    assert spine["originals_rewritten"] is False
    assert spine["candidate_joins_forbidden_for_scored_learning"] is True
    assert spine["counts"]["UNRESOLVED_WITH_REASON"] >= 1
    assert spine["counts"]["UNRESOLVED"] == spine["counts"]["UNRESOLVED_WITH_REASON"]
    assert "observation_decision_id_not_in_checkpoints" in spine["unresolved_reasons"]
    assert spine["counts"]["CANDIDATE_JOIN"] >= 1
    assert spine["chain_objects"] == list(CHAIN_OBJECTS)
    assert spine["counts"]["scored_learning_eligible"] == 0
    for row in spine["rows"][:5]:
        for name in CHAIN_OBJECTS:
            assert name in row["objects"]
            assert row["objects"][name]["status"] in {"PRESENT", "UNRESOLVED_WITH_REASON"}


def test_historical_store_does_not_earn_review_ready() -> None:
    out = attempt_historical_review_ready(
        CURRENT, source_sha="2d988c766db3e591dbaa9951f1f441513cf1193a",
        evidence_class="HISTORICAL_REPLAY",
    )
    assert out["status"] == "NO_HYPOTHESIS_EARNED_REVIEW_READY"
    assert out.get("financial_action") is False
    assert out.get("candidate_joins_used_for_scored_learning") is False
    assert out.get("eligible_n") == 0
    hyp = CURRENT / "data/cio/hypothesis_registrations.jsonl"
    assert not hyp.exists()


def test_registry_rejects_late_registration_and_changed_criteria(tmp_path) -> None:
    spec = {
        "statement": "x",
        "cohort_definition": {"k": 1},
        "metric": "objective_score",
        "expected_direction": "improve",
        "minimum_sample_size": 8,
        "training_cutoff": "2026-01-01T00:00:00+00:00",
        "holdout_start": "2026-02-01T00:00:00+00:00",
        "holdout_end": "2026-03-01T00:00:00+00:00",
        "acceptance_criteria": {"min_delta": 0.05},
    }
    late = register_hypothesis(
        tmp_path, spec, evidence_class="UNIT_TEST", source_sha="abc",
        registered_at="2026-04-01T00:00:00+00:00", mode="CONTEMPORANEOUS",
    )
    assert late["ok"] is False
    assert late["reason"] == "REGISTRATION_AFTER_HOLDOUT_VISIBLE"
    live_recon = register_hypothesis(
        tmp_path, spec, evidence_class="LIVE", source_sha="abc",
        mode="RECONSTRUCTED_AS_OF",
    )
    assert live_recon["ok"] is False
    dry = register_hypothesis(
        CURRENT, spec, evidence_class="UNIT_TEST", source_sha="abc",
        registered_at="2026-01-01T00:00:00+00:00", mode="CONTEMPORANEOUS",
        persist=False,
    )
    assert dry["ok"] is True
    assert dry["registration"]["persisted"] is False
    assert not (CURRENT / "data/cio/hypothesis_registrations.jsonl").exists()
    ok = register_hypothesis(
        tmp_path, spec, evidence_class="UNIT_TEST", source_sha="abc",
        registered_at="2026-01-01T00:00:00+00:00", mode="CONTEMPORANEOUS",
    )
    assert ok["ok"] is True
    changed = dict(spec)
    changed["metric"] = "other"
    ev = evaluate_registration(
        ok["registration"],
        train_rows=[{"objective_score": 0.5}] * 8,
        holdout_rows=[{"objective_score": 0.9}] * 8,
        spec=changed,
    )
    assert ev["status"] == "CRITERIA_CHANGED_AFTER_REGISTRATION"


def test_registry_can_earn_review_ready_when_holdout_is_real(tmp_path) -> None:
    spec = {
        "statement": "holdout mean exceeds train by threshold",
        "source_lesson_ids": ["les_1"],
        "cohort_definition": {"policy": "FAST"},
        "metric": "objective_score",
        "expected_direction": "improve",
        "minimum_sample_size": 8,
        "training_cutoff": "2026-01-15T00:00:00+00:00",
        "holdout_start": "2026-01-15T00:00:00+00:00",
        "holdout_end": "2026-02-01T00:00:00+00:00",
        "acceptance_criteria": {"min_delta": 0.05},
    }
    reg = register_hypothesis(
        tmp_path, spec, evidence_class="UNIT_TEST", source_sha="unit",
        registered_at="2026-01-15T00:00:00+00:00", mode="CONTEMPORANEOUS",
    )
    train = [{"objective_score": 0.50, "decision_id": f"d{i}"} for i in range(10)]
    hold = [{"objective_score": 0.80, "decision_id": f"h{i}"} for i in range(10)]
    ev = evaluate_registration(reg["registration"], train_rows=train, holdout_rows=hold, spec=spec)
    assert ev["status"] == "REVIEW_READY"
    assert ev["holdout_n"] == 10
    assert ev["delta"] >= 0.05
    assert set(ev["underlying_decision_ids"]) == {f"d{i}" for i in range(10)} | {f"h{i}" for i in range(10)}
    assert ev["cohort_definition"]["policy"] == "FAST"
    assert ev["provenance"]["source_sha"] == "unit"
    miss = evaluate_registration(
        reg["registration"],
        train_rows=[{"objective_score": 0.8, "decision_id": "t"}] * 10,
        holdout_rows=[{"objective_score": 0.5, "decision_id": "h"}] * 10,
        spec=spec,
    )
    assert miss["status"] == "NO_HYPOTHESIS_EARNED_REVIEW_READY"


def test_registry_rejects_row_timestamp_leakage(tmp_path) -> None:
    spec = {
        "statement": "x",
        "cohort_definition": {},
        "metric": "objective_score",
        "expected_direction": "improve",
        "minimum_sample_size": 8,
        "training_cutoff": "2026-01-15T00:00:00+00:00",
        "holdout_start": "2026-01-15T00:00:00+00:00",
        "holdout_end": "2026-02-01T00:00:00+00:00",
        "acceptance_criteria": {"min_delta": 0.01},
    }
    reg = register_hypothesis(
        tmp_path, spec, evidence_class="UNIT_TEST", source_sha="unit",
        registered_at="2026-01-15T00:00:00+00:00",
    )
    leaked = evaluate_registration(
        reg["registration"],
        train_rows=[{"objective_score": 0.5, "decision_timestamp": "2026-01-20T00:00:00+00:00"}] * 8,
        holdout_rows=[{"objective_score": 0.9, "decision_timestamp": "2026-01-21T00:00:00+00:00"}] * 8,
        spec=spec,
    )
    assert leaked["status"] == "TRAIN_HOLDOUT_OVERLAP"


def _sources():
    return {
        "holdings": ["NOC", "RTX"],
        "symbol_profiles": [
            {"symbol": "NOC", "sector": "Industrials", "industry": "Aerospace", "company": "Northrop",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "RTX", "sector": "Industrials", "industry": "Aerospace", "company": "RTX Corp",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "LMT", "sector": "Industrials", "industry": "Aerospace", "company": "Lockheed",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "BA", "sector": "Industrials", "industry": "Aerospace", "company": "Boeing"},
            {"symbol": "AAPL", "sector": "Technology", "industry": "Consumer Electronics", "company": "Apple",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "SCHD", "sector": "Financial", "industry": "ETF", "company": "Schwab",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "SPCX", "sector": "Financial", "industry": "ETF", "company": "SPCX",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
        ],
        "graph_profiles": [
            {"symbol": "NOC", "catalyst_guids": ["cat-e"], "security_guid": "sec-noc",
             "relationships": [
                 {"relationship_guid": "rel-cat", "source_guid": "sec-noc", "target_guid": "cat-e",
                  "relationship": "MACRO", "target_kind": "catalyst"},
             ]},
            {"symbol": "RTX", "catalyst_guids": ["cat-e"], "security_guid": "sec-rtx"},
        ],
        "trs": [
            {"symbol": "NOC", "security_guid": "sec-noc"},
            {"symbol": "RTX", "security_guid": "sec-rtx"},
        ],
        "screener_active": [],
        "discovery_validated": [],
    }


def _manifest():
    return build_universe(sources=_sources())


def test_r20_auditable_propagation_excludes_incomplete_edges() -> None:
    out = propagate_from_canonical_root(CURRENT, "NOC", evidence_class="HISTORICAL_REPLAY", max_n=8)
    assert out["silent_incomplete_edges_used_for_score"] is False
    cov = out["provenance_coverage"]
    assert cov["securities_in_universe"] and cov["securities_in_universe"] > 200
    used = (cov["fully_provenance_complete_edges"] or 0) + (cov["candidate_incomplete_edges"] or 0)
    if used:
        assert cov["provenance_complete_ratio"] == round(
            cov["fully_provenance_complete_edges"] / used, 4
        )
        assert cov["edges_used_for_propagation"] == cov["fully_provenance_complete_edges"]
    for c in out.get("candidates") or []:
        assert c.get("status") == "PROVENANCE_COMPLETE"
        assert c.get("edges")
        assert all(e.get("provenance_complete") for e in c["edges"])
    for inc in out.get("incomplete_candidates") or []:
        assert inc.get("status") == "PROVENANCE_INCOMPLETE"
    uni = out["universe_provenance_coverage"]
    assert uni["edges_total"] is not None
    assert uni["silent_incomplete_edges_used_for_score"] is False


def test_r20_traces_cover_multiple_paths() -> None:
    out = propagate_from_canonical_root(CURRENT, "NOC", evidence_class="HISTORICAL_REPLAY", max_n=12)
    paths = {p for c in out.get("candidates") or [] for p in c.get("paths") or []}
    assert "industry" in paths or "sector" in paths
    assert out["starting_evidence_artifact"]["symbol"] == "NOC"
    assert out["originating_entity"]["membership_reasons"]
    assert out["origin_security_trace"]["path"] == "security"
    assert out["origin_security_trace"]["target_security"]["symbol"] == "NOC"
    if out.get("truncated"):
        assert out["excluded_sample"][0]["why_excluded"] == "RANK_BELOW_CUTOFF"


def test_r20_fixture_marks_unprovenanced_classification_incomplete() -> None:
    src = _sources()
    m = build_universe(sources=src)
    out = impact_candidates(m, "NOC", evidence_class="UNIT_TEST", max_n=10, graph_profiles=src["graph_profiles"])
    symbols = {c["symbol"] for c in out["candidates"]}
    assert "RTX" in symbols
    assert "BA" not in symbols
    incomplete = {c["symbol"] for c in out["incomplete_candidates"]}
    assert "BA" in incomplete
    for c in out["candidates"]:
        assert c["status"] == "PROVENANCE_COMPLETE"
        for e in c["edges"]:
            for field in (
                "relationship_guid", "source_entity_guid", "target_entity_guid",
                "evidence_artifact_guid", "producer", "producer_version", "observed_at",
            ):
                assert e.get(field)


def test_r20_shared_industry_is_not_supply_chain_and_needs_evidence_for_economic() -> None:
    origin = {"symbol": "NOC", "security_guid": "sec-noc"}
    bare = sourced_economic_edge(origin, {"kind": "supplier", "symbol": "HWM"})
    assert bare is None
    edged = sourced_economic_edge(origin, {
        "kind": "supplier",
        "symbol": "HWM",
        "security_guid": "sec-hwm",
        "evidence": True,
        "evidence_artifact_guid": "art-1",
        "source_id": "filing-1",
        "source_type": "sec_filing",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "producer": "manual_evidence",
        "producer_version": "v1",
        "confidence": 0.8,
        "status": "CANDIDATE",
    })
    assert edged is not None
    assert edged["provenance_complete"] is True
    assert edged["not_from_shared_sector_alone"] is True


def test_r20_mention_edge_is_auditable() -> None:
    m = _manifest()
    mention = {
        "relationship_guid": "rel-m",
        "source_entity_guid": "tg-schd",
        "target_entity_guid": "tg-spcx",
        "source_symbol": "SCHD",
        "target_symbol": "SPCX",
        "relationship_type": "MENTION",
        "relationship_class": "mention",
        "source_type": "cio_theses",
        "source_id": "ev-1",
        "source_url": None,
        "evidence_artifact_guid": "ev-1",
        "derivation_method": "thesis.linked_symbols",
        "observed_at": "2026-08-11T20:07:36+00:00",
        "recorded_at": "2026-08-11T20:07:36+00:00",
        "valid_from": "2026-08-11T20:07:36+00:00",
        "valid_to": None,
        "confidence": 0.6,
        "status": "CANDIDATE",
        "producer": "operator",
        "producer_version": "desk@v3",
        "provenance_complete": True,
    }
    out = impact_candidates(m, "SCHD", evidence_class="UNIT_TEST", max_n=5, mention_edges=[mention])
    assert any(c["symbol"] == "SPCX" and "mention" in c["paths"] for c in out["candidates"])
    hit = next(c for c in out["candidates"] if c["symbol"] == "SPCX")
    assert hit["traces"][0]["source_artifact"]["symbol"] == "SCHD"
    assert hit["traces"][0]["target_security"]["symbol"] == "SPCX"


def test_r20_catalyst_without_artifact_is_incomplete() -> None:
    src = _sources()
    m = build_universe(sources=src)
    out = impact_candidates(
        m, "NOC", evidence_class="UNIT_TEST", max_n=10, graph_profiles=src["graph_profiles"],
    )
    for c in out["candidates"]:
        assert "catalyst" not in c["paths"]
    inc = [c for c in out["incomplete_candidates"] if "catalyst" in c["paths"]]
    assert inc
    assert all(c["status"] == "PROVENANCE_INCOMPLETE" for c in inc)


def test_r20_universe_coverage_ratio_matches_counts() -> None:
    m = _manifest()
    cov = universe_provenance_coverage(m, graph_profiles=m.get("graph_profiles") or [])
    used = cov["fully_provenance_complete_edges"] + cov["candidate_incomplete_edges"]
    assert cov["edges_total"] == used
    if used:
        assert cov["provenance_complete_ratio"] == round(cov["fully_provenance_complete_edges"] / used, 4)
    assert cov["edges_used_for_propagation"] == cov["fully_provenance_complete_edges"]


def test_r20_historical_traces_do_not_bulk_research() -> None:
    out = historical_propagation_traces(CURRENT)
    assert out["auto_research_entire_universe"] is False
    assert out["financial_action"] is False
    assert "security" in out["traces"]
    assert "industry" in out["traces"]
    assert "sector" in out["traces"]
    assert "catalyst" in out["traces"]
    assert "mention" in out["traces"]
    assert out["traces"]["security"]["sample"]["target_security"]["symbol"] == "NOC"
    cov = out["universe_provenance_coverage"]
    assert cov["securities_in_universe"] and cov["securities_in_universe"] > 200
