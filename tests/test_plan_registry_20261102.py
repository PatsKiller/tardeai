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
    pid = r.add(title="T", body_path=p, author="s", vendor="claude", approved_at="2026-08-01T10:00:00Z")
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
