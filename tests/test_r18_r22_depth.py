"""Anti-theater + historical replay depth tests for R18–R22.

Do not mock the canonical universe loader. Do not echo golden blobs.
Do not treat CURRENT writes as in-scope.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from scripts.lib.cio_forward_program import gated_live_run
from scripts.lib.cio_institutional_learning import reject_lookahead
from scripts.lib.cio_model_learning import snapshot_registries
from scripts.lib.r18_calibration_fabric import load_historical_records, replay_calibration
from scripts.lib.r19_learning_engine import (
    advance_learning_stage,
    build_learning_record,
    registry_fingerprint,
    replay_learning_pipeline,
)
from scripts.lib.r20_universe_propagation import impact_candidates, propagate_from_canonical_root
from scripts.lib.r21_portfolio_cognition import portfolio_cognition
from scripts.lib.r22_cio_loop import run_cycle
from scripts.lib.transferson_universe import collect_live_sources, load_universe

CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
REPO = Path(__file__).resolve().parents[1]


def _have_current() -> bool:
    return (CURRENT / "SOURCE_COMMIT").is_file() and (CURRENT / "data/cio/outcome_observations.jsonl").is_file()


def test_r20_entry_calls_real_canonical_loader() -> None:
    src = inspect.getsource(propagate_from_canonical_root)
    assert "collect_live_sources" in src
    assert "load_universe" in src
    assert "MagicMock" not in src
    prod = Path(__file__).resolve().parents[1] / "scripts/lib/r20_universe_propagation.py"
    text = prod.read_text()
    assert "collect_live_sources" in text


def test_r18_historical_replay_uses_store_ids() -> None:
    assert _have_current()
    hist = load_historical_records(CURRENT)
    assert hist["observation_ids"], "historical observation store is empty"
    replay = replay_calibration(CURRENT, evidence_class="HISTORICAL_REPLAY")
    assert replay["evidence_class"] == "HISTORICAL_REPLAY"
    assert set(replay["source_observation_ids"]) == set(hist["observation_ids"])
    assert set(replay["source_checkpoint_ids"]) == set(hist["checkpoint_ids"])
    assert replay["tiny_samples_are_not_truth"] is True
    # Honest: observations do not join checkpoints in this store.
    assert replay["joined_observation_checkpoint_n"] == hist["joined_n"]
    for row in replay["hit_rate_by_horizon"]:
        if row["n"] < 8:
            assert row["hit_rate"] is None
            assert row["uncertainty"] == "INSUFFICIENT_SAMPLE"


def test_lookahead_rejects_future_outcome() -> None:
    audit = reject_lookahead(
        {"evidence": [{"id": "future", "as_of": "2099-01-01T00:00:00+00:00"}]},
        as_of="2026-01-01T00:00:00+00:00",
    )
    assert audit["allowed"] is False
    assert audit["leaks"]


def test_r19_zero_observations_is_insufficient_not_a_lesson() -> None:
    out = replay_learning_pipeline(
        outcomes=[],
        evidence_class="HISTORICAL_REPLAY",
        statement="should not become a lesson",
        train_cutoff="2026-08-26T00:00:00+00:00",
        repo_root=REPO,
    )
    assert out["status"] == "INSUFFICIENT_EVIDENCE"
    assert out["lesson"] is None
    assert out["supporting_outcome_ids"] == []
    zero = build_learning_record(
        decision={"decision_id": "d0", "recommendation": "HOLD"},
        outcome={"outcome_id": "o0"},
        statement="zero support",
        supporting_outcome_ids=[],
        counterexamples=[],
        searched_counterexamples=True,
        evidence_class="UNIT_TEST",
    )
    assert zero["status"] == "INSUFFICIENT_EVIDENCE"
    assert zero["lesson"] is None


def test_r19_historical_replay_and_registry_hash() -> None:
    hist = load_historical_records(CURRENT)
    outcomes = hist["observations"]
    before = registry_fingerprint(REPO)
    out = replay_learning_pipeline(
        outcomes=outcomes,
        evidence_class="HISTORICAL_REPLAY",
        statement="HOLD_CASH/WAIT observational linkage is not a methodology",
        train_cutoff="2026-08-25T18:00:00+00:00",
        repo_root=REPO,
    )
    after = registry_fingerprint(REPO)
    assert before == after == out["registry_hash_before"] == out["registry_hash_after"]
    assert out["registry_unchanged"] is True
    assert out["auto_policy"] is False
    if out.get("status") == "INSUFFICIENT_EVIDENCE":
        if out.get("reason") == "NO_HOLDOUT_WINDOW":
            assert out.get("stage") == "SHADOW"
            assert out.get("eval_n") == 0
            assert out.get("lesson") is not None
        else:
            assert out["lesson"] is None
            assert len(out["supporting_outcome_ids"]) < 5
    else:
        assert out["lesson"]["supporting_outcome_ids"]
        assert out["hypothesis"]["preregistered"] is True
        assert out["self_authorize_blocked"] is True
        assert out.get("eval_n", 0) > 0


def test_r19_cannot_self_promote_or_mutate_registry() -> None:
    rec = build_learning_record(
        decision={"decision_id": "d1", "recommendation": "HOLD", "security_guid": "sec-1"},
        outcome={"outcome_id": "o1", "security_guid": "sec-1"},
        statement="enough support only for candidate",
        supporting_outcome_ids=[f"o{i}" for i in range(6)],
        counterexamples=["c1"],
        searched_counterexamples=True,
        evidence_class="GOLDEN_SHADOW",
    )
    blocked = advance_learning_stage(rec, "OPERATOR_AUTHORIZED")
    assert blocked["ok"] is False
    snap = snapshot_registries(REPO)
    digest = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in snap.items()}
    assert digest == registry_fingerprint(REPO)


def test_r20_canonical_loader_not_fixture_subset() -> None:
    out = propagate_from_canonical_root(
        CURRENT, "NOC", evidence_class="HISTORICAL_REPLAY", max_n=8,
    )
    assert out["schema"] == "ImpactCandidateSet@v1"
    assert out["auto_research_entire_universe"] is False
    assert out["canonical_universe_count"] and out["canonical_universe_count"] > 200
    assert out["related_n"] >= out["n"]
    assert out["originating_entity"]["symbol"] == "NOC"
    assert out["starting_evidence_artifact"]
    if out["candidates"]:
        c0 = out["candidates"][0]
        assert "paths" in c0 and "score" in c0 and "membership_reasons" in c0
        assert c0.get("not_supply_chain") is True
    if out["truncated"]:
        assert out["excluded_sample"]
        assert out["excluded_sample"][0]["why_excluded"] == "RANK_BELOW_CUTOFF"


def test_r20_does_not_use_ticker_as_security_identity() -> None:
    out = propagate_from_canonical_root(CURRENT, "NOC", evidence_class="HISTORICAL_REPLAY", max_n=5)
    origin_guid = out["originating_entity"]["subject_guid"]
    if origin_guid:
        assert origin_guid != "NOC"
    for c in out.get("candidates") or []:
        if c.get("subject_guid"):
            assert c["subject_guid"] != c["symbol"]


def test_r21_portfolio_from_live_holdings() -> None:
    sources = collect_live_sources(root=CURRENT)
    manifest = load_universe(root=CURRENT, sources=sources)
    held = sources.get("holdings") or []
    out = portfolio_cognition(manifest, held_symbols=held, evidence_class="HISTORICAL_REPLAY")
    assert out["advisory_only"] is True
    assert out["graph_proximity_is_not_an_action"] is True
    kinds = {f["kind"] for f in out.get("findings") or []}
    assert kinds <= {"FACT", "DERIVED_RELATIONSHIP", "HYPOTHESIS"}
    assert all(f.get("investment_recommendation") is None for f in out.get("findings") or [])


def test_r22_end_to_end_trace() -> None:
    trace = run_cycle(
        root=CURRENT,
        change={"symbol": "NOC", "materiality": 0.8, "recommendation": "HOLD"},
        evidence_class="HISTORICAL_REPLAY",
        max_impact=6,
    )
    assert trace["trace_id"]
    assert trace["lineage"] == [
        "change", "identity", "materiality", "prior_cognition",
        "graph_impact", "gap", "free_first_inspect", "advisory_synthesis",
    ]
    ff = next(s for s in trace["steps"] if s["step"] == "free_first_inspect")
    assert ff["wrote"] is False
    assert ff["paid_dispatch"] is False
    assert trace["financial_action"] is False
    assert trace["synthesis"]["investment_recommendation"] is None


def test_live_activation_still_off() -> None:
    assert gated_live_run("R18", evidence_class="LIVE")["ok"] is False
    assert gated_live_run("R19", evidence_class="LIVE")["ok"] is False
    assert gated_live_run("R20", evidence_class="LIVE")["ok"] is False
    assert gated_live_run("R22", evidence_class="LIVE")["ok"] is False
