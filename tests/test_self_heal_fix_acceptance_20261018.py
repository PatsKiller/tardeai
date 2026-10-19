"""Repair qualification regressions. External effects are temporary fixtures only."""

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import self_heal_fix_evaluator as E
from scripts.lib import self_heal_fixer as F
from scripts import self_heal_fixer as S

SHA = "a" * 40
POLICY = {
    "schema": "SelfHealCiAcceptancePolicy@v1",
    "version": "2026-10-18.1",
    "required_checks": ["cio-hardening", "agent-governance", "release-readiness"],
}
NOW = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)


def rollup(conclusion="SUCCESS", names=("mandatory",)):
    return [{"name": name, "status": "COMPLETED", "conclusion": conclusion} for name in names]


def test_required_checks_cannot_be_empty():
    assert E.pr_head_verdict({"headRefOid": SHA, "statusCheckRollup": rollup()}, expected_head=SHA)["verdict"] != "pass"


@pytest.mark.parametrize("conclusion", ["SKIPPED", "NEUTRAL"])
def test_mandatory_check_must_succeed(conclusion):
    assert (
        E.pr_head_verdict(
            {"headRefOid": SHA, "statusCheckRollup": rollup(conclusion)}, expected_head=SHA, required=["mandatory"]
        )["verdict"]
        != "pass"
    )


def test_short_equal_heads_do_not_identify_candidate():
    short = SHA[:12]
    assert (
        E.pr_head_verdict(
            {"headRefOid": short, "statusCheckRollup": rollup()}, expected_head=short, required=["mandatory"]
        )["verdict"]
        != "pass"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"result":"complete"}',
        '{"total_cost_usd":null}',
        '{"total_cost_usd":"bad"}',
        '{"total_cost_usd":-1}',
        '{"total_cost_usd":true}',
        '{"total_cost_usd":NaN}',
    ],
)
def test_unknown_or_invalid_provider_cost_stays_unknown(raw):
    # A parser exception is not the contract: unknown cost must be a typed result.
    try:
        cost = F.parse_claude_result(raw)["cost_usd"]
    except (ValueError, TypeError):
        cost = "parser_exception"
    assert cost is None


def test_ci_rejection_blocks_deployment_even_with_merged_ancestor(tmp_path, monkeypatch):
    release = tmp_path / "sha"
    release.write_text("c" * 40)
    job = {
        "state": F.FIX_PR_OPENED,
        "lane": "safe-canary",
        "pr_number": 1,
        "head_sha": SHA,
        "deadline_at": "2026-10-18T22:00:00+00:00",
        "history": [],
        "iterations": [{"passed": True, "acceptance": {"accepted": True, "commit_sha": SHA}}],
    }
    doc = {
        "state": "MERGED",
        "mergeCommit": {"oid": "b" * 40},
        "headRefOid": SHA,
        "statusCheckRollup": rollup("FAILURE", POLICY["required_checks"]),
    }
    monkeypatch.setattr(S, "git", lambda *a, **k: {"rc": 0, "out": "", "err": ""})
    result = S.advance(
        job,
        cfg={"acceptance": POLICY, "lifecycle": {"release_current_sha_file": str(release)}},
        now=NOW,
        diag_state={},
        root=tmp_path,
        repo=tmp_path,
        gh=lambda *a: {"rc": 0, "out": json.dumps(doc), "err": ""},
    )
    assert job["acceptance"]["accepted"] is False
    assert result is None and job["state"] == F.FIX_PR_OPENED


def test_previous_rejection_blocks_output_recovery(tmp_path, monkeypatch):
    job = {
        "state": F.FIX_DEPLOYED,
        "lane": "safe-canary",
        "head_sha": SHA,
        "history": [],
        "acceptance": {"accepted": False},
        "deployed_at": NOW.isoformat(),
        "deadline_at": "2026-10-18T22:00:00+00:00",
    }
    monkeypatch.setattr(
        S, "output_recovered", lambda *a: {"recovered": True, "run_id": "fresh", "finished_at": NOW.isoformat()}
    )
    result = S.advance(
        job,
        cfg={"acceptance": POLICY, "intake": {"ledger_rel": "ledger"}},
        now=NOW,
        diag_state={},
        root=tmp_path,
        repo=tmp_path,
        gh=lambda *a: {},
    )
    assert result is None and job["state"] == F.FIX_DEPLOYED


def test_collection_error_is_not_red_first():
    cand = {"commit_sha": SHA, "tree_sha": "d" * 40, "base_sha": "b" * 40}
    runs = [
        {
            "kind": kind,
            "run_id": kind,
            "checkout_sha": cand["base_sha"] if kind == "red_first" else SHA,
            "head_after": cand["base_sha"] if kind == "red_first" else SHA,
            "overlay_from": SHA if kind == "red_first" else None,
            "integrity_ok": True,
            "rc": 2 if kind == "red_first" else 0,
        }
        for kind in E.REQUIRED_RUNS
    ]
    fact = {
        "tests_run": ["tests/test_safe.py"],
        "red_first": True,
        "targeted_rc": 0,
        "ci_rc": 0,
        "refusals": [],
        "candidate": cand,
        "guard": {"tree_sha": cand["tree_sha"]},
        "test_runs": runs,
    }
    assert E.local_verdict(fact)["accepted"] is False


def test_subprocess_is_bounded_by_absolute_job_deadline(tmp_path, monkeypatch):
    marker = tmp_path / "late-effect"

    class SlowSetup:
        def __init__(self, *args, **kwargs):
            self.branch = "safe"
            self.fix_wt = tmp_path / "wt"
            self.eval_root = tmp_path / "eval"

        def setup(self):
            S.run(
                [
                    sys.executable,
                    "-c",
                    "import time; from pathlib import Path; time.sleep(.25); Path("
                    + repr(str(marker))
                    + ').write_text("late")',
                ],
                timeout=5,
            )
            return "setup_stopped"

        def teardown(self, **kwargs):
            pass

    monkeypatch.setattr(S, "Attempt", SlowSetup)
    cfg = {"iteration": {"max_minutes": 0.001}}
    job = {"state": F.FIX_REQUESTED, "history": [], "iterations": [], "cost_usd": 0}
    S.attempt_job(
        job, {}, cfg=cfg, environ={}, now=lambda: NOW, evidence_dir=tmp_path, may_push=False, rails="", backend="test"
    )
    assert not marker.exists(), "subprocess performed work after absolute job deadline"


def verdict(doc, required=None, version="2026-10-18.1", head=SHA):
    return E.pr_head_verdict(
        doc, expected_head=head, required=required or POLICY["required_checks"], policy_version=version
    )


def test_named_versioned_policy_exact_head_success_and_missing_checks():
    doc = {"headRefOid": SHA, "statusCheckRollup": rollup(names=POLICY["required_checks"])}
    assert verdict(doc)["verdict"] == "pass"
    assert verdict(doc, version=None)["verdict"] == "policy_unavailable"
    assert verdict(doc, head=SHA[:12])["verdict"] == "head_moved"
    for name in POLICY["required_checks"]:
        missing = copy.deepcopy(doc)
        missing["statusCheckRollup"] = [c for c in missing["statusCheckRollup"] if c["name"] != name]
        assert verdict(missing)["missing_required"] == [name]
        assert verdict(missing)["verdict"] != "pass"
    assert not E.ci_policy({**POLICY, "required_checks": []})["valid"]
    assert not E.ci_policy({**POLICY, "required_checks": ["ci", "ci"]})["valid"]


@pytest.mark.parametrize("conclusion", ["SKIPPED", "NEUTRAL", "FAILURE", "CANCELLED", None])
def test_versioned_mandatory_check_non_success_is_held(conclusion):
    doc = {"headRefOid": SHA, "statusCheckRollup": rollup(names=POLICY["required_checks"])}
    doc["statusCheckRollup"][0]["conclusion"] = conclusion
    assert verdict(doc)["verdict"] != "pass"


def test_duplicate_context_cannot_hide_failure_or_pending():
    for state in ["FAILURE", None]:
        doc = {"headRefOid": SHA, "statusCheckRollup": rollup(state) + rollup()}
        assert verdict(doc, ["mandatory"])["verdict"] != "pass"


@pytest.mark.parametrize("value", [0, 0.25, 2])
def test_explicit_finite_cost_is_known(value):
    result = F.parse_claude_result(json.dumps({"total_cost_usd": value}))
    assert result["cost_usd"] == value and result["cost_status"] == "known"


def test_unknown_cost_retains_reservation_and_known_lower_bound(tmp_path):
    from scripts.lib import self_heal_fixer_claims as C

    db = tmp_path / "claims.sqlite"
    cid, _ = C.claim(
        db,
        dedupe_key="safe",
        job_id="j",
        day="2026-10-18",
        reserve_iterations=3,
        reserve_usd=12,
        reserve_seconds=60,
        lease_ttl_s=60,
        daily_job_cap=2,
        daily_usd_cap=24,
    )
    assert cid
    C.record_progress(db, cid, iterations_done=1, spent_usd=0.75)
    C.record_progress(db, cid, iterations_done=2, spent_usd=None)
    assert C.settle(db, cid, outcome="fix_failed", spent_usd=None, iterations_done=2)
    row = C.rows(db)[0]
    assert row["state"] == C.INTERRUPTED and row["outcome"] == "cost_unknown" and row["spent_usd"] == 0.75
    assert C.day_usage(db, "2026-10-18")["usd"] == 12
    assert not C.settle(db, cid, outcome="fake", spent_usd=0, iterations_done=0)


def test_deadline_kills_descendant_and_refuses_next_spawn(tmp_path):
    import time

    marker = tmp_path / "descendant"
    child = "import time; from pathlib import Path; time.sleep(.25); Path(" + repr(str(marker)) + ').write_text("late")'
    parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(child) + "]); time.sleep(5)"
    token = S._DEADLINE.set(time.monotonic() + 0.05)
    try:
        assert S.run([sys.executable, "-c", parent], timeout=5)["rc"] == 124
        assert (
            S.run([sys.executable, "-c", "from pathlib import Path; Path(" + repr(str(marker)) + ").touch()"])["rc"]
            == 124
        )
    finally:
        S._DEADLINE.reset(token)
    time.sleep(0.3)
    assert not marker.exists()


def test_junit_collection_error_runtime_error_and_assertion_are_distinct(tmp_path):
    report = tmp_path / "result.xml"
    report.write_text(
        '<testsuite><testcase classname="tests.safe" name="test_ok"/><testcase name="collect"><error>collection failed</error></testcase></testsuite>'
    )
    proof = S.pytest_proof(report)
    assert proof["errors"] == 1 and proof["assertion_failures"] == []
    report.write_text(
        '<testsuite><testcase classname="tests.safe" name="test_expected"><failure message="assert 0 == 1">AssertionError</failure></testcase><testcase name="oops"><failure>RuntimeError</failure></testcase></testsuite>'
    )
    proof = S.pytest_proof(report)
    assert proof["assertion_failures"] == ["tests.safe::test_expected"] and len(proof["report_sha256"]) == 64


def test_legacy_acceptance_requires_requalification_and_cannot_ship():
    pr = verdict({"headRefOid": SHA, "statusCheckRollup": rollup(names=POLICY["required_checks"])})
    legacy = {"schema": "SelfHealLocalAcceptance@v1", "accepted": True, "commit_sha": SHA, "tree_sha": "b" * 40}
    assert not E.final_acceptance(legacy, pr)["accepted"]
    assert not E.ship_verdict(legacy, commit_sha=SHA, tree_sha="b" * 40, prepush_refusals=[])["accepted"]
    assert not E.accepted_for_policy({"schema": "SelfHealAcceptance@v1", "accepted": True}, POLICY, SHA)


@pytest.mark.parametrize("deadline", [None, "", "malformed", "2026-10-18T22:00:00"])
def test_unavailable_or_naive_lifecycle_deadline_is_held(deadline, tmp_path):
    calls = []
    job = {"state": F.FIX_READY_LOCAL, "branch": "safe", "deadline_at": deadline}
    assert (
        S.advance(
            job,
            cfg={},
            now=NOW,
            diag_state={},
            root=tmp_path,
            repo=tmp_path,
            gh=lambda args: calls.append(args) or {"rc": 0, "out": "[]"},
        )
        is None
    )
    assert calls == [] and job["deadline_hold"] == "absolute_job_deadline_unavailable"


def test_lifecycle_transport_receives_remaining_absolute_budget(tmp_path):
    import time

    marker = tmp_path / "late"
    job = {"state": F.FIX_READY_LOCAL, "branch": "safe", "deadline_at": "2026-10-18T18:00:00.050000+00:00"}

    def gh(args):
        return S.run(
            [
                sys.executable,
                "-c",
                "import time; from pathlib import Path; time.sleep(.25); Path(" + repr(str(marker)) + ").touch()",
            ],
            timeout=5,
        )

    assert S.advance(job, cfg={}, now=NOW, diag_state={}, root=tmp_path, repo=tmp_path, gh=gh) is None
    assert not marker.exists()


@pytest.mark.parametrize("conclusion", ["SKIPPED", "NEUTRAL"])
def test_optional_nonmandatory_context_does_not_veto_three_required_successes(conclusion):
    doc = {
        "headRefOid": SHA,
        "statusCheckRollup": rollup(names=POLICY["required_checks"]) + rollup(conclusion, ["cio-hardening-full"]),
    }
    result = verdict(doc)
    assert result["verdict"] == "pass" and result["nonmandatory_checks"] == ["cio-hardening-full"]
    doc["statusCheckRollup"].append(rollup(conclusion, [POLICY["required_checks"][0]])[0])
    assert verdict(doc)["verdict"] != "pass", "duplicate mandatory skip cannot be hidden behind success"


@pytest.mark.parametrize("status,conclusion", [("COMPLETED", "FAILURE"), ("IN_PROGRESS", None)])
def test_optional_failed_or_applicable_pending_check_still_blocks(status, conclusion):
    doc = {
        "headRefOid": SHA,
        "statusCheckRollup": rollup(names=POLICY["required_checks"])
        + [{"name": "extra-tests", "status": status, "conclusion": conclusion}],
    }
    assert verdict(doc)["verdict"] != "pass"
