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


def test_mergify_rules_require_every_check_on_the_head_to_be_settled_and_green():
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text())
    for rule in cfg["pull_request_rules"]:
        if "queue" not in (rule.get("actions") or {}):
            continue
        conds = _flat(rule.get("conditions"))
        assert "#check-failure=0" in conds, rule["name"]
        assert "#check-pending=0" in conds, rule["name"]
    for rule in cfg["queue_rules"]:
        conds = _flat(rule.get("merge_conditions"))
        assert "#check-failure=0" in conds, rule["name"]
        assert "#check-pending=0" in conds, rule["name"]


def test_mergify_never_re_tests_a_pr_with_an_update_action():
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text())
    offenders = [r["name"] for r in cfg["pull_request_rules"]
                 if set(r.get("actions") or {}) & {"update", "rebase"}]
    assert offenders == [], offenders
