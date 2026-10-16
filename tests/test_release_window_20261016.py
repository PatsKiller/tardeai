"""Release windows (operator 2026-10-16): scripts/release_window.py.

Hermetic: a fake host (no git, gh, systemctl, guard ledger or network) and a tmp_path state dir. Replays the
2026-10-16 overnight refusal (main moved a7fc2175b -> 94ee3770a between selection and prepare).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import release_window as RW  # noqa: E402

ET = RW.TZ
NOON = datetime(2026, 10, 16, 12, 5, tzinfo=ET)
HEAD = "94ee3770a65f7e67e574bd61a04dc350f098e56f"
BASE = "11b469ffe0000000000000000000000000000000"
GOOD_REASON = ("RELEASE_WINDOW release-window-20261016-1200 actions=prepare,promote,verify,rollback "
               "stop=verify_failed,rolled_back,ci_not_green scope=exact origin/main head with green main CI")


def grant(reason=GOOD_REASON, uses=3, expires_in=7200, gid="g-window-1200"):
    return {"tier": "release-write", "grant_id": gid, "reason": reason, "uses": uses,
            "expires": NOON.timestamp() + expires_in}


def green(sha=HEAD):
    return {"ok": True, "candidate_sha": sha, "errors": [], "checks": [
        {"path": ".github/workflows/cio-production-hardening-ci.yml", "status": "completed", "conclusion": "success"},
        {"path": ".github/workflows/agent-governance.yml", "status": "completed", "conclusion": "success"}]}


def pending(sha=HEAD):
    return {"ok": False, "candidate_sha": sha, "errors": ["not_successful:.github/workflows/cio-production-hardening-ci.yml"],
            "checks": [{"path": ".github/workflows/cio-production-hardening-ci.yml", "status": "in_progress",
                        "conclusion": None}]}


def red(sha=HEAD):
    return {"ok": False, "candidate_sha": sha, "errors": ["not_successful:.github/workflows/agent-governance.yml"],
            "checks": [{"path": ".github/workflows/agent-governance.yml", "status": "completed", "conclusion": "failure"}]}


class FakeHost:
    def __init__(self, tmp: Path, *, head=HEAD, ci=None, grants=None, prepare_out=None, prepare_rc=0,
                 promote_rc=0, health=(200,), units_after=None, served_rc=0, rollback_rc=0,
                 deploy_rolls_back=False):
        self.tmp = tmp
        self.releases = tmp / "releases"
        self.prev = self.releases / f"{BASE[:9]}-main-exact-phase2-prev"
        self.new = self.releases / f"{head[:9]}-main-exact-phase2-new"
        self.cur = self.prev
        self.sha_of = {self.prev: BASE, self.new: head}
        self.head = head
        self.ci = ci if ci is not None else green(head)
        self._grants = [grant()] if grants is None else grants
        self.prepare_out = prepare_out
        self.prepare_rc, self.promote_rc, self.rollback_rc = prepare_rc, promote_rc, rollback_rc
        self.health = list(health)
        self.units_after = units_after
        self.served_rc = served_rc
        self.deploy_rolls_back = deploy_rolls_back
        self.calls: list[tuple] = []
        self.revoked = 0

    def now(self):
        return NOON.astimezone(timezone.utc)

    def main_head(self):
        return self.head

    def current_release(self):
        return self.cur

    def build_sha(self, release):
        return self.sha_of.get(Path(release), "")

    def commit_messages(self, base, head):
        return ["Merge pull request #1813 from x/y\n\nbody", "Merge pull request #1809 from x/z", "fix thing (#1811)",
                "plain commit"]

    def ci_evidence(self, sha):
        self.calls.append(("ci", sha))
        return self.ci

    def grants(self):
        return list(self._grants)

    def requests(self):
        return []

    def checkout_clean(self):
        return True

    def checkout_sha(self, sha):
        self.calls.append(("checkout", sha))
        return 0, ""

    def run_deploy(self, args, env):
        self.calls.append(("deploy", tuple(args), env.get("TRADEAI_RELEASE_CAMPAIGN"), env.get("TRADEAI_RELEASE_PR"),
                           env.get("TRADEAI_EMERGENCY_RELEASE_SHA")))
        if args[0] == "prepare":
            out = self.prepare_out if self.prepare_out is not None else f"[phase2] PREPARE OK: {self.new}\n{self.new}\n"
            return self.prepare_rc, out
        if args[0] == "promote":
            if not self.deploy_rolls_back:
                self.cur = Path(args[1])
            return self.promote_rc, "[phase2] PROMOTE OK" if self.promote_rc == 0 else "ERROR"
        if args[0] == "rollback":
            if self.rollback_rc == 0:
                self.cur = Path(args[1])
                self.health = [200]
            return self.rollback_rc, "ROLLBACK OK" if self.rollback_rc == 0 else "ERROR: rollback health failed"
        raise AssertionError(args)

    def units_active(self, units):
        if self.units_after is not None and self.cur == self.new:
            return dict(self.units_after)
        return {u: True for u in units}

    def http_status(self, url):
        return self.health[0] if len(self.health) == 1 else self.health.pop(0)

    def served_copy(self, release):
        return self.served_rc, "checked=7 split=0"

    def revoke(self):
        self.revoked += 1
        self._grants = [g for g in self._grants if g.get("tier") != "release-write"]
        return 0, "revoked: release-write"

    def sleep(self, s):
        pass


def runner(tmp_path, host, env=None):
    return RW.Runner(host, RW.State(tmp_path / "state"), env=env or {}, units=("portfolio-server.service",),
                     health_attempts=2, health_sleep_s=0)


def deploys(host):
    return [c for c in host.calls if c[0] == "deploy"]


# ── windows ──

@pytest.mark.parametrize("hh,mm,expect", [(12, 0, "1200"), (12, 44, "1200"), (12, 45, None), (11, 59, None),
                                           (17, 30, "1730"), (18, 14, "1730"), (9, 0, None)])
def test_open_window_bounds(hh, mm, expect):
    w = RW.open_window(datetime(2026, 10, 16, hh, mm, tzinfo=ET))
    assert (w.hhmm if w else None) == expect


def test_window_is_new_york_time_across_dst():
    # 2026-11-02 is after the DST change: 12:00 ET == 17:00 UTC (EST), not 16:00.
    assert RW.open_window(datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)).hhmm == "1200"
    assert RW.open_window(datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)) is None


# ── authorization ──

def test_window_grant_authorizes_prepare_promote_rollback():
    w = RW.window_for(NOON, "1200")
    v = RW.grant_verdict(w, HEAD, [grant()], now_ts=NOON.timestamp())
    assert v["ok"], v["errors"]
    assert v["grant_id"] == "g-window-1200"
    assert set(v["binding"]) == {"prepare", "promote", "rollback"}


@pytest.mark.parametrize("g,needle", [
    (grant(reason="Operator 2026-10-16: merge + release PR #1808; prepare + promote exact main"), "names neither"),
    (grant(reason=GOOD_REASON.replace("1200", "1730")), "names neither"),
    (grant(reason=GOOD_REASON.replace("stop=verify_failed,rolled_back,ci_not_green", "")), "stop conditions"),
    (grant(reason=GOOD_REASON.replace("RELEASE_WINDOW ", "")), "RELEASE_WINDOW token"),
    (grant(reason=GOOD_REASON + " release-window-20261016-1730"), "more than one window"),
    (grant(uses=1), "uses"),
    (grant(expires_in=300), "expires in"),
    (grant(expires_in=-1), "expired"),
])
def test_grant_refusals(g, needle):
    w = RW.window_for(NOON, "1200")
    v = RW.grant_verdict(w, HEAD, [g], now_ts=NOON.timestamp())
    assert not v["ok"]
    assert needle in " ".join(v["errors"]) + " ".join(str(r) for b in (v.get("binding") or {}).values()
                                                      for r in b.get("refused_grants", []))


def test_multi_window_grant_allowed_only_when_amendment_active(monkeypatch):
    w = RW.window_for(NOON, "1200")
    g = grant(reason=GOOD_REASON + " release-window-20261016-1730")
    monkeypatch.setattr(RW, "MULTI_WINDOW_GRANT_STATUS", "ACTIVE")
    v = RW.grant_verdict(w, HEAD, [g], now_ts=NOON.timestamp())
    assert v["ok"], v["errors"]
    assert RW.later_windows_named(w, v) == ["release-window-20261016-1730"]


@pytest.mark.parametrize("name,value", [("TRADEAI_EMERGENCY_RELEASE_SHA", HEAD), ("TRADEAI_RELEASE_GRANT_BINDING", "warn"),
                                        ("TRADEAI_CONFORMANCE_GATE_OVERRIDE", "x"), ("TRADEAI_RELEASE_PIN_MODE", "off"),
                                        ("TRADEAI_TREE_ATTESTED_PROMOTE", "1"), ("TRADEAI_GUARD_CONSUME", "0"),
                                        ("CIO_DEPLOY_FF_DEV_TREE", "0")])
def test_bypass_environment_refuses_before_any_host_action(tmp_path, name, value):
    host = FakeHost(tmp_path)
    code, body = runner(tmp_path, host, env={name: value}).run("1200")
    assert code == RW.EXIT_REFUSED and body["outcome"] == "REFUSED_BYPASS_ENV" and body["names"] == [name]
    assert host.calls == [] and host.revoked == 0


def test_deploy_env_never_carries_a_guarded_name():
    w = RW.window_for(NOON, "1200")
    env = RW.deploy_env({"PATH": "/bin", "TRADEAI_EMERGENCY_RELEASE_SHA": HEAD, "TRADEAI_RELEASE_PR": "1"}, w, 1813)
    assert not set(env) & set(RW.GUARDED_ENV)
    assert env["TRADEAI_RELEASE_CAMPAIGN"] == "release-window-20261016-1200" and env["TRADEAI_RELEASE_PR"] == "1813"


# ── the window ──

def test_released_happy_path_prepares_then_promotes_that_artifact(tmp_path):
    host = FakeHost(tmp_path)
    r = runner(tmp_path, host)
    code, rec = r.run("1200")
    assert code == RW.EXIT_OK and rec["outcome"] == "RELEASED", rec
    d = deploys(host)
    assert [c[1][0] for c in d] == ["prepare", "promote"]
    assert d[1][1] == ("promote", str(host.new))                        # THAT prepared artifact
    assert all(c[2] == "release-window-20261016-1200" and c[4] is None for c in d)
    assert rec["candidate"]["sha"] == HEAD and rec["candidate"]["prs"] == [1813, 1809, 1811]
    assert rec["grant"]["grant_id"] == "g-window-1200" and rec["ci"]["ok"] is True
    assert all(c["ok"] for c in rec["verification"].values())
    assert host.revoked == 1 and rec["revocation"]["done"]
    assert r.state.read(r.state.receipt_path(RW.window_for(NOON, "1200")))["outcome"] == "RELEASED"
    assert r.state.read(r.state.latch) is None


def test_second_run_in_same_window_is_a_no_op(tmp_path):
    host = FakeHost(tmp_path)
    r = runner(tmp_path, host)
    r.run("1200")
    n = len(host.calls)
    code, body = r.run("1200")
    assert code == RW.EXIT_OK and body["outcome"] == "ALREADY_RAN" and len(host.calls) == n


@pytest.mark.parametrize("ci,outcome", [(pending(), "STOP_CI_PENDING"), (red(), "STOP_CI_NOT_GREEN")])
def test_ci_not_green_stops_the_window_without_a_deploy(tmp_path, ci, outcome):
    host = FakeHost(tmp_path, ci=ci)
    r = runner(tmp_path, host)
    code, rec = r.run("1200")
    assert code == RW.EXIT_STOPPED and rec["outcome"] == outcome
    assert deploys(host) == [] and ("checkout", HEAD) not in host.calls
    assert host.revoked == 1                       # a stop condition ends the grant
    assert r.state.read(r.state.latch) is None     # no release happened, nothing to latch


def test_replay_20261016_main_moved_between_selection_and_prepare(tmp_path):
    out = ("ERROR: ROOT HEAD a7fc2175b84ab62b2a077f5f4e5f951714ac1bc3 != origin/main "
           "94ee3770a65f7e67e574bd61a04dc350f098e56f — refuse hybrid promote. Checkout origin/main first.\n")
    host = FakeHost(tmp_path, head="a7fc2175b84ab62b2a077f5f4e5f951714ac1bc3", prepare_out=out, prepare_rc=1)
    code, rec = runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_STOPPED and rec["outcome"] == "STOP_MAIN_MOVED"
    assert [c[1][0] for c in deploys(host)] == ["prepare"]          # never promotes, never rolls back
    assert host.cur == host.prev


def test_verification_failure_rolls_back_and_latches(tmp_path):
    host = FakeHost(tmp_path, health=(502,))
    r = runner(tmp_path, host)
    code, rec = r.run("1200")
    assert code == RW.EXIT_ROLLED_BACK and rec["outcome"] == "ROLLED_BACK"
    assert rec["verification"]["api_health"]["ok"] is False
    assert deploys(host)[-1][1] == ("rollback", str(host.prev)) and host.cur == host.prev
    assert rec["rollback"]["ok"] is True and host.revoked == 1
    latch = r.state.read(r.state.latch)
    assert latch and latch["outcome"] == "ROLLED_BACK"
    # the next window refuses until the operator clears the latch
    code2, body2 = runner(tmp_path, FakeHost(tmp_path)).run("1200", now=datetime(2026, 10, 16, 17, 35, tzinfo=ET))
    assert code2 == RW.EXIT_REFUSED and body2["outcome"] == "REFUSED_STOP_LATCHED"


@pytest.mark.parametrize("kw,check", [({"served_rc": 1}, "served_copy"), ({"promote_rc": 1}, "promote_exit"),
                                      ({"units_after": {"portfolio-server.service": False}}, "units")])
def test_each_verification_check_can_fail_the_window(tmp_path, kw, check):
    host = FakeHost(tmp_path, **kw)
    code, rec = runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_ROLLED_BACK and rec["verification"][check]["ok"] is False


def test_deploy_internal_rollback_is_recognised_without_a_second_rollback(tmp_path):
    host = FakeHost(tmp_path, deploy_rolls_back=True, promote_rc=1)
    code, rec = runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_ROLLED_BACK and rec["rollback"]["by"].startswith("deploy promote")
    assert [c[1][0] for c in deploys(host)] == ["prepare", "promote"]


def test_rollback_failure_is_exit_5_and_latched(tmp_path):
    host = FakeHost(tmp_path, health=(502,), rollback_rc=1)
    r = runner(tmp_path, host)
    code, rec = r.run("1200")
    assert code == RW.EXIT_ROLLBACK_FAILED and rec["outcome"] == "ROLLBACK_FAILED"
    assert r.state.read(r.state.latch)["outcome"] == "ROLLBACK_FAILED"


def test_no_change_releases_nothing(tmp_path):
    host = FakeHost(tmp_path, head=BASE)
    code, rec = runner(tmp_path, host).run("1200")
    assert code == RW.EXIT_OK and rec["outcome"] == "NO_CHANGE" and deploys(host) == []


def test_disarmed_without_a_window_grant(tmp_path):
    host = FakeHost(tmp_path, grants=[grant(reason="Operator: release PR #1813 prepare promote")])
    r = runner(tmp_path, host)
    code, rec = r.run("1200")
    assert code == RW.EXIT_REFUSED and rec["outcome"] == "DISARMED"
    assert deploys(host) == [] and host.revoked == 0
    assert r.state.read(r.state.receipt_path(RW.window_for(NOON, "1200"))) is None   # a later grant may still run it


def test_off_window_run_is_refused(tmp_path):
    host = FakeHost(tmp_path)
    code, body = runner(tmp_path, host).run(None, now=datetime(2026, 10, 16, 14, 0, tzinfo=ET))
    assert code == RW.EXIT_REFUSED and body["outcome"] == "REFUSED_OFF_WINDOW" and host.calls == []


def test_plan_writes_nothing_and_never_deploys(tmp_path):
    host = FakeHost(tmp_path)
    r = runner(tmp_path, host)
    code, rec = r.plan("1730", now=datetime(2026, 10, 16, 9, 0, tzinfo=ET))
    assert rec["campaign"] == "release-window-20261016-1730"
    assert rec["outcome"] == "DISARMED"           # the noon grant does not cover 17:30
    assert deploys(host) == [] and not (tmp_path / "state").exists()


def test_revoke_skips_a_grant_that_is_no_longer_the_window_grant(tmp_path):
    host = FakeHost(tmp_path)
    r = runner(tmp_path, host)
    rec = {"grant": {"grant_id": "g-window-1200", "windows_named": ["release-window-20261016-1200"]}}
    host._grants = [grant(gid="g-someone-else")]
    r._revoke(RW.window_for(NOON, "1200"), rec, force=True)
    assert host.revoked == 0 and rec["revocation"]["done"] is False


def test_clear_stop_archives_never_deletes(tmp_path):
    host = FakeHost(tmp_path, health=(502,))
    r = runner(tmp_path, host)
    r.run("1200")
    code, body = r.clear_stop("operator reviewed receipt")
    assert body["outcome"] == "STOP_CLEARED" and not r.state.latch.exists()
    assert list((r.state.windows).glob("STOP-*.json.archived"))


def test_pr_list_parsing():
    assert RW.prs_from_messages(["Merge pull request #1813 from a/b", "x (#1700)", "Merge pull request #1813 from c",
                                 "no pr"]) == [1813, 1700]
