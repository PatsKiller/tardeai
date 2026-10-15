"""Public source and owned fixtures only; no host, provider, credentials or DB."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from scripts import audit_n8n_contract_baselines as A
from scripts import n8n_cutover_checklist as C
from scripts.lib import n8n_health_contracts as H
from scripts.lib.n8n_momentum_lifecycle import contract_body_digest, contract_review_proven

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 12)
NOW = datetime.fromisoformat("2026-10-12T14:00:00-04:00")
SHA = "a" * 40


def source_contract(cid="trade-ai-scalp-live"):
    catalogue = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())
    return copy.deepcopy(next(row for row in catalogue["contracts"] if row["id"] == cid))


def fixture_review(contract):
    contract["status"] = "REVIEWED"
    contract["ownership_confirmation"] = "OWNER_ACCEPTED"
    contract["review"] = {"reviewed_by": "isolated-fixture-owner", "decision_ref": "fixture://explicit-owner-decision"}
    contract["review"]["contract_body_sha256"] = contract_body_digest(contract)
    return contract


def test_all_operative_baselines_have_applicable_fields_and_order():
    catalogue, _, _, _ = A.load_sources(ROOT)
    # + 2 (2026-10-14 scalp-premarket-onboard: finviz-enrichment-scalp-hot, scalp-hot-list)
    # + 3 (2026-10-15 n8n fabric process hermes-learning: outcome-grader, outcome-learning, config-governor)
    # + 3 (2026-10-15 hermes-learning unblock: tag-engine, outcome-feedback-agent, autonomous-self-tune)
    # + 6 (2026-10-15 shadow wave LD-W1: tests/test_shadow_wave_ld_w1_20261015.py)
    assert len(catalogue["contracts"]) == 132
    assert not {row["id"]: A.baseline_errors(row) for row in catalogue["contracts"] if A.baseline_errors(row)}


def test_source_correction_covers_exact_population_and_preserves_105_bodies():
    audit = json.loads((ROOT / A.AUDIT_REL).read_text())
    assert audit["contracts_changed"] == 13
    assert audit["changed_reviewed_bodies_held_draft"] == 5
    assert audit["contracts_with_unresolved_baselines"] == 0
    unchanged = [row for row in audit["records"] if not row["changed_fields"]]
    assert len(unchanged) == 105
    assert all(row["body_sha256_before"] == row["body_sha256_after"] for row in unchanged)
    assert all(row["status_before"] == row["status_after"] for row in unchanged)
    for field in A.FIELDS:
        assert audit["fields"][field]["required"] == audit["fields"][field]["present_after"] == 118
        assert audit["fields"][field]["unresolved"] == audit["fields"][field]["not_applicable"] == 0


@pytest.mark.parametrize(
    "cid,timeout,degraded,failed",
    [
        ("momentum-lifecycle-monitor", 60, 0.167, 0.25),
        ("momentum-cache-reconcile", 60, 0.167, 0.25),
        ("trade-ai-scalp-live", 295, 0.167, 0.25),
        ("tradeai-momentum-lifecycle-candidate", 50, 0.167, 0.25),
        ("tradeai-dispatcher", 50, 0.033, 0.05),
        ("tradeai-event-router", 50, 0.033, 0.05),
        ("tradeai-incident-router", 50, 0.033, 0.05),
        ("tradeai-approval-router", 50, 0.167, 0.25),
        ("tradeai-digest-scheduler", 50, 0.167, 0.25),
        ("tradeai-heartbeat-watcher", 150, 0.167, 0.25),
        ("incident-notifier", 120, 0.2, 0.3),
        ("n8n-failure-diagnosis", 600, 0.5, 0.75),
        ("n8n-siem-bridge", 120, 0.2, 0.3),
    ],
)
def test_exact_declared_sources_not_empirical_business_baselines(cid, timeout, degraded, failed):
    contract = source_contract(cid)
    assert tuple(contract["baseline"][field] for field in A.FIELDS) == (timeout, degraded, failed)
    assert contract["review"]["proposed_contract_body_sha256"] == contract_body_digest(contract)
    if contract["status"] == "DRAFT":
        assert contract["review"]["baseline_correction_requires_review"] is True
        assert not contract_review_proven(contract)
    else:
        # A later real review must bind the corrected body; the audit is not authority.
        assert contract["review"]["baseline_correction_requires_review"] is False
        assert contract_review_proven(contract)


def test_prior_review_and_baseline_are_history_never_current_authority():
    contract = source_contract()
    previous = contract["review"]["previous_review"]
    assert previous["status"] == "REVIEWED"
    assert previous["metadata"]["decision_ref"]
    assert previous["metadata"]["contract_body_sha256"] == previous["body_sha256"]
    assert previous["body_sha256"] != contract_body_digest(contract)
    if contract["status"] == "DRAFT":
        assert contract["review"]["reviewed_by"] is None
        assert contract["review"]["decision_ref"] is None
        assert contract["review"]["contract_body_sha256"] is None
    else:
        assert contract_review_proven(contract)


@pytest.mark.parametrize("field", A.FIELDS)
@pytest.mark.parametrize("value", [None, 0, -1, True, False, "295", float("inf"), float("nan")])
def test_body_digest_and_owner_review_cannot_accept_invalid_numbers(field, value):
    contract = source_contract()
    contract["baseline"][field] = value
    fixture_review(contract)  # Even a correctly recomputed digest cannot bypass semantics.
    assert any(field in error for error in H.validate_contract(contract))
    assert not contract_review_proven(contract)


def test_missing_or_inverted_baseline_cannot_pass_review():
    contract = source_contract()
    del contract["baseline"]["timeout_s"]
    assert not contract_review_proven(fixture_review(contract))
    for failed in (0.167, 0.1):
        contract = source_contract()
        contract["baseline"]["freshness_failed_after_h"] = failed
        fixture_review(contract)
        assert any("must exceed" in error for error in H.validate_contract(contract))
        assert not contract_review_proven(contract)


def test_unmeasured_draft_is_a_structural_proposal_and_cannot_be_promoted():
    contract = source_contract()
    contract["status"] = "DRAFT"
    contract["baseline"].pop("timeout_s")
    contract["baseline"]["freshness_degraded_after_h"] = None
    contract["baseline"]["freshness_failed_after_h"] = H.UNKNOWN
    assert H.validate_contract(contract) == []
    assert not contract_review_proven(contract)
    # A correct body digest and explicit fixture owner decision cannot invent measurements.
    fixture_review(contract)
    assert len([error for error in H.validate_contract(contract) if "baseline." in error]) == 3
    assert not contract_review_proven(contract)


@pytest.mark.parametrize("field", A.FIELDS)
@pytest.mark.parametrize("value", [0, -1, True, False, "295", float("inf"), float("nan")])
def test_supplied_draft_numbers_still_require_valid_limits(field, value):
    contract = source_contract()
    contract["status"] = "DRAFT"
    contract["baseline"][field] = value
    assert any(field in error for error in H.validate_contract(contract))


def test_source_correction_preserves_complete_operator_and_empirical_baselines():
    complete = fixture_review(source_contract())
    complete["baseline"].update(basis="OPERATOR_SLO", freshness_degraded_after_h=63.25, freshness_failed_after_h=63.5)
    fixture_review(complete)
    doc = {"contracts": [complete]}
    corrected, audit = A.correct_catalogue(doc, {}, {}, {}, as_of=DAY)
    assert corrected == doc
    assert audit["contracts_changed"] == 0


def test_unknown_sources_remain_unaccepted_with_specific_collection_action():
    contract = fixture_review(source_contract())
    contract["baseline"] = {"basis": "CLASS_DEFAULT_PROVISIONAL"}
    corrected, audit = A.correct_catalogue({"contracts": [contract]}, {}, {}, {}, as_of=DAY)
    row = corrected["contracts"][0]
    assert row["status"] == "DRAFT"
    assert not contract_review_proven(row)
    assert audit["contracts_with_unresolved_baselines"] == 1
    assert "bounded timeout and calendar/cadence" in audit["records"][0]["collection_action"]


def acceptance_fixture(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    contract = fixture_review(source_contract())
    (config / "n8n_health_contracts.json").write_text(json.dumps({"contracts": [contract]}))
    packet = {
        "tested_sha": SHA,
        "deployed_sha": SHA,
        "fixes_deployed_at": "2026-10-12T13:50:00-04:00",
        "observed_at": "2026-10-12T13:59:00-04:00",
    }
    return contract, packet


def test_real_scalp_acceptance_context_uses_declared_timeout_and_freshness(tmp_path):
    contract, packet = acceptance_fixture(tmp_path)
    assert contract_review_proven(contract)
    context, errors = C.acceptance_context(tmp_path, "trade-ai-scalp-live", packet, SHA, NOW)
    assert errors == []
    assert context["timeout"] == 295 and context["freshness"] == 0.167
    assert C._current_receipt({"code_sha": SHA, "finished_at": packet["observed_at"]}, context, NOW)
    assert not C._current_receipt({"code_sha": "b" * 40, "finished_at": packet["observed_at"]}, context, NOW)
    assert not C._current_receipt({"code_sha": SHA, "finished_at": "2026-10-12T13:49:00-04:00"}, context, NOW)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"tested_sha": "b" * 40}, "DRIFT"),
        ({"observed_at": "2026-10-12T13:49:00-04:00", "fixes_deployed_at": "2026-10-12T13:40:00-04:00"}, "STALE"),
        ({"observed_at": "2026-10-12T13:59:00"}, "timezone-aware"),
        ({"observed_at": "2026-10-12T14:01:00-04:00"}, "ordered"),
    ],
)
def test_actual_acceptance_context_still_rejects_sha_stale_and_bad_timing(tmp_path, change, reason):
    _, packet = acceptance_fixture(tmp_path)
    packet.update(change)
    _, errors = C.acceptance_context(tmp_path, "trade-ai-scalp-live", packet, SHA, NOW)
    assert any(reason in error for error in errors)


def test_observer_has_workflow_health_baseline_but_never_a_host_eligibility_row():
    catalogue, registry, allowlist, _ = A.load_sources(ROOT)
    cid = "tradeai-momentum-lifecycle-candidate"
    assert any(row["id"] == cid and row["kind"] == "generic_workflow" for row in catalogue["contracts"])
    assert cid not in registry and cid not in allowlist
