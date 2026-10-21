"""Release train (operator plan approved 2026-10-21): scripts/release_window.py as the train's release step.

What 2026-10-21 taught (seven one-at-a-time releases, grants exhausted):
  * the window runner required only 2 of main's 3 required checks (release-readiness was not required), so an
    `ok` evidence with release-readiness missing or still running looked green;
  * a merge in the ~45 min before a window meant no release at all (head CI pending, no fallback);
  * a promote refused by the exact-SHA CI check had already consumed a release-write use, because
    cio_phase2_exact_main_deploy.sh ran the consuming grant preflight BEFORE the CI check (71df62acc,
    deploy_receipt extra=post_merge_ci_refused, 2026-10-21T18:43Z).

Hermetic: fake host, tmp_path state and HOME, a tmp git repo for the deploy-script tests, a fake interpreter that
only logs its argv. No gh, systemctl, guard ledger, network or production path is touched (AGENTS §24.6).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import release_window as RW  # noqa: E402
from scripts.lib import needs_action as NA  # noqa: E402
from scripts.lib import release_grant_binding as B  # noqa: E402
from tests.test_release_window_20261016 import BASE, HEAD, NOON, FakeHost, deploys, grant, runner  # noqa: E402

ET = RW.TZ
MID = "5f0ea5b8c0000000000000000000000000000001"     # first-parent commit between BASE and HEAD
OLDER = "5f0ea5b8c0000000000000000000000000000002"
WF_CIO = ".github/workflows/cio-production-hardening-ci.yml"
WF_GOV = ".github/workflows/agent-governance.yml"
WF_RR = ".github/workflows/release-readiness.yml"


def run(path, status="completed", conclusion="success"):
    return {"path": path, "status": status, "conclusion": conclusion}


def evidence(sha, checks, errors=None):
    errors = list(errors or [])
    for c in checks:
        if c["status"] != "completed" or c["conclusion"] != "success":
            errors.append("not_successful:" + c["path"])
    return {"ok": not errors, "candidate_sha": sha, "errors": errors, "checks": checks}


def green3(sha):
    return evidence(sha, [run(WF_CIO), run(WF_GOV), run(WF_RR)])


def head_pending(sha):
    return evidence(sha, [run(WF_CIO, "in_progress", None), run(WF_GOV), run(WF_RR)])


_DEFAULT_CHAIN = object()


class TrainHost(FakeHost):
    """The 2026-10-16 fake host plus a first-parent chain, per-SHA CI, CC GETs and the comms intent."""

    def __init__(self, tmp, *, ci_by_sha=None, chain=_DEFAULT_CHAIN, http=None, **kw):
        super().__init__(tmp, **kw)
        self.ci_by_sha = ci_by_sha if ci_by_sha is not None else {HEAD: green3(HEAD)}
        self.chain = [HEAD, MID, OLDER] if chain is _DEFAULT_CHAIN else chain
        self.http = dict(http or {})
        self.notified: list[tuple[str, str]] = []
        for sha in (MID, OLDER):
            self.sha_of.setdefault(self.releases / f"{sha[:9]}-main-exact-phase2-new", sha)

    def ci_evidence(self, sha):
        self.calls.append(("ci", sha))
        return self.ci_by_sha.get(sha) or evidence(sha, [], ["missing:" + WF_CIO])

    def first_parent_chain(self, head, base, limit):
        self.calls.append(("chain", head, base))
        return list(self.chain) if self.chain is not None else None

    def run_deploy(self, args, env):
        if args[0] == "prepare":
            sha = env.get("TRADEAI_RELEASE_TRAIN_SHA") or self.head
            self.new = self.releases / f"{sha[:9]}-main-exact-phase2-new"
            self.sha_of[self.new] = sha
        self.calls.append(("train_env", args[0], env.get("TRADEAI_RELEASE_TRAIN_SHA")))
        return super().run_deploy(args, env)

    def http_get(self, url):
        for suffix, answer in self.http.items():
            if url.endswith(suffix):
                return answer
        if url.endswith("/api/v2/system/platform-health"):
            return 200, '{"schema": "PlatformHealth@v1", "status": "OK", "overall": "OK"}'
        if url.endswith("/api/v2/needs-action"):
            return 200, '{"schema": "NeedsAction@v1", "counts": {"P0": 0, "P1": 1}, "total": 1}'
        return 200, "<!doctype html><div id=root></div>"

    def notify(self, message, priority):
        self.notified.append((priority, message))
        return {"accepted": True, "priority": priority}


def train_runner(tmp_path, host, env=None):
    return RW.Runner(host, RW.State(tmp_path / "state"), env=env or {}, units=("portfolio-server.service",),
                     health_attempts=2, health_sleep_s=0)


# ── 1. exact-SHA verdict on all three required checks ─────────────────────────────────────────────

def test_required_checks_are_the_three_branch_protection_contexts():
    assert set(RW.REQUIRED_TRAIN_WORKFLOWS) == {WF_CIO, WF_GOV, WF_RR}


def test_evidence_ok_without_release_readiness_is_not_green():
    # The weak logic: evaluate_push_checks only REQUIRES two workflows, so ok=True with release-readiness absent.
    ev = evidence(HEAD, [run(WF_CIO), run(WF_GOV)])
    assert ev["ok"] is True
    assert RW.train_ci_verdict(ev) == "STOP_CI_PENDING"


@pytest.mark.parametrize("conclusion", ["neutral", "skipped", "cancelled", "timed_out", "action_required", None,
                                        "failure", "stale", ""])
def test_anything_but_literal_success_on_a_completed_required_check_is_not_green(conclusion):
    ev = {"ok": True, "candidate_sha": HEAD, "errors": [],
          "checks": [run(WF_CIO), run(WF_GOV), run(WF_RR, "completed", conclusion)]}
    assert RW.train_ci_verdict(ev) == "STOP_CI_NOT_GREEN"


def test_in_flight_required_check_is_pending_and_unavailable_is_not_green():
    assert RW.train_ci_verdict(head_pending(HEAD)) == "STOP_CI_PENDING"
    ev = green3(HEAD)
    ev["errors"], ev["ok"] = ["checks_unavailable:CalledProcessError"], False
    assert RW.train_ci_verdict(ev) == "STOP_CI_NOT_GREEN"
    assert RW.train_ci_verdict(green3(HEAD)) == "GREEN"


def test_a_red_optional_push_workflow_still_blocks():
    ev = evidence(HEAD, [run(WF_CIO), run(WF_GOV), run(WF_RR), run(".github/workflows/provider-cost-ci.yml",
                                                                    "completed", "failure")])
    assert RW.train_ci_verdict(ev) == "STOP_CI_NOT_GREEN"


# ── 2. selection: head if green, else newest green first-parent commit since the last release ─────

def test_green_head_is_selected(tmp_path):
    host = TrainHost(tmp_path)
    code, rec = train_runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_OK and rec["outcome"] == "RELEASED", rec
    assert rec["candidate"]["sha"] == HEAD and rec["candidate"]["selected_by"] == "head_green"
    assert ("train_env", "prepare", None) in host.calls          # head: the deploy's latest-main rule, unchanged


def test_pending_head_falls_back_to_newest_green_since_last_release(tmp_path):
    host = TrainHost(tmp_path, ci_by_sha={HEAD: head_pending(HEAD), MID: green3(MID), OLDER: green3(OLDER)})
    code, rec = train_runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_OK and rec["outcome"] == "RELEASED", rec
    cand = rec["candidate"]
    assert cand["sha"] == MID and cand["selected_by"] == "fallback_newest_green"
    assert cand["head"] == HEAD and cand["head_ci_verdict"] == "STOP_CI_PENDING"
    assert ("train_env", "prepare", MID) in host.calls and ("train_env", "promote", MID) in host.calls
    assert ("ci", OLDER) not in host.calls                       # newest green wins; older never queried
    assert rec["verification"]["build_sha"]["expected"] == MID


def test_nothing_green_stops_without_deploy_and_names_every_sha_tried(tmp_path):
    host = TrainHost(tmp_path, ci_by_sha={HEAD: head_pending(HEAD), MID: head_pending(MID),
                                          OLDER: evidence(OLDER, [run(WF_CIO, "completed", "failure")])})
    code, rec = train_runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_STOPPED and rec["outcome"] == "STOP_CI_PENDING"
    assert deploys(host) == []
    assert [s["sha"] for s in rec["candidate"]["tried"]] == [HEAD, MID, OLDER]


def test_no_fallback_when_the_served_release_is_not_on_mains_first_parent_chain(tmp_path):
    host = TrainHost(tmp_path, ci_by_sha={HEAD: head_pending(HEAD), MID: green3(MID)}, chain=None)
    code, rec = train_runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_STOPPED and deploys(host) == []
    assert "fallback_unavailable" in rec["candidate"]


def test_a_train_sha_set_from_outside_is_a_bypass(tmp_path):
    host = TrainHost(tmp_path)
    code, body = train_runner(tmp_path, host, env={"TRADEAI_RELEASE_TRAIN_SHA": MID}).run("1200")
    assert code == RW.EXIT_REFUSED and body["outcome"] == "REFUSED_BYPASS_ENV" and host.calls == []


def test_plan_quotes_the_fallback_pick_and_writes_nothing(tmp_path):
    host = TrainHost(tmp_path, ci_by_sha={HEAD: head_pending(HEAD), MID: green3(MID)})
    code, rec = train_runner(tmp_path, host).plan("1730", now=datetime(2026, 10, 16, 9, 0, tzinfo=ET))
    assert rec["candidate"]["sha"] == MID and rec["candidate"]["selected_by"] == "fallback_newest_green"
    assert deploys(host) == [] and host.notified == [] and not (tmp_path / "state").exists()


# ── 3. verification: pages 200, platform-health, needs-action ─────────────────────────────────────

@pytest.mark.parametrize("suffix,answer,check", [
    ("/api/v2/system/platform-health", (500, "boom"), "platform_health"),
    ("/api/v2/system/platform-health", (200, '{"schema": "PlatformHealth@v1", "status": "UNAVAILABLE"}'),
     "platform_health"),
    ("/api/v2/needs-action", (401, "unauthorized"), "needs_action"),
    ("/api/v2/needs-action", (200, "not json"), "needs_action"),
    ("/v3/", (404, "missing"), "pages"),
])
def test_each_new_verification_fails_the_window_and_rolls_back(tmp_path, suffix, answer, check):
    host = TrainHost(tmp_path, http={suffix: answer})
    code, rec = train_runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_ROLLED_BACK and rec["verification"][check]["ok"] is False, rec["verification"]
    assert deploys(host)[-1][1][0] == "rollback"


def test_released_receipt_carries_the_new_checks(tmp_path):
    host = TrainHost(tmp_path)
    code, rec = train_runner(tmp_path, host).run("1200")
    v = rec["verification"]
    assert v["platform_health"]["ok"] and v["platform_health"]["overall"] == "OK"
    assert v["needs_action"]["ok"] and v["needs_action"]["counts"] == {"P0": 0, "P1": 1}
    assert v["pages"]["ok"] and set(v["pages"]["status"]) == set(RW.VERIFY_PAGES)


# ── 4. one receipt per window; Needs-action item + comms intent on failure ────────────────────────

def test_rollback_sends_one_p1_intent_and_leaves_a_needs_action_item(tmp_path):
    host = TrainHost(tmp_path, health=(502,))
    r = train_runner(tmp_path, host)
    code, rec = r.run("1200")
    assert code == RW.EXIT_ROLLED_BACK
    assert len(host.notified) == 1 and host.notified[0][0] == "P1"
    assert "ROLLED_BACK" in host.notified[0][1] and HEAD[:9] in host.notified[0][1]
    assert rec["notification"]["accepted"] is True
    assert rec["needs_action_item"]["severity"] == "P1"
    receipts = list((tmp_path / "state" / "windows").glob("*.json"))
    assert [p.name for p in receipts] == ["20261016-1200.json"]
    items = NA.rule_release_window(NA.read_release_window_state(tmp_path / "state"), NOON.astimezone(timezone.utc))
    assert {i["severity"] for i in items} == {"P1"} and any("STOP" in i["title"] for i in items)


def test_ci_pending_window_does_not_page(tmp_path):
    host = TrainHost(tmp_path, ci_by_sha={HEAD: head_pending(HEAD)}, chain=[HEAD])
    code, rec = train_runner(tmp_path, host).run("1200")
    assert rec["outcome"] == "STOP_CI_PENDING" and host.notified == []


def test_ci_red_window_is_a_p2_intent(tmp_path):
    host = TrainHost(tmp_path, ci_by_sha={HEAD: evidence(HEAD, [run(WF_RR, "completed", "failure")])}, chain=[HEAD])
    code, rec = train_runner(tmp_path, host).run("1200")
    assert rec["outcome"] == "STOP_CI_NOT_GREEN" and [p for p, _ in host.notified] == ["P2"]


def test_needs_action_rule_is_quiet_after_a_release_and_when_never_run(tmp_path):
    now = NOON.astimezone(timezone.utc)
    assert NA.rule_release_window(NA.read_release_window_state(tmp_path / "absent"), now) == []
    assert NA.rule_release_window({"latch": None, "last": {"outcome": "RELEASED",
                                                            "finished_at": now.isoformat()}}, now) == []
    old = (now - timedelta(hours=72)).isoformat()
    assert NA.rule_release_window({"latch": None, "last": {"outcome": "STOP_PREPARE_FAILED",
                                                            "finished_at": old}}, now) == []
    assert "release_window" in NA.RULES


# ── 5. per-window campaign grant: both spellings of the window bind ───────────────────────────────

@pytest.mark.parametrize("token", ["RELEASE_WINDOW release-window-20261016-1200",
                                   "RELEASE_WINDOW 20261016 1200", "RELEASE_WINDOW 2026-10-16 12:00"])
def test_binding_accepts_a_release_window_campaign_grant(token):
    reason = f"{token} actions=prepare,promote,verify,rollback stop=verify_failed,rolled_back,ci_not_green"
    act = B.ReleaseAction(action="promote", target_sha=MID, campaign="release-window-20261016-1200",
                          now=NOON.timestamp())
    v = B.decide(act, grants=[grant(reason=reason)])
    assert v.allowed and v.matched_by == ["campaign:release-window-20261016-1200"], v.to_dict()
    w = RW.window_for(NOON, "1200")
    gv = RW.grant_verdict(w, MID, [grant(reason=reason)], now_ts=NOON.timestamp())
    assert gv["ok"], gv["errors"]


def test_window_token_for_another_window_does_not_bind():
    reason = "RELEASE_WINDOW 2026-10-16 17:30 actions=prepare,promote stop=verify_failed,rolled_back,ci_not_green"
    act = B.ReleaseAction(action="promote", target_sha=MID, campaign="release-window-20261016-1200",
                          now=NOON.timestamp())
    assert not B.decide(act, grants=[grant(reason=reason)]).allowed
    # and a window grant never binds a release run outside the window runner (no campaign exported)
    act2 = B.ReleaseAction(action="promote", target_sha=MID, now=NOON.timestamp())
    assert not B.decide(act2, grants=[grant(reason=reason.replace("17:30", "12:00"))]).allowed


# ── 6. a promote refused by exact-SHA CI consumes no release-write use ────────────────────────────

FAKE_PY = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
case " $* " in
  *" --ci-only "*) exit "${FAKE_CI_RC:-2}" ;;
esac
if [[ "$*" == *release_grant_preflight.py* ]]; then
  if [[ "$*" == *"--no-consume"* ]]; then exit 0; fi
  exit "${FAKE_CONSUME_RC:-2}"
fi
exit 0
"""


def _deploy_sandbox(tmp_path):
    """A copy of the deploy script whose ROOT is a tmp tree; HOME, releases and state are tmp."""
    root = tmp_path / "root"
    (root / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh", root / "scripts")
    shutil.copy2(ROOT / "scripts" / "lib" / "release_venv.sh", root / "scripts" / "lib")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("fakepy", "python3"):
        p = bindir / name
        p.write_text(FAKE_PY, encoding="utf-8")
        p.chmod(0o755)
    canonical = tmp_path / "canonical"
    (canonical / "scripts").mkdir(parents=True)
    (canonical / "scripts" / "release_grant_preflight.py").write_text("# presence only\n", encoding="utf-8")
    home = tmp_path / "home"
    rel = home / "trade-ai-releases" / "portfolio-server"
    prev, new = rel / "prev", rel / "new"
    for d, sha in ((prev, BASE), (new, HEAD)):
        d.mkdir(parents=True)
        (d / "BUILD_SHA").write_text(sha + "\n", encoding="utf-8")
    (rel / "CURRENT").symlink_to(prev)
    log = tmp_path / "py.log"
    env = {"PATH": f"{bindir}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(home), "TRADE_AI_CI": "1",
           "VENV_PYTHON": str(bindir / "fakepy"), "CANONICAL_SOURCE": str(canonical), "FAKE_LOG": str(log)}
    return root, env, log, new, rel


def _calls(log):
    return [ln for ln in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def test_promote_refused_by_ci_consumes_no_grant_use(tmp_path):
    root, env, log, new, rel = _deploy_sandbox(tmp_path)
    p = subprocess.run(["bash", str(root / "scripts" / "cio_phase2_exact_main_deploy.sh"), "promote", str(new)],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0
    calls = [c for c in _calls(log) if "release_grant_preflight.py" in c]
    assert any("--ci-only" in c for c in calls), calls
    consuming = [c for c in calls if "--action promote" in c and "--no-consume" not in c]
    assert consuming == [], f"a CI-refused promote consumed a release-write use: {calls}"
    assert [c for c in calls if "--no-consume" in c], "the binding must still be checked before CI"
    assert os.readlink(rel / "CURRENT").endswith("prev")


def test_promote_consumes_only_after_ci_passes_and_before_activation(tmp_path):
    root, env, log, new, rel = _deploy_sandbox(tmp_path)
    env.update(FAKE_CI_RC="0", FAKE_CONSUME_RC="2")       # CI green; the consuming call refuses, so we stop there
    p = subprocess.run(["bash", str(root / "scripts" / "cio_phase2_exact_main_deploy.sh"), "promote", str(new)],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0 and "release grant binding refused promote" in p.stderr
    calls = [c for c in _calls(log) if "release_grant_preflight.py" in c]
    order = ["no-consume" if "--no-consume" in c else "ci" if "--ci-only" in c else "consume" for c in calls]
    assert order == ["no-consume", "ci", "consume"], calls
    assert os.readlink(rel / "CURRENT").endswith("prev")       # never activated


def test_preflight_no_consume_never_touches_the_ledger(tmp_path, monkeypatch, capsys):
    from scripts import release_grant_preflight as P

    reason = "RELEASE_WINDOW 2026-10-16 12:00 actions=prepare,promote stop=verify_failed,rolled_back,ci_not_green"
    gpath = tmp_path / "grants.json"
    gpath.write_text('{"release-write": {"expires": 99999999999, "uses": 3, "reason": "%s", "grant_id": "g1"}}'
                     % reason, encoding="utf-8")
    monkeypatch.setattr(B, "GRANTS_PATH", gpath)
    monkeypatch.setattr(B, "REQUESTS_PATH", tmp_path / "none.json")
    monkeypatch.setattr(P, "decide_from_disk", lambda act: B.decide_from_disk(act, grants_path=gpath,
                                                                              requests_path=tmp_path / "none.json"))
    consumed = []
    monkeypatch.setattr(P, "consume_release_grant", lambda **kw: consumed.append(1) or {"ok": True})
    monkeypatch.setattr(sys, "argv", ["p", "--action", "promote", "--sha", MID, "--no-consume",
                                      "--campaign", "release-window-20261016-1200"])
    assert P.main() == 0 and consumed == []
    assert '"consumed": {"skipped": "no_consume"' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["p", "--action", "promote", "--sha", MID,
                                      "--campaign", "release-window-20261016-1200"])
    assert P.main() == 0 and consumed == [1]


# ── 7. the deploy script prepares a train SHA only if it is a clean first-parent main commit ──────

def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})
    return subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _train_repo(tmp_path, root):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", str(origin))
    (root / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    c1 = _git(root, "commit", "-q", "-m", "c1")
    _git(root, "checkout", "-q", "-b", "side")
    side = _git(root, "commit", "-q", "--allow-empty", "-m", "side work")
    _git(root, "checkout", "-q", "main")
    c2 = _git(root, "commit", "-q", "--allow-empty", "-m", "c2")
    _git(root, "merge", "-q", "--no-ff", "side", "-m", "Merge pull request #1 from x/side")
    head = _git(root, "push", "-q", "origin", "main")
    return c1, c2, side, head


@pytest.mark.parametrize("which,expect_ok", [("c2", True), ("side", False), ("head", True)])
def test_prepare_accepts_a_train_sha_only_on_the_first_parent_chain(tmp_path, which, expect_ok):
    root, env, log, _new, _rel = _deploy_sandbox(tmp_path)
    c1, c2, side, head = _train_repo(tmp_path, root)
    sha = {"c2": c2, "side": side, "head": head}[which]
    _git(root, "checkout", "-q", "--detach", sha)
    env.update(TRADEAI_RELEASE_TRAIN_SHA=sha, FAKE_CI_RC="0", FAKE_CONSUME_RC="2")
    p = subprocess.run(["bash", str(root / "scripts" / "cio_phase2_exact_main_deploy.sh"), "prepare"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0                                    # the fake binding refuses: we stop before a build
    if expect_ok:
        assert "release grant binding refused prepare of " + sha in p.stderr, p.stderr
        assert any("--ci-only" in c and sha in c for c in _calls(log))
    else:
        assert "not on origin/main's first-parent history" in p.stderr, p.stderr


def test_prepare_refuses_a_train_sha_whose_ci_is_not_green(tmp_path):
    root, env, log, _new, _rel = _deploy_sandbox(tmp_path)
    c1, c2, side, head = _train_repo(tmp_path, root)
    _git(root, "checkout", "-q", "--detach", c2)
    env.update(TRADEAI_RELEASE_TRAIN_SHA=c2, FAKE_CI_RC="2")
    p = subprocess.run(["bash", str(root / "scripts" / "cio_phase2_exact_main_deploy.sh"), "prepare"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0 and "exact-SHA CI is not green" in p.stderr, p.stderr
    assert not [c for c in _calls(log) if "--action prepare" in c]


def test_prepare_refuses_train_and_emergency_together(tmp_path):
    root, env, log, _new, _rel = _deploy_sandbox(tmp_path)
    c1, c2, side, head = _train_repo(tmp_path, root)
    _git(root, "checkout", "-q", "--detach", c2)
    env.update(TRADEAI_RELEASE_TRAIN_SHA=c2, TRADEAI_EMERGENCY_RELEASE_SHA=c2)
    p = subprocess.run(["bash", str(root / "scripts" / "cio_phase2_exact_main_deploy.sh"), "prepare"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0 and "both set" in p.stderr, p.stderr


# ── 8. fail-closed STOP latch (Release Train v2 Phase 0, 2026-10-21) ─────────────────────────────

def _damage_latch(state_root: Path, kind: str) -> Path:
    state_root.mkdir(parents=True, exist_ok=True)
    latch = state_root / "STOP.json"
    if kind == "corrupt":
        latch.write_text('{"latched_at": "2026-10-21T18:00:00Z", "outcome": "ROLLED_BA', encoding="utf-8")
    elif kind == "non_object":
        latch.write_text('["ROLLED_BACK"]', encoding="utf-8")
    elif kind == "unreadable":
        latch.write_text('{"outcome": "ROLLED_BACK"}', encoding="utf-8")
        latch.chmod(0o000)
    elif kind == "directory":
        latch.mkdir()
    else:
        raise AssertionError(kind)
    return latch


@pytest.mark.parametrize("kind", ["corrupt", "non_object", "unreadable", "directory"])
def test_unreadable_stop_latch_refuses_every_mutating_path(tmp_path, kind):
    latch = _damage_latch(tmp_path / "state", kind)
    try:
        if kind == "unreadable" and os.access(latch, os.R_OK):
            pytest.skip("running as a user that can read a mode-000 file (root)")
        host = TrainHost(tmp_path)
        r = train_runner(tmp_path, host)
        code, body = r.run("1200")
        assert code == RW.EXIT_REFUSED and body["outcome"] == "REFUSED_STOP_UNREADABLE", body
        assert host.calls == [] and deploys(host) == [] and host.notified == []     # no prepare, no promote
        code, body = r.plan("1200")
        assert code == RW.EXIT_REFUSED and body["outcome"] == "REFUSED_STOP_UNREADABLE"
        _, st = r.status()
        assert st["latch_state"] == "UNREADABLE" and st["latch"]["error"]
        items = NA.rule_release_window(NA.read_release_window_state(tmp_path / "state"),
                                       NOON.astimezone(timezone.utc))
        assert [i["severity"] for i in items] == ["P1"] and "unreadable" in items[0]["title"]
    finally:
        if latch.exists() and not latch.is_dir():
            latch.chmod(0o600)


def test_missing_latch_is_no_stop_and_readable_latch_is_stop(tmp_path):
    r = train_runner(tmp_path, TrainHost(tmp_path))
    assert r.state.read_latch() == ("ABSENT", None)
    assert r.status()[1]["latch_state"] == "ABSENT"
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "STOP.json").write_text('{"outcome": "ROLLED_BACK"}', encoding="utf-8")
    assert r.state.read_latch() == ("SET", {"outcome": "ROLLED_BACK"})
    assert r.run("1200")[1]["outcome"] == "REFUSED_STOP_LATCHED"


def test_clear_stop_archives_an_unreadable_latch(tmp_path):
    _damage_latch(tmp_path / "state", "directory")
    r = train_runner(tmp_path, TrainHost(tmp_path))
    code, body = r.clear_stop("operator inspected the damaged latch")
    assert body["outcome"] == "STOP_CLEARED" and body["latch_state"] == "UNREADABLE"
    assert not (tmp_path / "state" / "STOP.json").exists()
    assert list((tmp_path / "state" / "windows").glob("STOP-*.json.archived"))       # archived, not deleted
    assert r.state.read_latch() == ("ABSENT", None)


# ── 9. TRADEAI_RELEASE_TRAIN_SHA identifies, never authorizes ─────────────────────────────────────
#
# Audit (2026-10-21): the variable is read in exactly two deploy-script functions, git_sha (which SHA prepare
# stamps) and require_head_is_origin_main (which ADDS checks: 40-hex, HEAD match, clean tree, first-parent of
# origin/main, exact-SHA CI green, never with the emergency SHA). The release-write binding (prepare and both
# promote calls), conformance and promote's CI re-query never read it. release_window.py only refuses it from
# its own environment (GUARDED_ENV) and sets it for a fallback candidate it already qualified.

REAL_PY_SHIM = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
case " $* " in
  *" --ci-only "*) exit "${FAKE_CI_RC:-2}" ;;
esac
if [[ "$*" == *release_grant_preflight.py* ]]; then exec "$REAL_PY" "$@"; fi
exit 0
"""


def _real_binding_sandbox(tmp_path, grants: dict):
    """The deploy sandbox, but the release-write binding is the REAL preflight against a tmp grant ledger."""
    root, env, log, new, rel = _deploy_sandbox(tmp_path)
    canonical = Path(env["CANONICAL_SOURCE"])
    (canonical / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scripts" / "release_grant_preflight.py", canonical / "scripts")
    shutil.copy2(ROOT / "scripts" / "lib" / "release_grant_binding.py", canonical / "scripts" / "lib")
    (canonical / "scripts" / "lib" / "__init__.py").write_text("", encoding="utf-8")
    shim = Path(env["VENV_PYTHON"])
    shim.write_text(REAL_PY_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    _write_grants(tmp_path, grants)
    env.update(REAL_PY=sys.executable, TRADEAI_GUARD_GRANTS_PATH=str(tmp_path / "grants.json"),
               TRADEAI_GUARD_REQUESTS_PATH=str(tmp_path / "no-requests.json"))
    return root, env, log, new, rel


def _write_grants(tmp_path, grants: dict):
    import json as _json

    (tmp_path / "grants.json").write_text(_json.dumps(grants), encoding="utf-8")


def _run_deploy(root, env, *args):
    return subprocess.run(["bash", str(root / "scripts" / "cio_phase2_exact_main_deploy.sh"), *args],
                          env=env, capture_output=True, text=True, timeout=120)


def _grant_naming(text):
    return {"release-write": {"expires": 99999999999, "uses": 3, "grant_id": "g-test", "reason": text}}


def test_train_sha_with_no_grant_is_refused_at_prepare(tmp_path):
    root, env, log, _new, _rel = _real_binding_sandbox(tmp_path, {})
    c1, c2, side, head = _train_repo(tmp_path, root)
    _git(root, "checkout", "-q", "--detach", c2)
    env.update(TRADEAI_RELEASE_TRAIN_SHA=c2, FAKE_CI_RC="0")          # qualified commit, CI green, NO grant
    p = _run_deploy(root, env, "prepare")
    assert p.returncode != 0 and "release grant binding refused prepare of " + c2 in p.stderr, p.stderr
    assert '"allowed": false' in p.stdout and "PREPARE OK" not in p.stdout


def test_train_sha_with_a_grant_for_another_release_is_refused(tmp_path):
    root, env, log, _new, _rel = _real_binding_sandbox(
        tmp_path, _grant_naming("Operator: release PR #1906 sha 7faa8cddf37c prepare promote"))
    c1, c2, side, head = _train_repo(tmp_path, root)
    _git(root, "checkout", "-q", "--detach", c2)
    env.update(TRADEAI_RELEASE_TRAIN_SHA=c2, FAKE_CI_RC="0")
    p = _run_deploy(root, env, "prepare")
    assert p.returncode != 0 and "release grant binding refused prepare" in p.stderr, p.stderr


@pytest.mark.parametrize("which,ci_rc,needle", [
    ("c2", "2", "exact-SHA CI is not green"),
    ("side", "0", "not on origin/main's first-parent history"),
])
def test_train_sha_with_a_valid_grant_still_needs_green_ci_and_first_parent(tmp_path, which, ci_rc, needle):
    root, env, log, _new, _rel = _real_binding_sandbox(tmp_path, {})
    c1, c2, side, head = _train_repo(tmp_path, root)
    sha = {"c2": c2, "side": side}[which]
    _write_grants(tmp_path, _grant_naming(f"release sha {sha} prepare promote"))
    _git(root, "checkout", "-q", "--detach", sha)
    env.update(TRADEAI_RELEASE_TRAIN_SHA=sha, FAKE_CI_RC=ci_rc)
    p = _run_deploy(root, env, "prepare")
    assert p.returncode != 0 and needle in p.stderr, p.stderr
    assert not [c for c in _calls(log) if "--action prepare" in c]     # refused before the binding is consulted


@pytest.mark.parametrize("grant_named,ci_rc,needle", [
    (False, "0", "release grant binding refused promote"),
    (True, "2", "activation refused"),
])
def test_train_sha_in_the_environment_does_not_relax_promote(tmp_path, grant_named, ci_rc, needle):
    # promote never reads the variable: binding (before CI), conformance and the exact-SHA CI re-query all run.
    root, env, log, new, rel = _real_binding_sandbox(tmp_path, {})
    if grant_named:
        _write_grants(tmp_path, _grant_naming(f"release sha {HEAD} prepare promote"))
    env.update(TRADEAI_RELEASE_TRAIN_SHA=HEAD, FAKE_CI_RC=ci_rc)
    p = _run_deploy(root, env, "promote", str(new))
    assert p.returncode != 0 and needle in p.stderr, p.stderr
    assert os.readlink(rel / "CURRENT").endswith("prev")


def test_train_sha_is_read_only_by_git_sha_and_require_head():
    """Static audit: no other function of the deploy script reads TRAIN_SHA / TRADEAI_RELEASE_TRAIN_SHA."""
    import re as _re

    text = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text(encoding="utf-8")
    func = None
    readers = set()
    for line in text.splitlines():
        m = _re.match(r"^([a-z_]+)\(\) *\{", line)
        if m:
            func = m.group(1)
        code = line.split("#", 1)[0]
        if _re.search(r"\$\{?TRAIN_SHA|TRADEAI_RELEASE_TRAIN_SHA:-", code):
            readers.add(func)
        if line.startswith("}") or (m and line.rstrip().endswith("}")):
            func = None
    assert readers == {None, "git_sha", "require_head_is_origin_main"}, readers     # None = the one assignment
    rw = (ROOT / "scripts" / "release_window.py").read_text(encoding="utf-8")
    assert rw.count('"TRADEAI_RELEASE_TRAIN_SHA"') == 2       # GUARDED_ENV (refuse from outside) + deploy_env (set)
