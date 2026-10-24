"""Work board + design registry (operator 2026-10-23): hermetic, temp dirs; the seeded docs/designs must parse.

Covers: DSN id/phase/task validation; the seeded registry parses; design -> phase -> task tree with task-board holders;
work items from tasks, operator to-dos, bare claims and open PRs with the stage mapping
open -> claimed -> in_progress -> in_review -> merged -> live; designs awaiting approval (designs + packet READMEs);
single-flight cache (one rebuild per TTL, no reparse of unchanged files); GET-only API routes; `take <DSN task>`
refused on file overlap.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import agent_task_board as TB  # noqa: E402
from scripts.lib import design_registry as D  # noqa: E402

DESIGN = """---
id: DSN-20261023-demo
title: Demo
status: IN_PROGRESS
approval: awaiting operator
phases:
  - id: DSN-20261023-demo-P1
    title: one
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261023-demo-P1-T1
        title: first
        status: PROPOSED
        areas: [scripts/a.py]
      - id: DSN-20261023-demo-P1-T2
        title: second
        status: DONE
---
body
"""


def write_root(tmp_path: Path, designs: dict[str, str] | None = None, packets: dict[str, str] | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "docs" / "designs").mkdir(parents=True)
    for name, text in (designs or {"DSN-20261023-demo": DESIGN}).items():
        (root / "docs" / "designs" / f"{name}.md").write_text(text)
    for name, status in (packets or {}).items():
        d = root / "docs" / "ops" / "packets" / name
        d.mkdir(parents=True)
        d.joinpath("README.md").write_text(f"# {name}\n\n```\nStatus: {status}\n```\n")
    return root


def test_seeded_registry_parses_and_ids_are_consistent():
    designs, errors = D.DesignStore(ROOT).load()
    assert errors == []
    ids = {d["id"] for d in designs}
    assert {
        "DSN-20261021-release-train",
        "DSN-20261022-momentum-alerts",
        "DSN-20261023-ask-the-cio",
        "DSN-20261022-cio-prospect-store",
        "DSN-20261022-data-domains",
    } <= ids
    rt = next(d for d in designs if d["id"] == "DSN-20261021-release-train")
    assert [p["id"].rsplit("-", 1)[1] for p in rt["phases"]] == [f"P{i}" for i in range(8)]


@pytest.mark.parametrize(
    "text,err",
    [
        ("no front matter", "front matter"),
        ("---\nid: nope\n---\n", "DSN-"),
        ("---\nid: DSN-20261023-demo\nstatus: MAYBE\n---\n", "status"),
        ("---\nid: DSN-20261023-demo\nphases:\n  - id: DSN-20261023-other-P1\n---\n", "phase id"),
        (
            "---\nid: DSN-20261023-demo\nphases:\n  - id: DSN-20261023-demo-P1\n    tasks:\n      - id: DSN-20261023-demo-P2-T1\n---\n",
            "task id",
        ),
    ],
)
def test_parse_rejects_bad_designs(text, err):
    with pytest.raises(D.DesignError, match=err):
        D.parse_design(text, stem="DSN-20261023-demo")


def test_bad_file_is_reported_not_fatal(tmp_path):
    root = write_root(tmp_path, {"DSN-20261023-demo": DESIGN, "DSN-20261023-bad": "---\nid: x\n---\n"})
    designs, errors = D.DesignStore(root).load()
    assert [d["id"] for d in designs] == ["DSN-20261023-demo"]
    assert errors[0]["path"].endswith("DSN-20261023-bad.md")


def test_store_reparses_only_changed_files(tmp_path, monkeypatch):
    root = write_root(tmp_path)
    store = D.DesignStore(root)
    calls = []
    real = D.parse_design
    monkeypatch.setattr(D, "parse_design", lambda t, stem=None: calls.append(stem) or real(t, stem=stem))
    store.load()
    store.load()
    assert calls == ["DSN-20261023-demo"]
    p = root / "docs" / "designs" / "DSN-20261023-demo.md"
    p.write_text(DESIGN.replace("title: Demo", "title: Demo two"))
    assert store.load()[0][0]["title"] == "Demo two" and len(calls) == 2


def test_tree_uses_task_board_holder(tmp_path):
    root = write_root(tmp_path)
    claims = B.ClaimBoard(tmp_path / "claims")
    tb = TB.TaskBoard(claims)
    tb.add(title="first", kind="build", areas=["scripts/a.py"], task_id="DSN-20261023-demo-P1-T1")
    tb.next(vendor="codex", session="cx-12345678", agent=None, task_id="DSN-20261023-demo-P1-T1")
    designs, _ = D.DesignStore(root).load()
    tree = D.design_tree(designs, tb.board()["tasks"])
    t1, t2 = tree[0]["phases"][0]["tasks"]
    assert t1["status"] == "IN_PROGRESS" and t1["holder"] == "codex:cx-12345" and t1["registered"]
    assert t2["status"] == "DONE" and not t2["registered"]
    assert tree[0]["phases"][0]["tasks_done"] == 1


def test_work_items_sources_and_stages(tmp_path):
    claims = B.ClaimBoard(tmp_path / "claims")
    tb = TB.TaskBoard(claims)
    free = tb.add(title="operator todo", kind="fix", areas=["docs/x.md"], source="operator")
    taken = tb.add(title="taken", kind="build", areas=["scripts/t.py"])
    _t, c = tb.next(vendor="claude", session="2e7e1d01-aaaa", agent=None, task_id=taken["task_id"])
    claims.stage(c["claim_id"], "pr_open", session="2e7e1d01-aaaa", pr="1994")
    bare = claims.claim(vendor="cursor", session="cu1", agent=None, task="bare claim", paths=["apps/x.tsx"], branch="b")
    prs = [
        {"number": 1994, "title": "covered", "html_url": "u1", "user": {"login": "p"}},
        {
            "number": 2000,
            "title": "uncovered PR",
            "html_url": "u2",
            "user": {"login": "p"},
            "draft": True,
            "head": {"ref": "codex/x"},
            "created_at": "2026-10-23T10:00:00Z",
        },
    ]
    rows = D.work_items(tb.board()["tasks"], claims.board()["claims"], prs)
    by = {r["id"]: r for r in rows}
    assert by[free["task_id"]]["stage"] == "open" and by[free["task_id"]]["source"] == "operator"
    assert by[taken["task_id"]]["stage"] == "in_review" and by[taken["task_id"]]["holder"] == "claude:2e7e1d01"
    assert by[taken["task_id"]]["worklog"] is True
    assert by[bare["claim_id"]]["source"] == "claim" and by[bare["claim_id"]]["stage"] == "claimed"
    assert "PR-1994" not in by  # covered by the task's claim
    assert by["PR-2000"]["stage"] == "in_review" and by["PR-2000"]["draft"] is True
    assert [r["stage"] for r in rows] == sorted((r["stage"] for r in rows), key=D.WORK_STAGES.index)


def test_awaiting_approval_lists_designs_and_packets(tmp_path):
    root = write_root(
        tmp_path, packets={"p-prop": "PROPOSED (nothing installed)", "p-live": "ACTIVE", "p-ok": "APPROVED 2026-10-20"}
    )
    designs, _ = D.DesignStore(root).load()
    got = {(a["kind"], a["id"]) for a in D.designs_awaiting(root, designs)}
    assert got == {("design", "DSN-20261023-demo"), ("packet", "p-prop")}


def test_single_flight_cache_builds_once_per_ttl(tmp_path):
    n = {"builds": 0}
    gate = threading.Event()

    def build():
        n["builds"] += 1
        gate.wait(1)
        return n["builds"]

    c = D._Cached(build, ttl=30)
    out = []
    threads = [threading.Thread(target=lambda: out.append(c.get())) for _ in range(8)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()
    assert n["builds"] == 1 and set(out) == {1}
    assert c.get() == 1 and n["builds"] == 1


def test_work_board_views_and_degraded_github(tmp_path):
    root = write_root(tmp_path)

    class GH:
        repo = "o/r"

        def get(self, path):
            assert path.startswith("repos/o/r/pulls?state=open")
            return None, "gh not installed: GitHub stages not observed"

    wb = D.WorkBoard(root, tmp_path / "claims", gh_factory=lambda: GH())
    t = wb.tasks(background=False)
    assert t["schema"] == "WorkBoardTasks@v1" and t["stages"] == list(D.WORK_STAGES)
    assert "gh not installed" in t["open_prs_warning"] and t["sources"]["open_prs"] is None
    d = wb.designs()
    assert d["designs"][0]["id"] == "DSN-20261023-demo" and d["awaiting_approval"][0]["id"] == "DSN-20261023-demo"
    assert not (tmp_path / "claims").exists()  # read-only: never creates the store


def test_api_routes_are_get_only():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    i = src.index('if base_path in ("/api/v2/coordination/tasks", "/api/v2/coordination/designs"):')
    block = src[i : i + 900]
    assert 'if method != "GET":' in block and '"read_only"' in block and "work_board" in block


def test_take_design_task_refused_on_overlap(tmp_path):
    claims = B.ClaimBoard(tmp_path / "claims")
    tb = TB.TaskBoard(claims)
    tb.add(title="x", kind="build", areas=["scripts/a.py"], task_id="DSN-20261023-demo-P1-T1")
    claims.claim(vendor="codex", session="other", agent=None, task="t", paths=["scripts"], branch="b")
    with pytest.raises(B.ClaimConflict):
        tb.next(vendor="claude", session="me", agent=None, task_id="DSN-20261023-demo-P1-T1")
    assert tb.get("DSN-20261023-demo-P1-T1")["status"] == "free"


def test_ci_gate_and_build_registration():
    from scripts.lib import ci_gates

    doc = json.loads((ROOT / "config" / "ci_gates" / "work_board_designs_20261023.json").read_text())
    ci_gates.validate(doc, stem="work_board_designs_20261023")
    pkg = json.loads((ROOT / "apps" / "command-center-v3" / "package.json").read_text())
    assert "src/lib/workBoard.test.ts" in pkg["scripts"]["build"]
