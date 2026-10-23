"""Work pipeline (operator 2026-10-23 13:15 ET): one row per work item, incubator stages with RAG. Hermetic.

The operator's complaint was that finished work waiting for a batch looked "stale". These tests pin the stage/RAG
derivation (green CI = AMBER waiting for batch, never stale; stale only pre-PR without heartbeat or CI failed and
idle), the grouping (task > PR > claim > design), the next-step owner, and the memory/GitHub bounds of the served view
(single-flight cache, census at most once per 60 s, never on the request path, read-only gh only).
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import work_pipeline as W  # noqa: E402

NOW = datetime(2026, 10, 23, 17, 30, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ago(**kw) -> str:
    return iso(NOW - timedelta(**kw))


def claim(cid="20261023T150000Z-claude-aaaaaaaa", *, state="live", stage="claimed", hb_min=5, pr=None, ci=None, **kw):
    d = {
        "claim_id": cid,
        "state": state,
        "status": "active",
        "stage": stage,
        "stages": {"claimed": ago(hours=3)},
        "vendor": "claude",
        "agent": "acctlabel",
        "session": "2e7e1d01-acctlabel",
        "task": "Account labels",
        "paths": ["scripts/a.py", "apps/b.tsx"],
        "branch": "feat/x",
        "worktree": "/home/x/wt-x",
        "started_at": ago(hours=3),
        "heartbeat_at": ago(minutes=hb_min),
        "pr_number": pr,
        "ci": ci,
        "worklog": {"exists": False},
    }
    d.update(kw)
    return d


def open_pr(n=2005, ci_state="green", **kw):
    d = {
        "number": n,
        "title": f"PR {n}",
        "url": f"https://github.com/o/r/pull/{n}",
        "branch": f"feat/{n}",
        "head_sha": "abc1234def",
        "base": "main",
        "draft": False,
        "author": "PatsKiller",
        "created_at": ago(hours=4),
        "updated_at": ago(hours=3),
        "state": "open",
        "ci": {"state": ci_state, "failing": ["shard 5"] if ci_state == "failing" else [], "pending": [], "total": 20,
               "completed_at": ago(hours=3) if ci_state == "green" else None},
    }  # fmt: skip
    d.update(kw)
    return d


def cell(d, stage):
    return next(c for c in d["cells"] if c["stage"] == stage)


# --------------------------------------------------------------------------------------------- the operator's rule


def test_green_ci_not_in_batch_is_amber_waiting_for_batch_never_stale():
    # no heartbeat for 3 h: the old view called this "stale"
    c = claim(state="stale", stage="ci_green", hb_min=180, pr=2005, ci={"state": "green"})
    d = W.derive(claims=[c], pr=open_pr(2005), now=NOW)
    assert d["stage"] == "in_batch" and d["rag"] == "amber" and d["label"] == "waiting for batch"
    assert d["stale"] is False and d["waiting_for_batch"] is True
    assert "stale" not in json.dumps(d["cells"]).lower()
    assert cell(d, "ci")["rag"] == "green" and cell(d, "merged")["rag"] == "grey"
    assert d["next"]["text"].startswith("Coordinator: add #2005")


def test_stale_only_pre_pr_without_heartbeat():
    fresh = W.derive(claims=[claim(hb_min=30)], now=NOW)
    assert fresh["stage"] == "claimed" and fresh["rag"] == "amber" and not fresh["stale"]
    building = W.derive(claims=[claim(hb_min=30, stages={"claimed": ago(hours=3), "building": ago(hours=2)})], now=NOW)
    assert building["stage"] == "building" and building["rag"] == "amber"
    old = W.derive(claims=[claim(state="stale", hb_min=150)], now=NOW)
    assert old["stage"] == "claimed" and old["rag"] == "red" and old["stale"] and old["label"] == "stale"
    assert "takeover" in old["next"]["text"]


def test_ci_failing_red_and_stale_only_when_idle_over_2h():
    busy = W.derive(pr=open_pr(2016, "failing", updated_at=ago(minutes=20)), now=NOW)
    assert busy["stage"] == "ci" and busy["rag"] == "red" and not busy["stale"] and "fail" in busy["label"]
    idle = W.derive(pr=open_pr(2011, "failing", updated_at=ago(hours=3)), now=NOW)
    assert idle["rag"] == "red" and idle["stale"] and idle["label"] == "stale"
    assert idle["blocker"].startswith("CI failing: shard 5")
    pending = W.derive(pr=open_pr(2017, "pending", updated_at=ago(hours=5)), now=NOW)
    assert pending["stage"] == "ci" and pending["rag"] == "amber" and not pending["stale"]


def test_in_batch_member_and_batch_pr():
    batches = {2018: {"number": 2018, "members": [2012, 1994], "excluded": {1997: "Active Trader files. The operator merges those."},
                      "ci": {"state": "failing", "failing": ["shard 5", "ci-gate"]}}}  # fmt: skip
    m = W.derive(pr=open_pr(2012), batches=batches, now=NOW)
    assert m["stage"] == "in_batch" and m["rag"] == "amber" and m["label"] == "#2018" and m["batch"] == 2018
    assert "shard 5" in m["blocker"] and m["next"]["text"] == "Agent: fix batch #2018 CI"
    ex = W.derive(pr=open_pr(1997), batches=batches, now=NOW)
    assert ex["label"] == "operator merge" and ex["next"]["owner"] == "operator" and "merge #1997" in ex["next"]["text"]
    b = W.derive(
        pr=open_pr(2018, "failing", branch="release/batch-9-20261023", updated_at=ago(minutes=10)),
        batches=batches,
        now=NOW,
    )
    assert b["is_batch"] and b["stage"] == "ci" and b["rag"] == "red"
    bg = W.derive(pr=open_pr(2018, "green", branch="release/batch-9-20261023"), batches=batches, now=NOW)
    assert bg["stage"] == "in_batch" and bg["next"] == {"owner": "operator", "text": "Operator: merge batch #2018"}


def test_merged_released_verified():
    merged = {**open_pr(2002), "state": "merged", "merged_at": ago(hours=2), "merge_sha": "80e93c99f", "ci": None}
    m = W.derive(pr=merged, now=NOW)
    assert m["stage"] == "merged" and m["rag"] == "amber" and m["label"] == "awaiting release"
    rel = {"at": ago(hours=1), "sha": "80e93c99f", "basis": "release_pins/apply-x.json"}
    r = W.derive(pr={**merged, "released": rel}, health={"ok": None, "sha": None}, now=NOW)
    assert r["stage"] == "released" and r["rag"] == "amber" and not r["finished"]
    bad = W.derive(
        pr={**merged, "released": rel}, health={"ok": False, "sha": "80e93c99f", "health": "degraded"}, now=NOW
    )
    assert bad["rag"] == "red"
    v = W.derive(
        pr={**merged, "released": rel}, health={"ok": True, "sha": "80e93c99f", "at": ago(minutes=50)}, now=NOW
    )
    assert v["stage"] == "verified" and v["finished"] and all(c["rag"] == "green" for c in v["cells"])


def test_queued_task_blocked_and_operator_todo():
    t = {
        "task_id": "T-20261023-fc7872",
        "title": "Server memory kills",
        "status": "free",
        "created_at": ago(hours=3),
        "blocked_by": [],
    }
    q = W.derive(task=t, now=NOW)
    assert q["stage"] == "queued" and q["rag"] == "amber" and q["next"]["owner"] == "agent"
    assert cell(q, "proposed")["rag"] == "green" and cell(q, "claimed")["rag"] == "grey"
    blocked = W.derive(task={**t, "blocked_by": ["DSN-20261023-agent-ops-P1-T1"]}, now=NOW)
    assert blocked["rag"] == "red" and blocked["blocker"].startswith("waits for")
    op = W.derive(task={**t, "title": "OPERATOR: run hotlist-budget-operator.sh"}, now=NOW)
    assert op["next"] == {"owner": "operator", "text": "Operator: run hotlist-budget-operator.sh"}


def test_held_and_queue_position():
    held = W.derive(
        pr=open_pr(2005), held={"by": "tailnet:op", "at": ago(minutes=5), "reason": "wait for review"}, now=NOW
    )
    assert held["label"] == "held" and held["next"]["owner"] == "operator" and "wait for review" in held["blocker"]
    q = W.derive(pr=open_pr(2005), queue_position=2, now=NOW)
    assert q["label"] == "next batch #2" and q["waiting_for_batch"]


def test_design_awaiting_is_proposed_operator_owned():
    d = W.derive(
        design={
            "id": "DSN-20261022-data-domains",
            "awaiting": True,
            "approval": "awaiting operator",
            "title": "Data domains",
        },
        now=NOW,
    )
    assert d["stage"] == "proposed" and d["next"]["owner"] == "operator"


def test_worklog_next_step_wins_before_ci_green_only():
    wl = {"exists": True, "next_step": "Operator: contract review of #2016", "blockers": 0}
    d = W.derive(claims=[claim(pr=2016, worklog=wl)], pr=open_pr(2016, "failing", updated_at=ago(minutes=5)), now=NOW)
    assert d["next"] == {"owner": "operator", "text": "Operator: contract review of #2016"}
    late = W.derive(claims=[claim(pr=2005, worklog={**wl, "next_step": "watch CI"})], pr=open_pr(2005), now=NOW)
    assert late["next"]["text"].startswith("Coordinator")


def test_draft_held_pr_is_proposed_for_operator():
    d = W.derive(pr=open_pr(1937, "failing", draft=True, title="DRAFT flip(release-train): controller ACTIVE"), now=NOW)
    assert d["stage"] == "proposed" and d["next"]["owner"] == "operator"


# --------------------------------------------------------------------------------------------- grouping


def test_build_items_groups_by_work_item_and_summarizes():
    tasks = [
        {"task_id": "T-20261023-aaaaaa", "title": "OPERATOR: rotate DB password", "status": "free", "created_at": ago(hours=2), "areas": ["x"]},
        {"task_id": "T-20261023-bbbbbb", "title": "Fix it", "status": "taken", "claim_id": "20261023T150000Z-claude-bbbbbbbb", "created_at": ago(hours=2), "areas": ["y"]},
    ]  # fmt: skip
    claims = [
        claim("20261023T150000Z-claude-bbbbbbbb", pr=2005),
        claim("20261023T150100Z-claude-cccccccc", pr=2005, agent="p3ui"),  # second claim on the same PR
        claim("20261023T150200Z-claude-dddddddd", pr=2017, paths=["a", "b", "c"]),
        claim("20261023T150300Z-claude-eeeeeeee", state="abandoned", stage="abandoned"),
    ]
    census = {"open": [open_pr(2005), open_pr(2017, "pending"), open_pr(1999)], "merged": [], "batches": {}}
    items = W.build_items(tasks=tasks, claims=claims, census=census, now=NOW, latest_line=lambda p: None)
    ids = [i["id"] for i in items]
    assert ids.count("T-20261023-bbbbbb") == 1 and "PR-2005" not in ids  # the task owns its PR
    task_item = next(i for i in items if i["id"] == "T-20261023-bbbbbb")
    assert task_item["pr_number"] == 2005 and len(task_item["how"]["claim_ids"]) == 2
    assert {"PR-2017", "PR-1999"} <= set(ids) and "20261023T150300Z-claude-eeeeeeee" not in ids
    op = next(i for i in items if i["id"] == "T-20261023-aaaaaa")
    assert op["who"]["label"] == "OPERATOR" and op["next"]["owner"] == "operator"
    assert op["next"]["command"].startswith("python3 scripts/agent_claim.py task show")
    assert "task_done" in op["actions"]["available"]
    pr17 = next(i for i in items if i["id"] == "PR-2017")
    assert pr17["where"]["file_count"] == 3 and pr17["links"]["ci"].endswith("/pull/2017/checks")
    s = W.summarize(items)
    assert s["needs_me"] == 1 and s["counts"]["queued"] == 1 and s["waiting_for_batch"] == 2


def test_operator_merge_command_has_real_pr_and_sha():
    batches = {2018: {"number": 2018, "members": [], "excluded": {1997: "Active Trader"}, "ci": {"state": "green"}}}
    items = W.build_items(
        tasks=[],
        claims=[],
        census={"open": [open_pr(1997, head_sha="0123456789ab")], "merged": [], "batches": batches},
        now=NOW,
    )
    assert items[0]["next"]["command"] == "gh pr merge 1997 --merge --match-head-commit 0123456789ab"


def test_actions_offered_match_state():
    claims = [claim(state="stale", hb_min=200)]
    items = W.build_items(tasks=[], claims=claims, census={"open": [open_pr(2005)], "merged": [], "batches": {}},
                          queue={"next_batch": [], "held_prs": {}}, now=NOW)  # fmt: skip
    by = {i["id"]: i for i in items}
    assert "release_stale_claim" in by[claims[0]["claim_id"]]["actions"]["available"]
    assert "batch_add" in by["PR-2005"]["actions"]["available"]
    items = W.build_items(tasks=[], claims=[], census={"open": [open_pr(2005)], "merged": [], "batches": {}},
                          queue={"next_batch": [{"pr": 2005}], "held_prs": {}}, now=NOW)  # fmt: skip
    assert "batch_remove" in items[0]["actions"]["available"] and items[0]["queue_position"] == 1


# --------------------------------------------------------------------------------------------- census + bounds


def test_ci_from_rollup_checkruns_and_status_contexts():
    roll = [
        {"__typename": "CheckRun", "name": "a", "status": "COMPLETED", "conclusion": "SUCCESS", "completedAt": "2026-10-23T15:00:00Z", "startedAt": "2026-10-23T14:50:00Z"},
        {"__typename": "CheckRun", "name": "b", "status": "COMPLETED", "conclusion": "FAILURE", "startedAt": "2026-10-23T14:50:00Z"},
        {"__typename": "CheckRun", "name": "b", "status": "COMPLETED", "conclusion": "SUCCESS", "completedAt": "2026-10-23T15:10:00Z", "startedAt": "2026-10-23T15:05:00Z"},
        {"__typename": "StatusContext", "context": "c", "state": "SUCCESS", "createdAt": "2026-10-23T15:01:00Z"},
    ]  # fmt: skip
    ci = W.ci_from_rollup(roll)
    assert ci["state"] == "green" and ci["completed_at"] == "2026-10-23T15:10:00Z"
    assert W.ci_from_rollup(roll, required=["a", "zz"])["state"] == "pending"
    assert W.ci_from_rollup(roll[:2])["state"] == "failing"
    assert W.ci_from_rollup(None)["state"] == "unknown"


def test_parse_batch_body():
    body = "## Included (in merge order)\n| # | Head | What |\n|---|---|---|\n| #2012 | e86 | mem |\n| #1994 | 237 | claims |\n\n## Excluded\n- #1991, #1997: Active Trader files. The operator merges those.\n- No AGENTS changes.\n"
    got = W.parse_batch_body(body)
    assert got["members"] == [2012, 1994] and set(got["excluded"]) == {1991, 1997}


class FakeGh:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.gate = threading.Event()
        self.gate.set()

    def __call__(self, argv):
        self.gate.wait(5)
        self.calls.append(argv)
        if argv[:3] == ["gh", "api", "--method"]:
            return json.dumps({"contexts": ["ci-gate"]}), None
        if argv[:3] == ["gh", "pr", "list"] and "open" in argv:
            return json.dumps([
                {"number": 2018, "title": "batch", "headRefName": "release/batch-9-x", "baseRefName": "main", "statusCheckRollup": [
                    {"name": "ci-gate", "status": "COMPLETED", "conclusion": "FAILURE"}]},
                {"number": 2005, "title": "x", "headRefName": "feat/x", "baseRefName": "main", "statusCheckRollup": [
                    {"name": "ci-gate", "status": "COMPLETED", "conclusion": "SUCCESS", "completedAt": "2026-10-23T15:00:00Z"}]},
            ]), None  # fmt: skip
        if argv[:3] == ["gh", "pr", "list"]:
            return "[]", None
        if argv[:3] == ["gh", "pr", "view"]:
            return json.dumps({"body": "## Included\n| #2012 | x | y |\n"}), None
        return None, "unexpected"


def test_census_single_flight_and_min_interval():
    gh = FakeGh()
    t = [0.0]
    c = W.PrCensus(runner=gh, clock=lambda: t[0], now=lambda: NOW)
    assert c.kick(background=False) is True
    n = len(gh.calls)
    assert c.kick(background=False) is False and len(gh.calls) == n  # within 60 s: no second refresh
    t[0] = 59.0
    assert c.kick(background=False) is False
    t[0] = 61.0
    gh.gate.clear()
    assert c.kick(background=True) is True
    assert c.kick(background=True) is False  # one in flight: never two
    gh.gate.set()
    for _ in range(100):
        if not c.snapshot()[1]["refreshing"]:
            break
        threading.Event().wait(0.02)
    val, meta = c.snapshot()
    assert meta["refreshes"] == 2 and 2018 in val["batches"] and val["batches"][2018]["members"] == [2012]
    assert next(p for p in val["open"] if p["number"] == 2005)["ci"]["state"] == "green"


def test_census_failure_keeps_last_good():
    gh = FakeGh()
    t = [0.0]
    c = W.PrCensus(runner=gh, clock=lambda: t[0], now=lambda: NOW)
    c.kick(background=False)
    good = c.snapshot()[0]
    c.runner = lambda argv: (None, "gh timed out after 25s")
    t[0] = 120.0
    c.kick(background=False)
    val, meta = c.snapshot()
    assert val is good and "unavailable" in meta["warning"]


def test_gh_runner_refuses_writes(monkeypatch):
    called = []
    monkeypatch.setattr(W.subprocess, "run", lambda *a, **k: called.append(a))
    for argv in (
        ["gh", "pr", "merge", "1"],
        ["gh", "api", "repos/x/pulls/1/merge"],
        ["gh", "api", "--method", "PUT", "x"],
    ):
        out, warn = W._gh_runner(argv)
        assert out is None and "refused" in warn
    assert called == []


def test_view_never_waits_on_github_and_is_cached():
    gh = FakeGh()
    gh.gate.clear()  # GitHub hangs
    builds = []
    c = W.PrCensus(runner=gh, now=lambda: NOW)
    wp = W.WorkPipeline(census=c, sources=lambda: builds.append(1) or {"tasks": [], "claims": [], "awaiting": []},
                        health=lambda: {"ok": None, "sha": None}, now=lambda: NOW, ttl=30)  # fmt: skip
    v1 = wp.view()  # census refresh starts in the background; the view returns at once
    v2 = wp.view()
    assert v1 is v2 and len(builds) == 1 and v1["schema"] == W.SCHEMA
    assert v1["sources"]["census"]["refreshing"] is True
    gh.gate.set()


def test_latest_worklog_line_bounded_tail(tmp_path):
    p = tmp_path / "w.md"
    filler = "x" * (W.WORKLOG_TAIL_BYTES * 2)
    p.write_text(
        f"# W\n{filler}\n## Plan\n\n- [x] Mockup  _(added 2026-10-23T17:19:12Z)_  _(done 2026-10-23T17:22:42Z)_\n"
        "## Decisions\n\n- `2026-10-23T17:40:00Z` chose single-flight\n- `2026-10-23T17:50:00Z` heartbeat (auto)\n"
    )
    assert W.latest_worklog_line(str(p)) == "chose single-flight"
    assert W.latest_worklog_line(str(tmp_path / "missing.md")) is None


def test_release_health_reads_receipt(tmp_path):
    (tmp_path / "deploy_receipt.json").write_text(
        json.dumps({"ok": True, "health": "ok", "deployed_sha": "80e93c99f", "at": "2026-10-23T16:06:35Z"})
    )
    h = W.release_health(tmp_path)
    assert h["ok"] is True and h["sha"] == "80e93c99f"
    assert W.release_health(tmp_path / "nope")["ok"] is None


def test_claim_without_pr_is_matched_to_its_branch_pr_not_stale():
    c = claim(state="stale", hb_min=240, branch="release/batch-8-20261023")
    merged = {**open_pr(2002, branch="release/batch-8-20261023"), "state": "merged", "merged_at": ago(hours=2), "merge_sha": "80e93c99f", "ci": None,
              "released": {"at": ago(hours=1), "sha": "80e93c99f", "basis": "served CURRENT/BUILD_SHA"}}  # fmt: skip
    items = W.build_items(tasks=[], claims=[c], census={"open": [], "merged": [merged], "batches": {}},
                          health={"ok": True, "sha": "80e93c99f", "at": ago(minutes=30)}, now=NOW)  # fmt: skip
    assert [i["id"] for i in items] == ["PR-2002"]
    assert items[0]["stage"] == "verified" and not items[0]["stale"] and items[0]["how"]["claim_ids"] == [c["claim_id"]]


def test_batch_member_merge_command_names_the_batch_pr_and_its_head():
    batches = {2018: {"number": 2018, "members": [2012], "excluded": {}, "ci": {"state": "green"}}}
    census = {
        "open": [open_pr(2012), open_pr(2018, branch="release/batch-9-x", head_sha="b" * 40)],
        "merged": [],
        "batches": batches,
    }
    items = {i["id"]: i for i in W.build_items(tasks=[], claims=[], census=census, now=NOW)}
    assert items["PR-2012"]["next"]["text"] == "Operator: merge batch #2018"
    assert items["PR-2012"]["next"]["command"] == "gh pr merge 2018 --merge --match-head-commit " + "b" * 40


def test_operator_task_command_has_no_placeholder():
    t = {
        "task_id": "T-20261023-73f31d",
        "title": "OPERATOR: run hotlist-budget-operator.sh",
        "status": "free",
        "created_at": ago(hours=1),
        "areas": ["x"],
    }
    items = W.build_items(tasks=[t], claims=[], census={}, now=NOW)
    cmd = items[0]["next"]["command"]
    assert "<" not in cmd and ">" not in cmd


def test_merged_batch_keeps_its_standing_exclusion():
    batches = {
        2018: {
            "number": 2018,
            "members": [],
            "excluded": {1997: "Active Trader files. The operator merges those."},
            "merged": True,
        }
    }
    d = W.derive(pr=open_pr(1997), batches=batches, now=NOW)
    assert d["label"] == "operator merge" and d["next"]["owner"] == "operator"
