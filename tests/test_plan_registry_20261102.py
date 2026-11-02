"""Plan registry core (2026-11-02): every approved plan persisted, linkable, and trackable.

Operator: "build the plan registry" — an approved plan is written once, on the server, for every
agent (Claude Code through an ExitPlanMode hook; Codex, Cursor and others through the CLI), and its
lifecycle is followed until it is done or abandoned.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import plan_registry as pr  # noqa: E402

CFG = {"schema": "PlanRegistryConfig@v1", "plans_rel": "data/coordination/plans",
       "inbox_rel": "data/coordination/coordinator/inbox.md", "stale_hours": 72,
       "stalled_prefix": "[PLAN-STALLED]"}


def _reg(tmp_path):
    return pr.Registry(tmp_path, dict(CFG))


def test_add_writes_the_plan_and_an_append_only_ledger_line(tmp_path):
    r = _reg(tmp_path)
    plan = tmp_path / "src.md"
    plan.write_text("# Plan\n\n- [ ] step one\n- [ ] step two\n")
    pid = r.add(title="Build the plan registry", body_path=plan, author="sess-1", vendor="claude",
                approved_at="2026-11-02T10:50:00Z", quote="build the plan registry")
    md = tmp_path / "data/coordination/plans" / f"{pid}.md"
    assert md.is_file()
    doc = pr.parse_plan(md.read_text())
    assert doc["front"]["status"] == "approved"
    assert doc["front"]["vendor"] == "claude"
    assert doc["front"]["operator_quote"] == "build the plan registry"
    assert "- [ ] step one" in doc["body"]
    ledger = [json.loads(l) for l in (tmp_path / "data/coordination/plans/ledger.jsonl").read_text().splitlines()]
    assert ledger[-1]["event"] == "add" and ledger[-1]["id"] == pid


def test_show_list_and_link(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# P\n\n- [ ] a\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="codex", approved_at="2026-11-02T10:00:00Z")
    r.link(pid, claim="C1", branch="wt/x", pr=42)
    doc = pr.parse_plan((tmp_path / "data/coordination/plans" / f"{pid}.md").read_text())
    assert doc["front"]["claim"] == "C1" and doc["front"]["pr"] == 42
    rows = r.list()
    assert rows[0]["id"] == pid and rows[0]["status"] == "approved"


def test_step_done_ticks_exactly_one_step(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# P\n\n- [ ] first\n- [ ] second\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    r.step_done(pid, "second")
    body = pr.parse_plan((tmp_path / "data/coordination/plans" / f"{pid}.md").read_text())["body"]
    assert "- [ ] first" in body and "- [x] second" in body


def test_set_status_refuses_an_unknown_value(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    r.set_status(pid, "done")
    assert r.get(pid)["front"]["status"] == "done"
    try:
        r.set_status(pid, "finished")
    except ValueError as exc:
        assert "status" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown status accepted")


def test_stale_flags_an_unlinked_old_plan_once(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="cursor", approved_at="2026-08-01T10:00:00Z")
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == [pid]
    inbox = (tmp_path / "data/coordination/coordinator/inbox.md").read_text()
    assert "[PLAN-STALLED]" in inbox and pid in inbox
    # the plan is now stalled; a second tick does not flag it again
    assert r.stale(now="2026-11-02T13:00:00Z", apply=True) == []
    assert r.get(pid)["front"]["status"] == "stalled"


def test_a_linked_plan_is_never_stale(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="codex", approved_at="2026-08-01T10:00:00Z")
    r.link(pid, pr=7)
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == []


def test_the_hook_writes_an_approved_plan_from_exit_plan_mode_json(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    payload = {"session_id": "sess-9", "tool_name": "ExitPlanMode",
               "tool_input": {"plan": "# Hooked plan\n\n- [ ] one\n"}}
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_registry_hook.py")],
                          input=json.dumps(payload), capture_output=True, text=True, env={
                              **__import__("os").environ, "TRADEAI_STATE_ROOT": str(tmp_path)}, check=False)
    assert proc.returncode == 0, proc.stderr
    plans = list((tmp_path / "data/coordination/plans").glob("*.md"))
    assert len(plans) == 1
    doc = pr.parse_plan(plans[0].read_text())
    assert doc["front"]["status"] == "approved" and doc["front"]["vendor"] == "claude"
    assert "Hooked plan" in doc["body"]


def test_a_second_hook_run_with_the_same_plan_does_not_duplicate(tmp_path):
    r = _reg(tmp_path)
    body = "# Same\n\n- [ ] x\n"
    a = r.add(title="Same", body=body, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    b = r.add(title="Same", body=body, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    assert a == b


def test_the_read_only_view_lists_and_shows_one_plan(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n\n- [x] one\n- [ ] two\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    listing = r.view()
    assert listing["schema"] == "PlanRegistryView@v1"
    row = listing["plans"][0]
    assert row["id"] == pid and row["steps_done"] == 1 and row["steps_left"] == 1
    assert "body" not in row
    detail = r.view(pid)["plan"]
    assert detail["body"].startswith("# T") and len(detail["steps"]) == 2
