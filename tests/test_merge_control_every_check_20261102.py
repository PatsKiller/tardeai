"""Every check on the exact head gates a merge (held merge-control PR + plan item 6, 2026-11-02).

Collision A: PR #2465 merged with `secret-scan` red on four heads because the merge paths read only
the four branch-protection checks; `main` went red at f96c6399f and the deploy poller refused to
promote. Collision E: Mergify's `update` action pushed main into an approved, already-green PR and
restarted the ~30-minute suite each time.

These tests hold the three merge paths to one rule — EVERY non-skipped check run on the exact head
must be success or neutral before a digest offers the PR or the Telegram approve path labels it —
and pin `.mergify.yml` to the same rule plus no `update` action at all.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import pr_all_checks_green as pacg  # noqa: E402
import scripts.lib.pr_all_checks_green as mra_checks  # noqa: E402
from scripts.lib import pr_merge_digest as pmd  # noqa: E402
from scripts.lib import pr_merge_telegram as pmt  # noqa: E402

REQUIRED = "cio-hardening", "agent-governance", "release-readiness", "ci-gate"


def _rollup(*, extra=(), required="success"):
    rows = [{"name": name, "status": "completed", "conclusion": required, "started_at": "2026-11-02T03:00:00Z"}
            for name in REQUIRED]
    rows += [{"name": name, "status": "completed", "conclusion": concl, "started_at": "2026-11-02T03:00:00Z"}
             for name, concl in extra]
    return rows


def _pr(rollup, *, number=101, title="A plain sentence about the change", body=None):
    return {
        "number": number,
        "title": title,
        "url": f"https://example.com/pull/{number}",
        "headRefOid": "a" * 40,
        "isDraft": False,
        "labels": [],
        "body": body or pmd_plain_body(),
        "files": ["scripts/demo.py"],
        "changedFiles": 1,
        "statusCheckRollup": rollup,
        "baseRefName": "main",
    }


def pmd_plain_body():
    return (
        "## In plain English\n"
        "**What changes:** A demo change.\n"
        "**Why:** Because the test says so.\n"
        "**Who / what it affects:** nobody in this fixture.\n"
        "**When it takes effect:** never; it is a test.\n"
        "**Approval:** plan test.\n"
        "**Risk and fallback:** revert it.\n"
    )


# ---------------------------------------------------------------- the helper itself
def test_a_red_non_required_check_is_not_green():
    result = pacg.evaluate(_rollup(extra=[("secret-scan", "failure")]))
    assert result["ok"] is False
    assert "secret-scan: failure" in result["failing"]


def test_no_check_runs_is_never_green_at_a_merge_gate():
    assert pacg.evaluate([])["ok"] is False


# ---------------------------------------------------------------- merge digest eligibility
def test_the_digest_never_offers_a_pr_with_a_red_non_required_check(monkeypatch):
    monkeypatch.setattr(pmd, "pr_all_files", lambda repo, number: ["scripts/demo.py"])
    item = pmd.classify_pr(_pr(_rollup(extra=[("secret-scan", "failure")])), repo="example-org/example-repo",
                           cfg=pmd.load_config())
    assert item["status"] == "skip"
    assert item["reason"] == "checks_not_green"
    assert any("secret-scan" in line for line in item.get("blocking_checks") or [])


def test_the_digest_still_offers_a_pr_when_every_check_is_green(monkeypatch):
    monkeypatch.setattr(pmd, "pr_all_files", lambda repo, number: ["scripts/demo.py"])
    item = pmd.classify_pr(_pr(_rollup(extra=[("secret-scan", "success"), ("provider-cost", "skipped")])),
                           repo="example-org/example-repo", cfg=pmd.load_config())
    assert item["status"] == "ready"


# ---------------------------------------------------------------- Telegram approve gate
def _fake_gh_view(rollup):
    def run(cmd, *a, **kw):
        assert cmd[:3] == ["gh", "pr", "view"], cmd
        return subprocess_result(json.dumps({"headRefOid": "a" * 40, "statusCheckRollup": rollup}))
    return run


def subprocess_result(stdout, rc=0):
    class P:
        returncode = rc
        text = ""
    p = P()
    p.stdout = stdout
    p.stderr = ""
    return p


def _check_run(name, conclusion):
    return {"name": name, "status": "COMPLETED", "conclusion": conclusion}


def test_the_approve_gate_refuses_a_red_non_required_check(monkeypatch):
    rollup = [_check_run(name, "SUCCESS") for name in REQUIRED] + [_check_run("secret-scan", "FAILURE")]
    monkeypatch.setattr(pmt.subprocess, "run", _fake_gh_view(rollup))

    green, statuses = pmt.pr_check_rollup_green(101, repo="example-org/example-repo")

    assert green is False
    assert statuses["secret-scan"] == "FAILURE"


def test_the_approve_gate_blocks_a_pending_non_required_check(monkeypatch):
    rollup = [_check_run(name, "SUCCESS") for name in REQUIRED]
    rollup.append({"name": "aif-financial-senses-integration", "status": "IN_PROGRESS", "conclusion": ""})
    monkeypatch.setattr(pmt.subprocess, "run", _fake_gh_view(rollup))

    green, _statuses = pmt.pr_check_rollup_green(101, repo="example-org/example-repo")

    assert green is False


def test_the_approve_gate_accepts_every_check_green(monkeypatch):
    rollup = [_check_run(name, "SUCCESS") for name in REQUIRED]
    rollup.append(_check_run("secret-scan", "SUCCESS"))
    rollup.append(_check_run("provider-cost", "SKIPPED"))
    rollup.append(_check_run("pr-plain-english", "NEUTRAL"))
    monkeypatch.setattr(pmt.subprocess, "run", _fake_gh_view(rollup))

    green, _statuses = pmt.pr_check_rollup_green(101, repo="example-org/example-repo")

    assert green is True


# ---------------------------------------------------------------- .mergify.yml
def _flat(conds):
    out = []
    for c in conds or []:
        out.append(c if isinstance(c, str) else " ".join(str(k) + " " + " ".join(map(str, v))
                                                         for k, v in c.items()))
    return out


GATE_FAIL = "-check-failure~=^(?!Mergify Merge Queue$|Rule: ).*"
GATE_PENDING = "-check-pending~=^(?!Mergify Merge Queue$|Rule: ).*"


def test_mergify_rules_require_every_check_to_be_settled_and_green_except_mergify_own():
    """Every queue entry rule and merge condition carries the whole-set gate, and it excludes Mergify's
    own checks by name: on an embarked PR "Mergify Merge Queue" stays IN_PROGRESS for the whole embark
    (#2306, #2265), so a bare #check-pending=0 would dequeue or deadlock the solo queue."""
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text())
    seen = 0
    for rule in cfg["pull_request_rules"]:
        if "queue" not in (rule.get("actions") or {}):
            continue
        conds = _flat(rule.get("conditions"))
        assert GATE_FAIL in conds, rule["name"]
        assert GATE_PENDING in conds, rule["name"]
        seen += 1
    for rule in cfg["queue_rules"]:
        conds = _flat(rule.get("merge_conditions"))
        assert GATE_FAIL in conds, rule["name"]
        assert GATE_PENDING in conds, rule["name"]
        seen += 1
    assert seen == 4, seen


def test_the_bare_count_gates_are_gone():
    """#check-failure=0 / #check-pending=0 count Mergify's own checks; they must not come back."""
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text())
    for rule in cfg["pull_request_rules"]:
        conds = _flat(rule.get("conditions"))
        assert "#check-failure=0" not in conds and "#check-pending=0" not in conds, rule["name"]
    for rule in cfg["queue_rules"]:
        conds = _flat(rule.get("merge_conditions"))
        assert "#check-failure=0" not in conds and "#check-pending=0" not in conds, rule["name"]


def test_mergify_never_re_tests_a_pr_with_an_update_action():
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text())
    offenders = [r["name"] for r in cfg["pull_request_rules"]
                 if set(r.get("actions") or {}) & {"update", "rebase"}]
    assert offenders == [], offenders


# ---------------------------------------------------------------- mutation proofs
def _run_row(name, conclusion, started_at, suite=None):
    row = {"name": name, "status": "completed", "conclusion": conclusion, "started_at": started_at}
    if suite is not None:
        row["check_suite"] = {"id": suite}
    return row


def test_a_later_skip_never_hides_a_failure():
    """Mutation (a): turning `_latest_per_name`'s skip `continue` into an assignment must fail here."""
    runs = [_run_row("x", "failure", "2026-11-02T02:00:00Z"),
            _run_row("x", "skipped", "2026-11-02T03:00:00Z")]
    surviving = list(mra_checks._latest_per_name(runs).values())
    assert [r["conclusion"] for r in surviving] == ["failure"]
    assert pacg.evaluate(runs)["ok"] is False


def test_an_older_run_never_replaces_a_newer_one():
    """Mutation (c): flipping `>=` to `<=` would let the list's last row win regardless of age."""
    runs = [_run_row("x", "success", "2026-11-02T02:00:00Z"),
            _run_row("x", "failure", "2026-11-02T01:00:00Z")]
    assert pacg.evaluate(runs)["ok"] is True


def test_paging_that_cannot_read_every_run_fails_closed():
    """Mutation (b): making the `ok=False` paging guards pass would let a red check sit unread."""
    page = [{"name": f"check-{i}", "status": "completed", "conclusion": "success"} for i in range(100)]

    def gh_json(_path):
        return {"total_count": 2000, "check_runs": page}

    result = pacg.all_checks_green(gh_json, "example-org/example-repo", "a" * 40)
    assert result["ok"] is False
    assert "could not read" in result["reason"]


def test_paging_stops_at_the_last_short_page():
    pages = {1: [{"name": "a", "status": "completed", "conclusion": "success"}] * 100,
             2: [{"name": "b", "status": "completed", "conclusion": "success"}]}

    def gh_json(path):
        page = int(path.rsplit("page=", 1)[1])
        return {"total_count": 101, "check_runs": pages.get(page, [])}

    runs, total, exhausted = pacg.check_runs_for(gh_json, "example-org/example-repo", "a" * 40)
    assert len(runs) == 101 and total == 101 and exhausted is False


def test_the_same_job_name_in_two_workflows_is_two_checks():
    """Grouped by name alone, a green `shard 0` in one workflow hides a red one in another."""
    runs = [_run_row("shard 0", "failure", "2026-11-02T01:00:00Z", suite=1),
            _run_row("shard 0", "success", "2026-11-02T02:00:00Z", suite=2)]
    result = pacg.evaluate(runs)
    assert result["ok"] is False
    assert any("shard 0 [1]" in line for line in result["failing"])


def test_a_rollup_at_the_read_limit_fails_closed():
    rows = [{"name": f"c{i}", "status": "COMPLETED", "conclusion": "SUCCESS"} for i in range(pacg.ROLLUP_LIMIT)]
    result = pacg.evaluate_rollup(rows)
    assert result["ok"] is False
    assert "limit" in result["reason"]


# ---------------------------------------------------------------- the queue monitor
def test_the_queue_monitor_does_not_requeue_while_a_non_required_check_is_red():
    from scripts.lib import mergify_queue_monitor as mqm

    checks = {name: ["SUCCESS"] for name in REQUIRED}
    checks["secret-scan"] = ["FAILURE"]
    plan = mqm.classify_dequeue(reason_code="CHECKS_FAILED", body="", mergeable="MERGEABLE",
                                checks=checks, hotfix_on_main=True)
    assert plan.classification == "REAL_CI_FAIL"
    assert plan.requeue is False
    assert "secret-scan" in " ".join(plan.detail["red"])


def test_the_queue_monitor_reads_every_check_on_the_head(monkeypatch):
    from scripts.lib import mergify_queue_monitor as mqm

    rollup = [{"name": name, "conclusion": "SUCCESS"} for name in REQUIRED]
    rollup.append({"name": "secret-scan", "conclusion": "FAILURE", "workflowName": "secret-scan"})
    monkeypatch.setattr(mqm.subprocess, "run",
                        lambda *a, **k: subprocess_result(json.dumps({"statusCheckRollup": rollup})))
    rollup = mqm.fetch_head_check_rollup(101, repo="example-org/example-repo")
    assert any(row.get("name") == "secret-scan" and row.get("conclusion") == "FAILURE" for row in rollup)
