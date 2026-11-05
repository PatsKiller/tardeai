"""deploy_on_main autonomy (2026-10-27): deploy-delegation binding, checkout hygiene, failure-streak alerting.

Hermetic: temporary Git fixtures, temp state roots, a stub native deploy script. No prepare/promote,
no Telegram, no production path is read or written.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from scripts.lib import deploy_delegation_binding as DDB
from scripts.lib import deploy_on_main as D

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40

STUB = r'''#!/usr/bin/env bash
# fixture native deploy: proves the poller handed it a valid one-run ticket for HEAD, then "promotes".
set -euo pipefail
action="$1"
[[ -z "${TRADEAI_EMERGENCY_RELEASE_SHA:-}${TRADEAI_RELEASE_TRAIN_SHA:-}" ]] || { echo "ERROR: foreign path env" >&2; exit 9; }
if [[ -f "${FIXTURE_FAIL_FLAG:-/nonexistent}" ]]; then echo "ERROR: fixture native refusal for $action" >&2; exit 1; fi
sha="$(git rev-parse HEAD)"
"$FIXTURE_PY" - "$sha" <<'PY'
import hashlib, json, os, sys
t = json.load(open(os.environ["TRADEAI_DEPLOY_DELEGATION_TICKET"]))
assert t["sha"] == sys.argv[1], "ticket sha != HEAD"
assert t["nonce_sha256"] == hashlib.sha256(os.environ["TRADEAI_DEPLOY_DELEGATION_NONCE"].encode()).hexdigest()
PY
echo "{\"allowed\": true, \"binding_source\": \"deploy_delegation\", \"matched_by\": [\"deploy_delegation\"], \"sha\": \"$sha\"}"
if [[ "$action" == promote ]]; then
  mkdir -p "$FIXTURE_RELEASES/$sha-main-exact-phase2-fixture"
  ln -sfn "$FIXTURE_RELEASES/$sha-main-exact-phase2-fixture" "$FIXTURE_RELEASES/CURRENT"
fi
'''

REAL_RUN = subprocess.run


def git(repo, *args):
    return REAL_RUN(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("TRADEAI_EMERGENCY_RELEASE_SHA", "TRADEAI_RELEASE_TRAIN_SHA", "TRADEAI_RELEASE_CAMPAIGN",
              "TRADEAI_DEPLOY_DELEGATION_SOFT", DDB.TICKET_ENV, DDB.NONCE_ENV, "TRADEAI_DEPLOY_PRESERVE_DIRTY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    state = tmp_path / "persistent-state"
    sd = state / "data/runtime/release_window"
    sd.mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(sd))
    deleg = tmp_path / "delegation.json"
    deleg.write_text(json.dumps({"schema": "DeployDelegation@v1", "status": "ACTIVE", "scope": "promote_only"}))
    monkeypatch.setenv("TRADEAI_DEPLOY_DELEGATION", str(deleg))
    releases = tmp_path / "releases"
    base_rel = releases / ("b" * 12 + "-main-exact-phase2-old")
    base_rel.mkdir(parents=True)
    (releases / "CURRENT").symlink_to(base_rel, target_is_directory=True)
    monkeypatch.setenv("TRADEAI_PORTFOLIO_SERVER_ROOT", str(releases))
    monkeypatch.setenv("FIXTURE_RELEASES", str(releases))
    monkeypatch.setenv("FIXTURE_PY", sys.executable)
    monkeypatch.setenv("FIXTURE_FAIL_FLAG", str(tmp_path / "fail.flag"))

    repo = tmp_path / "canonical"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    git(repo, "config", "core.hooksPath", str(hooks))
    (repo / "scripts").mkdir()
    (repo / "scripts/cio_phase2_exact_main_deploy.sh").write_text(STUB)
    (repo / "version").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "version").write_text("target\n")
    git(repo, "commit", "--quiet", "-am", "Fixture feature (#4242)")
    target = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", target)
    git(repo, "checkout", "--quiet", "--detach", base)

    alerts: list[dict] = []
    monkeypatch.setattr(D, "_alert", lambda message, **kw: alerts.append({"message": message, **kw}))
    ci = {"state": "green"}
    monkeypatch.setattr(D, "main_checks_status", lambda repo, sha: (ci["state"], []))
    return SimpleNamespace(repo=repo, base=base, target=target, state=state, sd=sd, releases=releases,
                           alerts=alerts, ci=ci, fail_flag=tmp_path / "fail.flag", deleg=deleg)


def receipts(env):
    d = env.state / "data/runtime/deploy_on_main"
    return [json.loads(p.read_text()) for p in sorted(d.glob("2*.json"))]


def poll(env):
    return D.poll_once(repo=env.repo, fetch=False, apply=True)


# ── end to end through poll_once ────────────────────────────────────────────────────────────────


def test_poller_promotes_on_its_own_with_deploy_delegation_ticket(env):
    out = poll(env)
    assert out["outcome"] == "verified", out
    assert out["matched_by"] == "deploy_delegation"
    last = receipts(env)[-1]
    assert last["outcome"] == "verified" and last["detail"]["matched_by"] == "deploy_delegation"
    assert last["detail"]["bindings"] == {"prepare": "deploy_delegation", "promote": "deploy_delegation"}
    assert D.current_pin_sha().startswith(env.target[:12])
    assert not (env.sd / DDB.TICKET_NAME).exists(), "ticket must be revoked after the run"
    assert env.alerts == []
    # next poll: already served, nothing to alert
    assert poll(env)["action"] == "noop" and env.alerts == []


def test_waiting_ci_is_not_a_failure_and_never_deploys(env):
    env.ci["state"] = "pending"
    out = poll(env)
    assert out["outcome"] == "waiting_ci"
    assert git(env.repo, "rev-parse", "HEAD") == env.base
    assert D._load_alert_state().get("fail_streak") in (None, {})
    assert env.alerts == []


def test_red_main_checks_count_as_failure(env):
    env.ci["state"] = "red"
    out = poll(env)
    assert out["outcome"] == "deploy_failed" and receipts(env)[-1]["reason"] == "main_checks_red"


def test_failure_streak_pages_once_then_ok_on_recovery(env):
    env.fail_flag.write_text("1")
    for _ in range(5):
        assert poll(env)["outcome"] == "deploy_failed"
    p1 = [a for a in env.alerts if a["kind"] == "deploy_on_main"]
    assert len(p1) == 1, env.alerts
    msg = p1[0]["message"]
    assert "3 times in a row" in msg and "fixture native refusal" in msg and "Fixture feature (#4242)" in msg
    assert receipts(env)[-1]["detail"]["reason_line"].startswith("ERROR: fixture native refusal")
    env.fail_flag.unlink()
    assert poll(env)["outcome"] == "verified"
    ok = [a for a in env.alerts if a["kind"] == "deploy_on_main_recovered"]
    assert len(ok) == 1 and ok[0]["priority"] == "P2" and ok[0]["resolving"] is True
    poll(env)  # already served
    assert len(env.alerts) == 2


def test_two_failures_do_not_page(env):
    env.fail_flag.write_text("1")
    poll(env)
    poll(env)
    assert env.alerts == []
    env.fail_flag.unlink()
    assert poll(env)["outcome"] == "verified"
    assert env.alerts == [], "no OK note without a preceding P1"


def test_dirty_checkout_is_preserved_alerted_and_deploy_proceeds(env):
    (env.repo / "version").write_text("agent staged edit\n")
    git(env.repo, "add", "version")
    (env.repo / "stray.txt").write_text("untracked agent file\n")
    out = poll(env)
    assert out["outcome"] == "verified", out
    hyg = receipts(env)[-1]["detail"]["dirty_checkout"]
    assert hyg["ok"] is True and set(hyg["paths"]) == {"version", "stray.txt"}
    patch = Path(hyg["patch"]).read_text()
    assert "agent staged edit" in patch and "untracked agent file" in patch
    assert Path(hyg["patch"]).is_relative_to(env.state)
    tag = hyg["tag"]
    assert tag in git(env.repo, "stash", "list")
    ref = git(env.repo, "rev-parse", f"refs/deploy-on-main/autostash/{tag}")
    assert ref == hyg["stash_sha"]
    # the work is recoverable from the stash
    assert git(env.repo, "show", f"{ref}:version") == "agent staged edit"
    dirty = [a for a in env.alerts if a["kind"] == "deploy_on_main_dirty_checkout"]
    assert len(dirty) == 1 and "version" in dirty[0]["message"] and "preserved and proceeding" in dirty[0]["message"]


def test_dirty_alert_is_deduped_per_sha_per_hour(env, monkeypatch):
    monkeypatch.setenv("TRADEAI_DEPLOY_PRESERVE_DIRTY", "0")
    (env.repo / "version").write_text("operator work\n")
    for _ in range(3):
        out = poll(env)
        assert out["outcome"] == "deploy_failed"
    assert (env.repo / "version").read_text() == "operator work\n", "flag off: never moved"
    assert git(env.repo, "stash", "list") == ""
    dirty = [a for a in env.alerts if a["kind"] == "deploy_on_main_dirty_checkout"]
    assert len(dirty) == 1 and "BLOCKED" in dirty[0]["message"]
    assert receipts(env)[-1]["reason"] == "checkout_dirty"


def test_stop_and_revoked_delegation_still_refuse_without_ticket(env):
    env.deleg.write_text(json.dumps({"status": "PAUSED", "scope": "promote_only"}))
    out = poll(env)
    assert out["action"] == "refuse" and "delegation_not_armed" in out["reason"]
    assert not (env.sd / DDB.TICKET_NAME).exists()


# ── the binding itself ────────────────────────────────────────────────────────────────────────


@pytest.fixture
def binding(tmp_path, monkeypatch):
    sd = tmp_path / "rw"
    sd.mkdir()
    path, nonce = DDB.issue_ticket(sd, SHA, pid=4242, now=1000.0)
    ok = dict(
        root=tmp_path, state_dir=sd, now=1010.0, self_pid=99,
        env={DDB.TICKET_ENV: str(path), DDB.NONCE_ENV: nonce},
        ancestors=lambda pid: [99, 50, 4242, 1],
        cgroup=lambda pid: "0::/user.slice/user@1000.service/app.slice/tradeai-deploy-on-main.service\n",
        lock_holders=lambda p: {4242},
        stop=lambda sd: (False, "ABSENT"),
        delegation=lambda: (True, "ACTIVE"),
        origin_main=lambda root: SHA,
        checks=lambda sha: (True, []),
    )
    return SimpleNamespace(sd=sd, path=path, nonce=nonce, ok=ok)


def test_binding_accepts_only_the_full_poller_context(binding):
    v = DDB.decide("prepare", SHA, **binding.ok)
    assert v.allowed and v.matched_by == ["deploy_delegation"]
    assert DDB.decide("promote", SHA, **binding.ok).allowed


@pytest.mark.parametrize("change,reason", [
    (dict(env={}), "no_poller_ticket"),
    (dict(env="badnonce"), "ticket_nonce_mismatch"),
    (dict(env="emergency"), "foreign_release_path"),
    (dict(env="campaign"), "foreign_release_path"),
    (dict(sha="b" * 40), "ticket_sha_mismatch"),
    (dict(now=1000.0 + DDB.TICKET_TTL_S + 1), "ticket_stale"),
    (dict(ancestors=lambda pid: [99, 1]), "ticket_pid_not_ancestor"),
    (dict(cgroup=lambda pid: "0::/user.slice/session-1.scope\n"), "ticket_pid_not_poller_unit"),
    (dict(lock_holders=lambda p: set()), "global_release_lock_not_held_by_poller"),
    (dict(lock_holders=lambda p: {7}), "global_release_lock_not_held_by_poller"),
    (dict(stop=lambda sd: (True, "SET")), "stop_latched"),
    (dict(delegation=lambda: (False, "status:PAUSED")), "delegation_not_armed"),
    (dict(origin_main=lambda root: "c" * 40), "sha_not_origin_main"),
    (dict(checks=lambda sha: (False, ["not_successful:x"])), "main_checks_not_green"),
    (dict(action="rollback"), "action_not_bindable"),
])
def test_binding_refuses_every_missing_condition(binding, change, reason):
    kw = dict(binding.ok)
    action, sha = change.pop("action", "prepare"), change.pop("sha", SHA)
    e = change.pop("env", None)
    if e == "badnonce":
        kw["env"] = {**kw["env"], DDB.NONCE_ENV: "0" * 48}
    elif e == "emergency":
        kw["env"] = {**kw["env"], "TRADEAI_EMERGENCY_RELEASE_SHA": SHA}
    elif e == "campaign":
        kw["env"] = {**kw["env"], "TRADEAI_RELEASE_CAMPAIGN": "release-train-x"}
    elif e is not None:
        kw["env"] = e
    kw.update(change)
    v = DDB.decide(action, sha, **kw)
    assert not v.allowed and v.reason == reason and v.matched_by == []


def test_binding_refuses_a_ticket_outside_the_state_dir(binding, tmp_path):
    other = tmp_path / "elsewhere.json"
    other.write_text(binding.path.read_text())
    kw = dict(binding.ok, env={DDB.TICKET_ENV: str(other), DDB.NONCE_ENV: binding.nonce})
    assert DDB.decide("prepare", SHA, **kw).reason == "ticket_path_mismatch"


def test_binding_real_proc_readers_see_this_process_holding_the_lock(binding):
    """Real /proc ancestry + /proc/locks: the binding holds only while the ticket pid holds the flock."""
    from scripts.lib.release_control import GLOBAL_LOCK_NAME

    path, nonce = DDB.issue_ticket(binding.sd, SHA, pid=os.getpid())
    kw = dict(binding.ok, env={DDB.TICKET_ENV: str(path), DDB.NONCE_ENV: nonce}, now=time.time(),
              self_pid=os.getpid(), ancestors=DDB.proc_ancestors, lock_holders=DDB.flock_holders)
    lock = binding.sd / GLOBAL_LOCK_NAME
    lock.touch()
    assert DDB.decide("prepare", SHA, **kw).reason == "global_release_lock_not_held_by_poller"
    with open(lock, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert DDB.decide("prepare", SHA, **kw).allowed
    assert not DDB.decide("prepare", SHA, **kw).allowed


def test_strict_delegation_never_accepts_soft_switch_or_wrong_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_DEPLOY_DELEGATION_SOFT", "1")
    monkeypatch.setenv("TRADEAI_DEPLOY_DELEGATION", str(tmp_path / "missing.json"))
    assert D.deploy_delegation_armed()[0] is True  # lab soft switch still arms the dry poller …
    assert DDB.read_delegation() == (False, "missing")  # … but never binds a release
    f = tmp_path / "d.json"
    f.write_text(json.dumps({"status": "ACTIVE", "scope": "release_write"}))
    monkeypatch.setenv("TRADEAI_DEPLOY_DELEGATION", str(f))
    assert DDB.read_delegation() == (False, "scope:release_write")


# ── the native preflight ────────────────────────────────────────────────────────────────────


@pytest.fixture
def preflight(monkeypatch):
    import scripts.release_grant_preflight as P
    from scripts.lib.release_grant_binding import Verdict

    monkeypatch.setattr(P, "decide_from_disk", lambda action: Verdict(
        allowed=False, reason="no release-write grant names this PR/SHA/campaign"))
    monkeypatch.setattr(P, "capability_binding_active", lambda: False)
    monkeypatch.setattr(P, "consume_release_grant", lambda **kw: pytest.fail("guard ledger consumed"))
    monkeypatch.setattr(P, "promote_ci_gate", lambda sha, receipt: {"ok": True, "source": "fixture", "errors": []})
    monkeypatch.delenv("TRADEAI_RELEASE_GRANT_BINDING", raising=False)
    monkeypatch.delenv("TRADEAI_RELEASE_CAMPAIGN", raising=False)
    calls = []

    def fake(action, sha, *, root):
        calls.append(action)
        return DDB.DelegationVerdict(True, "fixture", ["deploy_delegation"])

    monkeypatch.setattr(DDB, "decide_from_env", fake)
    return SimpleNamespace(P=P, calls=calls)


def _run_preflight(P, monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["release_grant_preflight.py", *argv])
    rc = P.main()
    out = capsys.readouterr()
    return rc, json.loads(out.out.strip().splitlines()[-1]), out.err


@pytest.mark.parametrize("action", ["prepare", "promote"])
def test_preflight_binds_deploy_delegation_only_with_poller_ticket(preflight, monkeypatch, capsys, action):
    monkeypatch.setenv(DDB.TICKET_ENV, "/fixture/ticket.json")
    rc, out, _ = _run_preflight(preflight.P, monkeypatch, capsys, "--action", action, "--sha", SHA)
    assert rc == 0 and out["allowed"] is True
    assert out["binding_source"] == "deploy_delegation" and out["matched_by"] == ["deploy_delegation"]
    assert out["consumed"] == {"skipped": "deploy_delegation"}
    assert D._binding_of(json.dumps(out)) == "deploy_delegation"


def test_preflight_without_ticket_is_unchanged_refusal(preflight, monkeypatch, capsys):
    monkeypatch.delenv(DDB.TICKET_ENV, raising=False)
    rc, out, err = _run_preflight(preflight.P, monkeypatch, capsys, "--action", "prepare", "--sha", SHA)
    assert rc == 2 and out["allowed"] is False and preflight.calls == []
    assert "RELEASE GRANT BINDING: REFUSED" in err
    assert D._binding_of(json.dumps(out)) == "none"


def test_preflight_never_uses_delegation_for_rollback(preflight, monkeypatch, capsys):
    monkeypatch.setenv(DDB.TICKET_ENV, "/fixture/ticket.json")
    rc, _, _ = _run_preflight(preflight.P, monkeypatch, capsys, "--action", "rollback", "--sha", SHA)
    assert rc == 2 and preflight.calls == []


# ── alert delivery truth ────────────────────────────────────────────────────────────────────


def test_page_p1_records_transport_truth_not_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    fake = ModuleType("scripts.telegram_alert")
    sent = []
    fake.send_telegram = lambda text, **kw: sent.append((text, kw)) or True
    fake.delivery_outcome = lambda accepted: {"status": "HELD", "delivered": False, "accepted": accepted}
    monkeypatch.setitem(sys.modules, "scripts.telegram_alert", fake)
    from scripts.delivery_failure_alerts import page_p1

    row = page_p1(kind="deploy_on_main", message="fixture")
    assert row["accepted"] is True and row["delivered"] is False and row["delivery_status"] == "HELD"
    assert sent[0][1]["priority"] == "P1" and sent[0][1]["dedupe_minutes"] == 0
    row = page_p1(kind="deploy_on_main_recovered", message="ok", priority="P2", resolving=True)
    assert sent[1][0].startswith("[P2]") and sent[1][1]["resolving"] is True


def test_ci_gate_registers_this_file():
    from scripts.lib.ci_gates import validate

    path = ROOT / "config/ci_gates/deploy_on_main_autonomy_20261027.json"
    gate = validate(json.loads(path.read_text()), stem=path.stem)
    assert gate["files"] == ["tests/test_deploy_on_main_autonomy_20261027.py"]


@pytest.mark.parametrize("evidence,state", [
    ({"ok": True, "errors": [], "checks": []}, "green"),
    ({"ok": False, "errors": ["missing:.github/workflows/agent-governance.yml"], "checks": []}, "pending"),
    ({"ok": False, "errors": ["not_successful:x"], "checks": [{"status": "in_progress", "conclusion": None}]}, "pending"),
    ({"ok": False, "errors": ["not_successful:x"], "checks": [{"status": "completed", "conclusion": "failure"}]}, "red"),
    ({"ok": False, "errors": ["checks_unavailable:OSError"], "checks": []}, "unavailable"),
])
def test_main_checks_status_classifies_exact_sha_evidence(tmp_path, monkeypatch, evidence, state):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/release_grant_preflight.py").write_text(
        "import json\nprint(json.dumps(" + repr(evidence) + "))\n")
    monkeypatch.delenv("TRADEAI_PY", raising=False)
    assert D.main_checks_status(tmp_path, SHA)[0] == state
