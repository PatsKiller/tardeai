"""The promote gate requires release-readiness green on the exact main SHA (alignment audit M6).

Branch protection on main requires three contexts: cio-hardening, agent-governance and
release-readiness (read 2026-10-21: strict false, contexts exactly those three). The promote
gate's REQUIRED_PUSH_WORKFLOWS named only the first two, so a manual `promote` accepted a SHA
whose release-readiness push run was red, missing or still running. Hermetic: synthetic runs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("preflight_rr_20261021", ROOT / "scripts" / "release_grant_preflight.py")
gate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(gate)

SHA = "a" * 40
RR = ".github/workflows/release-readiness.yml"
REQUIRED_CONTEXTS = {"cio-hardening", "agent-governance", "release-readiness"}


def _runs(**override):
    rows = []
    for i, path in enumerate(sorted(gate.REQUIRED_PUSH_WORKFLOWS), 1):
        row = dict(
            id=i,
            workflow_id=i + 10,
            path=path,
            name=Path(path).stem,
            run_number=1,
            head_sha=SHA,
            event="push",
            head_branch="main",
            status="completed",
            conclusion="success",
            run_attempt=1,
        )
        row.update(override.get(path, {}))
        rows.append(row)
    return rows


def test_release_readiness_is_a_required_push_workflow():
    assert RR in gate.REQUIRED_PUSH_WORKFLOWS
    assert len(gate.REQUIRED_PUSH_WORKFLOWS) == 3


def test_every_required_workflow_exists_runs_on_push_to_main_and_maps_to_a_protected_context():
    contexts = set()
    for path in gate.REQUIRED_PUSH_WORKFLOWS:
        wf = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
        on = wf.get("on", wf.get(True)) or {}
        assert "main" in (on.get("push") or {}).get("branches", []), path
        for job_id, job in wf["jobs"].items():
            contexts.add(job.get("name", job_id))
    assert REQUIRED_CONTEXTS <= contexts
    rr = yaml.safe_load((ROOT / RR).read_text(encoding="utf-8"))
    assert rr["name"] == "release-readiness" and "release-readiness" in rr["jobs"]


def test_all_three_green_passes():
    ev = gate.evaluate_push_checks(SHA, _runs())
    assert ev["ok"] is True, ev["errors"]
    assert RR in ev["required_workflows"]


def test_missing_release_readiness_run_refuses():
    rows = [r for r in _runs() if r["path"] != RR]
    ev = gate.evaluate_push_checks(SHA, rows)
    assert ev["ok"] is False
    assert f"missing:{RR}" in ev["errors"]


@pytest.mark.parametrize(
    "status,conclusion",
    [("completed", "failure"), ("completed", "cancelled"), ("in_progress", None), ("queued", None)],
)
def test_red_or_pending_release_readiness_refuses(status, conclusion):
    ev = gate.evaluate_push_checks(SHA, _runs(**{RR: {"status": status, "conclusion": conclusion}}))
    assert ev["ok"] is False
    assert f"not_successful:{RR}" in ev["errors"]


def test_release_readiness_on_another_sha_or_a_pr_does_not_count():
    for override in ({"head_sha": "b" * 40}, {"event": "pull_request"}, {"head_branch": "feature"}):
        ev = gate.evaluate_push_checks(SHA, _runs(**{RR: override}))
        assert f"missing:{RR}" in ev["errors"], override
