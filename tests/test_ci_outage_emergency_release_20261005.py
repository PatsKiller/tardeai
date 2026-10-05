"""CI-provider outage emergency release (operator 2026-10-05: "build an emergency path for
situations like this. Because this is not in our control").

Fakes only: status-page payloads, workflow runs/jobs and grants are dicts; the commit rule runs on
a throwaway local git repo. No network, no GitHub, no Telegram, no grant store, no deploy.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import ci_outage_emergency as em  # noqa: E402

SHA = "a" * 40
REQ = (".github/workflows/cio-production-hardening-ci.yml", ".github/workflows/agent-governance.yml")
NOW = 1_791_250_000.0


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(em, "STATE_DIR", tmp_path / "emergency")
    return tmp_path / "emergency"


INCIDENT = {"incidents": [{"id": "inc123", "name": "Incident with Actions", "status": "investigating",
                           "components": [{"name": "Actions"}], "created_at": "2026-10-05T19:11:58Z"}]}


def run(path, rid, conclusion="failure", status="completed"):
    return {"id": rid, "head_sha": SHA, "event": "push", "head_branch": "main", "path": path,
            "workflow_id": rid, "run_number": 1, "run_attempt": 1, "status": status, "conclusion": conclusion}


NEVER = {"id": 1, "name": "cio-hardening", "conclusion": "cancelled", "status": "completed", "steps": [], "runner_name": ""}
RAN_FAILED = {"id": 2, "name": "cio-hardening", "conclusion": "failure", "status": "completed", "runner_name": "GitHub Actions 7",
              "steps": [{"name": "Set up job", "status": "completed", "conclusion": "success"},
                        {"name": "CIO hardening gates", "status": "completed", "conclusion": "failure"}]}


# ── 1. outage proof ─────────────────────────────────────────────────────────

def test_actions_incident_matched_by_name_or_component_and_resolved_ignored():
    assert [i["id"] for i in em.actions_incidents(INCIDENT)] == ["inc123"]
    assert em.actions_incidents({"incidents": [{"id": "x", "name": "Pages slow", "status": "investigating",
                                                "components": [{"name": "Pages"}]}]}) == []
    assert em.actions_incidents({"incidents": [{**INCIDENT["incidents"][0], "status": "resolved"}]}) == []


def test_job_never_started_vs_ran():
    assert em.job_never_started(NEVER)
    assert em.job_never_started({"status": "queued", "steps": [], "conclusion": None})
    assert not em.job_never_started(RAN_FAILED)


def test_outage_proof_when_required_jobs_never_started():
    runs = [run(REQ[0], 11, "cancelled"), run(REQ[1], 12, "cancelled")]
    out = em.evaluate_outage(SHA, runs, {11: [NEVER], 12: [NEVER]}, em.actions_incidents(INCIDENT), REQ)
    assert out["ok"] and sorted(out["outage_affected"]) == sorted(REQ)


def test_real_failure_stays_red_even_during_an_incident():
    runs = [run(REQ[0], 11), run(REQ[1], 12, "cancelled")]
    out = em.evaluate_outage(SHA, runs, {11: [RAN_FAILED], 12: [NEVER]}, em.actions_incidents(INCIDENT), REQ)
    assert not out["ok"] and any("ran_or_pending" in e for e in out["errors"])


def test_no_incident_means_no_emergency():
    runs = [run(REQ[0], 11, "cancelled"), run(REQ[1], 12, "cancelled")]
    out = em.evaluate_outage(SHA, runs, {11: [NEVER], 12: [NEVER]}, [], REQ)
    assert not out["ok"] and "no_unresolved_actions_incident" in out["errors"]


def test_all_green_uses_the_normal_gate_and_running_is_not_an_outage():
    green = [run(REQ[0], 11, "success"), run(REQ[1], 12, "success")]
    assert "no_outage_affected_workflow (normal gate applies)" in \
        em.evaluate_outage(SHA, green, {}, em.actions_incidents(INCIDENT), REQ)["errors"]
    running = [run(REQ[0], 11, None, "in_progress"), run(REQ[1], 12, "cancelled")]
    jobs = {11: [{"id": 3, "status": "in_progress", "conclusion": None, "runner_name": "r1",
                  "steps": [{"status": "in_progress", "conclusion": None}]}], 12: [NEVER]}
    assert not em.evaluate_outage(SHA, running, jobs, em.actions_incidents(INCIDENT), REQ)["ok"]


# ── 2. workflow replay + evidence ───────────────────────────────────────────

WF = """
on: {push: {branches: [main]}}
jobs:
  gates:
    runs-on: ubuntu-latest
    env: {TRADE_AI_CI: "1", EVENT_NAME: "${{ github.event_name }}"}
    steps:
      - uses: actions/checkout@v4
      - name: Install deps
        run: pip install pytest
      - name: Fetch PR base
        if: github.event_name == 'pull_request'
        run: git fetch origin ${{ github.base_ref }}
      - name: Gates
        run: python3 scripts/run.py --sha ${{ github.sha }}
      - name: Weird
        if: contains(github.ref, 'x')
        run: echo hi
      - name: Upload
        if: always()
        uses: actions/upload-artifact@v4
"""


def test_workflow_replay_plan_skips_actions_and_known_steps_and_flags_unknowns():
    plan = em.workflow_job_steps(WF, "gates", {"Install deps": "local venv"}, SHA)
    assert [s["name"] for s in plan["steps"]] == ["Gates"]
    assert plan["steps"][0]["run"].endswith(SHA)
    assert plan["env"]["EVENT_NAME"] == "push"
    skipped = {s["name"] for s in plan["skipped"]}
    assert {"actions/checkout@v4", "Install deps", "Fetch PR base", "Upload"} <= skipped
    assert any(p.startswith("step:Weird:unknown_if") for p in plan["problems"])   # blocks the path


def _results(tmp_path, *, rc=0, suites=("workflow:gates", "build")):
    out = []
    for s in suites:
        log = tmp_path / f"{s.replace(':', '_')}.log"
        log.write_text(f"{s} ok\n")
        out.append({"suite": s, "exit_code": rc, "log": str(log), "log_sha256": em.sha256_file(log)})
    return out


def test_evidence_valid_only_for_its_tree_complete_green_untampered_and_fresh(tmp_path):
    req = ["workflow:gates", "build"]
    em.write_manifest(SHA, "tree1", _results(tmp_path), now=NOW)
    assert em.verify_evidence(SHA, "tree1", required_suites=req, max_age_h=12, now=NOW + 60)["ok"]
    assert "evidence_tree_mismatch" in em.verify_evidence(SHA, "tree2", required_suites=req, max_age_h=12, now=NOW)["errors"]
    assert any(e.startswith("evidence_stale") for e in
               em.verify_evidence(SHA, "tree1", required_suites=req, max_age_h=12, now=NOW + 13 * 3600)["errors"])
    assert "suite_missing:extra" in em.verify_evidence(SHA, "tree1", required_suites=req + ["extra"], max_age_h=12, now=NOW)["errors"]
    Path(_results(tmp_path)[0]["log"]).write_text("edited\n")
    assert "log_tampered_or_missing:workflow:gates" in \
        em.verify_evidence(SHA, "tree1", required_suites=req, max_age_h=12, now=NOW)["errors"]


def test_failed_suite_or_incomplete_replay_or_missing_manifest_blocks(tmp_path):
    em.write_manifest(SHA, "t", _results(tmp_path, rc=1), now=NOW)
    assert "suite_failed:build" in em.verify_evidence(SHA, "t", required_suites=["build"], max_age_h=12, now=NOW)["errors"]
    em.write_manifest(SHA, "t", _results(tmp_path), problems=["step:Weird:unknown_if"], now=NOW)
    assert any(e.startswith("replay_incomplete") for e in
               em.verify_evidence(SHA, "t", required_suites=["build"], max_age_h=12, now=NOW)["errors"])
    assert em.verify_evidence("b" * 40, "t", required_suites=[], max_age_h=12)["errors"] == ["local_evidence_missing"]


def test_required_suites_come_from_the_config():
    cfg = em.load_config()
    names = em.required_suite_names(cfg)
    assert "workflow:cio-hardening" in names and "workflow:agent-governance" in names
    assert "frontend-build-design-guard" in names and cfg["auto_rollback"] is False


# ── 3. operator authority ───────────────────────────────────────────────────

def grant(tier="release-emergency", reason=f"EMERGENCY release {SHA} during GitHub incident inc123", **kw):
    return {"tier": tier, "grant_id": "g1", "reason": reason, "uses": 2, "expires": NOW + 3600, **kw}


def test_emergency_grant_must_name_sha_and_incident_and_be_live():
    assert em.find_emergency_grant([grant()], SHA, ["inc123"], now=NOW)["ok"]
    assert not em.find_emergency_grant([grant(reason=f"release {SHA}")], SHA, ["inc123"], now=NOW)["ok"]
    assert not em.find_emergency_grant([grant(reason="incident inc123")], SHA, ["inc123"], now=NOW)["ok"]
    assert not em.find_emergency_grant([grant(expires=NOW - 1)], SHA, ["inc123"], now=NOW)["ok"]
    assert not em.find_emergency_grant([grant(uses=0)], SHA, ["inc123"], now=NOW)["ok"]


def test_a_release_write_grant_is_not_an_emergency_grant():
    assert not em.find_emergency_grant([grant(tier="release-write")], SHA, ["inc123"], now=NOW)["ok"]


# ── 4. commit rule (throwaway git repo) ─────────────────────────────────────

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t"); _git(r, "config", "user.name", "t")
    _git(r, "config", "core.hooksPath", "/dev/null")
    (r / "a.txt").write_text("a\n"); _git(r, "add", "a.txt"); _git(r, "commit", "-qm", "base")
    _git(r, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(r, "checkout", "-qb", "feature")
    (r / "b.txt").write_text("b\n"); _git(r, "add", "b.txt"); _git(r, "commit", "-qm", "feature")
    _git(r, "update-ref", "refs/remotes/origin/feature", "HEAD")     # pushed to GitHub
    _git(r, "checkout", "-q", "main")
    return r


def test_commit_on_main_is_on_main(repo):
    res = em.sha_rule(em.git_runner(repo), _git(repo, "rev-parse", "origin/main"))
    assert res["ok"] and res["label"] == "ON_MAIN" and res["tree"]


def test_local_merge_of_pushed_pr_is_pending_reconciliation(repo):
    _git(repo, "checkout", "-qb", "local", "origin/main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "local merge", "origin/feature")
    res = em.sha_rule(em.git_runner(repo), _git(repo, "rev-parse", "HEAD"))
    assert res["ok"] and res["label"] == em.PENDING and len(res["local_merges"]) == 1


def test_unpushed_commit_blocks(repo):
    _git(repo, "checkout", "-qb", "local", "origin/main")
    (repo / "c.txt").write_text("c\n"); _git(repo, "add", "c.txt"); _git(repo, "commit", "-qm", "local only")
    res = em.sha_rule(em.git_runner(repo), _git(repo, "rev-parse", "HEAD"))
    assert not res["ok"] and any(e.startswith("commits_not_on_github") for e in res["errors"])


# ── decision ────────────────────────────────────────────────────────────────

def test_decision_requires_every_condition():
    ok = {"ok": True}
    outage = {"ok": True, "incidents": [{"id": "inc123"}]}
    commit = {"ok": True, "label": "ON_MAIN", "tree": "t"}
    d = em.decide(sha=SHA, outage=outage, evidence=ok, grant={"ok": True, "grant_id": "g1"}, commit=commit)
    assert d["allowed"] and d["incident_ids"] == ["inc123"] and d["grant_id"] == "g1"
    for part in ("outage", "evidence", "grant", "commit"):
        parts = {"outage": outage, "evidence": ok, "grant": {"ok": True}, "commit": commit}
        parts[part] = {"ok": False, "errors": ["no"]}
        assert not em.decide(sha=SHA, **parts)["allowed"]


# ── 5. reconciliation ───────────────────────────────────────────────────────

REC = {"sha": SHA, "tree": "T", "label": em.PENDING, "promoted_at": NOW, "incident_ids": ["inc123"],
       "prev_release": "/rel/prev"}


def test_reconciled_when_main_carries_the_tree_and_ci_is_green():
    res = em.reconcile_record(REC, main_commits=[("m" * 40, "T")], checks_for=lambda s: {"ok": True, "checks": []},
                              jobs_ran_and_failed=lambda s: False, now=NOW + 3600, within_h=24)
    assert res["state"] == em.RECONCILED and res["main_sha"] == "m" * 40


def test_real_ci_failure_after_recovery_is_reconcile_failed():
    res = em.reconcile_record(REC, main_commits=[(SHA, "T")], checks_for=lambda s: {"ok": False, "errors": ["x"]},
                              jobs_ran_and_failed=lambda s: True, now=NOW + 3600, within_h=24)
    assert res["state"] == em.RECONCILE_FAILED


def test_pending_then_overdue_and_divergence():
    kw = dict(checks_for=lambda s: {"ok": False}, jobs_ran_and_failed=lambda s: False, within_h=24)
    assert em.reconcile_record(REC, main_commits=[], now=NOW + 3600, **kw)["state"] == em.PENDING
    assert em.reconcile_record(REC, main_commits=[], now=NOW + 25 * 3600, **kw)["state"] == em.OVERDUE
    assert em.reconcile_record(REC, main_commits=[("x" * 40, "OTHER")], now=NOW + 3600, content_merged=True,
                               **kw)["state"] == em.RECONCILE_FAILED


def test_ledger_tracks_open_emergencies_until_reconciled():
    em.append_ledger({"event": "EMERGENCY_PROMOTED", "state": em.PENDING, **REC})
    assert [r["sha"] for r in em.open_emergencies(em.load_ledger())] == [SHA]
    em.append_ledger({"event": em.RECONCILED, "state": em.RECONCILED, "sha": SHA})
    assert em.open_emergencies(em.load_ledger()) == []


# ── wiring ──────────────────────────────────────────────────────────────────

def test_deploy_script_only_bypasses_ci_gate_through_the_emergency_check():
    src = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text(encoding="utf-8")
    assert 'EMERGENCY_SHA="${TRADEAI_EMERGENCY_RELEASE_SHA:-}"' in src
    gate = src[src.index('--ci-only --sha "$sha"'):src.index("write_state\n  activate_release")]
    assert 'emergency_check "$sha" --record' in gate and '"$EMERGENCY_SHA" == "$sha"' in gate
    assert 'die "exact-SHA push-to-main checks are not completed successfully; activation refused"' in gate
    assert "emergency_check \"$EMERGENCY_SHA\"" in src[src.index("require_head_is_origin_main() {"):]
    assert "promote_ok_emergency_pending_reconciliation" in src


def test_emergency_code_has_no_broker_or_order_surface():
    for rel in ("scripts/lib/ci_outage_emergency.py", "scripts/ci_outage_emergency_release.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not mods & {"schwab", "futu", "moomoo", "alpaca", "alpaca_trade_api", "broker_execution"}
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "place_order" not in text and "--admin" not in text


def test_cli_refuses_short_sha(capsys):
    import ci_outage_emergency_release as cli
    assert cli.main(["check", "--sha", "abc123"]) == 2
    assert "full 40-hex" in json.loads(capsys.readouterr().out)["error"]
