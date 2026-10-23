"""cio-hardening split into parallel shards on every event (2026-10-23; supersedes #1943's push-only split).

Measured before (gh, 2026-10-23): the single `cio-hardening` job took 27-39 min on push to main and 28-38 min on the
release-batch PRs, one step ("CIO hardening gates") about 97% of it, and a release waited on it twice (PR, then the
exact-main push). It now reuses the cio-full-suite-sharded pattern on pull_request, push and dispatch: 8 shards +
serial + pg + integrity rails in parallel, and the required context `cio-hardening` keeps its name as the aggregate:

* green only when every job succeeded and the shard manifests prove each registered file ran exactly once on this
  tree and plan (run_cio_hardening_ci.py --verify-shards, CI_GATE_NEEDS); a registered file no shard ran fails it;
* on push it runs even when a shard failed, was cancelled or timed out (so main-red-alert still fires);
* a superseded PR run is never reported green; a draft PR runs nothing (push policy v2);
* every rail the single job ran after its gates, and the runner's tail checks, still run (in cio-integrity);
* the per-SHA push concurrency group and the alert wiring are unchanged; no job claims the `ci-gate` context.

The `if:` expressions are evaluated by a small interpreter for exactly the forms they use.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HARD_TEXT = (ROOT / ".github/workflows/cio-production-hardening-ci.yml").read_text(encoding="utf-8")
HARD = yaml.safe_load(HARD_TEXT)
SHARD = yaml.safe_load((ROOT / ".github/workflows/cio-full-suite-sharded.yml").read_text(encoding="utf-8"))
JOBS = HARD["jobs"]
PARTS = ("cio-shard", "cio-serial", "cio-pg", "cio-integrity")
AGG = JOBS["cio-hardening"]
N = int(HARD["env"]["CIO_SHARDS"])

#: Every rail the single `cio-hardening` job ran after its gates step (main at 98bef2794), plus the runner's tail
#: checks (run_cio_hardening_ci.py runs them after the gates in every profile; a shard runs no tail).
RAILS = (
    "python3 scripts/run_cio_adversarial_suite.py",
    "python3 scripts/check_dark_contracts.py --fail-on-new",
    "python3 scripts/check_retention_policy.py --fail-on-new",
    "python3 scripts/check_line_endings.py --range origin/main...HEAD",
    "python3 scripts/check_test_coverage.py --fail-on-new",
    "python3 scripts/check_test_host_paths.py --fail-on-new",
    "python3 scripts/report_docs_inventory.py --check-index",
    "python3 scripts/cio_release_manifest.py check-committed",
    'python3 scripts/cio_release_manifest.py candidate --out-dir "$RUNNER_TEMP/cio_manifest_candidate"',
)
SMOKES = ("Report HTML export smoke", "DOCX smoke (optional)", "PDF smoke (optional — needs chromium/weasyprint)")


def _eval(expr: str, ctx: dict) -> bool:
    """`(a == 'x' && !cancelled()) || (... && always())` with ==, !=, &&, ||, !cancelled(), always()."""
    expr = " ".join(str(expr).split())

    def sub(m: re.Match) -> str:
        v = ctx[m.group(1)]
        return repr((v == m.group(3)) if m.group(2) == "==" else (v != m.group(3)))

    py = re.sub(r"([\w.\-]+) (==|!=) '([^']*)'", sub, expr)
    py = re.sub(
        r"github\.event\.pull_request\.draft == (true|false)",
        lambda m: repr(ctx["draft"] == (m.group(1) == "true")),
        py,
    )
    py = py.replace("!cancelled()", repr(not ctx["cancelled"])).replace("always()", "True")
    py = py.replace("&&", " and ").replace("||", " or ")
    assert re.fullmatch(r"[\sA-Za-z()]*", py) and set(re.findall(r"[A-Za-z]+", py)) <= {"True", "False", "and", "or"}, (
        py
    )
    return bool(eval(py))  # noqa: S307 - the string is only True/False/and/or/parentheses


def _ctx(event: str, *, draft: bool = False, cancelled: bool = False) -> dict:
    return {"github.event_name": event, "draft": draft, "cancelled": cancelled}


def test_triggers_cover_ready_for_review_and_keep_push_and_dispatch():
    on = HARD.get(True, HARD.get("on"))
    assert on["push"] == {"branches": ["main"]}
    assert {"opened", "synchronize", "reopened", "ready_for_review"} <= set(on["pull_request"]["types"])
    assert "paths" not in on["pull_request"] and "paths-ignore" not in on["pull_request"]
    assert "workflow_dispatch" in on and "schedule" not in on


@pytest.mark.parametrize("job", PARTS)
@pytest.mark.parametrize(
    "ctx,runs",
    [
        (_ctx("push"), True),
        (_ctx("workflow_dispatch"), True),
        (_ctx("pull_request"), True),  # 2026-10-23: PRs are sharded too (release PRs took 28-38 min in one job)
        (_ctx("pull_request", draft=True), False),  # push policy v2: a draft runs none of the fleet
    ],
)
def test_parts_run_on_every_event_but_drafts(job, ctx, runs):
    assert _eval(JOBS[job]["if"], ctx) is runs
    assert JOBS[job]["timeout-minutes"] <= 20


def test_every_part_tests_the_pr_head_or_the_pushed_sha():
    assert HARD["env"]["TEST_SHA"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    for job in (*PARTS, "cio-hardening"):
        co = next(s for s in JOBS[job]["steps"] if s.get("uses", "").startswith("actions/checkout"))
        assert co["with"]["ref"] == "${{ env.TEST_SHA }}", job


def test_shard_matrix_matches_the_shard_count_and_the_runner_selectors():
    j = JOBS["cio-shard"]
    assert j["strategy"]["matrix"]["shard"] == list(range(N)) and j["strategy"]["fail-fast"] is False
    assert N == int(SHARD["env"]["CIO_SHARDS"])
    for job, sel in (
        ("cio-shard", '"$SHARD/$CIO_SHARDS"'),
        ("cio-serial", '"serial/$CIO_SHARDS"'),
        ("cio-pg", '"pg/$CIO_SHARDS"'),
    ):
        runs = [s.get("run", "") for s in JOBS[job]["steps"]]
        assert any(
            "scripts/run_cio_hardening_ci.py" in r and f"--shard {sel}" in r and "--shard-out" in r for r in runs
        ), job
        up = [s for s in JOBS[job]["steps"] if s.get("uses", "").startswith("actions/upload-artifact")]
        assert len(up) == 1 and up[0]["with"]["name"].startswith("cio-hardening-shard-") and up[0]["if"] == "always()"
        # agent_governance_sop needs the pinned Ruff: a missing one fails closed in every test job.
        install = "\n".join(runs)
        assert 'pip install pytest pyyaml requests "ruff==0.16.2"' in install and "PINNED_RUFF_VERSION" in install, job
    assert JOBS["cio-pg"]["services"]["m2"]["image"] == SHARD["jobs"]["pg"]["services"]["m2"]["image"]


def test_the_required_context_is_one_job_and_no_job_collides_with_another_context():
    names = [j.get("name", jid) for jid, j in JOBS.items()]
    assert names.count("cio-hardening") == 1 and "name" not in AGG
    assert "ci-gate" not in names and "ci-gate" not in JOBS
    # no part reuses a check name of the sharded workflow ("shard 0", "integrity rails", ...)
    sharded_names = {str(j.get("name", jid)).split("$")[0].strip() for jid, j in SHARD["jobs"].items()}
    for job in PARTS:
        assert str(JOBS[job]["name"]).split("$")[0].strip() not in sharded_names, job
        assert not str(JOBS[job]["name"]).startswith("cio-hardening"), job


def test_aggregate_needs_every_part_and_verifies_the_manifests():
    assert set(AGG["needs"]) == set(PARTS)
    steps = AGG["steps"]
    dl = next(s for s in steps if s.get("uses", "").startswith("actions/download-artifact"))
    assert dl["with"]["pattern"] == "cio-hardening-shard-*" and "if" not in dl
    gate = next(s for s in steps if "scripts/run_cio_hardening_ci.py" in s.get("run", ""))
    assert gate["env"]["CI_GATE_NEEDS"] == "${{ toJSON(needs) }}"
    assert '--shards "$CIO_SHARDS"' in gate["run"] and "--verify-shards" in gate["run"]
    assert "--profile" not in gate["run"]  # the aggregate runs no test itself
    assert steps.index(dl) < steps.index(gate)
    all_runs = [str(s.get("run", "")) for jid, j in JOBS.items() if jid != "cio-hardening-full" for s in j["steps"]]
    assert not any("--profile pr" in r or "--profile fast" in r for r in all_runs)


@pytest.mark.parametrize(
    "ctx,runs",
    [
        (_ctx("pull_request"), True),
        (_ctx("pull_request", cancelled=True), False),  # a superseded PR run is never reported green
        (_ctx("pull_request", draft=True), False),
        (_ctx("push"), True),
        (_ctx("push", cancelled=True), True),  # a cancelled/timed-out shard still yields a red aggregate
        (_ctx("workflow_dispatch"), True),
        (_ctx("schedule"), False),
    ],
)
def test_aggregate_runs_whenever_a_verdict_is_owed(ctx, runs):
    assert _eval(AGG["if"], ctx) is runs


def test_every_rail_of_the_single_job_still_runs_exactly_once():
    integ = JOBS["cio-integrity"]["steps"]
    runs = [str(s.get("run", "")).strip() for s in integ]
    for rail in RAILS:
        assert runs.count(rail) == 1, rail
        for job, j in JOBS.items():
            if job != "cio-integrity":
                assert all(rail not in str(s.get("run", "")) for s in j["steps"]), (job, rail)
    names = [s.get("name") for s in integ]
    for smoke in SMOKES:
        assert names.count(smoke) == 1, smoke
    ev = next(s for s in integ if s.get("name") == "Upload CIO CI evidence")
    assert ev["with"]["name"] == "cio-hardening-evidence" and ev["if"] == "always()"
    # everything the sharded workflow's integrity job runs, cio-integrity runs too
    for s in SHARD["jobs"]["integrity"]["steps"]:
        if "run" in s and "pip install" not in s["run"]:
            assert str(s["run"]).strip() in runs or s.get("name") in names, s.get("name")


def _manifest(shard: str, files: list[str], *, ok: bool = True) -> dict:
    from scripts.lib import ci_shards

    units = [{"files": files, "passed": ok}] if files else []
    return ci_shards.build_manifest(shard=shard, n=N, sha="s", tree="t", digest="d", files=files, units=units, wall=1.0)


def _plan_manifests() -> tuple[list[dict], list[str]]:
    from scripts import run_cio_hardening_ci as R
    from scripts.lib import ci_shards

    plan = R.shard_plan(N)
    manifests = [_manifest(sid, list(files)) for sid, files in plan["shards"].items()]
    expected = ci_shards.registered_files(R.GATES, lambda p: (ROOT / p).is_file())
    return manifests, expected


def test_the_real_plan_covers_every_registered_file_exactly_once():
    from scripts.lib import ci_shards

    manifests, expected = _plan_manifests()
    assert sorted(m["shard"] for m in manifests) == sorted(ci_shards.shard_ids(N))
    needs = {j: {"result": "success"} for j in PARTS}
    res = ci_shards.verify_manifests(manifests, expected_files=expected, n=N, needs=needs)
    assert res["ok"], res["errors"]
    assert res["ran_files"] == res["expected_files"] == len(expected) > 1000


@pytest.mark.parametrize("defect", ["missing_file", "duplicate_file", "missing_shard", "skipped_job", "failed_shard"])
def test_a_missing_or_doubled_gate_fails_the_aggregate(defect):
    from scripts.lib import ci_shards

    manifests, expected = _plan_manifests()
    needs = {j: {"result": "success"} for j in PARTS}
    if defect == "missing_file":
        m = next(m for m in manifests if m["files"])
        manifests[manifests.index(m)] = _manifest(m["shard"], m["files"][1:])
    elif defect == "duplicate_file":
        a, b = [m for m in manifests if m["files"]][:2]
        manifests[manifests.index(b)] = _manifest(b["shard"], b["files"] + a["files"][:1])
    elif defect == "missing_shard":
        manifests = manifests[1:]
    elif defect == "skipped_job":
        needs["cio-pg"] = {"result": "skipped"}
    elif defect == "failed_shard":
        m = next(m for m in manifests if m["files"])
        manifests[manifests.index(m)] = _manifest(m["shard"], m["files"], ok=False)
    res = ci_shards.verify_manifests(manifests, expected_files=expected, n=N, needs=needs)
    assert not res["ok"], defect


def test_alerting_and_concurrency_are_unchanged():
    assert set(JOBS["main-red-alert"]["needs"]) == {"cio-hardening", "cio-hardening-full"}
    assert "github.sha" in HARD["concurrency"]["group"]
    assert HARD["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    assert AGG["timeout-minutes"] <= 15
    assert JOBS["cio-hardening-full"]["if"] == "github.event_name == 'workflow_dispatch'"
