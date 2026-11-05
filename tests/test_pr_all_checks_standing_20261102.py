"""Standing merge checks: exact required SUCCESS and every other executed context.

Pure synthetic GitHub rows only. No broker imports, network, paid runs or mutations.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import socket
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("standing_all_checks_under_test", ROOT / "scripts/lib/pr_all_checks_green.py")
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)
REQUIRED = ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")


@pytest.fixture(autouse=True)
def no_external_effect(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Pure check evaluation cannot use network or subprocess")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)


def run(name, conclusion="SUCCESS", *, status="COMPLETED", workflow="primary", started="2031-01-02T03:00:00Z"):
    row = {"name": name, "status": status, "conclusion": conclusion, "startedAt": started}
    if workflow is not None:
        row["workflowName"] = workflow
    return row


def green():
    return [run(name) for name in REQUIRED]


def test_empty_and_skip_only_never_pass_a_merge_gate():
    assert G.evaluate([])["ok"] is False
    assert G.evaluate([], allow_empty=True)["ok"] is True  # Existing explicitly nongating use.
    skipped = [run(name, "SKIPPED") for name in REQUIRED]
    assert G.evaluate_rollup(skipped)["ok"] is False
    assert G.evaluate_rollup(skipped, allow_empty=True)["ok"] is False
    assert G.evaluate_merge_rollup([])["ok"] is False
    assert G.evaluate_merge_rollup(skipped)["ok"] is False


def test_one_optional_pass_does_not_replace_four_required_runs():
    result = G.evaluate_merge_rollup([*[run(n, "SKIPPED") for n in REQUIRED], run("optional-pass")])
    assert result["ok"] is False and result["required_success"] == []
    assert len(result["required_not_success"]) == 4


@pytest.mark.parametrize("missing", REQUIRED)
def test_every_required_name_must_exist(missing):
    result = G.evaluate_merge_rollup([r for r in green() if r["name"] != missing])
    assert result["ok"] is False and result["missing_required"] == [missing]


@pytest.mark.parametrize("status,conclusion", [
    ("COMPLETED", "NEUTRAL"), ("COMPLETED", "SKIPPED"), ("COMPLETED", "FAILURE"),
    ("COMPLETED", "CANCELLED"), ("IN_PROGRESS", "SUCCESS"), ("QUEUED", None),
])
def test_required_check_must_be_completed_success(status, conclusion):
    rows = green();rows[-1] = run("ci-gate", conclusion, status=status)
    result = G.evaluate_merge_rollup(rows)
    assert result["ok"] is False and "ci-gate" not in result["required_success"]
    assert any("ci-gate" in value for value in result["required_not_success"])


def test_required_conclusion_without_explicit_status_is_not_proof():
    rows = green();rows[-1].pop("status")
    assert G.evaluate_rollup(rows)["ok"] is True  # Preserve generic legacy normalization.
    result = G.evaluate_merge_rollup(rows)
    assert result["ok"] is False
    assert any("missing explicit" in value for value in result["required_not_success"])


def test_optional_legacy_context_is_compatible_but_cannot_impersonate_required_actions():
    assert G.evaluate_merge_rollup([*green(), {"context": "legacy-optional", "state": "SUCCESS"}])["ok"] is True
    rows = green()[:-1] + [{"context": "ci-gate", "state": "SUCCESS"}]
    assert G.evaluate_merge_rollup(rows)["ok"] is False


def test_required_runs_and_legitimate_optional_skips_and_neutral_pass():
    result = G.evaluate_merge_rollup([*green(), run("docs", "NEUTRAL"), run("not-triggered-by-design", "SKIPPED")])
    assert result["ok"] is True and result["required_success"] == list(REQUIRED)
    assert result["missing_required"] == [] and result["required_not_success"] == []


def test_any_other_red_or_pending_check_still_blocks():
    for row in [run("optional-red", "FAILURE"), run("optional-pending", None, status="IN_PROGRESS")]:
        result = G.evaluate_merge_rollup([*green(), row])
        assert result["ok"] is False and any(row["name"] in value for value in result["failing"])


def test_duplicate_required_name_in_another_workflow_cannot_borrow_success():
    result = G.evaluate_merge_rollup([*green(), run("ci-gate", "NEUTRAL", workflow="different-workflow")])
    assert result["ok"] is False and "ci-gate" not in result["required_success"]
    assert any("different-workflow" in value for value in result["required_not_success"])


def test_optional_workflow_isolation_is_preserved():
    result = G.evaluate_merge_rollup([*green(), run("shard 0", "FAILURE", workflow="workflow-a"),
                                    run("shard 0", "SUCCESS", workflow="workflow-b", started="2031-01-02T04:00:00Z")])
    assert result["ok"] is False and any("workflow-a" in value for value in result["failing"])


def test_supplied_check_suite_identity_survives_normalization():
    a, b = run("shard 0", "FAILURE", workflow=None), run("shard 0", workflow=None)
    a["check_suite"] = {"id": 1};b["check_suite"] = {"id": 2}
    result = G.evaluate_merge_rollup([*green(), a, b])
    assert result["ok"] is False and any("shard 0 [1]" in value for value in result["failing"])


def test_later_skip_does_not_hide_required_failure_but_real_recovery_counts():
    others = green()[:-1]
    failed = run("ci-gate", "FAILURE", started="2031-01-02T01:00:00Z")
    skipped = run("ci-gate", "SKIPPED", started="2031-01-02T03:00:00Z")
    assert G.evaluate_merge_rollup([*others, failed, skipped])["ok"] is False
    recovered = run("ci-gate", "SUCCESS", started="2031-01-02T02:00:00Z")
    assert G.evaluate_merge_rollup([*others, failed, recovered, skipped])["ok"] is True


def test_rollup_limit_remains_fail_closed_even_when_required_checks_succeed():
    rows = green() + [run(f"optional-{n}") for n in range(G.ROLLUP_LIMIT - len(REQUIRED))]
    result = G.evaluate_merge_rollup(rows)
    assert result["ok"] is False and "limit" in result["reason"]


@pytest.mark.parametrize("raw", ["bad", {}, [None], [[]], [7], [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
                                  [run("malformed", {"nested": "value"})]])
def test_malformed_rollup_is_structured_not_green(raw):
    result = G.evaluate_merge_rollup(raw)
    assert result["ok"] is False and isinstance(result["reason"], str)
    assert set(["passing", "failing", "skipped", "checked", "required_success", "missing_required", "required_not_success"]) <= result.keys()


@pytest.mark.parametrize("required", [(), ("ci-gate",), "ci-gate", [[], *REQUIRED], None])
def test_required_override_cannot_weaken_the_four(required):
    assert G.evaluate_merge_rollup(green(), required=required)["ok"] is False


def test_requirements_can_be_additive_only():
    names = (*REQUIRED, "extra-required")
    assert G.evaluate_merge_rollup(green(), required=names)["ok"] is False
    assert G.evaluate_merge_rollup([*green(), run("extra-required")], required=names)["ok"] is True


def test_existing_paginated_gate_still_refuses_unread_runs():
    def read(_):
        return {"total_count": 200, "check_runs": [run("visible-success")]}
    result = G.all_checks_green(read, "synthetic/repo", "a" * 40)
    assert result["ok"] is False and "could not read" in result["reason"]
