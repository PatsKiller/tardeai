"""Source-only and fixture-backed acceptance for the Temporal NOC POC."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from scripts.temporal_poc.contracts import (
    ACTIVITY_POLICIES,
    AUTHORITY,
    HARD_POLICY_ERRORS,
    MEMORY_BEHAVIOR_INFLUENCE,
    workflow_blueprint,
)
from scripts.temporal_poc.noc_shadow import InjectedCrash, NOCShadowWorkflow
from scripts.temporal_poc.temporal_workflow import TEMPORAL_SDK_AVAILABLE

ROOT = Path(__file__).resolve().parents[1]


def test_retry_policies_fail_closed_on_cost_and_policy_errors():
    for policy in ACTIVITY_POLICIES.values():
        assert set(HARD_POLICY_ERRORS).issubset(policy.non_retryable_error_types)
        assert policy.maximum_attempts <= 3
    assert ACTIVITY_POLICIES["acquire_research"].heartbeat_timeout_seconds == 20


def test_blueprint_preserves_domain_truth_and_advisory_authority():
    blueprint = workflow_blueprint()
    assert blueprint["canonical_truth"] == "Trade AI domain stores"
    assert blueprint["temporal_truth"].startswith("orchestration history")
    assert blueprint["authority"] == AUTHORITY == "READ_ONLY_ADVISORY"
    assert blueprint["memory_behavior_influence"] == MEMORY_BEHAVIOR_INFLUENCE == 0


def test_provider_ambiguous_boundary_resumes_without_duplicate_call(tmp_path):
    workflow = NOCShadowWorkflow(tmp_path)
    with pytest.raises(InjectedCrash, match="provider_after_response"):
        workflow.run(run_id="run_provider_crash", crash_after_provider=True)

    resumed = NOCShadowWorkflow(tmp_path).run(
        run_id="run_provider_crash", crash_after_provider=True
    )
    assert resumed["provider_calls"] == 1
    assert resumed["thesis_version_count"] == 2
    assert resumed["decision_writes"] == 1
    assert resumed["financial_writes"] == 0


def test_domain_write_ambiguous_boundary_does_not_churn_thesis(tmp_path):
    workflow = NOCShadowWorkflow(tmp_path)
    with pytest.raises(InjectedCrash, match="reconcile_after_domain_write"):
        workflow.run(run_id="run_db_crash", crash_after_reconcile_write=True)

    resumed = NOCShadowWorkflow(tmp_path).run(
        run_id="run_db_crash", crash_after_reconcile_write=True
    )
    assert resumed["thesis_version_count"] == 2
    assert resumed["decision_writes"] == 1
    assert resumed["decision"]["payload"]["authority"] == AUTHORITY


def test_identical_replay_is_no_new_info_and_emits_nothing(tmp_path):
    first = NOCShadowWorkflow(tmp_path).run(run_id="run_first")
    replay = NOCShadowWorkflow(tmp_path).run(run_id="run_replay")

    assert first["delta"]["classification"] == "STRENGTHENS"
    assert first["thesis_version_count"] == 2
    assert first["decision_writes"] == 1
    assert replay["delta"]["classification"] == "NO_NEW_INFO"
    assert replay["reconciliation"]["version_published"] is False
    assert replay["thesis_version_count"] == 2
    assert replay["decision"]["emitted"] is False
    assert replay["decision"]["suppression"] == "NO_NEW_INFO"
    assert replay["decision_writes"] == 1
    assert replay["provider_calls"] == 1


def test_poc_modules_do_not_import_financial_mutation_paths():
    forbidden_roots = {
        "broker",
        "orders",
        "order",
        "stops",
        "stop",
        "execution",
        "schwab",
        "two_factor",
    }
    for path in (ROOT / "scripts/temporal_poc").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for name in imported:
            parts = set(name.lower().replace("-", "_").split("."))
            assert not (parts & forbidden_roots), (path, name)


def test_temporal_runtime_gate_is_honest():
    assert TEMPORAL_SDK_AVAILABLE is (importlib.util.find_spec("temporalio") is not None)
