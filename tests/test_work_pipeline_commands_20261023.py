"""Work pipeline Tier 1 commands (operator 2026-10-23: "nothing is actionable on there" -> "both"). Hermetic.

POST /api/v2/coordination/commands: actor from auth only (the body cannot name one), the agent/service principal is
refused, CSRF refused, idempotency key required and replayed, every outcome audited append-only; each command's effect
on the coordination stores; Tier 2 and never-on-board commands refused; ``next``/``take`` skip a held task; the batch
builder view drops held PRs.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import agent_task_board as TB  # noqa: E402
from scripts.lib import work_pipeline_commands as C  # noqa: E402

T0 = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
OP = "tailnet:john@jwwhiting.com"


class Clock:
    def __init__(self, t: datetime = T0):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def make_ctx(tmp_path, *, principal=OP, listener="serve_proxy", csrf=(True, ""), census=None, clock=None):
    return C.Ctx(
        principal=lambda: principal,
        listener=lambda: listener,
        csrf=lambda m, p: csrf,
        allowed_logins=frozenset({"john@jwwhiting.com"}),
        claims_dir=tmp_path / "claims",
        census=lambda: census,
        now=clock or Clock(),
    )


_n = [0]


def post(ctx, command, params=None, key=None, **extra):
    _n[0] += 1
    body = {"command": command, "params": params or {}, "idempotency_key": key or f"test-key-{_n[0]:06d}", **extra}
    return C.handle("POST", body, ctx=ctx)


def audit(tmp_path):
    p = C.audit_path(tmp_path / "claims")
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def boards(tmp_path, clock=None):
    cb = B.ClaimBoard(tmp_path / "claims", now=clock or Clock())
    return cb, TB.TaskBoard(cb)


def add_task(tmp_path, title="Fix it", areas=("scripts/a.py",), **kw):
    _cb, tb = boards(tmp_path)
    return tb.add(title=title, kind="fix", areas=list(areas), **kw)


# --------------------------------------------------------------------------------------------- auth


def test_agent_service_token_and_non_proxy_refused_and_audited(tmp_path):
    for principal, listener in (
        ("service-token", "service"),
        (OP, "service"),
        ("tailnet:someone@else", "serve_proxy"),
        ("", None),
    ):
        st, body = post(
            make_ctx(tmp_path, principal=principal, listener=listener), "note", {"item": "PR-1", "text": "x"}
        )
        assert st == 403 and body["error"] == "AGENT_CALLER_REFUSED"
    rows = audit(tmp_path)
    assert len(rows) == 4 and all(r["outcome"] == "refused" for r in rows)
    assert not C.queue_path(tmp_path / "claims").exists()


def test_csrf_refused(tmp_path):
    st, body = post(make_ctx(tmp_path, csrf=(False, "csrf: Origin not on allowlist")), "hold", {"item": "PR-5"})
    assert st == 403 and body["error"] == "CSRF_REFUSED" and "Origin" in body["detail"]
    assert C.read_queue(tmp_path / "claims")["held_prs"] == {}


def test_actor_comes_from_auth_never_the_body(tmp_path):
    ctx = make_ctx(tmp_path)
    st, body = post(
        ctx, "hold", {"item": "PR-77", "reason": "r", "by": "agent:evil"}, actor="agent:evil", principal="x"
    )
    assert st == 200 and body["actor"] == OP
    assert C.read_queue(tmp_path / "claims")["held_prs"]["77"]["by"] == OP
    assert audit(tmp_path)[-1]["actor"] == OP


def test_idempotency_required_replayed_and_not_reusable(tmp_path):
    ctx = make_ctx(tmp_path)
    st, body = post(ctx, "batch_add", {"pr": 5}, key="short")
    assert st == 400 and body["error"] == "IDEMPOTENCY_KEY_REQUIRED"
    st, body = post(ctx, "batch_add", {"pr": 5}, key="idem-key-0001")
    assert st == 200 and body["result"]["position"] == 1
    st, again = post(ctx, "batch_add", {"pr": 5}, key="idem-key-0001")
    assert st == 200 and again["replayed"] is True and again["result"] == body["result"]
    assert len(C.read_queue(tmp_path / "claims")["history"]) == 1  # the replay wrote nothing
    st, other = post(ctx, "batch_remove", {"pr": 5}, key="idem-key-0001")
    assert st == 409 and other["error"] == "IDEMPOTENCY_KEY_REUSED"


def test_tier2_and_never_on_board_refused(tmp_path):
    ctx = make_ctx(tmp_path)
    for cmd in C.TIER2:
        st, body = post(ctx, cmd, {"pr": 1})
        assert st == 403 and body["error"] == "STEP_UP_REQUIRED"
    for cmd in ("place_order", "clear_kill_switch", "issue_grant", "set_stop"):
        st, body = post(ctx, cmd, {})
        assert st == 403 and body["error"] == "NEVER_ON_BOARD"
    st, body = post(ctx, "rm_rf", {})
    assert st == 400 and body["error"] == "UNKNOWN_COMMAND"
    assert C.handle("DELETE", {}, ctx=ctx)[0] == 405
    assert C.handle("GET", None, ctx=ctx)[1]["data"]["commands"] == list(C.COMMANDS)


# --------------------------------------------------------------------------------------------- effects


def test_note_on_task_claim_and_pr(tmp_path):
    ctx = make_ctx(tmp_path)
    t = add_task(tmp_path)
    st, body = post(ctx, "note", {"item": t["task_id"], "text": "please split this"})
    assert st == 200 and body["result"]["wrote"] == "task_history"
    _cb, tb = boards(tmp_path)
    ev = tb.get(t["task_id"])["history"][-1]
    assert ev["event"] == "note" and ev["by"] == OP and ev["text"] == "please split this"
    # a taken task with a worklog: the note lands in the worklog, tagged operator
    cb, tb = boards(tmp_path)
    taken, cl = tb.next(vendor="claude", session="s1", agent="a")
    st, body = post(ctx, "note", {"item": taken["task_id"], "text": "use the cache"})
    assert body["result"]["wrote"] == "worklog"
    text = cb.worklog(cl["claim_id"]).read()
    assert f"operator ({OP}): use the cache" in text
    st, body = post(ctx, "note", {"item": "#2016", "text": "contract review first"})
    assert body["result"]["wrote"] == "batch_queue.pr_notes"
    assert C.read_queue(tmp_path / "claims")["pr_notes"]["2016"][-1]["text"] == "contract review first"
    st, body = post(ctx, "note", {"item": "nonsense id", "text": "x"})
    assert st == 400 and body["error"] == "BAD_ITEM"


def test_set_priority(tmp_path):
    ctx = make_ctx(tmp_path)
    t = add_task(tmp_path, priority=3)
    st, body = post(ctx, "set_priority", {"task_id": t["task_id"], "priority": 1})
    assert st == 200 and body["result"]["priority"] == 1
    _cb, tb = boards(tmp_path)
    got = tb.get(t["task_id"])
    assert got["priority"] == 1 and got["history"][-1] == {
        **got["history"][-1],
        "event": "priority",
        "old": 3,
        "new": 1,
    }
    st, body = post(ctx, "set_priority", {"task_id": t["task_id"], "priority": 9})
    assert st == 400


def test_hold_task_is_skipped_by_next_and_take(tmp_path):
    ctx = make_ctx(tmp_path)
    t = add_task(tmp_path, priority=1)
    other = add_task(tmp_path, title="other", areas=["scripts/b.py"], priority=2)
    assert post(ctx, "hold", {"item": t["task_id"], "reason": "wait"})[0] == 200
    _cb, tb = boards(tmp_path)
    picked, _c = tb.next(vendor="claude", session="s1", agent=None)
    assert picked["task_id"] == other["task_id"]  # the held P1 task was skipped
    with pytest.raises(TB.TaskError, match="on hold"):
        tb.next(vendor="claude", session="s2", agent=None, task_id=t["task_id"])
    assert post(ctx, "unhold", {"item": t["task_id"]})[0] == 200
    _cb, tb = boards(tmp_path)
    assert tb.next(vendor="claude", session="s3", agent=None)[0]["task_id"] == t["task_id"]
    assert tb.board()["tasks"][0].get("held") is None


def test_hold_pr_blocks_batch_add_and_batch_builder_skips(tmp_path):
    ctx = make_ctx(tmp_path)
    assert post(ctx, "batch_add", {"pr": 2005})[0] == 200
    assert post(ctx, "batch_add", {"pr": 1996})[0] == 200
    assert post(ctx, "hold", {"item": "PR-1996", "reason": "operator review"})[0] == 200
    view = C.batch_builder_view(tmp_path / "claims")
    assert view["next_batch"] == [2005] and view["held_prs"] == [1996]
    st, body = post(ctx, "batch_add", {"pr": 1996})
    assert st == 409 and body["error"] == "PR_HELD"  # still listed; the builder drops it while held
    assert post(ctx, "batch_add", {"pr": 2001})[0] == 200
    assert post(ctx, "hold", {"item": "2000"})[0] == 200
    st, body = post(ctx, "batch_add", {"pr": 2000})
    assert st == 409 and body["error"] == "PR_HELD"
    st, body = post(ctx, "batch_remove", {"pr": 2005})
    assert body["result"]["removed"] is True
    assert C.batch_builder_view(tmp_path / "claims")["next_batch"] == [2001]


def test_batch_add_validates_against_census(tmp_path):
    census = {
        "open": [{"number": 2005, "ci": {"state": "green"}}, {"number": 2016, "ci": {"state": "failing"}}, {"number": 2012, "ci": {"state": "green"}}],
        "batches": {2018: {"members": [2012]}},
    }  # fmt: skip
    ctx = make_ctx(tmp_path, census=census)
    assert post(ctx, "batch_add", {"pr": 2005})[0] == 200
    assert post(ctx, "batch_add", {"pr": 2016})[1]["error"] == "CI_NOT_GREEN"
    assert post(ctx, "batch_add", {"pr": 2012})[1]["error"] == "ALREADY_IN_BATCH"
    assert post(ctx, "batch_add", {"pr": 9999})[1]["error"] == "PR_NOT_OPEN"


def test_task_add_and_split(tmp_path):
    ctx = make_ctx(tmp_path)
    st, body = post(
        ctx,
        "task_add",
        {
            "title": "New thing",
            "kind": "build",
            "areas": "scripts/x.py, docs/x.md",
            "priority": 2,
            "acceptance": "tests; docs",
        },
    )
    assert st == 200
    tid = body["result"]["task_id"]
    _cb, tb = boards(tmp_path)
    t = tb.get(tid)
    assert (
        t["source"] == "operator"
        and t["created_by"] == OP
        and t["areas"] == ["scripts/x.py", "docs/x.md"]
        and t["priority"] == 2
    )
    st, body = post(
        ctx,
        "task_split",
        {"task_id": tid, "parts": [{"title": "half 1", "areas": ["scripts/x.py"]}, "half 2 | docs/x.md | doc done"]},
    )
    assert st == 200 and len(body["result"]["children"]) == 2
    _cb, tb = boards(tmp_path)
    assert tb.get(tid)["status"] == "split"
    st, body = post(ctx, "task_add", {"title": "", "areas": "a"})
    assert st == 400


def _stale_claim(tmp_path, clock):
    cb = B.ClaimBoard(tmp_path / "claims", now=clock)
    c = cb.claim(
        vendor="claude", session="old-sess", agent="old", task="stale work", paths=["scripts/s.py"], branch="feat/s"
    )
    cb.worklog(c["claim_id"]).create(c, plan=["step one"])
    return c["claim_id"]


def test_release_stale_claim_only_when_red_stale(tmp_path):
    clock = Clock()
    cid = _stale_claim(tmp_path, clock)
    ctx = make_ctx(tmp_path, clock=clock)
    st, body = post(ctx, "release_stale_claim", {"claim_id": cid})
    assert st == 409 and body["error"] == "NOT_STALE"
    clock.t = T0 + timedelta(hours=3)
    st, body = post(ctx, "release_stale_claim", {"claim_id": cid})
    assert st == 200 and body["result"]["takeover"] == "operator"
    cb = B.ClaimBoard(tmp_path / "claims", now=clock)
    doc = json.loads(cb.claim_path(cid).read_text())
    assert doc["status"] == "abandoned" and doc["released_by"] == OP
    assert cb.worklog(cid).exists()  # kept
    assert "operator takeover" in cb.worklog(cid).read()
    assert not cb.conflicts(["scripts/s.py"], session="new")  # files freed
    assert audit(tmp_path)[-1]["command"] == "release_stale_claim" and audit(tmp_path)[-1]["outcome"] == "ok"


def test_release_stale_claim_refuses_green_pr_claim(tmp_path, monkeypatch):
    clock = Clock()
    cid = _stale_claim(tmp_path, clock)
    clock.t = T0 + timedelta(hours=3)
    orig = B.ClaimBoard.views

    def views(self):
        vs, bad = orig(self)
        for v in vs:
            v.lifecycle = {**v.lifecycle, "stage": "ci_green", "ci": {"state": "green"}}
        return vs, bad

    monkeypatch.setattr(B.ClaimBoard, "views", views)
    st, body = post(make_ctx(tmp_path, clock=clock), "release_stale_claim", {"claim_id": cid})
    assert st == 409 and body["error"] == "NOT_STALE" and "ci_green" in body["detail"]


def test_release_stale_claim_puts_its_task_back(tmp_path):
    clock = Clock()
    cb = B.ClaimBoard(tmp_path / "claims", now=clock)
    tb = TB.TaskBoard(cb)
    t = tb.add(title="T", kind="fix", areas=["scripts/q.py"])
    _t, cl = tb.next(vendor="codex", session="cx", agent=None)
    clock.t = T0 + timedelta(hours=3)
    st, body = post(make_ctx(tmp_path, clock=clock), "release_stale_claim", {"claim_id": cl["claim_id"]})
    assert st == 200 and body["result"]["task_id"] == t["task_id"]
    assert TB.TaskBoard(B.ClaimBoard(tmp_path / "claims", now=clock)).get(t["task_id"])["status"] == "free"


# --------------------------------------------------------------------------------------------- wiring


def test_api_routes_wired_get_only_view_and_governed_commands():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    i = src.index('if base_path == "/api/v2/coordination/pipeline":')
    block = src[i : i + 500]
    assert 'if method != "GET":' in block and '"read_only"' in block and "work_pipeline().view()" in block
    j = src.index('if base_path == "/api/v2/coordination/commands":')
    assert "_wpc.handle(method, body)" in src[j : j + 300]


def test_commands_route_is_a_hard_csrf_route():
    from scripts.lib import cc_auth

    cfg = cc_auth.load_config(ROOT / "config" / "cc_auth.yaml")
    assert cc_auth.csrf_class(cfg, "POST", "/api/v2/coordination/commands") == "hard"


def test_default_context_without_request_refuses(tmp_path, monkeypatch):
    """No cc_auth request context (an agent calling in-process or a script): refused, never applied."""
    monkeypatch.setenv("TRADEAI_AGENT_CLAIMS_DIR", str(tmp_path / "claims"))
    C._CTX = None
    try:
        st, body = C.handle("POST", {"command": "hold", "params": {"item": "PR-1"}, "idempotency_key": "abcdefgh1"})
    finally:
        C._CTX = None
    assert st in (403, 503) and body["ok"] is False
    assert not C.queue_path(tmp_path / "claims").exists()


def test_batch_queue_cli_reads_without_writing(tmp_path, capsys):
    from scripts import batch_queue

    ctx = make_ctx(tmp_path)
    post(ctx, "batch_add", {"pr": 2005})
    post(ctx, "batch_add", {"pr": 1996})
    post(ctx, "hold", {"item": "PR-1996"})
    before = C.queue_path(tmp_path / "claims").read_text()
    assert batch_queue.main(["next", "--claims-dir", str(tmp_path / "claims")]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "2005" and "1996" in out.err
    assert C.queue_path(tmp_path / "claims").read_text() == before


def test_task_done_only_for_operator_todos(tmp_path):
    ctx = make_ctx(tmp_path)
    op_task = add_task(tmp_path, title="OPERATOR: rotate DB password")
    agent_task = add_task(tmp_path, title="Fix it", areas=["scripts/z.py"])
    st, body = post(ctx, "task_done", {"task_id": agent_task["task_id"]})
    assert st == 409 and body["error"] == "TASK_REFUSED"
    st, body = post(ctx, "task_done", {"task_id": op_task["task_id"], "summary": "rotated"})
    assert st == 200 and body["result"]["status"] == "done"
    _cb, tb = boards(tmp_path)
    ev = tb.get(op_task["task_id"])["history"][-1]
    assert ev["event"] == "done" and ev["by"] == OP and ev["summary"] == "rotated"
