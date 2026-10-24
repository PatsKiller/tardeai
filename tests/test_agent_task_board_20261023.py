"""Agent task board (operator 2026-10-23; AGENTS.md 20.0.0 §28.3a names): hermetic, temp dirs only.

Covers: task add/split/list/show/done/release, `next` (priority, dependencies, overlap with live claims, kind filter),
`take <task-id>` (refusals say why), `claim --add` (refused on overlap), concurrent `next` from many processes never
handing out overlapping work, release then re-pick preserving history and carrying the worklog forward, acceptance
boxes checked on done, DSN design-task ids, and the additive task_board field in the claims API.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import agent_claim as CLI  # noqa: E402
from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import agent_claim_lifecycle as LC  # noqa: E402
from scripts.lib import agent_claim_worklog as WL  # noqa: E402
from scripts.lib import agent_task_board as TB  # noqa: E402

T0 = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t: datetime = T0):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t = self.t + timedelta(**kw)


def tb(tmp_path, clock=None) -> TB.TaskBoard:
    return TB.TaskBoard(B.ClaimBoard(tmp_path / "claims", now=clock or Clock()))


def add(t: TB.TaskBoard, title, areas, **kw):
    return t.add(title=title, kind=kw.pop("kind", "build"), areas=areas, **kw)


def nxt(t: TB.TaskBoard, session, **kw):
    return t.next(vendor="claude", session=session, agent=None, **kw)


def test_add_validates_and_writes_history(tmp_path):
    t = tb(tmp_path)
    with pytest.raises(TB.TaskError, match="kind"):
        t.add(title="x", kind="nope", areas=["a"])
    with pytest.raises(TB.TaskError, match="area"):
        t.add(title="x", kind="fix", areas=[])
    with pytest.raises(TB.TaskError, match="does not exist"):
        add(t, "x", ["a"], depends_on=["T-20261023-abcdef"])
    d = add(t, "x", ["scripts/a.py"], acceptance=["tests pass"], operator_quote="do x", estimate="1h")
    assert d["status"] == "free" and d["history"][0]["event"] == "added"
    ev = json.loads((t.history).read_text().splitlines()[-1])
    assert ev["schema"] == TB.EVENT_SCHEMA and ev["task_id"] == d["task_id"]


def test_next_priority_then_age_and_kind(tmp_path):
    clock = Clock()
    t = tb(tmp_path, clock)
    low = add(t, "low", ["a.py"], priority=3)
    clock.advance(minutes=1)
    high = add(t, "high", ["b.py"], priority=1)
    fix = add(t, "fix", ["c.py"], priority=5, kind="fix")
    assert nxt(t, "s1")[0]["task_id"] == high["task_id"]
    assert nxt(t, "s2", kind="fix")[0]["task_id"] == fix["task_id"]
    assert nxt(t, "s3")[0]["task_id"] == low["task_id"]
    assert nxt(t, "s4") is None


def test_next_respects_dependencies(tmp_path):
    t = tb(tmp_path)
    a = add(t, "design", ["docs/d.md"], kind="design", priority=5)
    b = add(t, "build", ["scripts/b.py"], depends_on=[a["task_id"]], priority=1)
    got, _claim = nxt(t, "s1")
    assert got["task_id"] == a["task_id"]  # b is higher priority but blocked
    assert nxt(t, "s2") is None
    t.done(a["task_id"], session="s1")
    assert nxt(t, "s2")[0]["task_id"] == b["task_id"]


def test_split_parent_done_when_children_done(tmp_path):
    t = tb(tmp_path)
    p = add(t, "big", ["scripts/x"], priority=2)
    dep = add(t, "after", ["docs/after.md"], depends_on=[p["task_id"]])
    kids = t.split(
        p["task_id"], [TB.parse_part("part one | scripts/x/a.py | a ok"), TB.parse_part("part two | scripts/x/b.py")]
    )
    assert t.get(p["task_id"])["status"] == "split" and len(kids) == 2
    assert kids[0]["acceptance"] == ["a ok"] and kids[0]["parent"] == p["task_id"]
    picked = [nxt(t, f"k{i}")[0] for i in range(2)]
    assert {g["parent"] for g in picked} == {p["task_id"]}
    assert nxt(t, "x") is None  # "after" still blocked
    for i, g in enumerate(picked):
        t.done(g["task_id"], session=f"k{i}")
    assert nxt(t, "x")[0]["task_id"] == dep["task_id"]
    cols = {r["task_id"]: r["column"] for r in t.board()["tasks"]}
    assert cols[p["task_id"]] == "done"


def test_next_skips_tasks_overlapping_a_live_claim(tmp_path):
    t = tb(tmp_path)
    t.claims.claim(vendor="codex", session="other", agent=None, task="t", paths=["scripts"], branch="b")
    blocked = add(t, "touches scripts", ["scripts/a.py"], priority=1)
    ok = add(t, "touches docs", ["docs/a.md"], priority=2)
    assert nxt(t, "s1")[0]["task_id"] == ok["task_id"]
    with pytest.raises(B.ClaimConflict):
        nxt(t, "s1", task_id=blocked["task_id"])


def test_take_specific_task_and_refusals(tmp_path):
    t = tb(tmp_path)
    a = add(t, "a", ["a.py"])
    b = add(t, "b", ["b.py"], depends_on=[a["task_id"]])
    with pytest.raises(TB.TaskError, match="waits on"):
        nxt(t, "s1", task_id=b["task_id"])
    got, claim = nxt(t, "s1", task_id=a["task_id"])
    assert got["status"] == "taken" and claim["paths"] == ["a.py"]
    with pytest.raises(TB.TaskError, match="held by claude/s1"):
        nxt(t, "s2", task_id=a["task_id"])


def test_next_opens_worklog_with_acceptance_plan_and_done_checks_it(tmp_path):
    t = tb(tmp_path)
    a = add(t, "a", ["a.py"], acceptance=["tests pass", "docs updated"], operator_quote="make it so")
    got, claim = nxt(t, "s1")
    text = WL.path_for(t.claims.dir, claim["claim_id"]).read_text()
    assert "- [ ] tests pass" in text and "- [ ] docs updated" in text and "> make it so" in text
    assert f"[{a['task_id']}]" in text
    done = t.done(a["task_id"], session="s1", summary="all good", actual_cost="$1")
    s = WL.summarize(WL.path_for(t.claims.dir, claim["claim_id"]).read_text())
    assert (s["plan_done"], s["plan_total"]) == (2, 2)
    assert done["actual"]["cost"] == "$1" and done["actual"]["minutes"] == 0.0
    with pytest.raises(TB.TaskError, match="not taken"):
        t.done(a["task_id"], session="s1")


def test_release_then_repick_preserves_history_and_worklog(tmp_path):
    clock = Clock()
    t = tb(tmp_path, clock)
    a = add(t, "a", ["a.py"], acceptance=["one", "two"])
    _got, c1 = nxt(t, "s1")
    t.claims.worklog(c1["claim_id"]).done("one")
    with pytest.raises(TB.TaskError, match="taken by session"):
        t.release(a["task_id"], session="s2", handoff="x")
    with pytest.raises(TB.TaskError, match="handoff"):
        t.release(a["task_id"], session="s1", handoff="")
    rel = t.release(a["task_id"], session="s1", handoff="finish step two; tests in tests/x.py")
    assert rel["status"] == "free" and rel["owner"] is None and rel["handoff"].startswith("finish step two")
    assert t.claims.get(c1["claim_id"]).doc["status"] == "abandoned"
    clock.advance(minutes=30)
    got, c2 = nxt(t, "s2")
    assert got["task_id"] == a["task_id"] and got["claims"] == [c1["claim_id"], c2["claim_id"]]
    assert [e["event"] for e in got["history"]] == ["added", "taken", "released", "taken"]
    text = WL.path_for(t.claims.dir, c2["claim_id"]).read_text()
    assert "- [x] one" in text and "- [ ] two" in text  # carried forward
    assert f"re-picked by claude/s2 from claim {c1['claim_id']}" in text and "finish step two" in text
    events = [json.loads(ln)["event"] for ln in t.history.read_text().splitlines()]
    assert events == ["added", "taken", "released", "taken"]  # append-only file agrees


def _worker(args):
    claims_dir, session = args
    t = TB.TaskBoard(B.ClaimBoard(claims_dir))
    out = []
    while True:
        got = t.next(vendor="claude", session=session, agent=None)
        if got is None:
            return out
        out.append((got[0]["task_id"], got[1]["claim_id"], tuple(got[0]["areas"])))


def test_concurrent_next_never_hands_out_overlapping_work(tmp_path):
    t = tb(tmp_path)
    # 12 tasks; several pairs share a directory, so at most one of each overlapping group may be live at once
    areas = [
        ["shared/x"],
        ["shared/x/a.py"],
        ["shared/x/b.py"],
        ["docs/one.md"],
        ["docs/*.md"],
        ["scripts/a.py"],
        ["scripts/a.py"],
        ["tests/t1.py"],
        ["tests/t2.py"],
        ["apps/**/*.tsx"],
        ["apps/x/y.tsx"],
        ["solo.txt"],
    ]
    for i, ar in enumerate(areas):
        add(t, f"t{i}", ar)
    ctx = mp.get_context("fork")
    with ctx.Pool(6) as pool:
        results = pool.map(_worker, [(str(tmp_path / "claims"), f"s{i}") for i in range(6)])
    taken = [x for r in results for x in r]
    ids = [x[0] for x in taken]
    assert len(ids) == len(set(ids))  # no task handed out twice
    for i in range(len(taken)):
        for j in range(i + 1, len(taken)):
            for pa in taken[i][2]:
                for pb in taken[j][2]:
                    assert not B.patterns_overlap(pa, pb), (taken[i], taken[j])
    # every handed-out task is taken by exactly the claim recorded
    for tid, cid, _ in taken:
        assert t.get(tid)["claim_id"] == cid


def test_claim_add_extends_and_refuses_overlap(tmp_path, capsys):
    base = ["--claims-dir", str(tmp_path / "claims"), "--no-gh", "--vendor", "claude"]
    assert (
        CLI.main([*base, "--session", "other", "claim", "--task", "t", "--paths", "scripts/held.py", "--branch", "b0"])
        == 0
    )
    assert CLI.main([*base, "--session", "s1", "claim", "--task", "t", "--paths", "docs/a.md", "--branch", "b1"]) == 0
    cid = capsys.readouterr().out.strip().splitlines()[-1]
    assert CLI.main([*base, "--session", "s1", "claim", "--add", "docs/b.md"]) == 0
    assert B.ClaimBoard(tmp_path / "claims").get(cid).doc["paths"] == ["docs/a.md", "docs/b.md"]
    assert CLI.main([*base, "--session", "s1", "claim", "--add", "scripts/held.py"]) == 1
    assert "held by" in capsys.readouterr().err
    changes = "\n".join(WL.parse(WL.path_for(tmp_path / "claims", cid).read_text())[1]["Changes made"])
    assert "claim extended: docs/b.md" in changes


def test_cli_task_flow(tmp_path, capsys):
    base = ["--claims-dir", str(tmp_path / "claims"), "--no-gh", "--vendor", "codex", "--session", "c1"]
    assert (
        CLI.main(
            [
                *base,
                "task",
                "add",
                "--title",
                "fix Y",
                "--kind",
                "fix",
                "--areas",
                "y.py",
                "--acceptance",
                "y fixed",
                "--priority",
                "1",
                "--estimate",
                "30m",
            ]
        )
        == 0
    )
    tid = capsys.readouterr().out.strip()
    assert CLI.main([*base, "next"]) == 0
    assert tid in capsys.readouterr().out
    assert CLI.main([*base, "next"]) == 3  # nothing left
    assert CLI.main([*base, "task", "list"]) == 0
    assert "taken" in capsys.readouterr().out
    assert CLI.main([*base, "task", "done", tid, "--summary", "ok"]) == 0
    capsys.readouterr()
    assert CLI.main([*base, "task", "show", tid, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert [e["event"] for e in shown["history"]] == ["added", "taken", "done"]
    assert TB.TaskBoard(B.ClaimBoard(tmp_path / "claims")).get(tid)["status"] == "done"


def test_design_task_ids_and_take(tmp_path, capsys):
    t = tb(tmp_path)
    with pytest.raises(TB.TaskError, match="design task id"):
        add(t, "x", ["a.py"], task_id="DSN-bad")
    d = add(t, "P2 T3", ["a.py"], task_id="DSN-20261023-release-train-P2-T3")
    assert d["design_id"] == "DSN-20261023-release-train" and d["phase_id"] == "DSN-20261023-release-train-P2"
    with pytest.raises(TB.TaskError, match="already exists"):
        add(t, "dup", ["b.py"], task_id="DSN-20261023-release-train-P2-T3")
    base = ["--claims-dir", str(tmp_path / "claims"), "--no-gh", "--vendor", "cursor", "--session", "cu"]
    assert CLI.main([*base, "take", "DSN-20261023-release-train-P2-T3"]) == 0
    assert "Design-Task: DSN-20261023-release-train-P2-T3" in capsys.readouterr().err
    assert t.get(d["task_id"])["owner"]["vendor"] == "cursor"


def test_api_task_board_is_additive(tmp_path):
    t = tb(tmp_path)
    a = add(t, "a", ["a.py"], estimate="2h")
    add(t, "b", ["b.py"], depends_on=[a["task_id"]])
    nxt(t, "s1")
    cache = LC.CachedObserver(lambda: LC.LifecycleObserver(None, None))
    out = B.board_view(t.claims.dir, observer=cache, background=False)
    tbv = out["task_board"]
    assert tbv["columns"] == ["free", "taken", "in_progress", "done"]
    cols = {r["title"]: r for r in tbv["tasks"]}
    assert cols["a"]["column"] == "taken" and cols["a"]["owner"]["session"] == "s1" and cols["a"]["estimate"] == "2h"
    assert cols["b"]["column"] == "free" and cols["b"]["blocked_by"] == [a["task_id"]]
    t.claims.stage(cols["a"]["claim_id"], "building", session="s1")
    out = B.board_view(t.claims.dir, observer=cache, background=False)
    assert {r["title"]: r["column"] for r in out["task_board"]["tasks"]}["a"] == "in_progress"
