"""Solo shared-infra trains (ANCHOR RELEASE_TRAIN_SOLO_SHARED_INFRA_20261025; AGENTS.md 20.4.0 hands-off delivery).

Operator 2026-10-25: "fully done, fully automatic, no input by me, for the train systems unless there's an issue."
A needs_operator shared-infra PR rides ALONE (one member, never mixed) when 20.4.0 is ACTIVE and every condition of
scripts/lib/release_train_solo.py holds; a solo train adds n8n allowlist / lane registry / watchdog dry-run checks to
verification, and a failed check takes the existing rollback + STOP latch + quarantine + P1 path.

Hermetic: pure functions with injected readers, and the controller test world (tmp git repo, fake GitHub + deploy
host) from tests/test_release_train_controller_20261021.py. No network, DB, systemd, broker or real claim board.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.test_release_train_controller_20261021 import World, runs_for  # noqa: E402  (psycopg2 stub)
from scripts.lib import hands_off_policy as HOP  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402
from scripts.lib import release_train_solo as SOLO  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
ACTIVE = {"active": True, "detail": "test: 20.4.0 ACTIVE"}
COORD_ROWS = [{"claim_id": "c-1", "session": "coord-1", "paths": [HOP.COORDINATOR_CLAIM_PATH], "_state": "live"}]
CFG = SOLO.load_config()


def receipt(head=HEAD, coordinator="coord-1", reviewer="claude-adv-1"):
    return f"Adversarial-review: MERGE reviewer={reviewer} head={head[:12]} coordinator={coordinator}"


def text(title="[shared-infra] lanes: add x", body="Real-layout proof: ran on temp PROJECT_ROOT /x, out.json",
         comments=None):
    return {"title": title, "body": body, "comments": [{"body": c, "author": "PatsKiller"} for c in
                                                         (comments if comments is not None else [receipt()])]}


def sir_runs(head=HEAD, conclusion="success", status="completed", app="github-actions"):
    return [{"id": 7, "name": "shared-infra-review", "head_sha": head, "status": status, "conclusion": conclusion,
             "app": app}]


def ev(**kw):
    args = dict(pr=21, head_sha=HEAD, title="[shared-infra] lanes: add x", risk="needs_operator",
                reasons=["scheduler_live_list:config/lane_registry.json"], paths=["config/lane_registry.json",
                                                                                 "tests/test_x.py"],
                pr_text=text(), runs=sir_runs(), claim_rows=COORD_ROWS, cfg=CFG, policy_state=ACTIVE,
                train_policy=json.loads((ROOT / "config/release_train_policy.json").read_text()),
                is_protected=T.is_protected)
    args.update(kw)
    return SOLO.evaluate(**args)


# ── eligibility ───────────────────────────────────────────────────────────────────────────────────────


def test_shipped_config_is_valid_and_batch_first():
    assert SOLO.validate_config(CFG) == []
    assert CFG["precedence"] == "batch_first" and CFG["required_check"] == "shared-infra-review"


def test_every_condition_met_is_eligible_and_carries_the_receipt():
    v = ev()
    assert v["eligible"], v["why"]
    assert v["receipt"]["reviewer"] == "claude-adv-1" and v["receipt"]["claim_id"] == "c-1"
    assert len(SOLO.ride_ref(v)) <= 200 and "reviewer=claude-adv-1" in SOLO.ride_ref(v)


@pytest.mark.parametrize("kw, why", [
    ({"policy_state": {"active": False, "detail": "AGENTS.md 20.2.0 is below 20.4.0"}}, "POLICY_NOT_ACTIVE"),
    ({"risk": "held"}, "CLASS_NOT_NEEDS_OPERATOR:held"),
    ({"risk": "blocked"}, "CLASS_NOT_NEEDS_OPERATOR:blocked"),
    ({"pr_text": text(title="lanes: add x")}, "TITLE_NOT_SHARED_INFRA"),
    ({"pr_text": None, "title": "[shared-infra] x"}, "PR_TEXT_UNREADABLE"),
    ({"runs": []}, "SHARED_INFRA_REVIEW_NOT_GREEN:MISSING"),
    ({"runs": sir_runs(conclusion="failure")}, "SHARED_INFRA_REVIEW_NOT_GREEN:FAILURE"),
    ({"runs": sir_runs(status="in_progress", conclusion=None)}, "SHARED_INFRA_REVIEW_NOT_GREEN:IN_PROGRESS"),
    ({"runs": sir_runs(head="b" * 40)}, "SHARED_INFRA_REVIEW_NOT_GREEN:MISSING"),
    ({"runs": sir_runs(app="some-bot")}, "SHARED_INFRA_REVIEW_NOT_GREEN:MISSING"),
    ({"pr_text": text(body="no proof here")}, "NO_REAL_LAYOUT_PROOF"),
    ({"pr_text": text(body="Real-layout proof: TBD")}, "NO_REAL_LAYOUT_PROOF"),
    ({"pr_text": text(comments=[])}, "NO_RECEIPT"),
    ({"pr_text": text(comments=["Adversarial-review: HOLD reviewer=x head=aaaaaaa coordinator=coord-1"])},
     "NO_RECEIPT"),
    ({"pr_text": text(comments=[receipt(head="b" * 40)])}, "RECEIPT_HEAD_MISMATCH"),
    ({"pr_text": text(comments=[receipt(coordinator="someone-else")])}, "RECEIPT_NOT_FROM_COORDINATOR"),
    ({"claim_rows": [dict(COORD_ROWS[0], _state="abandoned")]}, "RECEIPT_NOT_FROM_COORDINATOR"),
    ({"claim_rows": [dict(COORD_ROWS[0], paths=["scripts/x.py"])]}, "RECEIPT_NOT_FROM_COORDINATOR"),
    ({"paths": ["config/lane_registry.json", "scripts/lib/portfolio_math.py"]},
     "NOT_SHARED_INFRA:scripts/lib/portfolio_math.py"),
    ({"paths": []}, "NO_CHANGED_PATHS"),
    ({"reasons": ["deletion:config/n8n_x.json"]}, "DENY_REASON:deletion"),
    ({"reasons": ["oversized:"]}, "DENY_REASON:oversized"),
    ({"reasons": [{"rule": "ci_risk_tiers:policy_and_guard", "class": "needs_operator", "path": "x"}]},
     "DENY_REASON:ci_risk_tiers:policy_and_guard"),
])
def test_each_failed_condition_refuses_solo(kw, why):
    v = ev(**kw)
    assert not v["eligible"]
    assert any(w.startswith(why) for w in v["why"]), v["why"]


@pytest.mark.parametrize("path", [
    "AGENTS.md", "AI_WORK_POLICY.md", ".githooks/pre-push", ".cursor/hooks/guard_ledger.py", "bin/guard",
    "scripts/lib/guard_push_auth.py", "scripts/lib/tradeai_push_budget.py", "scripts/lib/hands_off_policy.py",
    "config/ci_gates/x.json", "config/release_train_policy.json", "config/release_train_solo_shared_infra.json",
    "scripts/lib/release_train_controller.py", "scripts/release_window.py", "scripts/cio_phase2_exact_main_deploy.sh",
    "scripts/check_shared_infra_pr.py", ".github/workflows/shared-infra-review.yml",
    "config/systemd/tradeai-active-trader-motion.service", "scripts/brokers/schwab.py", "scripts/run_schwab_x.sh",
    "migrations/001.sql", "config/n8n_secret_names.json",
])
def test_deny_wins_over_allow(path):
    v = ev(paths=["config/lane_registry.json", path])
    assert not v["eligible"]
    assert any(w.startswith("DENY_") and w.endswith(path) for w in v["why"]), v["why"]


def test_every_protected_surface_file_is_denied():
    for pat in T.PROTECTED_SURFACES:
        p = pat + "x" if pat.endswith("/") else pat
        assert SOLO.path_findings([p], CFG, is_protected=T.is_protected), p


@pytest.mark.parametrize("path", [
    "config/lane_registry.json", "config/n8n_run_allowlist.json", "config/systemd/tradeai-health-agent.service",
    "linux_launchers/systemd/tradeai-agent-claim-compact.timer", "config/host_comms_intent_routes.json",
    "scripts/run_drive_syncs.sh", "scripts/safe_flock.sh", "scripts/render_n8n_relay_env.py", "crontab.txt",
])
def test_shared_infra_paths_are_allowed(path):
    assert SOLO.path_findings([path], CFG, is_protected=T.is_protected) == []


def test_an_added_ci_gate_for_the_prs_own_test_is_exempt_but_a_modified_one_is_denied():
    paths = ["config/lane_registry.json", "config/ci_gates/x_20261025.json", "tests/test_x.py"]
    reasons = [{"rule": "guard_ci_enforcement", "class": "needs_operator", "path": "config/ci_gates/x_20261025.json"},
               {"rule": "scheduler_live_list", "class": "needs_operator", "path": "config/lane_registry.json"}]
    added = ev(paths=paths, reasons=reasons, statuses={"config/ci_gates/x_20261025.json": "A"})
    assert added["eligible"], added["why"]
    modified = ev(paths=paths, reasons=reasons, statuses={"config/ci_gates/x_20261025.json": "M"})
    assert not modified["eligible"]
    assert "DENY_GLOB:config/ci_gates/x_20261025.json" in modified["why"]
    assert "DENY_REASON:guard_ci_enforcement" in modified["why"]
    other = ev(paths=["config/lane_registry.json", ".githooks/pre-push"], statuses={".githooks/pre-push": "A"})
    assert not other["eligible"]  # only additive_globs are exempt


# ── precedence ────────────────────────────────────────────────────────────────────────────────────────


def test_batch_first_eligible_batch_goes_solo_waits():
    kind, members, deferred = SOLO.choose([11, 12], [21])
    assert kind == "batch" and members == [11, 12] and deferred == {21: "SOLO_DEFERRED_BATCH_FIRST"}


def test_no_batch_one_solo_alone_others_wait():
    kind, members, deferred = SOLO.choose([], [21, 22])
    assert kind == "solo_shared_infra" and members == [21] and deferred == {22: "SOLO_ONE_PER_TRAIN"}


def test_solo_first_defers_the_whole_batch_never_mixed():
    kind, members, deferred = SOLO.choose([11], [21], "solo_first")
    assert kind == "solo_shared_infra" and members == [21] and deferred == {11: "BATCH_DEFERRED_SOLO_FIRST"}


def test_nothing_solo_is_the_batch():
    assert SOLO.choose([11], []) == ("batch", [11], {})


# ── policy gate ───────────────────────────────────────────────────────────────────────────────────────


def _agents(version, status, row_status="ACTIVE", own="ACTIVE"):
    return (f"```\nPolicy-Version:      {version}\nStatus:              {status}\nEffective-Date: 2026-10-26\n```\n"
            f"| {version} | 2026-10-26 | {row_status} | MINOR | x | y |\n"
            + (f"| 20.4.0 | 2026-10-26 | {own} | MINOR | x | y |\n" if version != "20.4.0" else ""))


def test_gate_follows_agents_md_and_today_is_not_active():
    assert HOP.policy_state_from_text(_agents("20.4.0", "ACTIVE"))["active"] is True
    # Renumbered: ratified as 21.0.0 (PR #2128); the CURRENT version's row decides, no | 20.4.0 | row needed.
    assert HOP.policy_state_from_text(_agents("21.0.0", "ACTIVE"))["active"] is True
    assert HOP.policy_state_from_text(_agents("21.0.0", "ACTIVE", own="PROPOSED"))["active"] is True
    assert HOP.policy_state_from_text(_agents("21.0.0", "PROPOSED", "PROPOSED"))["active"] is False
    assert HOP.policy_state_from_text(_agents("21.0.0", "ACTIVE", "PROPOSED"))["active"] is False
    assert HOP.policy_state_from_text(_agents("20.4.0", "PROPOSED", "PROPOSED"))["active"] is False
    assert HOP.policy_state_from_text(_agents("20.3.0", "ACTIVE"))["active"] is False
    # The repository's own AGENTS.md decides (header >= 20.4.0, ACTIVE, its own row ACTIVE).
    real = SOLO.policy_state(ROOT)
    assert real["active"] == (HOP.policy_state_from_path(ROOT / "AGENTS.md")["state"] == "ACTIVE")


# ── verification ──────────────────────────────────────────────────────────────────────────────────────


class FakeRun:
    def __init__(self, new, old=None):
        self.new, self.old = new, old or new
        self.calls = []

    def __call__(self, argv, cwd, env, timeout):
        self.calls.append((argv, str(cwd)))
        table = self.new if str(cwd).endswith("new") else self.old
        key = "allowlist" if "-c" in argv else ("registry" if "check_lane_registry.py" in " ".join(argv) else "wd")
        val = table[key]
        if isinstance(val, Exception):
            raise val
        return val


GOOD = {"allowlist": (0, json.dumps({"lanes": 139, "refused": {}})),
        "registry": (1, json.dumps({"errors": [], "undeclared": [{"kind": "systemd", "expression": "a.timer"}]})),
        "wd": (0, json.dumps({"status": "UNKNOWN", "mode": "dry_run", "missed_lane_ids": [], "refusals": []}))}


def verify(new, old=None):
    return SOLO.verify_release(Path("/r/new"), Path("/r/old"), python="py", run=FakeRun(new, old))


def test_verify_clean_when_nothing_new():
    out = verify(GOOD)
    assert set(out) == set(SOLO.VERIFY_CHECKS) and all(c["ok"] for c in out.values()), out


@pytest.mark.parametrize("key, val, check", [
    ("allowlist", (1, json.dumps({"lanes": 139, "refused": {"x": "bad_lock"}})), "n8n_allowlist"),
    ("allowlist", (0, json.dumps({"lanes": 0, "refused": {}})), "n8n_allowlist"),
    ("allowlist", (1, "Traceback"), "n8n_allowlist"),
    ("registry", (1, json.dumps({"errors": ["row z: no output_signal"], "undeclared": [
        {"kind": "systemd", "expression": "a.timer"}]})), "lane_registry"),
    ("registry", (1, json.dumps({"undeclared": [{"kind": "cron", "expression": "new"},
                                                {"kind": "systemd", "expression": "a.timer"}]})), "lane_registry"),
    ("registry", (2, "cannot run"), "lane_registry"),
    ("wd", (1, json.dumps({"status": "CRIT", "mode": "dry_run"})), "watchdog_dry_run"),
    ("wd", (0, json.dumps({"status": "UNKNOWN", "mode": "dry_run", "missed_lane_ids": ["lane-x"]})),
     "watchdog_dry_run"),
    ("wd", (0, json.dumps({"status": "OK", "mode": "monitor"})), "watchdog_dry_run"),
    ("wd", OSError("boom"), "watchdog_dry_run"),
])
def test_verify_fails_on_any_new_problem(key, val, check):
    out = verify(dict(GOOD, **{key: val}), GOOD)
    assert out[check]["ok"] is False, out
    assert all(c["ok"] for n, c in out.items() if n != check)


def test_baseline_debt_alone_never_fails_and_baseline_crit_is_not_new():
    crit = dict(GOOD, wd=(1, json.dumps({"status": "CRIT", "mode": "dry_run"})))
    assert all(c["ok"] for c in verify(crit, crit).values())


# ── controller integration ────────────────────────────────────────────────────────────────────────────


class ConfigNeedsOperator:
    """config/** is needs_operator, everything else eligible (a stand-in for the policy classifier)."""

    version = "test-solo/1"
    policy_version = "test-policy/1"

    def classify(self, entry, change):
        paths = [p["path"] for p in (change or {}).get("paths") or []]
        if any(p.startswith("config/") for p in paths):
            return "needs_operator", ["scheduler_live_list:" + paths[0]]
        return "eligible", ["test"]


def solo_world(tmp_path, prs, *, active=True, verify_ok=True, comments=None):
    w = World(tmp_path, prs=prs)
    solo_head = w.repo.heads[21]
    w.gh.runs[solo_head] = runs_for(solo_head) + sir_runs(solo_head)
    reads = []

    def build(**kw):
        c = w.controller(classifier=ConfigNeedsOperator(), **kw)
        c.solo_policy_state = lambda: ACTIVE if active else {"active": False, "detail": "20.2.0 below 20.4.0"}
        c.solo_claim_rows = lambda: COORD_ROWS

        def pr_text(n):
            reads.append(n)
            return text(comments=comments if comments is not None else [receipt(head=w.repo.heads[n])])
        c.solo_pr_text = pr_text
        c.solo_verify = lambda new, prev: {n: {"ok": verify_ok} for n in SOLO.VERIFY_CHECKS}
        return c
    return w, build, reads


def test_live_solo_train_releases_one_needs_operator_pr_alone(tmp_path):
    w, build, _ = solo_world(tmp_path, [(21, {"config/lane_registry.json": "{}\n"})])
    code, rec = build().run()
    assert rec["outcome"] == T.RELEASED_VERIFIED, rec["steps"]
    assert rec["selection"]["members"] == [21] and rec["selection"]["train_kind"] == "solo_shared_infra"
    tc = rec["manifest"]["train_candidate"]
    assert [m["risk_class"] for m in tc["members"]] == ["needs_operator"]
    assert tc["members"][0]["ride_approval_ref"].startswith("solo-shared-infra adversarial-review MERGE")
    assert rec["manifest"]["train_kind"] == "solo_shared_infra"
    assert {f"solo_{n}" for n in SOLO.VERIFY_CHECKS} <= set(rec["verification"])
    assert [d[1] for d in w.deploys()] == ["prepare", "promote"]


def test_eligible_batch_goes_first_and_is_never_mixed_with_the_solo_pr(tmp_path):
    w, build, reads = solo_world(tmp_path, [(11, {"docs/a.md": "a\n"}), (21, {"config/lane_registry.json": "{}\n"})])
    code, rec = build().run()
    assert rec["outcome"] == T.RELEASED_VERIFIED, rec["steps"]
    assert rec["selection"]["members"] == [11] and rec["selection"]["train_kind"] == "batch"
    assert "SOLO_DEFERRED_BATCH_FIRST" in rec["selection"]["excluded"]["21"]
    assert reads == []  # batch_first: the deferred solo PR costs no GitHub read
    assert not any(k.startswith("solo_") for k in rec["verification"])


def test_policy_not_active_never_rides_solo(tmp_path):
    w, build, reads = solo_world(tmp_path, [(21, {"config/lane_registry.json": "{}\n"})], active=False)
    code, rec = build().run()
    assert rec["outcome"] == T.NO_OP and rec["reason"] == "NOTHING_ELIGIBLE"
    assert rec["solo"]["state"] == "NOT_ACTIVE" and reads == [] and w.writer.calls == []


def test_missing_receipt_never_rides_solo(tmp_path):
    w, build, _ = solo_world(tmp_path, [(21, {"config/lane_registry.json": "{}\n"})], comments=[])
    code, rec = build().run()
    assert rec["outcome"] == T.NO_OP and "NO_RECEIPT" in rec["selection"]["excluded"]["21"]


def test_two_solo_candidates_one_rides(tmp_path):
    w, build, _ = solo_world(tmp_path, [(21, {"config/lane_registry.json": "{}\n"}),
                                        (22, {"config/n8n_run_allowlist.json": "{}\n"})])
    w.gh.runs[w.repo.heads[22]] = runs_for(w.repo.heads[22]) + sir_runs(w.repo.heads[22])
    code, rec = build().run()
    assert rec["selection"]["members"] == [21] and rec["selection"]["excluded"]["22"] == "SOLO_ONE_PER_TRAIN"


def test_solo_verification_failure_rolls_back_latches_quarantines_and_alerts_p1(tmp_path):
    w, build, _ = solo_world(tmp_path, [(21, {"config/lane_registry.json": "{}\n"})], verify_ok=False)
    code, rec = build().run()
    assert rec["outcome"] == T.ROLLED_BACK and code == T.EXIT_ROLLED_BACK
    assert [d[1] for d in w.deploys()] == ["prepare", "promote", "rollback"]
    assert w.host.cur == Path(os.path.realpath(w.host.prev))
    assert w.state.read_latch()[0] == "SET"
    assert (w.state_dir / "quarantine.jsonl").exists()
    assert w.host.notified and w.host.notified[0][0] == "P1"


def test_dry_run_previews_the_solo_checks(tmp_path):
    w, build, _ = solo_world(tmp_path, [(21, {"config/lane_registry.json": "{}\n"})])
    w.repo.heads  # dry run classifies from the gh file list
    c = build(live=False)
    c.queue.entries = [T.QueueEntry(pr=21, head_sha=w.repo.heads[21], files=("config/lane_registry.json",))]
    code, rec = c.run()
    assert rec["outcome"] == "DRY_RUN_COMPLETE", rec["steps"]
    assert any("solo shared-infra" in s for s in rec["steps"])


# ── classifier follow-ups from the first live train (rt-20261025-1500-461185) ───────────────────────────

from scripts.lib import release_train_classify as RTC  # noqa: E402

POLICY = RTC.load_policy()


def classify(paths, semantic=None, rdeps=None):
    change = {"paths": [{"path": p, "status": "M"} for p in paths], "head_sha": "d" * 40,
              "semantic_config": semantic or {}}
    return RTC.classify_change(change, POLICY, tiers=None, impact_map={"rdeps": rdeps or {}})


def test_closure_blocks_what_a_protected_module_imports_not_what_imports_it():
    # rdeps[x] = the files that import x. release_window imports foo -> changing foo changes the verifier: blocked.
    dep = classify(["scripts/lib/foo_helper.py"], rdeps={"scripts/lib/foo_helper.py": ["scripts/release_window.py"]})
    assert dep["class"] == "blocked"
    assert any(r["rule"] == "import_closure" and "release_window.py" in r["detail"] for r in dep["reasons"])
    # bar imports release_window -> changing bar cannot change the verifier: not blocked by the closure.
    user = classify(["scripts/lib/bar_user.py"], rdeps={"scripts/release_window.py": ["scripts/lib/bar_user.py"]})
    assert user["class"] == "eligible", user["reasons"]


@pytest.mark.parametrize("keys, cls", [
    (["scripts.build"], "eligible"),
    (["scripts.test:e2e", "scripts.build"], "eligible"),
    (["dependencies.react"], "held"),
    (["scripts.build", "version"], "held"),
    (["$"], "held"),
    (None, "held"),
])
def test_cc_package_json_is_eligible_only_for_script_list_changes(keys, cls):
    p = "apps/command-center-v3/package.json"
    out = classify([p], semantic=({p: keys} if keys is not None else {}))
    assert out["class"] == cls, out["reasons"]
    if cls == "held":
        assert any(r["rule"] == "semantic_key_not_allowlisted" for r in out["reasons"])


@pytest.mark.parametrize("path", ["apps/command-center-v3/e2e-live/site-sweep.ts", "scripts/site_sweep.sh"])
def test_live_e2e_and_site_sweep_are_the_tests_class(path):
    assert classify([path])["class"] == "eligible"


@pytest.mark.parametrize("path", ["scripts/alerting.py", "scripts/lib/comms/channel_adapters.py"])
def test_comms_channel_code_is_in_the_solo_shared_infra_set(path):
    assert SOLO.path_findings([path], CFG, is_protected=T.is_protected) == []


def test_broker_and_train_self_stay_out_after_the_follow_ups():
    assert classify(["scripts/brokers/schwab_client.py"])["class"] == "held"
    assert classify(["scripts/release_window.py"])["class"] == "blocked"
    assert RTC.validate_policy(POLICY) == []
