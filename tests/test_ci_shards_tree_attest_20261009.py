"""Sharded full suite + tree-attested promote (operator-approved 2026-10-09).

Hermetic: no network, no gh, no git subprocess, no pytest subprocess. The GitHub/git layer of the
tree attestation is a fake; the shard plan is computed over the real GATES list but with
injected weights/classifiers where a property is being proven.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import ci_shards  # noqa: E402
from scripts.lib import tree_attested_promote as tap  # noqa: E402

# ---------------------------------------------------------------------------
# Shard assignment
# ---------------------------------------------------------------------------

GATES = [
    ("g1", ["tests/a.py", "tests/b.py", "tests/c.py", "tests/db1.py"]),
    ("g2", ["tests/b.py", "tests/d.py", "tests/serial1.py", "tests/gone.py"]),
    ("g3", ["tests/e.py", "tests/f.py", "tests/g.py", "tests/h.py", "tests/i.py"]),
]
WEIGHTS = {"tests/a.py": 50.0, "tests/b.py": 30.0, "tests/c.py": 20.0, "tests/d.py": 10.0, "tests/e.py": 9.0}


def _plan(n, gates=GATES, weights=WEIGHTS):
    return ci_shards.plan_shards(
        gates,
        n=n,
        weight=lambda p: weights.get(p, 1.0),
        needs_serial=lambda p: "serial" in p,
        needs_db=lambda p: "db" in p,
        exists=lambda p: "gone" not in p,
    )


def test_plan_is_complete_and_disjoint():
    plan = _plan(3)
    every = [f for fs in plan["shards"].values() for f in fs]
    assert len(every) == len(set(every)), "a file is in two shards"
    assert set(every) == set(ci_shards.registered_files(GATES, lambda p: "gone" not in p))
    assert "tests/gone.py" not in every
    assert plan["shards"]["pg"] == ["tests/db1.py"]
    assert plan["shards"]["serial"] == ["tests/serial1.py"]
    assert set(plan["shards"]) == set(ci_shards.shard_ids(3))


def test_plan_is_deterministic_under_input_order():
    a = _plan(3)
    shuffled = [(n, list(reversed(ps))) for n, ps in reversed(GATES)]
    b = _plan(3, gates=shuffled)
    assert a["shards"] == b["shards"]
    assert a["digest"] == b["digest"] == _plan(3)["digest"]


def test_lpt_balanced_within_largest_item():
    rng = random.Random(20261009)
    files = [f"tests/t{i:03d}.py" for i in range(300)]
    w = {f: round(rng.uniform(0.5, 40.0), 1) for f in files}
    for n in (2, 5, 8, 13):
        shards = ci_shards.assign_lpt(files, w.__getitem__, n)
        loads = [sum(w[f] for f in s) for s in shards]
        # Greedy list scheduling: no two loads differ by more than the heaviest item.
        assert max(loads) - min(loads) <= max(w.values()) + 1e-9
        # ... and here, with many small items, within 5% of the mean.
        assert max(loads) <= (sum(loads) / n) * 1.05
        assert sorted(f for s in shards for f in s) == sorted(files)


def test_real_gates_plan_complete_and_balanced():
    import run_cio_hardening_ci as runner

    plan = runner.shard_plan(8)
    every = [f for fs in plan["shards"].values() for f in fs]
    expected = ci_shards.registered_files(runner.GATES, lambda p: (ROOT / p).is_file())
    assert len(every) == len(set(every)) == len(expected)
    assert set(every) == set(expected)
    hints = runner.shard_hints()
    top = max(hints.get(f, 1.0) for f in every)
    numeric = [plan["loads"][str(i)] for i in range(8)]
    assert max(numeric) - min(numeric) <= top + 1e-6
    # Every serial-classified file is out of the parallel shards.
    for i in range(8):
        assert not any(runner.file_needs_serial(f) for f in plan["shards"][str(i)])
    assert runner.shard_plan(8)["digest"] == plan["digest"]


def test_db_classifier_matches_known_postgres_tests():
    assert ci_shards.source_needs_db("def test(m2_conn): ...")
    assert ci_shards.source_needs_db('psycopg2 = pytest.importorskip("psycopg2")')
    assert ci_shards.source_needs_db('DSN = os.getenv("ALERT_TEST_DSN", "x")')
    assert not ci_shards.source_needs_db("import json\nassert m2_connection_count == 0")


@pytest.mark.parametrize(
    "arg,want", [("3/8", ("3", 8)), ("serial/8", ("serial", 8)), ("pg/2", ("pg", 2)), ("07/8", ("7", 8))]
)
def test_parse_shard_arg(arg, want):
    assert ci_shards.parse_shard_arg(arg) == want


@pytest.mark.parametrize("arg", ["8/8", "x/8", "1", "1/0", ""])
def test_parse_shard_arg_rejects(arg):
    with pytest.raises(ValueError):
        ci_shards.parse_shard_arg(arg)


def test_gates_for_files_dedupes_to_first_gate():
    g = ci_shards.gates_for_files(GATES, ["tests/b.py", "tests/d.py"])
    assert g == [("g1", ["tests/b.py"]), ("g2", ["tests/d.py"])]


def test_file_seconds_from_junit():
    xml = (
        '<testsuites><testsuite><testcase classname="tests.test_x.TestA" name="a" time="2.0"/>'
        '<testcase classname="tests.test_x" name="b" time="1.0"/>'
        '<testcase file="tests/test_y.py" classname="whatever" name="c" time="3.0"/></testsuite></testsuites>'
    )
    out = ci_shards.file_seconds_from_junit(xml, ["tests/test_x.py", "tests/test_y.py"], wall=8.0)
    assert out == {"tests/test_x.py": 4.0, "tests/test_y.py": 4.0}
    assert ci_shards.file_seconds_from_junit("<<bad", ["a", "b"], wall=4.0) == {"a": 2.0, "b": 2.0}


# ---------------------------------------------------------------------------
# Aggregate completeness check
# ---------------------------------------------------------------------------


def _manifests(plan, *, tree="T", ok=True):
    out = []
    for sid, files in plan["shards"].items():
        units = [{"gate": "g", "files": list(files), "passed": ok, "rc": 0 if ok else 1}] if files else []
        out.append(
            ci_shards.build_manifest(
                shard=sid,
                n=plan["n"],
                sha="s" * 40,
                tree=tree,
                digest=plan["digest"],
                files=files,
                units=units,
                wall=1.0,
            )
        )
    return out


def _verify(ms, plan, **kw):
    expected = ci_shards.registered_files(GATES, lambda p: "gone" not in p)
    return ci_shards.verify_manifests(
        ms, expected_files=expected, n=plan["n"], expected_tree="T", expected_digest=plan["digest"], **kw
    )


def test_verify_passes_on_complete_green_shards():
    plan = _plan(3)
    res = _verify(_manifests(plan), plan, needs={"shard": {"result": "success"}, "pg": {"result": "success"}})
    assert res["ok"], res["errors"]
    assert res["ran_files"] == res["expected_files"]


def test_verify_fails_on_missing_shard_and_missing_files():
    plan = _plan(3)
    ms = [m for m in _manifests(plan) if m["shard"] != "1"]
    res = _verify(ms, plan)
    assert not res["ok"]
    assert "missing_shard:1" in res["errors"]
    assert set(res["missing_files"]) == set(plan["shards"]["1"])


def test_verify_fails_on_duplicate_and_unregistered_file():
    plan = _plan(3)
    ms = _manifests(plan)
    dup = plan["shards"]["0"][0]
    ms[1]["files"] = ms[1]["files"] + [dup, "tests/rogue.py"]
    ms[1]["planned_files"] = list(ms[1]["files"])
    res = _verify(ms, plan)
    assert not res["ok"]
    assert dup in res["duplicate_files"]
    assert res["extra_files"] == ["tests/rogue.py"]


def test_verify_fails_on_failed_unit_tree_digest_and_job():
    plan = _plan(3)
    ms = _manifests(plan)
    ms[0]["units"][0]["passed"] = False
    res = _verify(ms, plan)
    assert "failed_shard:" + ms[0]["shard"] in res["errors"]

    res = _verify(_manifests(plan, tree="OTHER"), plan)
    assert any(e.startswith("tree_mismatch:") for e in res["errors"])

    ms = _manifests(plan)
    ms[2]["plan_digest"] = "x"
    assert any(e.startswith("plan_digest_mismatch:") for e in _verify(ms, plan)["errors"])

    res = _verify(_manifests(plan), plan, needs={"integrity": {"result": "failure"}, "pg": {"result": "skipped"}})
    assert "job_not_successful:integrity:failure" in res["errors"]
    assert "job_not_successful:pg:skipped" in res["errors"]


def test_verify_fails_when_shard_ran_other_than_planned():
    plan = _plan(3)
    ms = _manifests(plan)
    ms[0]["files"] = ms[0]["files"][1:]
    res = _verify(ms, plan)
    assert f"ran_not_planned:{ms[0]['shard']}" in res["errors"]
    assert not res["ok"]


def test_merge_timings_takes_max_per_file():
    t = ci_shards.merge_timings([{"file_seconds": {"a": 1.0, "b": 2.0}}, {"file_seconds": {"a": 3.04}}])
    assert t["schema"] == ci_shards.TIMINGS_SCHEMA
    assert t["files"] == {"a": 3.0, "b": 2.0}


def test_shard_hints_file_is_a_complete_seed():
    doc = json.loads((ROOT / "config" / "ci_shard_duration_hints.json").read_text(encoding="utf-8"))
    assert doc["schema"] == ci_shards.TIMINGS_SCHEMA
    assert all(isinstance(v, (int, float)) and v >= 0 for v in doc["files"].values())


# ---------------------------------------------------------------------------
# Tree-attested promote (fake gh/git layer)
# ---------------------------------------------------------------------------

M = "a" * 40
H = "b" * 40
REPO = "owner/repo"
TREE = "c" * 40


class FakeIO:
    def __init__(self):
        self.trees = {M: TREE, H: TREE}
        self.objects = {(sha, p): f"obj-{p}" for sha in (M, H) for p in tap.WATCHED_PATHS}
        self.pulls = [
            {
                "number": 77,
                "merge_commit_sha": M,
                "merged_at": "2026-10-09T00:00:00Z",
                "base": {"ref": "main"},
                "head": {"sha": H},
            }
        ]
        self.protection = {"contexts": ["cio-hardening", "agent-governance"], "checks": []}
        self.checks = [
            self._check(1, "cio-hardening"),
            self._check(2, "agent-governance"),
            self._check(3, "ci-gate", suite=900),
        ]
        self.runs = [
            {
                "id": 5001,
                "run_number": 12,
                "run_attempt": 1,
                "path": tap.SHARDED_WORKFLOW,
                "head_sha": H,
                "check_suite_id": 900,
                "status": "completed",
                "conclusion": "success",
            }
        ]
        self.attestation = {"schema": tap.ATTESTATION_SCHEMA, "head_sha": H, "tested_tree": TREE, "ok": True}
        self.calls = []
        self.fail_gh = False

    @staticmethod
    def _check(i, name, *, conclusion="success", status="completed", suite=None, app="github-actions"):
        return {
            "id": i,
            "name": name,
            "head_sha": H,
            "status": status,
            "conclusion": conclusion,
            "app": {"slug": app},
            "check_suite": {"id": suite or 100 + i},
        }

    def gh_pages(self, endpoint):
        self.calls.append(endpoint)
        if self.fail_gh:
            raise tap.Unavailable("gh_api_failed")
        if endpoint.startswith(f"repos/{REPO}/commits/{M}/pulls"):
            return [self.pulls]
        if endpoint.endswith("/protection/required_status_checks"):
            return [self.protection]
        if endpoint.startswith(f"repos/{REPO}/commits/{H}/check-runs"):
            return [{"check_runs": self.checks}]
        if endpoint.startswith(f"repos/{REPO}/actions/runs?head_sha={H}"):
            return [{"workflow_runs": self.runs}]
        raise AssertionError("unexpected endpoint " + endpoint)

    def git(self, *args):
        assert args[0] == "rev-parse"
        ref = args[1]
        if ref.endswith("^{tree}"):
            sha = ref[: -len("^{tree}")]
            if sha not in self.trees:
                raise tap.Unavailable("git_failed")
            return self.trees[sha]
        if ref == f"{M}^2":
            return H
        sha, _, path = ref.partition(":")
        if (sha, path) not in self.objects:
            raise tap.Unavailable("git_failed")
        return self.objects[(sha, path)]

    def download_attestation(self, repo, run_id):
        assert run_id == 5001
        return self.attestation


def test_attest_passes_when_tree_equal_and_checks_green():
    io = FakeIO()
    ev = tap.attest(M, repo=REPO, io=io)
    assert ev["ok"], ev["reasons"]
    assert ev["pr"] == 77 and ev["head_sha"] == H and ev["tree"] == TREE
    assert ev["check_run_ids"] == {"agent-governance": 2, "cio-hardening": 1, "ci-gate": 3}
    assert ev["workflow_run_id"] == 5001
    assert ev["candidate_sha"] == M  # deploy receipt embeds evidence keyed on this


def test_tree_differs_falls_back():
    io = FakeIO()
    io.trees[H] = "d" * 40
    ev = tap.attest(M, repo=REPO, io=io)
    assert not ev["ok"] and "tree_differs" in ev["reasons"]
    assert "attestation_tree_mismatch" not in ev["reasons"]  # attested tree == merge tree here


def test_workflow_file_differs_falls_back():
    io = FakeIO()
    io.objects[(H, ".github/workflows")] = "other"
    ev = tap.attest(M, repo=REPO, io=io)
    assert "watched_path_differs:.github/workflows" in ev["reasons"]


@pytest.mark.parametrize("name", ["ci-gate", "agent-governance", "cio-hardening"])
def test_required_check_failed_falls_back(name):
    io = FakeIO()
    for c in io.checks:
        if c["name"] == name:
            c["conclusion"] = "failure"
    ev = tap.attest(M, repo=REPO, io=io)
    assert not ev["ok"] and f"check_not_successful:{name}" in ev["reasons"]


def test_check_missing_or_pending_falls_back():
    io = FakeIO()
    io.checks = [c for c in io.checks if c["name"] != "ci-gate"]
    assert "check_missing:ci-gate" in tap.attest(M, repo=REPO, io=io)["reasons"]

    io = FakeIO()
    io.checks[0]["status"] = "in_progress"
    io.checks[0]["conclusion"] = None
    assert "check_not_successful:cio-hardening" in tap.attest(M, repo=REPO, io=io)["reasons"]


def test_newer_failed_rerun_supersedes_old_success():
    io = FakeIO()
    io.checks.append(FakeIO._check(9, "ci-gate", conclusion="failure", suite=901))
    ev = tap.attest(M, repo=REPO, io=io)
    assert "check_not_successful:ci-gate" in ev["reasons"]


def test_check_from_non_actions_app_is_ignored():
    io = FakeIO()
    io.checks = [c for c in io.checks if c["name"] != "ci-gate"]
    io.checks.append(FakeIO._check(10, "ci-gate", app="some-other-app", suite=900))
    assert "check_missing:ci-gate" in tap.attest(M, repo=REPO, io=io)["reasons"]


def test_extra_required_context_from_protection_is_enforced():
    io = FakeIO()
    io.protection = {"contexts": ["cio-hardening"], "checks": [{"context": "frontend"}]}
    assert "check_missing:frontend" in tap.attest(M, repo=REPO, io=io)["reasons"]


def test_attestation_missing_or_wrong_tree_falls_back():
    io = FakeIO()
    io.attestation = None
    assert "attestation_missing" in tap.attest(M, repo=REPO, io=io)["reasons"]

    io = FakeIO()
    io.attestation = dict(io.attestation, tested_tree="e" * 40)
    assert "attestation_tree_mismatch" in tap.attest(M, repo=REPO, io=io)["reasons"]


def test_superseded_workflow_run_falls_back():
    io = FakeIO()
    io.runs.append(dict(io.runs[0], id=5002, run_number=13, check_suite_id=901, conclusion="failure"))
    assert "aggregate_run_superseded" in tap.attest(M, repo=REPO, io=io)["reasons"]


def test_pr_not_found_and_gh_unavailable_fall_back():
    io = FakeIO()
    io.pulls = []
    assert tap.attest(M, repo=REPO, io=io)["reasons"] == ["pr_not_found"]

    io = FakeIO()
    io.fail_gh = True
    ev = tap.attest(M, repo=REPO, io=io)
    assert not ev["ok"] and ev["reasons"][0].startswith("unavailable:")

    assert tap.attest("abc", repo=REPO, io=FakeIO())["reasons"] == ["candidate_sha_must_be_full"]


def test_flag_default_off():
    assert not tap.flag_enabled({})
    assert not tap.flag_enabled({tap.FLAG_ENV: "0"})
    assert not tap.flag_enabled({tap.FLAG_ENV: "true"})
    assert tap.flag_enabled({tap.FLAG_ENV: "1"})


# ---------------------------------------------------------------------------
# Preflight wiring (release_grant_preflight.collect_ci_evidence / backstop)
# ---------------------------------------------------------------------------


def _push_ok(sha):
    return {"ok": True, "candidate_sha": sha, "checks": [], "errors": [], "mode_marker": "push"}


def test_preflight_flag_off_never_attests():
    import release_grant_preflight as pf

    def boom(_sha):
        raise AssertionError("attestation must not run with the flag off")

    ev = pf.collect_ci_evidence(M, env={}, attest=boom, push=_push_ok)
    assert ev["mode_marker"] == "push"


def test_preflight_flag_on_attested_skips_main_wait():
    import release_grant_preflight as pf

    def no_push(_sha):
        raise AssertionError("push/main evidence must not be awaited when the tree is attested")

    ev = pf.collect_ci_evidence(
        M, env={tap.FLAG_ENV: "1"}, attest=lambda s: tap.attest(s, repo=REPO, io=FakeIO()), push=no_push
    )
    assert ev["ok"] and ev["mode"] == "tree_attested" and ev["pr"] == 77


def test_preflight_flag_on_unproven_falls_back_with_reasons():
    import release_grant_preflight as pf

    io = FakeIO()
    io.trees[H] = "d" * 40
    ev = pf.collect_ci_evidence(
        M, env={tap.FLAG_ENV: "1"}, attest=lambda s: tap.attest(s, repo=REPO, io=io), push=_push_ok
    )
    assert ev["mode_marker"] == "push"
    assert "tree_differs" in ev["tree_attested_fallback"]["reasons"]


@pytest.mark.parametrize(
    "evidence,status,rc",
    [
        ({"ok": True}, "green", 0),
        ({"ok": False, "errors": ["missing:x"], "checks": []}, "pending", 2),
        ({"ok": False, "errors": ["not_successful:x"], "checks": [{"status": "in_progress"}]}, "pending", 2),
        (
            {"ok": False, "errors": ["not_successful:x"], "checks": [{"status": "completed", "conclusion": "failure"}]},
            "red",
            3,
        ),
        ({"ok": False, "errors": ["checks_unavailable:OSError"], "checks": []}, "unavailable", 2),
    ],
)
def test_backstop_status_and_receipt(tmp_path, evidence, status, rc):
    import release_grant_preflight as pf

    assert tap.backstop_status(evidence) == (status, rc)
    receipt = tmp_path / "backstop.json"
    assert pf.backstop_check(M, receipt, push=lambda _s: dict(evidence)) == rc
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["status"] == status and body["candidate_sha"] == M and body["exit_code"] == rc


# ---------------------------------------------------------------------------
# pg shard: one fresh database per file for the per-file DSN env vars
# ---------------------------------------------------------------------------


def test_per_file_db_env_repoints_alert_dsn_to_fresh_test_database(monkeypatch):
    import subprocess as sp

    import run_cio_hardening_ci as runner

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setenv("ALERT_TEST_DSN", "postgresql://u:p@127.0.0.1:55432/m2_shadow_test_alerts")
    env = runner._per_file_db_env("tests/test_x.py", 3)
    assert env["ALERT_TEST_DSN"].endswith("/m2_shadow_test_alerts_f3")
    assert calls and calls[0][-2:] == ["--name", "m2_shadow_test_alerts_f3"]


def test_per_file_db_env_leaves_non_test_database_alone(monkeypatch):
    import run_cio_hardening_ci as runner

    def boom(*a, **k):
        raise AssertionError("must not create a database outside the m2_shadow_test pattern")

    monkeypatch.setattr(runner.subprocess, "run", boom)
    monkeypatch.setenv("ALERT_TEST_DSN", "postgresql://u:p@127.0.0.1:55435/delivtest")
    assert runner._per_file_db_env("tests/test_x.py", 0) is None
    monkeypatch.delenv("ALERT_TEST_DSN")
    assert runner._per_file_db_env("tests/test_x.py", 0) is None
