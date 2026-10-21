"""Main/nightly CI alarms fire on cancelled and timed-out runs; the nightly is the sharded suite.

Alignment audit H1, 2026-10-21: the nightly serial `cio-hardening-full` was cancelled at its
40-minute timeout on 8 of the last 10 nights (e.g. run 39563068389) and `main-red-alert` fired
only on `result == 'failure'`, so nothing was raised. Now:

* main-red-alert (push/dispatch on main) fires on failure, cancelled or timed_out;
* the nightly runs cio-full-suite-sharded.yml on schedule (every registered file + pg shard), with
  its own nightly-red-alert on the same outcomes; the serial profile stays on workflow_dispatch.

The `if:` expressions are evaluated by a small interpreter for exactly the forms they use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HARD = yaml.safe_load((ROOT / ".github/workflows/cio-production-hardening-ci.yml").read_text(encoding="utf-8"))
SHARD = yaml.safe_load((ROOT / ".github/workflows/cio-full-suite-sharded.yml").read_text(encoding="utf-8"))
OUTCOMES = ["success", "failure", "cancelled", "timed_out", "skipped"]
RED = {"failure", "cancelled", "timed_out"}


def _on(doc: dict) -> dict:
    return doc.get("on", doc.get(True)) or {}


def _eval(expr: str, ctx: dict) -> bool:
    """Evaluate `always() && ... && (... || ...)` built from ==, !=, contains(fromJSON(..), x)
    and contains(needs.*.result, 'x')."""
    expr = " ".join(expr.split())

    def atom(a: str) -> bool:
        a = a.strip()
        while a.startswith("(") and a.endswith(")") and _balanced(a[1:-1]):
            a = a[1:-1].strip()
        if "||" in _top(a, "||"):
            return any(atom(p) for p in _split(a, "||"))
        if "&&" in _top(a, "&&"):
            return all(atom(p) for p in _split(a, "&&"))
        if a == "always()":
            return True
        m = re.fullmatch(r"([\w.\-]+) (==|!=) '([^']*)'", a)
        if m:
            v = ctx[m.group(1)]
            return (v == m.group(3)) if m.group(2) == "==" else (v != m.group(3))
        m = re.fullmatch(r"contains\(fromJSON\('(.+)'\), ([\w.\-]+)\)", a)
        if m:
            return ctx[m.group(2)] in json.loads(m.group(1))
        m = re.fullmatch(r"contains\(needs\.\*\.result, '([^']*)'\)", a)
        if m:
            return m.group(1) in ctx["needs.*.result"]
        raise AssertionError(f"unsupported expression: {a!r}")

    return atom(expr)


def _balanced(s: str) -> bool:
    depth = 0
    for ch in s:
        depth += ch == "("
        depth -= ch == ")"
        if depth < 0:
            return False
    return depth == 0


def _split(s: str, op: str) -> list[str]:
    parts, depth, cur, i = [], 0, "", 0
    while i < len(s):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
        if depth == 0 and s.startswith(op, i):
            parts.append(cur)
            cur, i = "", i + len(op)
            continue
        cur += s[i]
        i += 1
    return parts + [cur]


def _top(s: str, op: str) -> str:
    return op if len(_split(s, op)) > 1 else ""


def _main_ctx(event: str, fast: str, full: str) -> dict:
    return {
        "github.event_name": event,
        "github.ref": "refs/heads/main",
        "needs.cio-hardening.result": fast,
        "needs.cio-hardening-full.result": full,
    }


@pytest.mark.parametrize("result", OUTCOMES)
def test_main_red_alert_fires_on_red_cancelled_and_timed_out_push_runs(result):
    cond = HARD["jobs"]["main-red-alert"]["if"]
    assert _eval(cond, _main_ctx("push", result, "skipped")) is (result in RED)


@pytest.mark.parametrize("result", OUTCOMES)
def test_main_red_alert_covers_the_dispatched_full_profile(result):
    cond = HARD["jobs"]["main-red-alert"]["if"]
    assert _eval(cond, _main_ctx("workflow_dispatch", "success", result)) is (result in RED)


@pytest.mark.parametrize("result", ["failure", "cancelled", "timed_out"])
def test_main_red_alert_never_fires_for_pull_requests(result):
    cond = HARD["jobs"]["main-red-alert"]["if"]
    assert _eval(cond, _main_ctx("pull_request", result, result)) is False


def test_serial_nightly_is_retired_and_the_sharded_suite_runs_on_schedule():
    assert "schedule" not in _on(HARD)
    assert HARD["jobs"]["cio-hardening-full"]["if"].strip() == "github.event_name == 'workflow_dispatch'"
    crons = [c["cron"] for c in _on(SHARD)["schedule"]]
    assert crons == ["17 7 * * *"]
    # PR and dispatch triggers unchanged
    assert "pull_request" in _on(SHARD) and "workflow_dispatch" in _on(SHARD)


@pytest.mark.parametrize("result", OUTCOMES)
def test_nightly_red_alert_fires_when_any_sharded_job_is_red(result):
    job = SHARD["jobs"]["nightly-red-alert"]
    assert set(job["needs"]) == {"shard", "serial", "pg", "integrity", "ci-gate"}
    results = ["success", "success", result, "success", "success"]
    ctx = {"github.event_name": "schedule", "needs.*.result": results}
    assert _eval(job["if"], ctx) is (result in RED)
    assert job["permissions"] == {"issues": "write"}


@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_nightly_red_alert_is_schedule_only(event):
    ctx = {"github.event_name": event, "needs.*.result": ["failure", "cancelled"]}
    assert _eval(SHARD["jobs"]["nightly-red-alert"]["if"], ctx) is False


def test_nightly_concurrency_group_is_separate_and_not_cancelled():
    conc = SHARD["concurrency"]
    assert "github.event_name == 'schedule' && '-nightly'" in conc["group"]
    assert conc["cancel-in-progress"].strip() == "${{ github.event_name != 'schedule' }}"


def test_alert_issue_label_is_shared():
    for doc, job in ((HARD, "main-red-alert"), (SHARD, "nightly-red-alert")):
        run = doc["jobs"][job]["steps"][0]["run"]
        assert "--label ci-main-red" in run
