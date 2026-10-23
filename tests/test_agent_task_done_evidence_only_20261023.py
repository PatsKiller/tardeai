"""``task done --evidence-only`` (2026-10-23): close a FREE task whose work already shipped, with no claim.

Before: ``task done`` was refused on a free task and ``take`` was refused when the task's areas overlapped a live
claim, so finished work (batch 9 released, #2012 shipped) could not be closed. Hermetic: temp dirs only.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import agent_claim as CLI  # noqa: E402
from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import agent_task_board as TB  # noqa: E402

T0 = datetime(2026, 10, 23, 19, 0, tzinfo=timezone.utc)


def setup(tmp_path):
    b = B.ClaimBoard(tmp_path / "claims", now=lambda: T0)
    tb = TB.TaskBoard(b)
    t = tb.add(title="release batch 9", kind="build", areas=["scripts/busy.py"])
    # Another session holds the task's area, so `take` would be refused.
    b.claim(vendor="codex", session="other", agent=None, task="x", paths=["scripts/busy.py"], branch="feat/other")
    return b, tb, t["task_id"]


def cli(tmp_path, *args):
    return CLI.main(
        ["--claims-dir", str(tmp_path / "claims"), "--vendor", "claude", "--session", "closer", "--agent", "c", *args]
    )


def test_take_refused_but_evidence_only_closes_free_task(tmp_path, capsys):
    b, tb, tid = setup(tmp_path)
    assert cli(tmp_path, "take", tid) != 0  # overlap with a live claim: the old dead end
    capsys.readouterr()
    rc = cli(
        tmp_path,
        "task",
        "done",
        tid,
        "--evidence-only",
        "--summary",
        "batch 9 released",
        "--evidence",
        "https://github.com/PatsKiller/tardeai/pull/2018",
        "receipt:release-batch-9",
    )
    assert rc == 0, capsys.readouterr().err
    t = tb.get(tid)
    assert t["status"] == "done" and t["done_mode"] == "evidence_only"
    assert t["closed_by"] == {"vendor": "claude", "session": "closer", "agent": "c"}
    assert t["evidence"][0].endswith("/pull/2018") and t["summary"] == "batch 9 released"
    assert not t.get("claim_id")  # no claim was made
    assert [v for v in b.views()[0] if v.doc.get("session") == "closer"] == []
    events = [json.loads(x) for x in tb.history.read_text().splitlines()]
    ev = [e for e in events if e["task_id"] == tid and e["event"] == "done"][-1]
    assert ev["mode"] == "evidence_only" and ev["actor"]["session"] == "closer"
    assert ev["summary"] == "batch 9 released" and len(ev["evidence"]) == 2


def test_evidence_only_needs_summary_and_evidence(tmp_path, capsys):
    _b, tb, tid = setup(tmp_path)
    assert cli(tmp_path, "task", "done", tid, "--evidence-only", "--summary", "s") == 2
    assert cli(tmp_path, "task", "done", tid, "--evidence-only", "--evidence", "https://x/pull/1") == 2
    assert tb.get(tid)["status"] == "free"


def test_evidence_only_refused_on_taken_or_done_task(tmp_path, capsys):
    b = B.ClaimBoard(tmp_path / "claims", now=lambda: T0)
    tb = TB.TaskBoard(b)
    tid = tb.add(title="t", kind="fix", areas=["scripts/a.py"])["task_id"]
    tb.next(vendor="claude", session="owner", agent=None, task_id=tid, branch="feat/owner")
    args = ["task", "done", tid, "--evidence-only", "--summary", "s", "--evidence", "https://x/pull/1"]
    assert cli(tmp_path, *args) == 2
    assert "closes free tasks only" in capsys.readouterr().err
    assert tb.get(tid)["status"] == "taken"


def test_plain_done_on_free_task_still_refused(tmp_path):
    _b, tb, tid = setup(tmp_path)
    assert cli(tmp_path, "task", "done", tid, "--summary", "s") == 2
    assert tb.get(tid)["status"] == "free"
