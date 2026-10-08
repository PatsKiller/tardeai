"""Operator evidence: receipts, office-truth boundary, settled learning, coverage census.

Regression for the 2026-10-02 review of aabecdb4b:
  * any non-empty advisory_use string ("NOT_USED", "no", "0") counted as USED;
  * RETRIEVED was assigned from the source file name;
  * cognition availability was hardcoded AVAILABLE;
  * learning PROVEN only meant an outcome id string was present, success_rate
    could exceed 1, calibration was passed through from the first row;
  * a missing producer store showed PARTIAL because shared consumers had rows;
  * no KNOWN_DARK classification existed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.cio_operator_evidence as evidence  # noqa: E402

NOW = "2026-10-02T12:00:00Z"


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture()
def cio(tmp_path, monkeypatch):
    root = tmp_path / "data" / "cio"
    root.mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.delenv("TRADEAI_RUNTIME_DIR", raising=False)
    return root


def _research(root: Path) -> dict:
    return evidence.build_operator_evidence(now=NOW, include_coverage=False)["blocks"]["research"]


# ── Phase 2: research ──────────────────────────────────────────────────────

def test_retrieved_is_not_used(cio):
    _write(cio / "hermes_research_results.jsonl", [
        {"result_id": "rr-1", "symbol": "AAA", "retrieved_at": "2026-10-01T10:00:00Z"},
    ])
    research = _research(cio)
    artifact = research["artifacts"][0]
    assert artifact["status"] == "RETRIEVED"
    assert artifact["status_basis"] == "retrieved_at"
    assert research["counts"]["used_in_judgment"] == 0
    assert research["used_in_judgment"] == []


@pytest.mark.parametrize("negative", ["NOT_USED", "no", "0", "rejected", "false", "unknown", "pending"])
def test_negative_use_strings_are_not_used(cio, negative):
    _write(cio / "hermes_research_results.jsonl", [
        {"result_id": "rr-neg", "advisory_use": negative, "consumed_by": negative, "used_in_judgment": negative},
    ])
    artifact = _research(cio)["artifacts"][0]
    assert artifact["status"] == "RETRIEVED"  # result_id is a retrieval fact, not a use receipt


def test_use_allowlist_and_consuming_decision_list(cio):
    _write(cio / "hermes_research_results.jsonl", [
        {"result_id": "rr-flag", "advisory_use": "USED_IN_JUDGMENT"},
        {"result_id": "rr-list", "consumed_by_decision_ids": ["dec-9"]},
        {"result_id": "rr-badlist", "consumed_by": ["NOT_USED"]},
        {"result_id": "rr-dict", "advisory_use": {"decision_id": "dec-x"}},
    ])
    by_id = {a["artifact_id"]: a for a in _research(cio)["artifacts"]}
    assert by_id["rr-flag"]["status"] == "USED_IN_JUDGMENT"
    assert by_id["rr-list"]["status"] == "USED_IN_JUDGMENT"
    assert "dec-9" in by_id["rr-list"]["decision_ids"]
    assert by_id["rr-badlist"]["status"] == "RETRIEVED"
    assert by_id["rr-dict"]["status"] == "RETRIEVED"


def test_lineage_advisory_used_receipt_proves_use_only_for_its_result(cio):
    _write(cio / "hermes_research_results.jsonl", [
        {"result_id": "rr-used", "completed_ts": "2026-10-01T10:00:00Z"},
        {"result_id": "rr-other", "completed_ts": "2026-10-01T10:00:00Z"},
    ])
    _write(cio / "intelligence_lineages.jsonl", [
        {"lineage_id": "lin-1", "status": "ADVISORY_USED", "research_result_ids": ["rr-used"], "at": "2026-10-01T11:00:00Z"},
        {"lineage_id": "lin-2", "status": "RESEARCH_COMPLETED", "research_result_ids": ["rr-other"], "at": "2026-10-01T11:00:00Z"},
        {"lineage_id": "lin-3", "status": "ADVISORY_USED", "research_result_ids": ["rr-other", "rr-x"], "at": "2026-10-01T11:00:00Z"},
    ])
    by_id = {a["artifact_id"]: a for a in _research(cio)["artifacts"]}
    assert by_id["rr-used"]["status"] == "USED_IN_JUDGMENT"
    assert by_id["rr-used"]["status_basis"] == "intelligence_lineages:ADVISORY_USED"
    assert by_id["rr-used"]["use_receipt_ref"]["lineage_id"] == "lin-1"
    assert by_id["rr-other"]["status"] == "RETRIEVED"
    assert by_id["rr-used"]["retrieved_at"] == "2026-10-01T10:00:00Z"


def test_missing_receipt_is_not_rejected_and_no_retrieval_fact_is_unknown(cio):
    _write(cio / "security_research_spine.jsonl", [{
        "symbol": "AAA", "as_of": "2026-10-01T10:00:00Z",
        "contributions": [{"artifact_id": "thesis-v1", "kind": "thesis_publish", "silo": "cio", "ts": "2026-10-01T10:00:00Z"}],
    }])
    research = _research(cio)
    artifact = research["artifacts"][0]
    assert artifact["status"] == "UNKNOWN"
    assert artifact["reason_used_or_rejected"] is None
    assert research["counts"] == {"retrieved": 0, "used_in_judgment": 0, "rejected": 0, "unknown": 1}
    # Spine envelope clocks are not the contribution's retrieval clock.
    assert artifact["retrieved_at"] is None


def test_rejected_carries_reason_and_status_without_reason_is_not_rejected(cio):
    _write(cio / "web_evidence_provenance.jsonl", [
        {"artifact_id": "w-rej", "retrieved_at": "2026-10-01T10:00:00Z", "rejection_reason": "stale filing superseded by 8-K/A"},
        {"artifact_id": "w-bare", "retrieved_at": "2026-10-01T10:00:00Z", "status": "REJECTED"},
    ])
    by_id = {a["artifact_id"]: a for a in _research(cio)["artifacts"]}
    assert by_id["w-rej"]["status"] == "REJECTED"
    assert by_id["w-rej"]["reason_used_or_rejected"] == "stale filing superseded by 8-K/A"
    assert by_id["w-bare"]["status"] == "RETRIEVED"


def test_artifact_exposes_full_field_set_with_nulls_not_inventions(cio):
    _write(cio / "hermes_research_results.jsonl", [{"result_id": "rr-min"}])
    artifact = _research(cio)["artifacts"][0]
    for field in (
        "artifact_id", "source_type", "publisher", "source_url", "source_ref", "publication_date",
        "retrieved_at", "source_as_of", "symbol", "affected_entities", "research_run_id", "agent_model",
        "relevance", "support_or_challenge", "status", "reason_used_or_rejected", "decision_id",
        "decision_ids", "trace_id", "evidence_class",
    ):
        assert field in artifact, field
    for field in ("source_type", "publisher", "source_url", "publication_date", "source_as_of",
                  "research_run_id", "agent_model", "relevance", "support_or_challenge", "trace_id", "evidence_class"):
        assert artifact[field] is None, field


# ── Phase 3: cognition ─────────────────────────────────────────────────────

def _cognition(root: Path) -> dict:
    return evidence.build_operator_evidence(now=NOW, include_coverage=False)["blocks"]["institutional_cognition"]


def test_office_truth_is_not_replaceable_by_memory(cio):
    _write(cio / "memory_contexts.jsonl", [{
        "context_id": "ctx-price", "price": 999.0, "holdings": {"AAA": 10}, "cash": 1,
        "summary": "remembered price", "created_at": "2026-10-01T10:00:00Z",
    }])
    # Metadata clocks may contain the digits of a withheld price.
    import os
    os.utime(cio / "memory_contexts.jsonl", ns=(1799999999999999999, 1799999999999999999))
    block = _cognition(cio)
    assert block["office_truth"]["sourced_from_memory"] is False
    assert block["office_truth"]["replaceable_by_cognition"] is False
    assert set(block["office_truth"]["categories"]) == {"price", "holdings", "cash", "orders", "broker_state", "risk_limits"}
    item = block["items"][0]
    assert item["office_truth_fields_withheld"] == ["cash", "holdings", "price"]
    assert "price" not in item and "holdings" not in item and "cash" not in item
    assert item["authority"] == "NON_AUTHORITATIVE_CONTEXT"
    def leaves(value):
        if isinstance(value, dict):
            return [leaf for nested in value.values() for leaf in leaves(nested)]
        if isinstance(value, list):
            return [leaf for nested in value for leaf in leaves(nested)]
        return [value]

    # Check values structurally, including accidental nesting, rather than digit
    # substrings in valid source-ref/mtime metadata. A leaked numeric price still fails.
    assert 999.0 not in leaves(block)
    assert "999.0" not in leaves(block)


def test_prior_operator_reject_and_defer_are_retrievable_cognition(cio):
    _write(cio / "operator_ticker_feedback.jsonl", [
        {"feedback_id": "otf-1", "intent": "DEFER", "free_text": "valuation elevated", "symbol": "UBER", "ts": "2026-09-01T10:00:00Z"},
        {"feedback_id": "otf-2", "intent": "ACK", "symbol": "UBER", "ts": "2026-09-01T10:00:00Z"},
    ])
    _write(cio / "decision_dispositions.jsonl", [
        {"decision_id": "dec-s", "disposition": "reject", "note": "too concentrated", "symbol": "SCHD", "occurred_at": "2026-09-02T10:00:00Z"},
    ])
    _write(cio / "cio_defer_lineage.jsonl", [
        {"lineage_id": "lin-q", "decision_id": "dec-q", "reason": "e2e", "deferred_at": "2026-08-15T14:25:00Z"},
        {"lineage_id": "lin-q", "decision_id": "dec-q", "reason": "e2e", "deferred_at": "2026-08-15T14:25:00Z", "quarantined": True, "classification": "SYNTHETIC_E2E"},
    ])
    block = _cognition(cio)
    prior = {i["id"]: i for i in block["prior_operator_decisions"]}
    assert set(prior) == {"otf-1", "dec-s"}
    assert prior["otf-1"]["operator_decision"] == "DEFER" and prior["otf-1"]["advice"] == "valuation elevated"
    assert prior["dec-s"]["operator_decision"] == "REJECT" and prior["dec-s"]["advice"] == "too concentrated"
    assert all(i["kind"] == "prior_operator_decision" and i["availability"] == "AVAILABLE" for i in prior.values())
    assert all(i["influence"] == "NOT_PROVEN" for i in prior.values())


def test_cognition_availability_requires_parseable_non_future_clock(cio):
    _write(cio / "memory_contexts.jsonl", [
        {"context_id": "ctx-ok", "created_at": "2026-10-01T10:00:00Z"},
        {"context_id": "ctx-none"},
        {"context_id": "ctx-future", "created_at": "2027-01-01T00:00:00Z"},
        {"context_id": "ctx-bad", "created_at": "yesterday"},
    ])
    by_id = {i["id"]: i for i in _cognition(cio)["items"]}
    assert by_id["ctx-ok"]["availability"] == "AVAILABLE"
    for cid in ("ctx-none", "ctx-future", "ctx-bad"):
        assert by_id[cid]["availability"] == "UNKNOWN", cid
        assert by_id[cid]["source_as_of"] is None


def test_contradictory_stays_visible_and_influence_needs_receipt(cio):
    _write(cio / "memory_contexts.jsonl", [
        {"context_id": "ctx-contested", "influence": {"consulted": True, "changed_decision": False, "flags": ["CONTESTED"]}, "created_at": "2026-10-01T10:00:00Z"},
        {"context_id": "ctx-changed", "influence": {"consulted": True, "changed_decision": True}, "created_at": "2026-10-01T10:00:00Z"},
    ])
    block = _cognition(cio)
    by_id = {i["id"]: i for i in block["items"]}
    assert by_id["ctx-contested"]["state"] == "RETRIEVED"
    assert by_id["ctx-contested"]["contradictory"] is True
    assert by_id["ctx-contested"]["influence"] == "NOT_PROVEN"
    assert [i["id"] for i in block["contradictory_items"]] == ["ctx-contested"]
    assert by_id["ctx-changed"]["changed_question_or_view"] is True
    assert by_id["ctx-changed"]["influence"] == "PROVEN"
    assert block["counts"]["contradictory"] == 1 and block["counts"]["changed"] == 1


# ── Phase 4: learning ──────────────────────────────────────────────────────

def _learning(root: Path) -> dict:
    return evidence.build_operator_evidence(now=NOW, include_coverage=False)["blocks"]["learning"]


def test_proven_requires_a_settled_outcome_row(cio):
    _write(cio / "advisory_outcomes_v1.jsonl", [
        {"outcome_id": "out-settled", "decision_id": "dec-1", "status": "SETTLED", "result": "SUCCESS"},
        {"outcome_id": "out-pending", "decision_id": "dec-2", "status": "PENDING"},
    ])
    _write(cio / "lesson_candidates.jsonl", [
        {"lesson_id": "l-settled", "supporting_outcome_ids": ["out-settled"], "promotion_stage": "REVIEW_READY"},
        {"lesson_id": "l-pending", "supporting_outcome_ids": ["out-pending"], "promotion_stage": "REVIEW_READY"},
        {"lesson_id": "l-ghost", "supporting_outcome_ids": ["out-does-not-exist"], "promotion_stage": "REVIEW_READY"},
    ])
    learning = _learning(cio)
    by_id = {row["lesson_id"]: row for row in learning["lessons"]}
    assert by_id["l-settled"]["evidence_state"] == "PROVEN"
    assert by_id["l-pending"]["evidence_state"] == "PENDING_OUTCOME"
    assert by_id["l-ghost"]["evidence_state"] == "INSUFFICIENT_EVIDENCE"
    assert by_id["l-ghost"]["unresolved_evidence_ids"] == ["out-does-not-exist"]
    assert [row["lesson_id"] for row in learning["review_ready"]] == ["l-settled"]
    assert learning["producer_review_ready_unproven"] == 2


def test_success_rate_never_exceeds_one(cio):
    _write(cio / "advisory_outcomes_v1.jsonl", [
        {"outcome_id": "o-1", "status": "SETTLED", "result": "SUCCESS"},
        {"outcome_id": "o-1", "status": "SETTLED", "result": "SUCCESS"},
        {"outcome_id": "o-1", "status": "CONFIRMED"},
        {"outcome_id": "o-2", "status": "SETTLED", "result": "LOSS"},
        {"outcome_id": "o-3", "status": "SETTLED"},  # settled, no directional verdict
    ])
    learning = _learning(cio)
    assert learning["sample_size"] == 2
    assert learning["successful_count"] == 1
    assert learning["success_rate"] == 0.5
    assert learning["settled_count"] == 3
    assert learning["settled_without_verdict_count"] == 1
    assert 0 <= learning["success_rate"] <= 1


def test_calibration_is_null_without_a_method(cio):
    _write(cio / "advisory_outcomes_v1.jsonl", [{"outcome_id": "o-p", "status": "PENDING"}])
    _write(cio / "cio_instrument_records.jsonl", [{
        "schema": "InstrumentRecord@v1", "subject_key": "HELD:AAA",
        "beliefs": [{"belief_key": "b-1", "outcome_ids": ["o-p"], "calibration": {"brier": 0.1}, "success_rate": 0.9}],
    }])
    learning = _learning(cio)
    assert learning["calibration"] is None
    assert learning["calibration_reason"]
    belief = learning["beliefs"][0]
    assert belief["calibration"] is None and belief["calibration_reason"]
    assert belief["evidence_state"] == "PENDING_OUTCOME"


def test_calibration_present_only_from_settled_outcomes_with_method(cio):
    _write(cio / "advisory_outcomes_v1.jsonl", [
        {"outcome_id": "o-a", "status": "SETTLED", "result": "SUCCESS", "horizon": "30d"},
        {"outcome_id": "o-b", "status": "SETTLED", "result": "LOSS", "horizon": "30d"},
    ])
    _write(cio / "cio_instrument_records.jsonl", [{
        "schema": "InstrumentRecord@v1", "subject_key": "HELD:AAA",
        "beliefs": [{"belief_key": "b-ok", "outcome_ids": ["o-a", "o-b"], "calibration_schema": "Calibration@v1",
                     "written_by": "cio_belief_writer", "sample_size": 2, "successful": 1, "success_rate": 0.5,
                     "lesson_ids": ["lesson-7"]}],
    }])
    learning = _learning(cio)
    assert learning["calibration"]["method"] == evidence.CALIBRATION_METHOD
    assert learning["calibration"]["groups"][0]["success_rate"] == 0.5
    belief = learning["beliefs"][0]
    assert belief["evidence_state"] == "PROVEN"
    assert belief["calibration"]["method"] == "Calibration@v1"
    graph = learning["link_graph"]
    assert graph["outcome_to_beliefs"] == {"o-a": ["b-ok"], "o-b": ["b-ok"]}
    assert graph["belief_to_lessons_hypotheses"]["b-ok"]["lesson_ids"] == ["lesson-7"]


def test_link_graph_uses_only_real_refs(cio):
    _write(cio / "advisory_outcomes_v1.jsonl", [
        {"outcome_id": "o-1", "decision_id": "dec-1", "status": "SETTLED", "result": "SUCCESS", "symbol": "AAA"},
    ])
    _write(cio / "lesson_candidates.jsonl", [
        {"lesson_id": "l-1", "supporting_outcome_ids": ["o-1"], "symbol": "AAA"},
        {"lesson_id": "l-symbol-only", "symbol": "AAA"},
    ])
    graph = _learning(cio)["link_graph"]
    assert graph["decision_to_outcomes"] == {"dec-1": ["o-1"]}
    assert graph["lesson_to_sources"] == {"l-1": {"decision_ids": ["dec-1"], "outcome_ids": ["o-1"]}}
    assert all(e["from_id"] != "l-symbol-only" for e in graph["edges"])


def test_belief_outcomes_resolve_against_runtime_advisory_ledger(cio):
    runtime = cio.parent / "runtime"
    runtime.mkdir()
    _write(runtime / "advisory_outcomes.jsonl", [
        {"source_row_id": "SCHD:ira|2026-09-01|abc", "horizon_d": 30, "correct": True, "verdict": "TRIM", "scored_at": "2026-10-01T00:00:00Z"},
    ])
    _write(cio / "cio_instrument_records.jsonl", [{
        "schema": "InstrumentRecord@v1", "subject_key": "HELD:SCHD",
        "beliefs": [{"belief_key": "b-adv", "outcome_ids": ["adv:SCHD:ira|2026-09-01|abc:30d"], "written_by": "cio_belief_writer"}],
    }])
    belief = _learning(cio)["beliefs"][0]
    assert belief["evidence_state"] == "PROVEN"
    assert belief["resolved_outcome_ids"] == ["adv:SCHD:ira|2026-09-01|abc:30d"]


# ── Phase 5: coverage ──────────────────────────────────────────────────────

def _coverage(root: Path, now: str = NOW) -> dict:
    return evidence.build_operator_evidence(now=now)["blocks"]["capability_coverage"]


def test_missing_producer_is_dark_even_when_shared_consumers_have_rows(cio):
    # Consumer stores have rows; the hypothesis producer store does not exist.
    _write(cio / "shadow_experiments.jsonl", [{"experiment_id": "x-1", "created_at": "2026-10-01T10:00:00Z"}])
    _write(cio / "cio_workflow_lineage.jsonl", [{"record_type": "envelope", "created_at": "2026-10-01T10:00:00Z"}])
    rows = {r["capability"]: r for r in _coverage(cio)["rows"]}
    assert rows["hypothesis"]["state"] == "DARK"
    assert "missing" in rows["hypothesis"]["reason"]
    assert rows["operator feedback"]["state"] == "DARK"
    # No producer module in the repo and no store -> UNKNOWN, never DARK.
    assert rows["canon retrieval"]["state"] == "UNKNOWN"


def test_shared_producer_store_is_discriminated_per_capability(cio):
    _write(cio / "cio_workflow_lineage.jsonl", [
        {"record_type": "node", "node_type": "CIO_PRODUCT", "node_id": "n-prod", "recorded_at": "2026-10-02T10:00:00Z"},
    ])
    _write(cio / "cio_instrument_records.jsonl", [
        {"schema": "InstrumentRecord@v1", "subject_key": "HELD:AAA", "updated_ts": "2026-10-02T09:00:00Z"},
    ])
    rows = {r["capability"]: r for r in _coverage(cio)["rows"]}
    assert rows["CIO synthesis"]["state"] == "PARTIAL"
    assert rows["CIO synthesis"]["producer_row_count"] == 1
    assert rows["judgment"]["state"] == "DARK"
    assert rows["specialist disagreement"]["state"] == "DARK"
    assert rows["InstrumentRecord"]["producer_row_count"] == 1
    assert rows["belief writer"]["state"] == "DARK"  # no beliefs written by cio_belief_writer


def test_explicit_consumer_reference_makes_live_and_indistinguishable_caps_partial(cio):
    _write(cio / "hermes_research_requests.jsonl", [{"research_id": "res-1", "ts": "2026-10-02T10:00:00Z"}])
    _write(cio / "hermes_research_results.jsonl", [{"research_id": "res-1", "result_id": "rr-1", "completed_ts": "2026-10-02T10:05:00Z"}])
    _write(cio / "security_research_spine.jsonl", [{"subject_guid": "g-1", "as_of": "2026-10-02T10:00:00Z"}])
    _write(cio / "context_use_receipts.jsonl", [{"security_guid": "g-1", "recorded_at": "2026-10-02T10:10:00Z"}])
    rows = {r["capability"]: r for r in _coverage(cio)["rows"]}
    assert rows["Hermes research"]["state"] == "LIVE"
    assert rows["Hermes research"]["last_consumed_at"] == "2026-10-02T10:05:00Z"
    assert rows["identity resolution"]["discriminated"] is False
    assert rows["identity resolution"]["state"] == "PARTIAL"
    assert "capped at PARTIAL" in rows["identity resolution"]["reason"]


def test_freshness_is_separate_from_state_and_future_clocks_are_ignored(cio):
    _write(cio / "cio_specialist_artifacts.jsonl", [
        {"artifact_id": "sp-old", "created_at": "2026-09-01T00:00:00Z"},
        {"artifact_id": "sp-future", "created_at": "2026-12-29T00:00:00Z"},
    ])
    _write(cio / "cio_workflow_lineage.jsonl", [{"specialist_artifact_id": "sp-old", "created_at": "2026-09-01T01:00:00Z"}])
    row = {r["capability"]: r for r in _coverage(cio)["rows"]}["specialist artifacts"]
    assert row["state"] == "LIVE"
    assert row["last_produced_at"] == "2026-09-01T00:00:00Z"
    assert row["freshness"] == "STALE"
    assert row["stale_after_seconds"] > 0
    assert row["state"] in evidence.STATES


def test_known_dark_classification_present_and_complete(cio):
    from scripts.check_dark_contracts import KNOWN_DARK

    block = _coverage(cio)["known_dark_classification"]
    assert block["status"] == "AVAILABLE"
    assert block["baseline_check"] == "OK"
    assert block["unclassified_baseline_modules"] == []
    modules = {item["module"] for item in block["items"]}
    assert set(KNOWN_DARK) <= modules
    for item in block["items"]:
        assert item["classification"] in {"WIRE", "RETAIN_WITH_REASON", "RETIRE"}
        assert item["reason"].strip()
        assert isinstance(item["cio_relevant"], bool)
    doc = (ROOT / "docs" / "cio" / "CIO_KNOWN_DARK_CLASSIFICATION.md").read_text()
    for module in modules:
        assert module in doc, module


# ── clocks ─────────────────────────────────────────────────────────────────

def test_source_as_of_fixed_while_composition_as_of_advances(cio):
    _write(cio / "hermes_research_results.jsonl", [{"result_id": "rr-c", "completed_ts": "2026-10-01T09:00:00Z", "as_of": "2026-10-01T09:00:00Z"}])
    _write(cio / "memory_contexts.jsonl", [{"context_id": "ctx-c", "created_at": "2026-10-01T08:00:00Z"}])
    _write(cio / "advisory_outcomes_v1.jsonl", [{"outcome_id": "o-c", "status": "SETTLED", "result": "SUCCESS", "created_at": "2026-10-01T07:00:00Z"}])
    _write(cio / "cio_specialist_artifacts.jsonl", [{"artifact_id": "sp-c", "created_at": "2026-10-01T06:00:00Z"}])
    first = evidence.build_operator_evidence(now="2026-10-02T10:00:00Z")
    second = evidence.build_operator_evidence(now="2026-10-02T11:30:00Z")
    assert first["composition_as_of"] != second["composition_as_of"]
    assert first["source_as_of"] == second["source_as_of"] is not None
    for name in ("research", "institutional_cognition", "learning", "capability_coverage"):
        assert first["blocks"][name]["source_as_of"] == second["blocks"][name]["source_as_of"] is not None, name
        assert first["blocks"][name]["composition_as_of"] != second["blocks"][name]["composition_as_of"]
    age1 = {r["capability"]: r["artifact_age"] for r in first["blocks"]["capability_coverage"]["rows"]}
    age2 = {r["capability"]: r["artifact_age"] for r in second["blocks"]["capability_coverage"]["rows"]}
    assert age2["specialist artifacts"] - age1["specialist artifacts"] == 5400
