"""Execute the configured checkout selector against PR and non-PR contexts.

No Actions, network calls, release mutation, or runtime effects run here.
"""

from pathlib import Path
import os
import re
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ".github/workflows/release-readiness.yml"


def configured_checkout(context):
    revision = os.environ.get("CI_WORKFLOW_SOURCE_REVISION")
    raw = (
        subprocess.check_output(["git", "show", f"{revision}:{WORKFLOW_PATH}"], cwd=ROOT, text=True)
        if revision
        else (ROOT / WORKFLOW_PATH).read_text()
    )
    steps = yaml.safe_load(raw)["jobs"]["release-readiness"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    # Actions' default ref resolves to github.sha (the merge preview on a PR).
    # This evaluator accepts only the object-path/coalescing expression used
    # by existing exact-head repository checks; no arbitrary expressions run.
    expression = checkout.get("with", {}).get("ref", "${{ github.sha }}")
    assert expression.startswith("${{ ") and expression.endswith(" }}")
    for path in expression[4:-3].split(" || "):
        assert re.fullmatch(r"github(?:\.[a-z_]+)+", path)
        value = context
        for field in path.split("."):
            value = value.get(field) if isinstance(value, dict) else None
        if value:
            return value
    return None


@pytest.mark.parametrize("event", ["pull_request", "push", "workflow_dispatch", "schedule"])
def test_release_proof_executes_candidate_head_or_exact_non_pr_event(event):
    candidate, event_sha = "a" * 40, "b" * 40
    context = {
        "github": {
            "sha": event_sha,
            "event": {"pull_request": {"head": {"sha": candidate}}} if event == "pull_request" else {},
        }
    }
    expected = candidate if event == "pull_request" else event_sha
    assert configured_checkout(context) == expected, "release proof must run the exact candidate, not a merge preview"
