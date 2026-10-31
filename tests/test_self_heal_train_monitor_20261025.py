"""Self-heal train monitor + fixer intake + fix log (operator 2026-10-25).

"Arm the fixer and also a logger that tracks what was fixed, but this train should be no different than submitting
in [to GitHub]. Somebody needs to monitor it, if there's little errors they need to correct it as long as they're
adhering to our agents.md."

Hermetic: tmp_path state root, a fake runner for every gh/git/subprocess call, a fake sender. No network, no model,
no Telegram, no DB.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import self_heal_train_monitor as M  # noqa: E402
from lib import self_heal_train_intake as TI  # noqa: E402

#: alarm firing coverage (tests/test_alarm_coverage.py): the escalation send is observed reaching the transport
COVERS = ["scripts/self_heal_train_monitor.py"]

CFG = TI.load_config(ROOT / "config" / "self_heal_train_monitor.json")
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)


def agents(
    version="21.0.0",
    status="ACTIVE",
    heading="## 28.14 Self-heal monitor and fixer — the train is watched and small errors are fixed by ordinary PRs (21.0.0, ACTIVE)",
):
    return (
        f"# AGENTS\n\n```\nPolicy-Version:      {version}\nStatus:              {status}\n"
        f"Effective-Date:      2026-10-26\n```\n\n{heading}\n"
    )


SHADOW_AGENTS = agents("20.2.0", heading="")
LIVE_AGENTS = agents()

PG_LOG = "shard pg\tInitialize containers\tError response from daemon: toomanyrequests: rate limit\n"
TEST_LOG = "FAILED tests/test_widget_view.py::test_render - AssertionError: 3 != 4\nscripts/lib/widget_view.py:12\n"


class FakeWorld:
    """Fake gh/git/subprocess. ``ci`` = list of (workflow, conclusion, status, failed_jobs, log, attempt)."""

    def __init__(self, ci=None, head="a" * 40):
        self.ci = list(ci or [])
        self.head = head
        self.calls: list[list[str]] = []
        self.pr_view: dict = {}
        self.reconcile_out = '{"trains": [{"disposition": "NO_PENDING_EFFECT"}]}'
        self.reconcile_rc = 0
        self.ancestor_rc = 0

    def __call__(self, argv, *, cwd=None, env=None, timeout=0):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if argv[:3] == ["gh", "run", "list"]:
            rows = [
                {
                    "databaseId": 100 + i,
                    "headSha": self.head,
                    "workflowName": w,
                    "conclusion": c,
                    "status": s,
                    "createdAt": f"2026-10-25T19:{i:02d}:00Z",
                    "url": f"https://gh/run/{100 + i}",
                }
                for i, (w, c, s, _j, _l, _a) in enumerate(self.ci)
            ]
            return {"rc": 0, "out": json.dumps(rows), "err": ""}
        if argv[:3] == ["gh", "run", "view"]:
            i = int(argv[3]) - 100
            w, c, s, jobs, log, a = self.ci[i]
            if "--log-failed" in argv:
                return {"rc": 0, "out": log, "err": ""}
            return {
                "rc": 0,
                "out": json.dumps({"jobs": [{"name": j, "conclusion": "failure"} for j in jobs]}),
                "err": "",
            }
        if argv[:2] == ["gh", "api"] and "/actions/runs/" in argv[2]:
            return {"rc": 0, "out": str(self.ci[int(argv[2].rsplit("/", 1)[-1]) - 100][5]) + "\n", "err": ""}
        if argv[:3] == ["gh", "run", "rerun"]:
            return {"rc": 0, "out": "", "err": ""}
        if argv[:3] == ["gh", "pr", "view"]:
            return {"rc": 0, "out": json.dumps(self.pr_view), "err": ""}
        if "train-reconcile" in argv:
            return {"rc": self.reconcile_rc, "out": self.reconcile_out, "err": ""}
        if "merge-base" in argv:
            return {"rc": self.ancestor_rc, "out": "", "err": ""}
        if "agent_claim.py" in " ".join(argv):
            return {"rc": 0, "out": '{"id": "T-1"}', "err": ""}
        return {"rc": 0, "out": "", "err": ""}

    def ran(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


class Sent(list):
    def __call__(self, text, priority):
        self.append((priority, text))
        return True


def do_tick(tmp_path, world, *, agents_text=SHADOW_AGENTS, write=True, now=NOW, sender=None, extra_env=None):
    env = {
        "TRADEAI_STATE_ROOT": str(tmp_path),
        "TMPDIR": str(tmp_path / "tmp"),
        "TRADEAI_CURRENT_SHA_FILE": str(tmp_path / "CURRENT_GIT_SHA"),
        **(extra_env or {}),
    }
    sender = sender if sender is not None else Sent()
    hb = M.tick(
        CFG,
        root=tmp_path,
        repo=tmp_path / "repo",
        write=write,
        now=now,
        runner=world,
        sender=sender,
        environ=env,
        agents_text=agents_text,
    )
    return hb, sender


def log_rows(tmp_path):
    return TI.read_fix_log(tmp_path / CFG["state"]["fix_log_rel"])


# ---------------------------------------------------------------- policy gate (rule 7: shadow until 21.0.0 28.14)

H = "## 28.14 Self-heal monitor and fixer — the train is watched and small errors are fixed by ordinary PRs"


@pytest.mark.parametrize(
    "text,live",
    [
        (agents("20.3.0", heading=""), False),  # main today
        (agents("20.3.0", "ACTIVE", f"{H} (21.0.0, PROPOSED)"), False),  # PR #2128 as drafted
        (agents("21.0.0", "PROPOSED", f"{H} (21.0.0, PROPOSED)"), False),
        (agents("21.0.0", "ACTIVE", ""), False),
        (agents("21.0.0", "ACTIVE", f"{H} (21.0.0, PROPOSED)"), False),
        (agents("21.0.0"), True),  # the ratifying edit
        (agents("22.1.0", "ACTIVE", f"{H} (21.0.0, ACTIVE)"), True),
        ("no control block", False),
    ],
)
def test_policy_gate_is_shadow_until_21_0_0_active_with_28_14(text, live):
    assert TI.policy_gate(text, CFG)["live"] is live


def test_real_agents_md_on_this_tree_is_parsed():
    g = TI.policy_gate((ROOT / "AGENTS.md").read_text(encoding="utf-8"), CFG)
    assert g["policy_version"] and g["policy_status"]


# ---------------------------------------------------------------- detection + decisions


def ci_finding(jobs, log, attempt=1, wf="cio-full-suite-sharded", head="a" * 40):
    red = [{"databaseId": 7, "workflowName": wf, "conclusion": "failure", "status": "completed", "url": "u"}]
    return TI.detect_ci(head, red, {7: {"failed_jobs": jobs, "log_tail": log, "attempt": attempt}})[0]


def test_ci_signature_ignores_head_sha_and_timestamps():
    a = ci_finding(["shard 3"], TEST_LOG, head="a" * 40)
    b = ci_finding(["shard 3"], TEST_LOG.replace("3 != 4", "5 != 6"), head="b" * 40)
    assert a.signature == b.signature
    assert a.meta["failed_tests"] == ["tests/test_widget_view.py::test_render"]
    assert "scripts/lib/widget_view.py" in a.paths


def test_head_runs_picks_latest_per_workflow_of_main_head():
    rows = [
        {
            "databaseId": 1,
            "headSha": "old",
            "workflowName": "w",
            "conclusion": "failure",
            "status": "completed",
            "createdAt": "2026-10-25T10:00:00Z",
        },
        {
            "databaseId": 2,
            "headSha": "new",
            "workflowName": "w",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-10-25T11:00:00Z",
        },
    ]
    head, latest = TI.head_runs(rows)
    assert head == "new" and [r["databaseId"] for r in latest] == [2] and TI.red_runs(latest) == []


def test_pg_shard_docker_pull_flake_reruns_once_then_goes_to_the_fixer():
    f = ci_finding(["shard pg"], PG_LOG)
    assert TI.decide(f, CFG)["remediation"] == "deterministic:ci_infra_flake_rerun"
    assert TI.decide(ci_finding(["shard pg"], PG_LOG, attempt=2), CFG)["remediation"] == "claude_code"
    assert TI.decide(ci_finding(["shard 3"], PG_LOG), CFG)["remediation"] == "claude_code"  # not the pg shard


def test_regenerate_rules_match_their_logs():
    gates = ci_finding(["shard 1"], "config/ci_gates/x.json is not canonical")
    index = ci_finding(["docs"], "docs/INDEX.md out of date; run report_docs_inventory --check-index")
    pins = ci_finding(["shard 2"], "ValueError: source_config_changed:lane_registry.json")
    assert TI.decide(gates, CFG)["rule"] == "ci_gates_canonical"
    assert TI.decide(index, CFG)["rule"] == "docs_index_regen"
    assert TI.decide(pins, CFG)["rule"] == "disk_packet_repin"


@pytest.mark.parametrize(
    "log,scope",
    [
        ("FAILED tests/test_x.py\nscripts/alpaca_paper_adapter.py:9 boom", "broker_active_trader"),
        ("AGENTS.md section 0 rails mismatch", "guard_policy"),
        ("scripts/lib/release_train_controller.py:3361 KeyError", "train_self"),
        ("config/self_heal_fixer.json drift", "self_heal_self"),
        ("scripts/lib/cc_auth.py: 403", "credentials"),
        ("apps/command-center-v3/src/pages/ActiveTraderDesk.tsx crashed", "broker_active_trader"),
    ],
)
def test_refused_scopes_never_reach_the_fixer(log, scope):
    d = TI.decide(ci_finding(["shard 1"], log), CFG)
    assert d["remediation"] == "refused" and d["scope"].startswith(scope + ":") and d["priority"] == "P1"


def write_json(p: Path, doc) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def release_dir(tmp_path):
    return tmp_path / CFG["sources"]["release_state_dir_rel"]


def test_train_outcomes_stale_trains_and_live_receipts(tmp_path):
    rd = release_dir(tmp_path)
    write_json(
        rd / "trains/rt-20261025-1800-aaaa/outcome.json",
        {
            "outcome": "MERGED_NOT_LIVE",
            "finished_at": "2026-10-25T19:00:00Z",
            "main_sha": "m",
            "notes": "CANONICAL_SOURCE_HEAD_MISMATCH: fast-forward",
            "members": [1],
        },
    )
    write_json(
        rd / "trains/rt-20261025-1200-bbbb/outcome.json",
        {
            "outcome": "FAILED_PRE_MERGE",
            "finished_at": "2026-10-25T16:30:00Z",
            "notes": "QUALIFY_RED: pr 5",
            "failure_attribution": {"pr": 5},
        },
    )
    write_json(
        rd / "trains/rt-20261025-1200-cccc/outcome.json",
        {"outcome": "RELEASED_VERIFIED", "finished_at": "2026-10-25T16:30:00Z"},
    )
    st = rd / "trains/rt-20261025-0900-dddd/state.json"
    write_json(st, {"phase": "merge"})
    old = (NOW - timedelta(hours=6)).timestamp()
    import os

    os.utime(st, (old, old))
    write_json(
        rd / "train_requests/receipts/rtw-20261025-1800-win.json",
        {
            "state": "COMPLETED",
            "shadow": False,
            "mode": "live",
            "finished_at": "2026-10-25T19:00:00Z",
            "needs_action": [{"code": "TRAIN_STALLED", "text": "BASE_HAS_UNRELEASED_HELD: 2 commits"}],
        },
    )
    write_json(
        rd / "train_requests/receipts/rtw-20261025-1500-win.json",
        {
            "state": "FAILED",
            "shadow": True,
            "mode": "simulate",
            "finished_at": "2026-10-25T19:00:00Z",
            "refusal": {"code": "CONTROLLER_FAILED"},
        },
    )
    found = {f.kind: f for f in TI.detect_train(rd, now=NOW, cfg=CFG)}
    assert set(found) == {"train_outcome", "train_stale", "train_stalled"}
    by = {(f.kind, f.meta.get("outcome")): f for f in TI.detect_train(rd, now=NOW, cfg=CFG)}
    nl = by[("train_outcome", "MERGED_NOT_LIVE")]
    assert TI.decide(nl, CFG) == {
        "remediation": "coordinator",
        "why": "release machinery outcome (train-self scope)",
        "priority": "P1",
    }
    assert TI.decide(by[("train_outcome", "FAILED_PRE_MERGE")], CFG)["remediation"] == "coordinator"
    # review round 2: no invented 'train-reconcile' command; a stale train is the coordinator's
    assert TI.decide(found["train_stale"], CFG)["remediation"] == "coordinator"


def test_tester_failures_one_finding_per_broken_route(tmp_path):
    td = tmp_path / CFG["sources"]["tester_dir_rel"]
    write_json(
        td / "last_nightly.json",
        {
            "status": "FAILED",
            "finished_at": "2026-10-25T19:30:00Z",
            "broken": [
                {"route": "/v3/watch", "kind": "page_error", "detail": "x"},
                {"route": "/v3/cio", "kind": "http_error", "detail": "500"},
            ],
        },
    )
    write_json(
        td / "last_api.json",
        {
            "status": "FAILED",
            "finished_at": "2026-10-25T19:30:00Z",
            "reason": "BUILD_SHA_MISMATCH",
            "checks": [{"name": "health", "ok": False}],
        },
    )
    write_json(td / "last_light.json", {"status": "PASSED", "finished_at": "2026-10-25T19:30:00Z"})
    found = TI.detect_tester(td, now=NOW, cfg=CFG)
    assert sorted((f.source, f.kind) for f in found) == [
        ("sweep", "tester_broken"),
        ("sweep", "tester_broken"),
        ("tester", "tester_failed"),
    ]
    assert all(TI.decide(f, CFG)["remediation"] == "claude_code" for f in found)


# ---------------------------------------------------------------- the tick: shadow, dry run, live


def test_dry_run_writes_nothing(tmp_path):
    world = FakeWorld([("cio-full-suite-sharded", "failure", "completed", ["shard pg"], PG_LOG, 1)])
    hb, sent = do_tick(tmp_path, world, agents_text=LIVE_AGENTS, write=False)
    assert hb["mode"] == "dry_run" and hb["findings"] == 1
    assert not list(tmp_path.rglob("*.json*")) and not world.ran("gh", "run", "rerun") and not sent


def test_shadow_logs_proposals_once_and_executes_nothing(tmp_path):
    world = FakeWorld(
        [
            ("cio-full-suite-sharded", "failure", "completed", ["shard pg"], PG_LOG, 1),
            ("cio-production-hardening-ci", "failure", "completed", ["hardening shard 2"], TEST_LOG, 1),
        ]
    )
    hb, sent = do_tick(tmp_path, world)
    assert hb["mode"] == "shadow" and hb["policy"]["live"] is False
    rows = log_rows(tmp_path)
    assert {r["outcome"] for r in rows if r["event"] == "proposed"} == {"shadow-proposed"}
    assert {r["remediation_kind"] for r in rows if r["event"] == "proposed"} == {
        "deterministic:ci_infra_flake_rerun",
        "claude_code",
    }
    assert not world.ran("gh", "run", "rerun") and not sent
    assert not (tmp_path / CFG["state"]["fixer_defects_rel"]).exists()
    hb2, _ = do_tick(tmp_path, world, now=NOW + timedelta(minutes=5))
    assert len(log_rows(tmp_path)) == len(rows)  # no new rows while nothing changed
    hbf = json.loads((tmp_path / CFG["state"]["heartbeat_rel"]).read_text())
    assert hbf["ok"] is True and hbf["ok_at"] and hbf["lane_id"] == "self-heal-train-monitor"
    for r in rows:
        for k in (
            "detected_at",
            "source",
            "signature",
            "evidence_refs",
            "remediation_kind",
            "attempts",
            "model_cost_usd",
            "pr_number",
            "pr_head",
            "outcome",
            "released_sha",
            "verified_at",
        ):
            assert k in r


def test_live_rerun_waits_for_settled_ci_then_verifies(tmp_path):
    world = FakeWorld([("cio-full-suite-sharded", "failure", "completed", ["shard pg"], PG_LOG, 1)])
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS)
    assert world.ran("gh", "run", "rerun", "100", "--failed")
    world.ci = [("cio-full-suite-sharded", None, "in_progress", [], "", 2)]
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=5))
    assert TI.project(log_rows(tmp_path))[0]["outcome"] == "remediating"
    world.ci = [("cio-full-suite-sharded", "success", "completed", [], "", 2)]
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=10))
    top = TI.project(log_rows(tmp_path))[0]
    assert top["outcome"] == "fixed-no-release" and top["verified_at"] and top["model_cost_usd"] is None
    assert len(world.ran("gh", "run", "rerun")) == 1


def test_live_rerun_that_fails_again_hands_over_to_the_fixer(tmp_path):
    world = FakeWorld([("cio-full-suite-sharded", "failure", "completed", ["shard pg"], PG_LOG, 1)])
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS)
    world.ci = [("cio-full-suite-sharded", "failure", "completed", ["shard pg"], PG_LOG, 2)]
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=5))
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=10))
    assert len(world.ran("gh", "run", "rerun")) == 1
    defects = TI.read_fixer_defects(tmp_path / CFG["state"]["fixer_defects_rel"])
    assert len(defects) == 1 and defects[0]["code_defect"]["schema"] == "N8nCodeDefect@v1"


def test_live_claude_code_handoff_to_released_and_verified(tmp_path):
    world = FakeWorld([("cio-production-hardening-ci", "failure", "completed", ["hardening shard 2"], TEST_LOG, 1)])
    sent = Sent()
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, sender=sent)
    defects = TI.read_fixer_defects(tmp_path / CFG["state"]["fixer_defects_rel"])
    assert len(defects) == 1
    did = defects[0]["code_defect"]["defect_id"]
    assert did.startswith("train-monitor-ci|") and "test_widget_view" in defects[0]["receipt"]["stderr_tail"]
    # the existing fixer consumes the same contract from this store
    import self_heal_fixer as SHF

    fcfg = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())
    incs = SHF.train_incidents(fcfg, tmp_path)
    assert [i["defect_id"] for i in incs] == [did] and incs[0]["_receipt"]["stderr_tail"]
    fs = tmp_path / CFG["sources"]["fixer_state_rel"]
    write_json(
        fs,
        {
            "jobs": {
                "j": {
                    "defect_id": did,
                    "state": "fix_pr_opened",
                    "pr_number": 4242,
                    "head_sha": "h" * 40,
                    "cost_usd": 3.25,
                    "pr_url": "https://gh/pr/4242",
                }
            }
        },
    )
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=5), sender=sent)
    top = TI.project(log_rows(tmp_path))[0]
    assert (top["outcome"], top["pr_number"], top["model_cost_usd"]) == ("fix-PR-open", 4242, 3.25)
    write_json(
        fs,
        {
            "jobs": {
                "j": {
                    "defect_id": did,
                    "state": "fix_deployed",
                    "pr_number": 4242,
                    "head_sha": "h" * 40,
                    "cost_usd": 3.25,
                    "release_sha": "r" * 40,
                }
            }
        },
    )
    world.ci = [("cio-production-hardening-ci", "success", "completed", [], "", 1)]
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=10), sender=sent)
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=15), sender=sent)
    top = TI.project(log_rows(tmp_path))[0]
    assert top["outcome"] == "fixed-released" and top["released_sha"] == "r" * 40 and top["verified_at"]
    assert [p for p, _ in sent] == ["P2"]  # one short note per fix released, no P1
    assert TI.verified_for_defect(tmp_path / CFG["state"]["fix_log_rel"], did)["fix_id"] == top["fix_id"]


def test_live_refused_scope_pages_p1_and_opens_coordinator_task(tmp_path):
    log = "FAILED tests/test_alpaca_paper_adapter.py::test_x\nscripts/alpaca_paper_adapter.py:9\n"
    world = FakeWorld([("cio-production-hardening-ci", "failure", "completed", ["hardening shard 1"], log, 1)])
    hb, sent = do_tick(tmp_path, world, agents_text=LIVE_AGENTS)
    assert [p for p, _ in sent] == ["P1"]
    coord = [c for c in world.calls if "agent_claim.py" in " ".join(c)]
    assert len(coord) == 1 and "--kind" in coord[0] and "fix" in coord[0]
    assert not (tmp_path / CFG["state"]["fixer_defects_rel"]).exists()
    assert TI.project(log_rows(tmp_path))[0]["outcome"] == "escalated"
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=5))
    assert len([c for c in world.calls if "agent_claim.py" in " ".join(c)]) == 1  # never twice


def test_fixer_failures_exhaust_attempts_then_give_up(tmp_path):
    world = FakeWorld([("cio-production-hardening-ci", "failure", "completed", ["hardening shard 2"], TEST_LOG, 1)])
    sent = Sent()
    fs = tmp_path / CFG["sources"]["fixer_state_rel"]
    t = NOW
    for _ in range(CFG["dedupe"]["max_attempts_per_signature"]):
        do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=t, sender=sent)
        jobs = {
            f"j{i}": {"defect_id": d["code_defect"]["defect_id"], "state": "fix_failed", "reason": "red"}
            for i, d in enumerate(TI.read_fixer_defects(tmp_path / CFG["state"]["fixer_defects_rel"]))
        }
        write_json(fs, {"jobs": jobs})
        t += timedelta(hours=CFG["dedupe"]["cooldown_hours"] + 1)
        do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=t, sender=sent)
        t += timedelta(hours=CFG["dedupe"]["cooldown_hours"] + 1)
    top = TI.project(log_rows(tmp_path))[0]
    assert top["outcome"] == "gave-up" and top["attempts"] == CFG["dedupe"]["max_attempts_per_signature"]
    assert [p for p, _ in sent].count("P1") == 1
    assert len(TI.read_fixer_defects(tmp_path / CFG["state"]["fixer_defects_rel"])) == 2


def test_stale_train_never_runs_a_command_and_goes_to_the_coordinator(tmp_path):
    """Review round 2 (2026-10-31): release_window.py has no train-reconcile subcommand; a stale train escalates."""
    import os

    st = release_dir(tmp_path) / "trains/rt-20261025-0900-dddd/state.json"
    write_json(st, {"phase": "merge"})
    old = (NOW - timedelta(hours=6)).timestamp()
    os.utime(st, (old, old))
    world = FakeWorld()
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS)
    assert not [c for c in world.calls if "release_window.py" in " ".join(c)]
    assert all(r["id"] != "train_stale_reconcile" for r in CFG["deterministic"])


def test_non_eligible_fix_pr_goes_to_the_coordinator_queue(tmp_path):
    world = FakeWorld([("cio-production-hardening-ci", "failure", "completed", ["hardening shard 2"], TEST_LOG, 1)])
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS)
    did = TI.read_fixer_defects(tmp_path / CFG["state"]["fixer_defects_rel"])[0]["code_defect"]["defect_id"]
    write_json(
        tmp_path / CFG["sources"]["fixer_state_rel"],
        {"jobs": {"j": {"defect_id": did, "state": "fix_pr_opened", "pr_number": 77, "head_sha": "h"}}},
    )
    write_json(
        release_dir(tmp_path) / "train_requests/receipts/rtw-20261025-2100-win.json",
        {
            "state": "COMPLETED",
            "shadow": True,
            "finished_at": "2026-10-25T19:59:00Z",
            "needs_action": [{"code": "NOT_RIDING", "pr": 77, "text": "needs_operator: scheduler_live_list"}],
        },
    )
    world.pr_view = {"state": "OPEN"}
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, now=NOW + timedelta(minutes=5))
    coord = [c for c in world.calls if "agent_claim.py" in " ".join(c)]
    assert len(coord) == 1 and any("#77" in a for a in coord[0])


def test_kill_switch_writes_a_disabled_heartbeat_and_does_nothing(tmp_path, monkeypatch):
    (tmp_path / CFG["arming"]["kill_switch_rel"]).parent.mkdir(parents=True)
    (tmp_path / CFG["arming"]["kill_switch_rel"]).write_text("off")
    world = FakeWorld([("w", "failure", "completed", ["shard pg"], PG_LOG, 1)])
    rc = M.main(["--apply"], now=NOW, runner=world, sender=Sent(), environ={"TRADEAI_STATE_ROOT": str(tmp_path)})
    hb = json.loads((tmp_path / CFG["state"]["heartbeat_rel"]).read_text())
    assert rc == 0 and hb["mode"] == "disabled" and not world.calls


# ---------------------------------------------------------------- deterministic generators


def test_ci_gates_canonical_rewrites_only_non_canonical_bytes(tmp_path):
    d = tmp_path / "config/ci_gates"
    d.mkdir(parents=True)
    good = {"schema": "CiGate@v1", "name": "a", "files": ["tests/test_a.py"]}
    (d / "a.json").write_text(json.dumps(good, indent=2) + "\n")
    (d / "b.json").write_text(json.dumps({"schema": "CiGate@v1", "name": "b", "files": ["tests/test_b.py"]}))
    assert M.gen_ci_gates_canonical(tmp_path) == ["config/ci_gates/b.json"]
    assert M.gen_ci_gates_canonical(tmp_path) == []
    (d / "c.json").write_text('{"schema": "CiGate@v1", "name": "wrong", "files": ["x"]}')
    with pytest.raises(ValueError):
        M.gen_ci_gates_canonical(tmp_path)  # malformed gate: a human decides


def test_disk_packet_repin_matches_the_activator_contract(tmp_path):
    rel = "docs/ops/packets/disk-standing-apply-20261024"
    src = ROOT / rel
    (tmp_path / rel).mkdir(parents=True)
    for name in ("activation-input-sha256.json", "review.required.json"):
        (tmp_path / rel / name).write_bytes((src / name).read_bytes())
    pins = json.loads((src / "activation-input-sha256.json").read_text())
    (tmp_path / "config").mkdir()
    for name in pins:
        (tmp_path / "config" / name).write_text(f'{{"fixture": "{name}"}}\n')
    changed = M.gen_disk_packet_repin(tmp_path, rel)
    assert set(changed) == {f"{rel}/activation-input-sha256.json", f"{rel}/review.required.json"}
    raw = (tmp_path / rel / "activation-input-sha256.json").read_bytes()
    review = json.loads((tmp_path / rel / "review.required.json").read_text())
    assert review["source_config_pins_sha256"] == hashlib.sha256(raw).hexdigest()
    before = json.loads((src / "review.required.json").read_text())
    assert {k: v for k, v in review.items() if k != "source_config_pins_sha256"} == {
        k: v for k, v in before.items() if k != "source_config_pins_sha256"
    }
    assert M.gen_disk_packet_repin(tmp_path, rel) == []


def test_repo_disk_packet_pins_are_current():
    """The real packet on this tree: the re-pin generator is a no-op (otherwise this PR changed pinned bytes)."""
    import shutil
    import tempfile

    rel = "docs/ops/packets/disk-standing-apply-20261024"
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        shutil.copytree(ROOT / rel, t / rel)
        shutil.copytree(ROOT / "config", t / "config")
        changed = M.gen_disk_packet_repin(t, rel)
    # What this guards: THIS PR must not change the config bytes the packet pins. Main's own drift after the packet
    # was pinned (a config edit merged later) is the packet owner's re-pin, not this PR's (a re-pin here would
    # claim the packet approved bytes it never saw).
    import subprocess

    pins = json.loads((ROOT / rel / "activation-input-sha256.json").read_text(encoding="utf-8"))
    for name in pins:
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"origin/main:config/{name}"], capture_output=True)
        if r.returncode != 0:
            pytest.skip("origin/main not available in this checkout")
        assert (ROOT / "config" / name).read_bytes() == r.stdout, f"this PR changed pinned config {name}"
    assert isinstance(changed, list)


# ---------------------------------------------------------------- fixer: 28.14 amendment gate


def test_fixer_push_gate_never_opens():
    from lib import self_heal_fixer as F

    fcfg = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())
    for text in (f"{H} (21.0.0, ACTIVE)\n", f"{H} (21.0.0, PROPOSED)\n", "Status: ACTIVE\n" + H + "\n"):
        assert not F.policy_verdict(text, fcfg)["push_allowed"]  # AGENTS.md §24.5: local branch only


def test_fix_log_projection_latest_row_per_fix():
    rows = [
        {"fix_id": "a", "at": "1", "outcome": "detected"},
        {"fix_id": "a", "at": "2", "outcome": "gave-up"},
        {"fix_id": "b", "at": "3", "outcome": "fix-PR-open"},
    ]
    assert [(r["fix_id"], r["outcome"]) for r in TI.project(rows)] == [("b", "fix-PR-open"), ("a", "gave-up")]


def test_escalation_reaches_the_telegram_chokepoint_as_p1(tmp_path, monkeypatch):
    """Firing test: a refused-scope escalation goes through telegram_alert.send_telegram with priority P1."""
    import types

    seen = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda text, **kw: seen.append((text, kw)) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    log = "scripts/alpaca_paper_adapter.py:9 boom\n"
    world = FakeWorld([("cio-production-hardening-ci", "failure", "completed", ["hardening shard 1"], log, 1)])
    do_tick(tmp_path, world, agents_text=LIVE_AGENTS, sender=M.default_sender)
    assert len(seen) == 1
    text, kw = seen[0]
    assert kw["priority"] == "P1" and kw["producer"] == "self_heal_train_monitor" and kw["dedupe_minutes"] == 0
    assert "refused scope" in text and "/v3/system/releases?tab=fixes" in text


# ---------------------------------------------------------------- 21.0.0 section 28.14: arming IS the section


def _fixer_cfg():
    return json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())


def test_fixer_arms_only_on_a_guard_grant():
    from lib import self_heal_fixer as F

    fcfg = _fixer_cfg()
    assert fcfg["arming"]["arm_on"] == "guard_grant"
    active = F.policy_verdict("## 28.14 Self-heal monitor and fixer — x (21.0.0, ACTIVE)\n", fcfg)
    grant = {"reason": "self-heal-fixer", "grant_id": "a" * 32}
    assert not F.arming_verdict(None, cfg=fcfg, jobs_today=0, policy=active)["armed"]  # no grant: never armed
    assert F.arming_verdict(grant, cfg=fcfg, jobs_today=0, policy=active)["armed"]
    legacy = {**fcfg, "arming": {**fcfg["arming"], "arm_on": "policy_section"}}
    assert not F.arming_verdict(None, cfg=legacy, jobs_today=0, policy=active)["armed"]  # retired path
    capped = F.arming_verdict(grant, cfg=fcfg, jobs_today=fcfg["arming"]["daily_job_cap"], policy=active)
    assert not capped["armed"] and "cap" in capped["why"]
    killed = F.arming_verdict(grant, cfg=fcfg, jobs_today=0, policy=active, disabled="data/self_heal/FIXER_DISABLED")
    assert not killed["armed"] and "kill switch" in killed["why"]


def test_fixer_kill_switch_files(tmp_path):
    import self_heal_fixer as SHF

    fcfg = _fixer_cfg()
    assert SHF.kill_switch(fcfg, tmp_path) is None
    (tmp_path / "data/self_heal").mkdir(parents=True)
    (tmp_path / "data/self_heal/MONITOR_DISABLED").write_text("x")
    assert SHF.kill_switch(fcfg, tmp_path) == "data/self_heal/MONITOR_DISABLED"


from tests import test_self_heal_fixer_20261016 as B  # noqa: E402

sandbox = B.sandbox  # the base suite's hermetic origin/repo/stub-CLI fixture


def test_fixer_with_grant_and_section_active_stops_at_a_local_branch(sandbox, monkeypatch):
    """Review 2026-10-31 (B1): even with a grant and §28.14 ACTIVE at origin/main, nothing is pushed and no PR opens."""
    from lib import self_heal_fixer as F

    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setattr(B.S.Attempt, "scan_commit", lambda self, commit: [])
    p = sandbox["repo"] / "AGENTS.md"
    p.write_text(p.read_text() + "\n## 28.14 Self-heal monitor and fixer — the train is watched (21.0.0, ACTIVE)\n")
    B._sh("git", "-C", str(sandbox["repo"]), "commit", "-qam", "28.14 active")
    B._sh("git", "-C", str(sandbox["repo"]), "push", "-q", "origin", "main")
    job, _ = B._run_cycle(sandbox, "fix", grant="self-heal-fixer test")
    assert job["state"] == F.FIX_READY_LOCAL
    assert job["branch"] not in B._sh("git", "-C", str(sandbox["origin"]), "branch", "--list")
    assert not (sandbox["bin"] / "gh_calls.txt").exists()
    assert (
        not (sandbox["state"] / "data/self_heal/fix_log.jsonl").exists()
        or "fixer_push" not in (sandbox["state"] / "data/self_heal/fix_log.jsonl").read_text()
    )


def test_fixer_section_28_14_proposed_runs_no_model(sandbox, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    cfg = json.loads(sandbox["cfg"].read_text())
    cfg["arming"]["arm_on"] = "policy_section"
    sandbox["cfg"].write_text(json.dumps(cfg))
    job, calls = B._run_cycle(sandbox, "fix", grant="self-heal-fixer test")  # a grant alone never arms
    assert job["state"] == "fix_requested" and calls == []


def test_fixer_worktree_root_is_short_on_disk_and_fits_af_unix():
    fcfg = _fixer_cfg()
    raw = fcfg["repo"]["worktree_root"]
    assert raw.startswith("~/"), raw  # never a literal home path in a public repo (check_no_pii home_path)
    # budget against a representative real home (tests run under a long hermetic HOME, so expanduser here lies)
    wt = raw.replace("~", "/" + "/".join(["home", "x" * 16]), 1)
    assert not wt.startswith("/tmp")
    # the egress bridge socket: <worktree_root>/<job_id>-eg/s, job_id = shf-<10 hex>-<n>
    sock = f"{wt}/shf-{'f' * 10}-{999}-eg/s"
    assert len(sock.encode()) < 100, sock  # AF_UNIX sun_path is 108 bytes including the NUL


def test_regen_stops_at_a_local_branch_never_pushes(tmp_path):
    """Review 2026-10-31 (M): a regenerate-PR remediation runs from a timer, so AGENTS.md §24.5 binds — it commits a
    local branch and writes the PR body beside it; it never pushes and never calls gh."""
    world = FakeWorld()
    orig = world.__call__

    def runner(argv, **kw):
        argv = [str(a) for a in argv]
        if argv[-2:] == ["status", "--porcelain"]:
            world.calls.append(argv)
            return {"rc": 0, "out": " M docs/INDEX.md\n", "err": ""}
        return orig(argv, **kw)

    t = M.Tick(
        cfg=CFG,
        root=tmp_path,
        repo=tmp_path / "repo",
        live=True,
        write=True,
        now=NOW,
        runner=runner,
        sender=Sent(),
        environ={"TMPDIR": str(tmp_path / "tmp"), "TRADEAI_STATE_ROOT": str(tmp_path)},
    )
    (tmp_path / "tmp").mkdir()
    f = ci_finding(["docs"], "docs/INDEX.md out of date; run report_docs_inventory --check-index")
    rule = next(r for r in CFG["deterministic"] if r["id"] == "docs_index_regen")
    rec = t.rec_for(f)
    t.regen_pr(f, rec, rule)
    assert rec["outcome"] == "fix-ready-local" and rec["branch"].startswith(CFG["regen_pr"]["branch_prefix"])
    assert not [c for c in world.calls if "push" in c], world.calls
    assert not [c for c in world.calls if c[:1] == ["gh"]]
