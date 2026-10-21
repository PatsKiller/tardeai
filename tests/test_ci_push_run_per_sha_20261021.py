"""cio-production-hardening-ci: one push-to-main run per SHA (alignment audit H2, 2026-10-21).

GitHub keeps one PENDING run per concurrency group. With the group keyed on the ref only, a
third merge while a main run was in progress cancelled the queued run (main runs 39617949518,
39609079036, 39608294713), so intermediate merged SHAs had no main CI and
release_grant_preflight read them as "not green". The push group now carries the SHA; the
pull_request group (cancel superseded PR runs) is unchanged.

The expression is evaluated here by a small interpreter for exactly the forms it uses, so the
test proves the resulting group strings, not only the text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "cio-production-hardening-ci.yml"
DOC = yaml.safe_load(WF.read_text(encoding="utf-8"))
CONC = DOC["concurrency"]


def _eval_expr(expr: str, ctx: dict) -> str | bool:
    """Evaluate the GitHub expression forms the concurrency block uses."""
    expr = expr.strip()
    m = re.fullmatch(r"(.+?)\s*&&\s*(.+?)\s*\|\|\s*(.+)", expr)
    if m:
        return _eval_expr(m.group(2), ctx) if _eval_expr(m.group(1), ctx) else _eval_expr(m.group(3), ctx)
    m = re.fullmatch(r"([\w.]+)\s*==\s*'([^']*)'", expr)
    if m:
        return ctx[m.group(1)] == m.group(2)
    m = re.fullmatch(r"format\('([^']*)',\s*([\w.]+)\)", expr)
    if m:
        return m.group(1).replace("{0}", str(ctx[m.group(2)]))
    m = re.fullmatch(r"'([^']*)'", expr)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w.]+", expr):
        return ctx[expr]
    raise AssertionError(f"unsupported expression form: {expr!r}")


def _render(template: str, ctx: dict) -> str:
    return re.sub(r"\$\{\{(.+?)\}\}", lambda m: str(_eval_expr(m.group(1), ctx)), str(template))


def _ctx(event: str, ref: str, sha: str) -> dict:
    return {
        "github.event_name": event,
        "github.ref": ref,
        "github.sha": sha,
        "github.workflow": "cio-production-hardening-ci",
    }


def test_two_main_pushes_get_distinct_groups_and_never_cancel():
    a = _render(CONC["group"], _ctx("push", "refs/heads/main", "a" * 40))
    b = _render(CONC["group"], _ctx("push", "refs/heads/main", "b" * 40))
    assert a != b
    assert a.endswith("-" + "a" * 40)
    assert _render(CONC["cancel-in-progress"], _ctx("push", "refs/heads/main", "a" * 40)) == "False"


def test_pull_request_group_is_unchanged_and_supersedes():
    a = _render(CONC["group"], _ctx("pull_request", "refs/pull/7/merge", "a" * 40))
    b = _render(CONC["group"], _ctx("pull_request", "refs/pull/7/merge", "b" * 40))
    assert a == b == "cio-hardening-cio-production-hardening-ci-refs/pull/7/merge"
    assert _render(CONC["cancel-in-progress"], _ctx("pull_request", "refs/pull/7/merge", "a" * 40)) == "True"


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_schedule_and_dispatch_keep_the_per_ref_group(event):
    g = _render(CONC["group"], _ctx(event, "refs/heads/main", "c" * 40))
    assert g == "cio-hardening-cio-production-hardening-ci-refs/heads/main"


def test_the_false_never_cancel_comment_is_gone():
    text = WF.read_text(encoding="utf-8")
    assert "main runs never cancel" not in text
    assert "ONE GROUP PER SHA" in text
