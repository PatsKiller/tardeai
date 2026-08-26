"""R17 natural feedback closure — unit/integration. No fabricated elapsed time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib.cio_institutional_learning import identity_safe_subject, persist_checkpoint, reject_lookahead
from scripts.lib.intelligence_coverage_v2 import coverage_matrix_v2
from scripts.lib.r17_checkpoint_binding import (
    bind_material_decision,
    classify_checkpoint,
    learning_cockpit_from_store,
    process_due_store,
    semantic_checkpoint_key,
)
from scripts.lib.r17_gui_pane import ticker_pane
from scripts.lib.r17_producer_links import (
    bounded_graph_wake,
    catalyst_trace,
    envelope_extras,
    event_research_path,
    market_context_bound,
)
from scripts.lib.transferson_universe import build_universe

NOW = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)


def _manifest():
    return build_universe(sources={
        "holdings": ["NOC"],
        "symbol_profiles": [
            {"symbol": "NOC", "sector": "Industrials", "industry": "Aerospace", "company": "Northrop",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "RTX", "sector": "Industrials", "industry": "Aerospace", "company": "RTX",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "COLD", "sector": "Industrials", "industry": "Aerospace", "company": "ColdCo",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
        ],
        "trs": [{"symbol": "NOC", "security_guid": "sec-noc"}],
        "screener_active": [],
        "discovery_validated": [],
    })


def test_coverage_v2_uses_na_not_false() -> None:
    m = coverage_matrix_v2()
    assert m["schema"] == "IntelligenceCoverageMatrix@v2"
    cash = next(r for r in m["rows"] if r["producer_id"] == "cash")
    assert cash["dimensions"]["IDENTITY"] == "NOT_APPLICABLE"
    assert "IDENTITY" not in cash["missing"]
    holdings = next(r for r in m["rows"] if r["producer_id"] == "holdings")
    assert holdings["dimensions"]["OUTCOME_LINKAGE"] == "SUPPORTED"
    sector = next(r for r in m["rows"] if r["producer_id"] == "sector_rotation")
    assert sector["dimensions"]["RESEARCH_TRIGGER"] == "SUPPORTED"
    assert m["not_optimized_for_full"] is True
    # Unexplained missing must be listed, not hidden as PARTIAL.
    for row in m["rows"]:
        for dim, state in row["dimensions"].items():
            assert state in {"SUPPORTED", "MISSING", "NOT_APPLICABLE"}


def test_semantic_dedupe_ignores_decision_id_churn(tmp_path) -> None:
    d1 = {
        "decision_id": "dec_aaa",
        "symbol": "NOC",
        "action": "HOLD",
        "security_guid": "sec-noc",
        "decision_evidence_digest": "gen-1",
        "thesis_version": "t1",
    }
    d2 = dict(d1, decision_id="dec_bbb")  # replay churn
    a = bind_material_decision(tmp_path, d1, source_sha="abc", now=NOW)
    b = bind_material_decision(tmp_path, d2, source_sha="abc", now=NOW)
    assert a["wrote_n"] >= 1
    assert b["wrote_n"] == 0
    assert b["skipped_n"] >= 1
    assert semantic_checkpoint_key(d1, "1_session") == semantic_checkpoint_key(d2, "1_session")


def test_material_generation_change_creates_new_checkpoint(tmp_path) -> None:
    d1 = {"decision_id": "dec_1", "symbol": "NOC", "action": "HOLD", "security_guid": "sec-noc", "decision_evidence_digest": "g1"}
    d2 = dict(d1, decision_id="dec_2", decision_evidence_digest="g2", action="TRIM")
    a = bind_material_decision(tmp_path, d1, source_sha="abc", now=NOW, horizons=("1_session",))
    b = bind_material_decision(tmp_path, d2, source_sha="abc", now=NOW, horizons=("1_session",))
    assert a["wrote_n"] == 1
    assert b["wrote_n"] == 1


def test_due_processor_not_due_and_pending_data(tmp_path) -> None:
    d = {"decision_id": "dec_due", "symbol": "NOC", "action": "HOLD", "security_guid": "sec-noc", "decision_evidence_digest": "g"}
    bind_material_decision(tmp_path, d, source_sha="abc", now=NOW, horizons=("1_session",))
    idle = process_due_store(tmp_path, source_available=True, persist=False, now=NOW)
    assert idle["observed"] == 0
    assert idle["no_action"] >= 1
    later = NOW + timedelta(days=2)
    pending = process_due_store(tmp_path, source_available=False, persist=False, now=later)
    assert pending["pending_data"] >= 1
    assert pending["invented"] is False
    obs = process_due_store(tmp_path, source_available=True, persist=True, now=later)
    assert obs["observed"] >= 1
    cockpit = learning_cockpit_from_store(tmp_path, now=later)
    assert cockpit["in_memory_only"] is False
    assert cockpit["observations_n"] >= 1
    assert cockpit["gui_cannot_self_promote"] is True


def test_never_mint_and_lookahead() -> None:
    assert identity_safe_subject({"symbol": "NOC"}) is None
    audit = reject_lookahead(
        {"evidence": [{"id": "future", "as_of": "2099-01-01T00:00:00+00:00"}]},
        as_of="2026-01-01T00:00:00+00:00",
    )
    assert audit["allowed"] is False


def test_sector_wake_is_bounded() -> None:
    m = _manifest()
    out = bounded_graph_wake(m, origin_symbol="NOC", kind="industry", material=True)
    wake_syms = {w["symbol"] for w in out["wake"]}
    assert "COLD" not in wake_syms or any(s["reason"] == "membership_without_exposure" for s in out["skipped_sample"])
    assert out["inferred_from_shared_industry_text"] is False
    cold = bounded_graph_wake(m, origin_symbol="NOC", kind="industry", material=False)
    assert cold["wake"] == []


def test_catalyst_trace_and_market_context() -> None:
    tr = catalyst_trace(
        source="earnings_calendar", catalyst_guid="cat-e",
        security={"symbol": "NOC", "security_guid": "sec-noc"},
        cognition_ref="trs-1", research_ref="hermes-1",
        decision_id="dec_1", outcome_id=None,
    )
    assert tr["gui_visible"] is True
    assert tr["outcome_linked"] is True
    mc = market_context_bound(regime={"vol": "elevated"}, held=["NOC"], thesis_symbols=["RTX"], material=True)
    assert mc["wake_entire_universe"] is False
    assert "NOC" in mc["eligible_symbols"]


def test_event_research_does_not_fabricate() -> None:
    assert event_research_path("NO_CHANGE")["fired"] is False
    armed = event_research_path("MATERIAL_CHANGE")
    assert armed["paid_dispatch"] is False
    assert armed["searx_residual_only"] is True


def test_gui_pane_is_projection() -> None:
    m = _manifest()
    pane = ticker_pane("/tmp", m, "NOC")
    assert pane["gui_is_projection"] is True
    assert pane["ingestion_forbidden"] is True
    assert pane["identity"]["ticker_guid_is_not_security"] or pane["ticker_guid_is_not_security"]


def test_envelope_extras_preserve_specialist_disagreement() -> None:
    extra = envelope_extras()
    assert extra["SPECIALISTS"]["maria"]["disagreement_preserved"] is True
    assert extra["NEWS"]["not_truth"] is True
    assert extra["STOP_ADVISORY"]["execution"] is False


def test_operator_feedback_still_zero_influence() -> None:
    from scripts.lib.preference_candidate import SCHEMA
    assert SCHEMA == "PreferenceCandidate@v1"
    extra = envelope_extras()
    assert extra["memory_behavior_influence"] == 0


def test_restart_survives_checkpoint_file(tmp_path) -> None:
    d = {"decision_id": "dec_rs", "symbol": "NOC", "action": "HOLD", "security_guid": "sec-noc", "decision_evidence_digest": "g"}
    bind_material_decision(tmp_path, d, source_sha="abc", now=NOW, horizons=("1_session",))
    n1 = learning_cockpit_from_store(tmp_path, now=NOW)["checkpoints_n"]
    n2 = learning_cockpit_from_store(tmp_path, now=NOW)["checkpoints_n"]
    assert n1 == n2 >= 1


def test_classify_due() -> None:
    future = {"due_at": (NOW + timedelta(days=3)).isoformat(), "status": "SCHEDULED"}
    past = {"due_at": (NOW - timedelta(days=1)).isoformat(), "status": "SCHEDULED"}
    assert classify_checkpoint(future, now=NOW) == "PENDING"
    assert classify_checkpoint(past, now=NOW) == "DUE"
