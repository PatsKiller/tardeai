"""LQ-20261107-1192: local-only self-heal arming (operator 2026-11-08: "enable self-healing right now", NO git pushes).

* ``arming.local_only.enabled`` arms the lane WITHOUT a guard grant; daily_job_cap and daily_cost_cap_usd still bind.
* Under it nothing pushes: may_push is forced False even with AGENTS §24.16 ACTIVE and a git-push grant present;
  ``Attempt.push_and_pr`` refuses on its own (belt); the lifecycle advance makes no gh call.
* A job that reaches fix_ready_local writes a FINDING into the lead's inbox.
* Non-code failures (dependency / data / timeout / data_quality / audit BLOCK) are not admitted for a code fix: one
  ESCALATION FINDING per signature per ET day instead.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import self_heal_fixer as F  # noqa: E402 -- scripts/ must be on sys.path first
import self_heal_fixer as S  # noqa: E402 -- scripts/ must be on sys.path first
from tests import test_self_heal_fixer_20261016 as B  # noqa: E402 -- scripts/ must be on sys.path first
from tests.test_self_heal_fixer_20261016 import sandbox  # noqa: E402,F401 -- pytest fixture imported by name; needs sys.path first

NOW = B.NOW
REPO_CFG = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())
GRANT = {"reason": "self-heal-fixer test", "grant_id": "a" * 32}
INBOX = Path("data/coordination/coordinator/inbox/claude-lead")


@pytest.fixture(autouse=True)
def _ci(monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")


def _local(cfg: dict, enabled=True) -> dict:
    c = json.loads(json.dumps(cfg))
    c["arming"]["local_only"] = {"enabled": enabled, "why": "test"}
    return c


def _set_local(sb, enabled=True, **arming):
    cfg = _local(json.loads(sb["cfg"].read_text()), enabled)
    cfg["arming"].update(arming)
    sb["cfg"].write_text(json.dumps(cfg))
    return cfg


def _amend(sb):
    marker = B.CFG["policy_gate"]["amendment_heading_marker"]
    p = sb["repo"] / "AGENTS.md"
    p.write_text(p.read_text() + f"\n{marker} (13.0.0, ACTIVE)\n")
    B._sh("git", "-C", str(sb["repo"]), "commit", "-qam", "amend")
    B._sh("git", "-C", str(sb["repo"]), "push", "-q", "origin", "main")


def _main(sb, *extra, grant=GRANT, gh_calls=None, now=NOW):
    def gh(cmd):
        if gh_calls is not None:
            gh_calls.append(cmd)
        return {"rc": 1, "out": "", "err": "", "seconds": 0}

    return S.main(
        ["--cycle", "--config", str(sb["cfg"]), "--incident", str(sb["incident"]), *extra],
        now=lambda: now,
        environ=sb["env"],
        grant_reader=lambda tier: dict(grant) if grant else None,
        gh=gh,
    )


def _state(sb) -> dict:
    p = sb["state"] / B.CFG["state"]["state_rel"]
    return json.loads(p.read_text()) if p.exists() else {"jobs": {}}


def _findings(sb) -> list[Path]:
    d = sb["state"] / INBOX
    return sorted(d.glob("FINDING-*.md")) if d.exists() else []


def _calls(sb) -> list:
    p = sb["bin"] / "calls.jsonl"
    return p.read_text().splitlines() if p.exists() else []


# ---------------------------------------------------------------- 1. the repo config is the operator's switch


def test_repo_config_enables_local_only_with_caps_unchanged():
    a = REPO_CFG["arming"]
    assert a["local_only"]["enabled"] is True and "no-push" in a["local_only"]["why"]
    assert a["daily_job_cap"] == 3 and a["daily_cost_cap_usd"] == 24.0 and a["max_jobs_per_cycle"] == 1
    assert REPO_CFG["findings"]["inbox_rel"] == str(INBOX)
    assert F.local_only(REPO_CFG) is not None


# ---------------------------------------------------------------- 2. arming verdict


def test_local_only_arms_without_a_grant_and_never_may_push():
    v = F.arming_verdict(None, cfg=_local(B.CFG), jobs_today=0)
    assert v["armed"] is True and v["local_only"] is True and v["may_push"] is False
    assert v["grant_ignored"] is False and v["daily_cost_cap_usd"] == 24.0


def test_local_only_wins_over_a_present_git_push_grant():
    v = F.arming_verdict(GRANT, cfg=_local(B.CFG), jobs_today=0)
    assert v["armed"] is True and v["may_push"] is False and v["grant_ignored"] is True


def test_local_only_respects_the_daily_job_cap():
    v = F.arming_verdict(None, cfg=_local(B.CFG), jobs_today=3)
    assert v["armed"] is False and v["local_only"] is True and "daily job cap" in v["why"]


@pytest.mark.parametrize("enabled", ["true", 1, None, False])
def test_only_a_literal_true_turns_the_switch_on(enabled):
    cfg = _local(B.CFG, enabled)
    assert F.local_only(cfg) is None
    v = F.arming_verdict(None, cfg=cfg, jobs_today=0)
    assert v["armed"] is False and "grant" in v["why"]  # falls back to the grant path, which has no grant


def test_grant_path_unchanged_when_switch_absent():
    v = F.arming_verdict(GRANT, cfg=B.CFG, jobs_today=0)
    assert v["armed"] is True and v["may_push"] is True and "local_only" not in v


# ---------------------------------------------------------------- 3. no push path is reachable


def test_local_only_cycle_never_pushes_even_with_amendment_active_and_grant(sandbox, monkeypatch):
    """§24.16 ACTIVE at the base + a git-push grant present: before this change that pushes and opens a PR
    (test_success_with_amendment_pushes_one_branch_and_opens_labelled_pr). Local-only: push_and_pr is never called,
    gh is never called, nothing reaches origin, and the job ends at fix_ready_local with a FINDING."""
    _set_local(sandbox)
    _amend(sandbox)
    (sandbox["bin"] / "scenario").write_text("fix")
    pushes = []
    real = S.Attempt.push_and_pr
    monkeypatch.setattr(S.Attempt, "push_and_pr", lambda self, *a, **k: pushes.append(a) or real(self, *a, **k))
    gh_calls: list = []
    assert _main(sandbox, "--apply", gh_calls=gh_calls) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_READY_LOCAL and job["reason"] == "local_only_no_push"
    assert pushes == [] and gh_calls == []
    assert not (sandbox["bin"] / "gh_calls.txt").exists()
    assert job["branch"] not in B._sh("git", "-C", str(sandbox["origin"]), "branch", "--list")
    assert job["branch"] in B._sh("git", "-C", str(sandbox["repo"]), "branch", "--list")  # committed locally
    rcpt = json.loads((sandbox["state"] / B.CFG["state"]["receipt_rel"]).read_text())
    assert rcpt["arming"]["armed"] and rcpt["arming"]["local_only"] and rcpt["policy"]["push_allowed"] is True
    # the FIX_READY_LOCAL finding for the lead
    (f,) = _findings(sandbox)
    assert f.name == f"FINDING-SELF-HEAL-READY-LOCAL-{job['job_id']}.md" and job["finding_path"] == str(f)
    text = f.read_text()
    for needle in (job["lane"], job["job_id"], job["branch"], job["head_sha"], job["evidence_dir"], "passed=True"):
        assert str(needle) in text
    assert "Nothing was pushed" in text
    # a second cycle neither rewrites the finding nor calls gh to look for a PR
    assert _main(sandbox, "--apply", gh_calls=gh_calls) == 0
    assert gh_calls == [] and len(_findings(sandbox)) == 1


def test_push_and_pr_itself_refuses_under_local_only(monkeypatch):
    """Belt: even if a caller asked, the method refuses before any git or gh call."""
    ran = []
    monkeypatch.setattr(S, "run", lambda *a, **k: ran.append(a) or {"rc": 0, "out": "", "err": ""})
    fake = SimpleNamespace(cfg=_local(B.CFG), may_push=True, environ={}, fix_wt=Path("/nonexistent"))
    out = S.Attempt.push_and_pr(fake, "body", "c" * 40)
    assert out["ok"] is False and out["why"] == "local_only_no_push" and ran == []
    fake2 = SimpleNamespace(cfg=B.CFG, may_push=False, environ={}, fix_wt=Path("/nonexistent"))
    assert S.Attempt.push_and_pr(fake2, "body", "c" * 40)["why"] == "local_only_no_push" and ran == []


def test_dry_run_plan_says_no_push_under_local_only(sandbox, tmp_path):
    _set_local(sandbox)
    _amend(sandbox)
    out = tmp_path / "dry"
    assert _main(sandbox, "--dry-run", "--out", str(out)) == 0
    plan = json.loads((out / "plan.json").read_text())
    assert plan["would_push"] is False and plan["local_only"] is True
    assert _calls(sandbox) == [] and not (sandbox["state"] / B.CFG["state"]["state_rel"]).exists()


# ---------------------------------------------------------------- 4. caps still bind


def test_daily_job_cap_holds_under_local_only(sandbox):
    _set_local(sandbox)
    (sandbox["bin"] / "scenario").write_text("fix")
    st = sandbox["state"] / B.CFG["state"]["state_rel"]
    st.parent.mkdir(parents=True, exist_ok=True)
    jobs = {
        f"old-{i}": {"job_id": f"old-{i}", "lane": f"l{i}", "state": F.FIX_FAILED, "dedupe_key": f"k{i}",
                     "attempt_started_at": (NOW - timedelta(minutes=5 + i)).isoformat()}
        for i in range(3)
    }
    st.write_text(json.dumps({"schema": F.STATE_SCHEMA, "jobs": jobs}))
    assert _main(sandbox, "--apply") == 0
    rcpt = json.loads((sandbox["state"] / B.CFG["state"]["receipt_rel"]).read_text())
    assert rcpt["arming"]["armed"] is False and "daily job cap" in rcpt["arming"]["why"]
    assert any(str(a["outcome"]).startswith("not_armed:") for a in rcpt["attempted"])
    assert _calls(sandbox) == [] and _findings(sandbox) == []


def test_daily_cost_cap_holds_under_local_only(sandbox):
    """The whole attempt budget is reserved before the model runs; a day cap below it refuses the claim."""
    _set_local(sandbox, daily_cost_cap_usd=5.0)  # max_cost_usd per attempt is 12
    (sandbox["bin"] / "scenario").write_text("fix")
    assert _main(sandbox, "--apply") == 0
    rcpt = json.loads((sandbox["state"] / B.CFG["state"]["receipt_rel"]).read_text())
    assert rcpt["arming"]["armed"] is True
    (att,) = rcpt["attempted"]
    assert att["outcome"].startswith("not_claimed:") and _calls(sandbox) == []


# ---------------------------------------------------------------- 5. non-code failures -> escalation finding


@pytest.mark.parametrize(
    "incident,receipt,want",
    [
        ({"failure_class": "dependency_unavailable"}, None, "dependency_unavailable"),
        ({"failure_class": "code_error", "failure_kind": "timeout:run"}, None, "timeout"),
        ({}, {"reason": "data_quality"}, "data_quality"),
        ({"event_type": "RUN_TIMEOUT"}, None, "timeout"),
        ({}, {"stderr_tail": "lane exit 3: audit BLOCK (2 findings)"}, "audit_block"),
        ({}, {"stderr_tail": '{"verdict": "BLOCK"}'}, "audit_block"),
        ({}, {"stderr_tail": "psycopg2.OperationalError: connection refused"}, "dependency_unavailable"),
        ({}, {"stderr_tail": "status=dependency_unavailable provider=x"}, "dependency_unavailable"),
        ({}, {"stderr_tail": "subprocess.TimeoutExpired: Command timed out"}, "timeout"),
        ({"failure_class": "code_error"}, {"stderr_tail": "ZeroDivisionError: division by zero"}, None),
        ({"failure_class": "code_error", "failure_kind": "code_error:incident"}, None, None),
    ],
)
def test_non_code_class(incident, receipt, want):
    assert F.non_code_class(incident, receipt, B.CFG) == want


def test_config_can_add_a_non_code_marker():
    cfg = json.loads(json.dumps(B.CFG))
    cfg["intake"]["non_code"] = {"classes": ["quota"], "markers": {"quota": [r"\bQUOTA_EXHAUSTED\b"]}}
    assert F.non_code_class({}, {"stderr_tail": "QUOTA_EXHAUSTED"}, cfg) == "quota"
    assert F.non_code_class({"failure_class": "quota"}, None, cfg) == "quota"


def _make_non_code(sb, stderr="dependency_unavailable: alpha vantage 503 Service Unavailable"):
    doc = json.loads(sb["incident"].read_text())
    doc["receipt"]["stderr_tail"] = stderr
    sb["incident"].write_text(json.dumps(doc))


def test_non_code_incident_is_escalated_once_per_signature_per_day_never_admitted(sandbox):
    _set_local(sandbox)
    _make_non_code(sandbox)
    (sandbox["bin"] / "scenario").write_text("fix")
    assert _main(sandbox, "--apply") == 0
    assert _state(sandbox)["jobs"] == {} and _calls(sandbox) == []
    rcpt = json.loads((sandbox["state"] / B.CFG["state"]["receipt_rel"]).read_text())
    (sk,) = rcpt["skipped"]
    assert sk["why"] == "non_code:dependency_unavailable" and sk["deduped"] is False
    (f,) = _findings(sandbox)
    assert f.name.startswith(f"FINDING-SELF-HEAL-ESCALATION-{F.et_day(NOW)}-buggy-lane-")
    assert "dependency_unavailable" in f.read_text() and "buggy-lane" in f.read_text()
    # same day, same signature: deduped, no second file
    assert _main(sandbox, "--apply") == 0
    rcpt = json.loads((sandbox["state"] / B.CFG["state"]["receipt_rel"]).read_text())
    assert rcpt["skipped"][0]["deduped"] is True and len(_findings(sandbox)) == 1
    # next ET day: one new finding
    assert _main(sandbox, "--apply", now=NOW + timedelta(days=1)) == 0
    assert len(_findings(sandbox)) == 2 and _state(sandbox)["jobs"] == {}


def test_non_code_escalation_also_without_local_only(sandbox):
    """The intake rule is not tied to the switch: a dependency outage is never a code-fix job."""
    _make_non_code(sandbox, stderr="lane exit 2: audit BLOCK")
    assert _main(sandbox, "--apply", grant=None) == 0
    assert _state(sandbox)["jobs"] == {} and len(_findings(sandbox)) == 1


def test_dry_run_reports_the_escalation_but_writes_nothing(sandbox, tmp_path):
    _set_local(sandbox)
    _make_non_code(sandbox)
    out = tmp_path / "dry"
    assert _main(sandbox, "--dry-run", "--out", str(out)) == 0
    rcpt = json.loads((out / "receipt.json").read_text())
    (fd,) = rcpt["findings"]
    assert fd["kind"] == "non_code_escalation" and fd["written"] is False
    assert _findings(sandbox) == [] and not (sandbox["state"] / B.CFG["state"]["state_rel"]).exists()


def test_a_queued_job_with_a_non_code_cause_is_refused_and_escalated(sandbox):
    """Jobs admitted before the rule (or whose failing run turns out non-code) are refused at attempt time."""
    _set_local(sandbox)
    (sandbox["bin"] / "scenario").write_text("fix")
    st = sandbox["state"] / B.CFG["state"]["state_rel"]
    st.parent.mkdir(parents=True, exist_ok=True)
    job = {
        "schema": F.JOB_SCHEMA, "job_id": "shf-q-1", "dedupe_key": "q|sig-q", "lane": "queued-lane",
        "signature": "sig-q", "defect_id": "cd-q", "state": F.FIX_REQUESTED, "failure_kind": "timeout",
        "created_at": (NOW - timedelta(hours=1)).isoformat(), "updated_at": (NOW - timedelta(hours=1)).isoformat(),
        "history": [{"state": F.FIX_REQUESTED, "at": (NOW - timedelta(hours=1)).isoformat()}],
        "iterations": [], "cost_usd": 0.0, "escalated_at": None,
    }
    st.write_text(json.dumps({"schema": F.STATE_SCHEMA, "jobs": {"shf-q-1": job}}))
    _make_non_code(sandbox)  # the incident file itself is non-code too, so nothing new is admitted
    assert _main(sandbox, "--apply") == 0
    q = _state(sandbox)["jobs"]["shf-q-1"]
    assert q["state"] == F.FIX_REFUSED and q["reason"] == "non_code:timeout"
    assert _calls(sandbox) == []
    names = [f.name for f in _findings(sandbox)]
    assert any("queued-lane" in n for n in names) and any("buggy-lane" in n for n in names)
