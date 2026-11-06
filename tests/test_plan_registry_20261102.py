"""Plan registry core (2026-11-02): every registered plan persisted, linkable, and trackable.

Operator: "build the plan registry" — a plan is written once, on the server, for every
agent (Claude Code through an ExitPlanMode hook; Codex, Cursor and others through the CLI), and its
lifecycle is followed until it is done or abandoned. Registration is not an approval.
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
       "inbox_rel": "data/coordination/coordinator/inbox/codex", "stale_hours": 72,
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
    assert doc["front"]["status"] == "registered"  # registration is not an approval
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
    assert rows[0]["id"] == pid and rows[0]["status"] == "registered"


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
    pid = r.add(title="T", body_path=p, author="s", vendor="cursor", approved_at="2026-08-01T10:00:00Z",
                status="approved")
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == [pid]
    notices = sorted((tmp_path / "data/coordination/coordinator/inbox/codex").glob("*plan-stalled.md"))
    assert len(notices) == 1, notices
    notice = notices[0].read_text()
    assert "[PLAN-STALLED]" in notice and f"- {pid}" in notice
    # the plan is now stalled; a second tick does not flag it again
    assert r.stale(now="2026-11-02T13:00:00Z", apply=True) == []
    assert r.get(pid)["front"]["status"] == "stalled"


def test_a_linked_plan_is_never_stale(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="codex", approved_at="2026-08-01T10:00:00Z",
                status="approved")
    r.link(pid, pr=7)
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == []


def test_the_hook_registers_a_plan_from_exit_plan_mode_json(tmp_path, monkeypatch):
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
    assert doc["front"]["status"] == "registered" and doc["front"]["vendor"] == "claude"
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


# ---------------------------------------------------------------- review (lead) round 1
def test_ids_are_validated_and_contained(tmp_path):
    import pytest

    r = _reg(tmp_path)
    for bad in ("../evil", "/tmp/evil", "a/b", "UPPER", "-lead", "x" * 100, ""):
        with pytest.raises(ValueError):
            r.add(title="T", body="x", author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z", pid=bad)
        with pytest.raises(ValueError):
            r.get(bad)


def test_a_symlinked_plan_file_cannot_escape_the_store(tmp_path):
    import pytest

    r = _reg(tmp_path)
    inside = tmp_path / "data/coordination/plans"
    inside.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("---\nid: \"evil\"\nstatus: \"approved\"\n---\n\nsecret\n")
    (inside / "evil.md").symlink_to(outside)
    with pytest.raises(ValueError):
        r.get("evil")


def test_listing_and_the_view_never_serve_a_plan_that_escapes_the_store(tmp_path):
    """The same containment as an id, on the two paths that read every file: list() and view()."""
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n\n- [ ] a\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-08-01T10:00:00Z",
                status="approved")
    inside = tmp_path / "data/coordination/plans"
    outside = tmp_path / "outside.md"
    outside.write_text("---\nid: \"evil\"\ntitle: \"Evil\"\nstatus: \"approved\"\n"
                       "approved_at: \"2026-08-01T10:00:00Z\"\n---\n\nsecret\n")
    (inside / "evil.md").symlink_to(outside)
    assert [row["id"] for row in r.list()] == [pid]
    assert [row["id"] for row in r.view()["plans"]] == [pid]
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == [pid]


def test_hook_prefers_the_approved_tool_response_plan(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    plan_file = tmp_path / "edited.md"
    plan_file.write_text("# From file\n")
    payload = {"session_id": "s", "tool_name": "ExitPlanMode",
               "tool_input": {},  # 2.1.269+: empty input
               "tool_response": {"plan": "# Approved text\n\n- [ ] a\n", "planFilePath": str(plan_file)}}
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_registry_hook.py")],
                          input=json.dumps(payload), capture_output=True, text=True,
                          env={**os.environ, "TRADEAI_STATE_ROOT": str(tmp_path)}, check=False)
    assert proc.returncode == 0
    plans = list((tmp_path / "data/coordination/plans").glob("*.md"))
    assert "Approved text" in plans[0].read_text() and "From file" not in plans[0].read_text()


def test_hook_falls_back_to_the_plan_file_path(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    plans_dir = tmp_path / "data" / "coordination" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_file = plans_dir / "edited.md"  # a real plan location under the state root
    plan_file.write_text("# Edited on disk\n")
    payload = {"session_id": "s", "tool_name": "ExitPlanMode", "tool_input": {},
               "tool_response": {"planFilePath": str(plan_file)}}
    subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_registry_hook.py")],
                   input=json.dumps(payload), capture_output=True, text=True,
                   env={**os.environ, "TRADEAI_STATE_ROOT": str(tmp_path)}, check=False)
    plans = list((tmp_path / "data/coordination/plans").glob("*.md"))
    assert plans and "Edited on disk" in plans[0].read_text()


def test_a_non_object_payload_is_fail_soft(tmp_path):
    import os
    for raw in ("[]", "\"x\"", "not json"):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_registry_hook.py")],
                              input=raw, capture_output=True, text=True,
                              env={**os.environ, "TRADEAI_STATE_ROOT": str(tmp_path)}, check=False)
        assert proc.returncode == 0, (raw, proc.stderr)


def test_idempotency_ignores_the_day_but_not_the_author(tmp_path):
    r = _reg(tmp_path)
    a = r.add(title="T", body="same", author="alice", vendor="claude", approved_at="2026-11-01T10:00:00Z")
    b = r.add(title="T", body="same", author="alice", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    c = r.add(title="T", body="same", author="bob", vendor="codex", approved_at="2026-11-02T10:00:00Z")
    assert a == b and a != c


def test_stale_rechecks_linkage_inside_the_lock(tmp_path, monkeypatch):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-08-01T10:00:00Z",
                status="approved")
    real_list = r.list

    def listed_then_linked():
        rows = real_list()
        r.link(pid, pr=9)  # links between the scan and the mark
        return rows

    monkeypatch.setattr(r, "list", listed_then_linked)
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == []
    assert r.get(pid)["front"]["status"] == "approved"


# ---------------------------------------------------------------- review 2 (cc3, 2026-11-02) B1/B2
def test_list_never_serves_a_file_that_escapes_the_store(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    inside = tmp_path / "data/coordination/plans"
    outside = tmp_path / "victim.md"
    outside.write_text('---\ntitle: "victim"\nstatus: "approved"\n---\n\noutside\n')
    (inside / "leak.md").symlink_to(outside)
    assert [row["id"] for row in r.list()] == [pid]
    assert r.stale(now="2026-11-02T12:00:00Z", apply=False) == []


def test_a_planted_temp_symlink_never_redirects_a_write(tmp_path):
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    inside = tmp_path / "data/coordination/plans"
    outside = tmp_path / "outside-target"
    outside.write_text("untouched\n")
    (inside / f"{pid}.md.tmp").symlink_to(outside)  # the name the old code wrote through
    r.set_status(pid, "in_progress")
    assert outside.read_text() == "untouched\n"
    assert r.get(pid)["front"]["status"] == "in_progress"
    assert (inside / f"{pid}.md.tmp").is_symlink()  # the planted name is untouched, not written through


def test_a_planted_lock_symlink_is_refused(tmp_path):
    import pytest

    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    inside = tmp_path / "data/coordination/plans"
    outside = tmp_path / "lock-target"
    outside.write_text("untouched\n")
    (inside / ".lock").unlink()
    (inside / ".lock").symlink_to(outside)
    with pytest.raises(ValueError):
        r.set_status(pid, "done")
    assert outside.read_text() == "untouched\n"


def test_a_planted_ledger_symlink_is_refused(tmp_path):
    import pytest

    r = _reg(tmp_path)
    inside = tmp_path / "data/coordination/plans"
    inside.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "ledger-target"
    outside.write_text("untouched\n")
    (inside / "ledger.jsonl").symlink_to(outside)
    with pytest.raises(ValueError):
        r.add(title="T", body="x", author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    assert outside.read_text() == "untouched\n"


def test_author_proof_names_a_live_claim_or_says_self_declared(tmp_path):
    import json as _json

    r = _reg(tmp_path)
    claims = tmp_path / "data/coordination/claims"
    claims.mkdir(parents=True)
    (claims / "c1.json").write_text(_json.dumps({"status": "active", "session": "sess-1", "claim_id": "c1"}))
    a = r.add(title="A", body="x", author="sess-1", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    b = r.add(title="B", body="x", author="sess-2", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    plans = tmp_path / "data/coordination/plans"
    assert 'author_proof: "claim:c1"' in (plans / f"{a}.md").read_text()
    assert 'author_proof: "self-declared"' in (plans / f"{b}.md").read_text()


def test_the_hook_reads_only_a_bounded_regular_file_under_the_plan_roots(tmp_path, monkeypatch):
    import plan_registry_hook as hook

    plans = tmp_path / "plans"
    plans.mkdir()
    monkeypatch.setattr(hook, "plan_file_roots", lambda: [plans.resolve()])
    (plans / "p.md").write_text("# Plan\n")
    secret = tmp_path / "secret.env"
    secret.write_text("TOKEN=super-secret\n")
    (plans / "link.md").symlink_to(secret)
    (plans / "big.md").write_text("x" * (hook.MAX_PLAN_BYTES + 1))
    assert hook.read_plan_file(str(plans / "p.md")) == "# Plan\n"
    assert hook.read_plan_file(str(secret)) == ""
    assert hook.read_plan_file(str(plans / "link.md")) == ""
    assert hook.read_plan_file(str(plans / "big.md")) == ""


def test_the_hook_stores_no_plan_when_the_named_file_is_outside_the_roots(tmp_path, monkeypatch):
    import plan_registry_hook as hook

    plans = tmp_path / "plans"
    plans.mkdir()
    monkeypatch.setattr(hook, "plan_file_roots", lambda: [plans.resolve()])
    secret = tmp_path / "secret.env"
    secret.write_text("TOKEN=super-secret\n")
    text = hook.plan_from_payload({"tool_response": {"planFilePath": str(secret)}, "tool_input": {}})
    assert "super-secret" not in text and text == ""


# ---------------------------------------------------------------- review 2 round 2 (cc3, 2026-11-02)
def test_the_default_plan_roots_are_only_plan_directories(tmp_path, monkeypatch):
    import plan_registry_hook as hook

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    roots = hook.plan_file_roots()
    assert roots == [(tmp_path / "data/coordination/plans").resolve(),
                     (__import__("pathlib").Path.home() / ".claude/plans").resolve()]
    # the breadth that mattered: neither all of ~/.claude nor the temp dir is a plan root
    assert not any(str(r).endswith("/.claude") for r in roots)
    assert not any(str(r) == "/tmp" for r in roots)


def test_credential_shaped_names_under_an_allowed_root_are_refused(tmp_path, monkeypatch):
    import plan_registry_hook as hook

    plans = tmp_path / "plans"
    plans.mkdir()
    monkeypatch.setattr(hook, "plan_file_roots", lambda: [plans.resolve()])
    for name in ("credentials-synthetic.json", "token.md", "my-secret.md", "api_key.txt",
                 ".hidden.md", "plan.json", "notes"):
        p = plans / name
        p.write_text("SYNTHETIC-not-a-real-credential\n")
        assert hook.read_plan_file(str(p)) == "", name
    good = plans / "approved-plan.md"
    good.write_text("# Plan\n\n- [ ] step\n")
    assert hook.read_plan_file(str(good)).startswith("# Plan")


def test_binary_or_non_utf8_plan_input_is_refused(tmp_path, monkeypatch):
    import plan_registry_hook as hook

    plans = tmp_path / "plans"
    plans.mkdir()
    monkeypatch.setattr(hook, "plan_file_roots", lambda: [plans.resolve()])
    (plans / "nul.md").write_bytes(b"# Plan\x00rest")
    (plans / "latin1.md").write_bytes("# Plan\n".encode() + b"\xff\xfe")
    assert hook.read_plan_file(str(plans / "nul.md")) == ""
    assert hook.read_plan_file(str(plans / "latin1.md")) == ""


def test_containment_is_proven_on_the_open_descriptor_not_the_path(tmp_path, monkeypatch):
    """A parent-directory symlink is not stopped by O_NOFOLLOW; the /proc/self/fd check must catch it."""
    import plan_registry_hook as hook

    plans = tmp_path / "plans"
    plans.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "steal.md").write_text("# Not a plan root\n")
    (plans / "sub").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(hook, "plan_file_roots", lambda: [plans.resolve()])
    assert hook.read_plan_file(str(plans / "sub" / "steal.md")) == ""


def test_a_final_component_symlink_is_refused_by_nofollow(tmp_path, monkeypatch):
    import plan_registry_hook as hook

    plans = tmp_path / "plans"
    plans.mkdir()
    # The target is INSIDE the allowed root, so containment alone would let a followed link through:
    # only O_NOFOLLOW can refuse this one.
    real = plans / "real-plan.md"
    real.write_text("# Plan\n")
    (plans / "link.md").symlink_to(real)
    monkeypatch.setattr(hook, "plan_file_roots", lambda: [plans.resolve()])
    assert hook.read_plan_file(str(real)).startswith("# Plan")
    assert hook.read_plan_file(str(plans / "link.md")) == ""


def test_view_skips_an_unreadable_entry_instead_of_taking_the_listing_down(tmp_path):
    """F1 from the core/API integration review (2026-11-02): one odd entry must not 500 /api/v2/plans.

    A directory named ``*.md`` is matched by the glob and reading it raises ``IsADirectoryError``;
    it is served as an explicit unreadable row (review 3) instead of vanishing, and the valid plan
    beside it still lists."""
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n\n- [ ] a\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    inside = tmp_path / "data/coordination/plans"
    (inside / "adir.md").mkdir()  # glob matches it; read_text raises IsADirectoryError (an OSError)
    listing = r.view()
    ids = [row["id"] for row in listing["plans"]]
    assert pid in ids and "adir" in ids, ids
    gap = next(row for row in listing["plans"] if row["id"] == "adir")
    assert gap["status"] == "unreadable" and gap["reason"] == pr.NOT_REGULAR_REASON  # a directory is not a regular file
    assert sorted(row["id"] for row in r.list()) == sorted(ids)


# ---------------------------------------------------------------- cc3 review 3 (2026-11-02) BLOCK
def test_the_plans_api_returns_the_view_for_a_valid_id(tmp_path, monkeypatch):
    import api_v2

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    r = pr.Registry(tmp_path)
    pid = r.add(title="T", body="# T\n\n- [ ] a\n", author="s", vendor="claude",
                approved_at="2026-11-02T10:00:00Z")
    status, payload = api_v2.handle("/api/v2/plans", method="GET", query={"id": [pid]})
    assert status == 200, payload
    assert payload["ok"] is True
    view = payload["data"]
    assert view["schema"] == "PlanRegistryView@v1"
    assert view["plan"]["id"] == pid and view["plan"]["status"] == "registered"
    assert view["plan"]["body"].startswith("# T")


def test_the_plans_api_returns_400_not_500_for_an_invalid_id(tmp_path, monkeypatch):
    """Old code caught only KeyError; Registry.get raised ValueError for an invalid id, which the
    generic dispatcher turned into a 500 echoing the exception text (and the id)."""
    import api_v2

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    for bad in ("../x", "a/b", "UPPER", "-lead", "x" * 100, ".hidden", "a b"):
        status, payload = api_v2.handle("/api/v2/plans", method="GET", query={"id": [bad]})
        assert status == 400, (bad, status, payload)
        assert payload == {"ok": False, "error": "invalid plan id"}, (bad, payload)
        blob = json.dumps(payload)
        assert bad not in blob and "expected" not in blob and "resolves" not in blob


def test_the_plans_api_returns_404_for_an_unknown_but_valid_id(tmp_path, monkeypatch):
    import api_v2

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    status, payload = api_v2.handle("/api/v2/plans", method="GET", query={"id": ["no-such-plan"]})
    assert status == 404, payload
    assert payload == {"ok": False, "error": "plan not found"}
    assert "no-such-plan" not in json.dumps(payload)


def test_the_dispatcher_never_emits_a_bool_as_an_http_status(monkeypatch):
    """A handler's own (status, body) is passed through (the plans route needs 400/404), but ``bool``
    is a subclass of ``int``: ``(True, ...)`` must stay a normal 200 data payload, not status True."""
    import api_v2

    monkeypatch.setitem(api_v2.ROUTES, "/api/v2/__bool_status_probe__", lambda: (True, {"x": 1}))
    status, payload = api_v2.handle("/api/v2/__bool_status_probe__")
    assert status == 200, payload
    assert payload == {"ok": True, "data": (True, {"x": 1})}

    monkeypatch.setitem(api_v2.ROUTES, "/api/v2/__int_status_probe__", lambda: (404, {"ok": False}))
    assert api_v2.handle("/api/v2/__int_status_probe__") == (404, {"ok": False})


def test_a_truncated_plan_is_an_explicit_unreadable_row_not_a_silent_gap(tmp_path):
    """A real approved plan whose front matter is truncated used to vanish from a page that promises
    every plan. It must stay visible as a gap with its id, filename and a reason."""
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n\n- [ ] a\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    inside = tmp_path / "data/coordination/plans"
    (inside / "truncated-plan.md").write_text('---\nid: "truncated-plan"\ntitle: "An approved pla')

    listing = r.view()
    ids = [row["id"] for row in listing["plans"]]
    assert pid in ids, "the valid plan must survive the truncated neighbour"
    gap = next(row for row in listing["plans"] if row["id"] == "truncated-plan")
    assert gap["status"] == "unreadable"
    assert gap["filename"] == "truncated-plan.md"
    assert gap["reason"]
    assert "truncated" in gap["reason"].lower()
    # the valid plan's row keeps its normal shape
    good = next(row for row in listing["plans"] if row["id"] == pid)
    assert good["status"] == "registered" and good["steps_left"] == 1


def test_a_plan_file_without_front_matter_is_an_unreadable_row(tmp_path):
    r = _reg(tmp_path)
    inside = tmp_path / "data/coordination/plans"
    inside.mkdir(parents=True, exist_ok=True)
    (inside / "bare.md").write_text("# Just a body, no front matter\n")
    gap = next(row for row in r.view()["plans"] if row["id"] == "bare")
    assert gap["status"] == "unreadable" and gap["reason"]


def test_a_non_utf8_plan_file_is_an_unreadable_row_not_a_500(tmp_path):
    r = _reg(tmp_path)
    inside = tmp_path / "data/coordination/plans"
    inside.mkdir(parents=True, exist_ok=True)
    (inside / "binary.md").write_bytes(b"\xff\xfe---\nid: x\n")
    gap = next(row for row in r.view()["plans"] if row["id"] == "binary")
    assert gap["status"] == "unreadable" and "UTF-8" in gap["reason"]


# ---------------------------------------------------------------- cc5 review (2026-11-02): list/get/stale
def test_the_listing_keeps_a_non_utf8_plan_as_an_unreadable_row(tmp_path):
    """list() caught only OSError; UnicodeDecodeError is a ValueError, so one corrupt .md took the
    whole listing — and the hourly stale scan that reads it — down with a 500."""
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n\n- [ ] a\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    inside = tmp_path / "data/coordination/plans"
    (inside / "binary.md").write_bytes(b"\xff\xfe---\nid: x\n")

    rows = r.list()
    ids = [row["id"] for row in rows]
    assert pid in ids and "binary" in ids, ids
    gap = next(row for row in rows if row["id"] == "binary")
    assert gap["status"] == "unreadable" and gap["filename"] == "binary.md"
    assert "UTF-8" in gap["reason"]
    assert next(row for row in rows if row["id"] == pid)["status"] == "registered"


def test_the_stale_scan_completes_with_a_non_utf8_plan_in_the_store(tmp_path):
    r = _reg(tmp_path)
    pid = r.add(title="T", body="x", author="s", vendor="claude", approved_at="2026-08-01T10:00:00Z",
                status="approved")
    inside = tmp_path / "data/coordination/plans"
    (inside / "binary.md").write_bytes(b"\xff\xfe---\nid: x\n")
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == [pid]
    gap = next(row for row in r.list() if row["id"] == "binary")
    assert gap["status"] == "unreadable"
    assert r.get(pid)["front"]["status"] == "stalled"


def test_get_raises_key_error_for_a_non_utf8_plan(tmp_path):
    import pytest

    r = _reg(tmp_path)
    inside = tmp_path / "data/coordination/plans"
    inside.mkdir(parents=True, exist_ok=True)
    (inside / "binary.md").write_bytes(b"\xff\xfe---\nid: x\n")
    with pytest.raises(KeyError):
        r.get("binary")


def test_the_plans_api_detail_is_404_for_a_non_utf8_plan(tmp_path, monkeypatch):
    import api_v2

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    inside = tmp_path / "data/coordination/plans"
    inside.mkdir(parents=True, exist_ok=True)
    (inside / "binary.md").write_bytes(b"\xff\xfe---\nid: x\n")
    status, payload = api_v2.handle("/api/v2/plans", method="GET", query={"id": ["binary"]})
    assert status == 404, payload
    assert payload == {"ok": False, "error": "plan not found"}


def test_a_planted_inbox_symlink_is_refused_when_reporting_stale_plans(tmp_path):
    import pytest

    r = _reg(tmp_path)
    pid = r.add(title="T", body="x", author="s", vendor="claude", approved_at="2026-08-01T10:00:00Z",
                status="approved")
    inbox = tmp_path / "data/coordination/coordinator/inbox/codex"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "inbox-target"
    outside.mkdir()
    inbox.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        r.stale(now="2026-11-02T12:00:00Z", apply=True)
    assert list(outside.iterdir()) == []      # nothing was written through the link
    assert pid  # the scan still found the plan; only the notice was refused


def test_the_stale_scan_writes_nothing_when_nothing_is_stalled(tmp_path):
    r = _reg(tmp_path)
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == []
    inbox = tmp_path / "data/coordination/coordinator/inbox/codex"
    assert not inbox.exists() or list(inbox.glob("*plan-stalled.md")) == []


def test_each_stale_run_writes_its_own_dated_notice(tmp_path):
    import time
    r = _reg(tmp_path)
    a = r.add(title="A", body="x", author="s", vendor="claude", approved_at="2026-08-01T10:00:00Z",
              status="approved")
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == [a]
    time.sleep(0.002)  # the filename carries microseconds; distinct runs still get distinct names
    b = r.add(title="B", body="x", author="s", vendor="claude", approved_at="2026-08-01T10:00:00Z",
              status="approved")
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == [b]
    notices = sorted((tmp_path / "data/coordination/coordinator/inbox/codex").glob("*plan-stalled.md"))
    assert len(notices) == 2, notices
    bodies = "\n".join(n.read_text() for n in notices)
    assert f"- {a}" in bodies and f"- {b}" in bodies


# ---------------------------------------------------------------- review 4 (2026-11-03) BLOCK A/B/C
def test_a_store_that_was_never_read_is_absent_not_a_genuinely_empty_store(tmp_path):
    """BLOCK A: a nonexistent state root used to render a valid schema with `plans: []`, identical
    to an empty store. It must say the store is absent, with a fixed reason and no path."""
    import pytest

    r = _reg(tmp_path)
    listing = r.view()
    assert listing["schema"] == "PlanRegistryView@v1"
    assert listing["store"] == {"state": "absent", "reason": "the plan store directory does not exist"}
    assert listing["plans"] == []
    assert listing["as_of"]
    assert str(tmp_path) not in json.dumps(listing["store"])
    with pytest.raises(KeyError):
        r.view("no-such-plan")  # a detail read in an absent store takes the fixed 404 path


def test_an_unlistable_store_is_reported_and_does_not_render_empty(tmp_path):
    """BLOCK A: a directory that exists but cannot be listed is `unlistable`, not `ok` + no rows."""
    import os

    import pytest

    r = _reg(tmp_path)
    plans = tmp_path / "data/coordination/plans"
    plans.mkdir(parents=True)
    if os.geteuid() == 0:
        pytest.skip("root can list a 0o000 directory")
    plans.chmod(0)
    try:
        listing = r.view()
    finally:
        plans.chmod(0o755)
    assert listing["store"] == {"state": "unlistable", "reason": "the plan store directory cannot be listed"}
    assert listing["plans"] == []
    assert str(tmp_path) not in json.dumps(listing["store"])


def test_an_existing_empty_store_is_ok_and_as_of_is_utc(tmp_path):
    """BLOCK A: the honest empty answer carries `ok` and a UTC timestamp."""
    from datetime import datetime

    r = _reg(tmp_path)
    (tmp_path / "data/coordination/plans").mkdir(parents=True)
    listing = r.view()
    assert listing["store"] == {"state": "ok", "reason": None}
    assert listing["plans"] == []
    stamp = datetime.fromisoformat(listing["as_of"].replace("Z", "+00:00"))
    assert stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0


def test_an_unreadable_file_is_a_visible_gap_and_the_other_rows_still_list(tmp_path):
    """BLOCK A: a per-file OSError used to be a silent `continue`; now it is an unreadable row."""
    r = _reg(tmp_path)
    p = tmp_path / "p.md"
    p.write_text("# T\n\n- [ ] a\n")
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-11-02T10:00:00Z")
    inside = tmp_path / "data/coordination/plans"
    (inside / "adir.md").mkdir()  # read_text raises IsADirectoryError (an OSError)

    rows = r.view()["plans"]
    gap = next(row for row in rows if row["id"] == "adir")
    assert gap["status"] == "unreadable" and gap["filename"] == "adir.md"
    assert gap["reason"] == pr.NOT_REGULAR_REASON  # a directory is not a regular file (review 6)
    assert next(row for row in rows if row["id"] == pid)["status"] == "registered"
    lrows = r.list()
    assert next(row for row in lrows if row["id"] == "adir")["status"] == "unreadable"
    assert next(row for row in lrows if row["id"] == pid)["status"] == "registered"


def test_a_truncated_plan_detail_is_404_while_the_listing_shows_the_gap(tmp_path):
    """BLOCK B: a parsed doc with empty front matter is not a plan; detail is KeyError/404, but the
    listing keeps its unreadable row so the file is never hidden."""
    import pytest

    r = _reg(tmp_path)
    inside = tmp_path / "data/coordination/plans"
    inside.mkdir(parents=True, exist_ok=True)
    (inside / "truncated-plan.md").write_text('---\nid: "truncated-plan"\ntitle: "An approved pla')
    (inside / "bare.md").write_text("# Just a body, no front matter\n")

    gap = next(row for row in r.view()["plans"] if row["id"] == "truncated-plan")
    assert gap["status"] == "unreadable"
    assert next(row for row in r.list() if row["id"] == "truncated-plan")["status"] == "unreadable"
    for bad in ("truncated-plan", "bare"):
        with pytest.raises(KeyError):
            r.get(bad)
        with pytest.raises(KeyError):
            r.view(bad)


def test_registration_is_not_an_approval_and_author_proof_is_served(tmp_path):
    """BLOCK C: add() defaults to `registered`; author_proof is served by list and detail; an
    explicit `--status approved` through the CLI still records a real approval."""
    r = _reg(tmp_path)
    pid = r.add(title="Reg", body="# R\n\n- [ ] a\n", author="s", vendor="codex")
    front = pr.parse_plan((tmp_path / "data/coordination/plans" / f"{pid}.md").read_text())["front"]
    assert front["status"] == "registered"
    assert front["author_proof"] == "self-declared"
    # A registration carries no approval time: approved_at is never defaulted from the clock.
    assert "approved_at" not in front

    row = r.view()["plans"][0]
    assert row["status"] == "registered" and row["author_proof"] == "self-declared"
    detail = r.view(pid)
    assert detail["plan"]["author_proof"] == "self-declared"
    assert detail["plan"]["approved_at"] is None
    assert detail["store"] == {"state": "ok", "reason": None}
    assert detail["as_of"]

    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_registry.py"),
                           "--state-root", str(tmp_path), "add", "--title", "Explicitly approved",
                           "--body", "# A\n", "--author", "s", "--vendor", "codex",
                           "--status", "approved", "--approved-at", "2026-11-02T10:00:00Z", "--json"],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    approved_id = json.loads(proc.stdout)["id"]
    approved = pr.parse_plan((tmp_path / "data/coordination/plans" / f"{approved_id}.md").read_text())
    assert approved["front"]["status"] == "approved"
    assert approved["front"]["approved_at"] == "2026-11-02T10:00:00Z"

    # The CLI must not stamp a registration with the clock either: no --approved-at, no approval time.
    plain = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_registry.py"),
                            "--state-root", str(tmp_path), "add", "--title", "Registered via CLI",
                            "--body", "# B\n", "--author", "s", "--vendor", "codex", "--json"],
                           capture_output=True, text=True, check=False)
    assert plain.returncode == 0, plain.stderr
    plain_id = json.loads(plain.stdout)["id"]
    plain_front = pr.parse_plan(
        (tmp_path / "data/coordination/plans" / f"{plain_id}.md").read_text())["front"]
    assert plain_front["status"] == "registered"
    assert "approved_at" not in plain_front


def test_the_hook_registers_a_plan_without_claiming_approval(tmp_path, monkeypatch):
    """BLOCK C: the ExitPlanMode hook registers with the default status; it never writes `approved`."""
    import io

    import plan_registry_hook as hook

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    payload = {"session_id": "sess-reg", "tool_name": "ExitPlanMode",
               "tool_input": {"plan": "# Registered plan\n\n- [ ] one\n"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    plans = sorted((tmp_path / "data/coordination/plans").glob("*.md"))
    assert len(plans) == 1
    front = pr.parse_plan(plans[0].read_text())["front"]
    assert front["status"] == "registered" and front["vendor"] == "claude"
    assert "approved_at" not in front  # the hook records no approval time


# ---------------------------------------------------------------- review 4 (cc4, 2026-11-03) BLOCK ground 1/2
def _digest_store(tmp_path):
    """One store holding every row class the digest must survive (cc-deepseek-2, ground 2)."""
    r = _reg(tmp_path)
    inside = tmp_path / "data/coordination/plans"
    p = tmp_path / "p.md"
    p.write_text("# P\n\n- [ ] a\n")
    pid = r.add(title="Valid", body_path=p, author="s", vendor="claude",
                approved_at="2026-11-02T10:00:00Z")
    linked = r.add(title="Linked", body="x", author="s", vendor="claude",
                   approved_at="2026-08-01T10:00:00Z", status="approved")
    r.link(linked, pr=3)
    recent = r.add(title="Recent", body="x", author="s", vendor="claude",
                   approved_at="2026-11-02T11:00:00Z", status="approved")
    (inside / "id-less-plan.md").write_text(
        '---\ntitle: "No id"\nstatus: "approved"\napproved_at: "2026-08-01T10:00:00Z"\n---\n\n')
    (inside / "bare.md").write_text("# Body only\n")
    (inside / "binary.md").write_bytes(b"\xff\xfe---\nid: x\n")
    (inside / "adir.md").mkdir()
    (inside / "Upper Case Plan.md").write_text('---\ntitle: "T"\nstatus: "approved"\n---\n\n')
    outside = tmp_path / "outside.md"
    outside.write_text('---\ntitle: "Evil"\nstatus: "approved"\n---\n\nsecret\n')
    (inside / "escape.md").symlink_to(outside)
    expected = {pid, linked, recent, "id-less-plan", "bare", "binary", "adir", "Upper Case Plan"}
    return r, expected


def test_an_id_less_approved_plan_is_listed_viewed_and_stale_flagged(tmp_path):
    """Ground 1 (cc4, executed twice): ``list()`` returned the raw front matter, so an approved
    plan whose front matter has no ``id`` made ``stale()`` raise ``KeyError: 'id'`` and the CLI
    exit 2 having flagged nothing. Reverting the ``{**front, "id": path.stem}`` row identity in
    ``list()`` reproduces that KeyError here."""
    r = _reg(tmp_path)
    inside = tmp_path / "data/coordination/plans"
    inside.mkdir(parents=True, exist_ok=True)
    (inside / "id-less-plan.md").write_text(
        '---\ntitle: "An approved plan with no id"\nstatus: "approved"\n'
        'approved_at: "2026-08-01T10:00:00Z"\n---\n\n# P\n\n- [ ] a\n')

    rows = r.list()
    row = next(row for row in rows if row["id"] == "id-less-plan")
    assert row["status"] == "approved"
    assert [row["id"] for row in r.view()["plans"]] == ["id-less-plan"]
    assert r.stale(now="2026-11-02T12:00:00Z", apply=True) == ["id-less-plan"]

    notices = sorted((tmp_path / "data/coordination/coordinator/inbox/codex").glob("*plan-stalled.md"))
    assert len(notices) == 1, notices
    assert "- id-less-plan" in notices[0].read_text()  # named by the id the store uses
    assert r.get("id-less-plan")["front"]["status"] == "stalled"


def test_the_store_wide_digest_shows_every_contained_file_and_still_refuses_an_escape(tmp_path):
    """Ground 2 (cc-deepseek-2): a contained file whose stem fails the id rule was dropped by
    ``_iter_plans``/``list``/``view`` with no row at all. Reverting the contained-but-unaddressable
    branch to ``continue`` drops ``Upper Case Plan`` again, and the escaping symlink must stay
    refused either way."""
    r, expected = _digest_store(tmp_path)
    for rows in (r.list(), r.view()["plans"]):
        ids = {row["id"] for row in rows}
        assert ids == expected, sorted(ids)
        assert "escape" not in ids  # the symlink that resolves outside the store stays skipped
        addressed = next(row for row in rows if row["id"] == "Upper Case Plan")
        assert addressed["status"] == "unreadable"
        assert addressed["reason"] == pr.UNADDRESSABLE_NAME_REASON
        assert addressed["filename"] == "Upper Case Plan.md"
        assert str(tmp_path) not in json.dumps(addressed)  # no path beyond its own filename
        assert "invalid plan id" not in addressed["reason"]  # fixed, no exception text
        assert "^[a-z0-9]" not in addressed["reason"]
    # the whole digest completes on the same rows list()/view() just returned
    assert r.stale(now="2026-11-02T12:00:00Z", apply=False) == ["id-less-plan"]


def test_the_stale_scan_over_the_digest_store_flags_exactly_the_eligible_ids(tmp_path):
    """Ground 1/2 together: the scan reads the same digest ``list()`` returns and flags only the
    approved/in-progress, unlinked, old plans — never a linked, recent, registered or unreadable
    row. Reverting the row identity or the digest rows changes this exact set."""
    r, _ = _digest_store(tmp_path)
    assert r.stale(now="2026-11-02T12:00:00Z", apply=False) == ["id-less-plan"]
    inbox = tmp_path / "data/coordination/coordinator/inbox/codex"
    assert not inbox.exists() or list(inbox.glob("*plan-stalled.md")) == []

    # a store where nothing is eligible writes no notice at all, even with --apply
    quiet = pr.Registry(tmp_path / "quiet", dict(CFG))
    quiet.add(title="Registered only", body="x", author="s", vendor="claude",
              approved_at="2026-08-01T10:00:00Z")
    assert quiet.stale(now="2026-11-02T12:00:00Z", apply=True) == []
    quiet_inbox = tmp_path / "quiet" / "data/coordination/coordinator/inbox/codex"
    assert not quiet_inbox.exists() or list(quiet_inbox.glob("*plan-stalled.md")) == []


# ---------------------------------------------------------------- review 6 (2026-11-03) BLOCK
def _run_isolated(code: str, tmp_path, timeout: float = 15) -> subprocess.CompletedProcess:
    """Run a probe in a child process so a hang fails the test instead of blocking the suite."""
    import os

    env = {**os.environ, "TRADEAI_STATE_ROOT": str(tmp_path),
           "TRADEAI_PERSISTENT_STATE_ROOT": str(tmp_path / "ps"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                          timeout=timeout, env=env, cwd=str(ROOT))


def test_a_fifo_in_the_store_is_unreadable_and_never_hangs_the_listing(tmp_path):
    """Revert the lstat check -> read_text on the FIFO blocks forever (rc=124 in a 6 s child)."""
    r = _reg(tmp_path)
    plans = tmp_path / "data/coordination/plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "blocked-entry.md").unlink(missing_ok=True)
    import os

    os.mkfifo(plans / "blocked-entry.md")
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
        "from plan_registry import Registry\n"
        f"r = Registry(root={str(tmp_path)!r})\n"
        "print(json.dumps([[x['id'], x.get('status'), x.get('reason')] for x in r.list()]))\n"
        "print(json.dumps([[x['id'], x.get('status'), x.get('reason')] for x in r.view()['plans']]))\n"
    )
    proc = _run_isolated(code, tmp_path)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    listed, viewed = [json.loads(line) for line in proc.stdout.strip().splitlines()[-2:]]
    for rows in (listed, viewed):
        row = next(item for item in rows if item[0] == "blocked-entry")
        assert row[1] == "unreadable" and row[2] == "the plan entry is not a regular file", row


def test_a_fifo_ledger_or_lock_is_refused_without_hanging(tmp_path):
    """Opening a FIFO for writing blocks before it returns a descriptor; O_NONBLOCK plus fstat refuse it."""
    import os

    for name, expected in (("ledger.jsonl", "plan ledger"), (".lock", "plan store lock")):
        root = tmp_path / f"store-{name.strip('.')}"
        plans = root / "data/coordination/plans"
        plans.mkdir(parents=True, exist_ok=True)
        os.mkfifo(plans / name)
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "from plan_registry import Registry\n"
            f"try:\n    Registry(root={str(root)!r}).add(title='t', body='x', author='s', vendor='claude')\n"
            "    print('NO REFUSAL')\n"
            "except ValueError as exc:\n    print('refused:', exc)\n"
        )
        proc = _run_isolated(code, root)
        assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
        assert "NO REFUSAL" not in proc.stdout, (name, proc.stdout)
        assert expected in proc.stdout and "refusing" in proc.stdout, (name, proc.stdout)
