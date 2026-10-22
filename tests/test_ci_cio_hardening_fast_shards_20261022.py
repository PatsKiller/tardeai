"""cio-hardening FAST profile split into parallel jobs (2026-10-22 follow-up to #1934).

The push-to-main FAST profile ran every registered gate in ONE job: 26-38 min on 2026-10-22 (run
39817528884 cancelled at 35 min on both attempts; timeout raised to 50 in #1934). It now reuses the
cio-full-suite-sharded pattern on push/dispatch: 8 shards + serial + pg + integrity rails in
parallel, and the required context `cio-hardening` is the aggregate:

* green only when every FAST job succeeded and the shard manifests prove each registered file ran
  exactly once on this tree (run_cio_hardening_ci.py --verify-shards, CI_GATE_NEEDS);
* runs even when a shard failed, was cancelled or timed out (so main-red-alert still fires);
* on pull_request the FAST jobs are skipped and `cio-hardening` keeps the PR profile;
* the per-SHA push concurrency group and the alert wiring are unchanged.

The `if:` expressions are evaluated by a small interpreter for exactly the forms they use.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HARD = yaml.safe_load((ROOT / ".github/workflows/cio-production-hardening-ci.yml").read_text(encoding="utf-8"))
SHARD = yaml.safe_load((ROOT / ".github/workflows/cio-full-suite-sharded.yml").read_text(encoding="utf-8"))
JOBS = HARD["jobs"]
FAST = ("fast-shard", "fast-serial", "fast-pg", "fast-integrity")
AGG = JOBS["cio-hardening"]


def _eval(expr: str, ctx: dict) -> bool:
    """`(a == 'x' && !cancelled()) || (... && always())` with ==, !=, &&, ||, !cancelled(), always()."""
    expr = " ".join(str(expr).split())

    def sub(m: re.Match) -> str:
        v = ctx[m.group(1)]
        return repr((v == m.group(3)) if m.group(2) == "==" else (v != m.group(3)))

    py = re.sub(r"([\w.\-]+) (==|!=) '([^']*)'", sub, expr)
    py = py.replace("!cancelled()", repr(not ctx["cancelled"])).replace("always()", "True")
    py = py.replace("&&", " and ").replace("||", " or ")
    assert re.fullmatch(r"[\sA-Za-z()]*", py) and set(re.findall(r"[A-Za-z]+", py)) <= {"True", "False", "and", "or"}, py
    return bool(eval(py))  # noqa: S307 - the string is only True/False/and/or/parentheses


@pytest.mark.parametrize("job", FAST)
@pytest.mark.parametrize("event,runs", [("push", True), ("workflow_dispatch", True), ("pull_request", False),
                                        ("schedule", False)])
def test_fast_jobs_run_on_push_and_dispatch_only(job, event, runs):
    assert _eval(JOBS[job]["if"], {"github.event_name": event, "cancelled": False}) is runs
    assert JOBS[job]["timeout-minutes"] <= 20


def test_shard_matrix_matches_the_shard_count_and_the_runner_selectors():
    j = JOBS["fast-shard"]
    n = int(j["env"]["CIO_SHARDS"])
    assert j["strategy"]["matrix"]["shard"] == list(range(n)) and j["strategy"]["fail-fast"] is False
    assert n == int(SHARD["env"]["CIO_SHARDS"])
    for job, sel in (("fast-shard", '"$SHARD/$CIO_SHARDS"'), ("fast-serial", '"serial/$CIO_SHARDS"'),
                     ("fast-pg", '"pg/$CIO_SHARDS"')):
        runs = [s.get("run", "") for s in JOBS[job]["steps"]]
        assert any("scripts/run_cio_hardening_ci.py" in r and f"--shard {sel}" in r and "--shard-out" in r
                   for r in runs), job
        up = [s for s in JOBS[job]["steps"] if s.get("uses", "").startswith("actions/upload-artifact")]
        assert len(up) == 1 and up[0]["with"]["name"].startswith("cio-fast-shard-") and up[0]["if"] == "always()"
    assert JOBS["fast-pg"]["services"]["m2"]["image"] == SHARD["jobs"]["pg"]["services"]["m2"]["image"]


def test_the_required_context_is_one_job_and_no_job_claims_ci_gate():
    names = [j.get("name", jid) for jid, j in JOBS.items()]
    assert names.count("cio-hardening") == 1 and "name" not in AGG
    assert "ci-gate" not in names and "ci-gate" not in JOBS


def test_aggregate_needs_every_fast_job_and_verifies_the_manifests():
    assert set(AGG["needs"]) == set(FAST)
    steps = AGG["steps"]
    dl = next(s for s in steps if s.get("uses", "").startswith("actions/download-artifact"))
    assert dl["with"]["pattern"] == "cio-fast-shard-*" and dl["if"] == "github.event_name != 'pull_request'"
    gate = next(s for s in steps if "scripts/run_cio_hardening_ci.py" in s.get("run", ""))
    assert gate["env"]["CI_GATE_NEEDS"] == "${{ toJSON(needs) }}"
    assert '--profile pr --base "origin/$BASE_REF"' in gate["run"]
    n = JOBS["fast-shard"]["env"]["CIO_SHARDS"]
    assert f"--shards {n} --verify-shards" in gate["run"] and "--profile fast" not in gate["run"]
    assert steps.index(dl) < steps.index(gate)


@pytest.mark.parametrize("event,cancelled,runs", [
    ("pull_request", False, True),     # PR profile, FAST jobs skipped
    ("pull_request", True, False),     # a superseded PR run is never reported green
    ("push", False, True),
    ("push", True, True),              # a cancelled/timed-out shard still yields a red aggregate
    ("workflow_dispatch", False, True),
    ("schedule", False, False),
])
def test_aggregate_runs_whenever_a_verdict_is_owed(event, cancelled, runs):
    assert _eval(AGG["if"], {"github.event_name": event, "cancelled": cancelled}) is runs


def test_rails_after_the_gates_are_pr_only_in_the_aggregate_and_all_present_in_fast_integrity():
    steps = AGG["steps"]
    gate_i = next(i for i, s in enumerate(steps) if "scripts/run_cio_hardening_ci.py" in s.get("run", ""))
    rails = [s for s in steps[gate_i + 1:] if "cio-fast-shard-timings" not in str(s.get("with", {}))]
    assert rails
    for s in rails:
        assert "github.event_name == 'pull_request'" in s["if"], s["name"]
    integ = {s.get("name"): s for s in JOBS["fast-integrity"]["steps"]}
    for s in rails:
        assert s["name"] in integ, s["name"]
        if "run" in s:
            assert integ[s["name"]]["run"] == s["run"], s["name"]
    # everything the sharded workflow's integrity job runs, the FAST integrity job runs too
    runs = {s.get("run") for s in JOBS["fast-integrity"]["steps"]}
    for s in SHARD["jobs"]["integrity"]["steps"]:
        if "run" in s and "pip install" not in s["run"]:
            assert s["run"] in runs, s.get("name")


def test_alerting_and_concurrency_are_unchanged():
    assert set(JOBS["main-red-alert"]["needs"]) == {"cio-hardening", "cio-hardening-full"}
    assert "github.sha" in HARD["concurrency"]["group"]
    assert AGG["timeout-minutes"] <= 50
