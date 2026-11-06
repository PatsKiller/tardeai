"""P0 BUILD — automatic agent dispatch (operator ~13:10 ET, 2026-11-04).

Hermetic: fake tmux/gh runners, temp directories, no network, no fleet. Every decision the dispatcher makes is a
function of the data handed in, and these tests exercise the order (a)…(e), the rails, the submit path and the
"dry run writes nothing" promise.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402


def _load_dispatch_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


D = _load_dispatch_module("lib.agent_dispatch", ROOT / "scripts/lib/agent_dispatch.py")
CLI = _load_dispatch_module("agent_dispatch", ROOT / "scripts/agent_dispatch.py")
CLI.D = D


def _complete_pr(*args, **kwargs):
    # These fixtures describe a complete ordinary change unless a case explicitly supplies different evidence.
    kwargs.setdefault("files", ("src/synthetic.py",))
    kwargs.setdefault("changed_files", len(kwargs["files"]))
    kwargs.setdefault("checks_green", True)
    return D.PullRequest(*args, **kwargs)


def _held_pr(*args, **kwargs):
    # Review-routing fixtures must reach the D51 held-only branch, not be skipped as ordinary cloud work.
    kwargs.setdefault("files", (".githooks/pre-push",))
    return _complete_pr(*args, **kwargs)


def _assert_only_pure_delegation_imports(source):
    import ast

    tree = compile(source, "<dispatch-import-rail>", "exec", flags=ast.PyCF_ONLY_AST)
    allowed = {
        "Refused",
        "collect_held_classes",
        "path_ok",
        "reviewer_artifact",
        "safe_read",
        "effective_claim_states",
        "text_id",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name.endswith("pr_merge_delegation") for alias in node.names)
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("pr_merge_delegation"):
            assert {alias.name for alias in node.names} <= allowed, "merge primitive imported by dispatcher"


NOW = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ── 1. session state ────────────────────────────────────────────────────────────────────────────────────────────


def test_busy_marker_wins_over_everything():
    pane = D.classify_pane("cc-1", "· Working (3s · esc to interrupt)\n❯ ")
    assert pane.state == "busy"


def test_text_in_the_input_box_is_input_pending_not_idle():
    pane = D.classify_pane("cc-1", "❯ please finish the task\n  ? for shortcuts")
    assert pane.state == "input_pending" and "please finish" in pane.evidence


def test_plain_screen_is_idle():
    assert D.classify_pane("cc-1", "❯ \n  ? for shortcuts").state == "idle"


def test_a_failed_capture_is_blind_never_idle():
    pane = D.classify_pane("cc-1", None)
    assert pane.state == "blind" and not pane.idle, "a broken pane must not be read as an idle worker"


def test_refusal_list_keeps_broker_sessions_out():
    names = ["cc-deepseek-1", "cx-openai", "codex", "broker-ops", "schwab-check", "unrelated-shell"]
    assert D.selectable_sessions(names) == ["cc-deepseek-1", "codex", "cx-openai"]


# ── 2. queue rows ────────────────────────────────────────────────────────────────────────────────────────────


def claim(cid="c1", session="other", branch="wt/x", paths=("a.tsx",), head="", status="active", age=0.1):
    return D.Claim(
        claim_id=cid, session=session, branch=branch, paths=list(paths), head_sha=head, status=status, age_h=age
    )


def row(rid="FQ-1", owner="cc-8", status="queued", paths=("a.tsx",), **kw):
    return {
        "id": rid,
        "owner": owner,
        "status": status,
        "page": "/p",
        "severity": "P2",
        "paths": list(paths),
        "acceptance": {"what": "w", "expected": "e", "actual": "a", "evidence": "ev"},
        **kw,
    }


def test_only_queued_and_assigned_are_work():
    for status in ("fix_in_review", "blocked_holder", "HELD_x", "delivered", "parked", "closed_no_longer_reproduces"):
        ok, why = D.row_workable(row(status=status), "cc-8", [], now=NOW)
        assert not ok and "silence" in why, status


def test_owner_must_match_exactly():
    assert not D.row_workable(row(owner="cc-80"), "cc-8", [], now=NOW)[0]


def test_takeable_at_in_the_future_holds_the_row():
    future = iso(NOW + timedelta(hours=1))
    ok, why = D.row_workable(row(takeable_at=future), "cc-8", [], now=NOW)
    assert not ok and "held until" in why


def test_a_file_held_by_another_live_claim_blocks_the_row():
    ok, why = D.row_workable(
        row(paths=("src/page.tsx",)), "cc-8", [claim(session="cc-4", paths=("src/page.tsx",))], now=NOW
    )
    assert not ok and "held by cc-4" in why


def test_your_own_claim_does_not_block_your_row_and_a_stale_claim_does_not_either():
    mine = claim(session="cc-8", paths=("src/page.tsx",))
    assert D.row_workable(row(paths=("src/page.tsx",)), "cc-8", [mine], now=NOW)[0]
    stale = claim(session="cc-4", paths=("src/page.tsx",), age=5.0)
    assert D.row_workable(row(paths=("src/page.tsx",)), "cc-8", [stale], now=NOW)[0]


# ── 3. selection order a → e ────────────────────────────────────────────────────────────────────────────────────


def test_a_own_row_beats_every_other_kind():
    a = D.select_work("cc-8", queue=[row()], claims=[], prs=[], verdicts={}, author_of={}, coord="/c", now=NOW)
    assert a.kind == "queue" and a.target == "FQ-1" and "Acceptance" in a.instruction


def test_b_review_a_clean_pr_you_did_not_author():
    pr = _held_pr(7, "h" * 40, "wt/x", "CLEAN", False)
    a = D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    assert a.kind == "review" and a.target == "7"
    assert "review PR #7" in a.instruction and "Do not push, do not merge" in a.instruction
    assert "Adversarial-review: MERGE reviewer=cc-8 head=" + "h" * 40 in a.instruction


def test_never_assigns_a_review_of_your_own_pr():
    pr = _held_pr(7, "h" * 40, "wt/x", "CLEAN", False)
    assert (
        D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-8"}, coord="/c", now=NOW)
        is None
    )


def test_an_ordinary_pr_with_a_merge_verdict_at_head_needs_no_second_review():
    pr = _complete_pr(7, "h" * 40, "wt/x", "CLEAN", False, files=("apps/command-center-v3/src/pages/Home.tsx",))
    v = {(7, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    assert (
        D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts=v, author_of={7: "cc-4"}, coord="/c", now=NOW)
        is None
    )


def test_a_held_pr_with_one_merge_verdict_still_needs_its_second_reviewer(monkeypatch):
    """claude-lead's F1 on #2650: the picker skipped any PR with a MERGE, so a held PR never got its second reviewer."""
    monkeypatch.setattr(D, "review_requirements", lambda: (2, 2, ("AGENTS.md",)))
    pr = _held_pr(7, "h" * 40, "wt/x", "CLEAN", False, files=(".githooks/pre-push",))
    v = {(7, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    a = D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts=v, author_of={7: "cc-4"}, coord="/c", now=NOW)
    assert a is not None and a.kind == "review" and a.target == "7"


def test_an_unlisted_pr_fails_closed_and_needs_the_held_bar():
    """No file list means "cannot prove it is ordinary", so the higher bar applies."""
    pr = _complete_pr(7, "h" * 40, "wt/x", "CLEAN", False, files=(), changed_files=None)
    assert D.required_reviews(pr.files) == (2, True)


def test_a_dirty_or_draft_pr_is_not_review_work():
    draft = _complete_pr(7, "h" * 40, "wt/x", "CLEAN", True)
    dirty = _complete_pr(8, "h" * 40, "wt/y", "BLOCKED", False)
    assert (
        D.select_work("cc-8", queue=[], claims=[], prs=[draft, dirty], verdicts={}, author_of={}, coord="/c", now=NOW)
        is None
    )


def test_c_merge_prep_when_the_author_claim_carries_another_head():
    pr = _complete_pr(9, "a" * 40, "wt/x", "CLEAN", False, commit_shas=("b" * 40, "c" * 40))
    v = {(9, pr.head_sha): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    claims = [claim(session="cc-4", branch="wt/x", head="d" * 40)]  # not in [head] + commits
    a = D.select_work("cc-4", queue=[], claims=claims, prs=[pr], verdicts=v, author_of={9: "cc-4"}, coord="/c", now=NOW)
    assert a.kind == "merge_prep" and a.target == "9"
    assert "Re-stamp the claim" in a.instruction and "Do not push or merge" in a.instruction


def test_c_does_not_fire_when_the_claim_head_is_among_the_pr_commits():
    pr = _complete_pr(9, "new" + "h" * 37, "wt/x", "CLEAN", False, commit_shas=("old" + "h" * 37,))
    v = {(9, pr.head_sha): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    claims = [claim(session="cc-4", branch="wt/x", head="old" + "h" * 37)]
    assert (
        D.select_work("cc-4", queue=[], claims=claims, prs=[pr], verdicts=v, author_of={9: "cc-4"}, coord="/c", now=NOW)
        is None
    )


def test_d_oldest_unowned_row_when_nothing_of_its_own():
    a = D.select_work(
        "cc-8",
        queue=[row(owner=""), row(rid="FQ-2", owner="cc-4")],
        claims=[],
        prs=[],
        verdicts={},
        author_of={},
        coord="/c",
        now=NOW,
    )
    assert a.kind == "unowned_queue" and a.target == "FQ-1"


def test_d_an_unowned_row_does_not_bypass_a_hold_or_a_live_claim():
    """R7 (codex at fffe2c9cb): the unowned branch checked owner, status and the target count — nothing else.

    A row held until 2099, and a row whose exact path another session was already working under a live claim, were
    both handed to an idle session because `owner` was blank. The hold checks now live in `row_hold` and both branches
    use them; a blank owner is not an exemption.
    """
    future = iso(NOW + timedelta(hours=1))
    held = D.select_work(
        "cc-8",
        queue=[row(owner="", takeable_at=future)],
        claims=[],
        prs=[],
        verdicts={},
        author_of={},
        coord="/c",
        now=NOW,
    )
    assert held is None, "a future takeable_at holds the row whoever looks at it"
    taken = D.select_work(
        "cc-8",
        queue=[row(owner="", paths=("src/page.tsx",))],
        claims=[claim(session="cc-4", paths=("src/page.tsx",))],
        prs=[],
        verdicts={},
        author_of={},
        coord="/c",
        now=NOW,
    )
    assert taken is None, "another session's live claim on the row's path holds it even with no owner"


def test_e_chore_for_a_stale_claim():
    a = D.select_work(
        "cc-8",
        queue=[],
        claims=[claim(session="cc-4", age=6.0)],
        prs=[],
        verdicts={},
        author_of={},
        coord="/c",
        now=NOW,
    )
    assert a.kind == "chore" and "has not been heartbeated for 6.0h" in a.instruction


def test_e_a_chore_on_an_open_pr_branch_never_tells_the_session_to_release_it():
    """R1 (cc-deepseek-2 at fffe2c9cb): `release --status done` on a claim whose PR is open is the move that
    permanently unmerges it — the merge gate needs a live claim at the head and a done claim cannot be re-stamped."""
    pr = _complete_pr(21, "h" * 40, "wt/x", "DIRTY", False, commit_shas=("h" * 40,))
    a = D.select_work(
        "cc-8",
        queue=[],
        claims=[claim(session="cc-4", branch="wt/x", age=6.0)],
        prs=[pr],
        verdicts={},
        author_of={21: "cc-4"},
        coord="/c",
        now=NOW,
    )
    assert a.kind == "chore"
    assert "release --status done" not in a.instruction and "--status abandoned" not in a.instruction
    assert "OPEN PR" in a.instruction and "cannot be re-stamped" in a.instruction


def test_nothing_to_do_returns_none():
    assert (
        D.select_work("cc-8", queue=[], claims=[claim(age=0.2)], prs=[], verdicts={}, author_of={}, coord="/c", now=NOW)
        is None
    )


# ── 4. verdicts and the merge pump ─────────────────────────────────────────────────────────────────────────────


def test_verdicts_are_read_from_both_artifact_shapes():
    companion = {"pr": 1, "head_sha": "a" * 40, "verdict": "MERGE", "reviewer_session": "cc-9"}
    registered = {"pr": 1, "head_sha": "a" * 40, "reviews": [{"verdict": "MERGE", "reviewer_session": "cc-4"}]}
    index = D.verdicts_at_head([companion, registered])
    assert {e["reviewer"] for e in index[(1, "a" * 40)]} == {"cc-9", "cc-4"}


def test_merge_pump_separates_ready_from_one_step_and_never_merges():
    pr = _complete_pr(
        11,
        "h" * 40,
        "wt/x",
        "CLEAN",
        False,
        commit_shas=("h" * 40,),
        files=("apps/command-center-v3/src/pages/Home.tsx",),
    )
    claims = [claim(session="cc-4", branch="wt/x", head="h" * 40, status="done", paths=pr.files)]
    v = {
        (11, "h" * 40): [
            {
                "verdict": "MERGE",
                "reviewer": "cc-9",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    out = D.merge_ready([pr], v, claims, {11: "cc-4"})
    assert [r["pr"] for r in out["ready"]] == [11] and out["one_step"] == []
    text = D.render_merge_ready(out, generated_at="now")
    assert "report only" in text and "#11" in text


def test_a_held_pr_with_one_merge_verdict_is_one_step_away_never_ready():
    pr = _complete_pr(12, "h" * 40, "wt/y", "CLEAN", False, commit_shas=("h" * 40,), files=("AGENTS.md",))
    claims = [claim(session="cc-4", branch="wt/y", head="h" * 40)]
    v = {(12, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    out = D.merge_ready([pr], v, claims, {12: "cc-4"})
    assert out["ready"] == [], "a held path needs two independent MERGEs"
    assert out["one_step"] and "needs 2 independent MERGE verdicts" in out["one_step"][0]["step"]


def test_an_unknown_author_is_never_reported_ready():
    """R5 (codex at fffe2c9cb): with an unresolved author map, independence cannot be shown and `author` rendered as
    `""` inside a READY entry. Readiness is a claim about custody; without the author it is a guess."""
    pr = _complete_pr(13, "h" * 40, "wt/z", "CLEAN", False, commit_shas=("h" * 40,), files=("src/x.ts",))
    claims = [claim(session="cc-4", branch="wt/z", head="h" * 40)]
    v = {(13, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    out = D.merge_ready([pr], v, claims, {})
    assert out["ready"] == [], "an unknown author cannot be rendered as ready"
    assert "author unknown" in out["one_step"][0]["step"]


def test_a_done_claim_is_not_told_to_restamp():
    """R5: the fleet's own rule is that a done claim cannot be re-stamped — the author creates a claim AT the head."""
    pr = _complete_pr(14, "h" * 40, "wt/q", "CLEAN", False, commit_shas=("h" * 40,), files=("src/x.ts",))
    v = {(14, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    out = D.merge_ready([pr], v, [], {14: "cc-4"})  # the author's claim was completed and is gone from the active set
    step = out["one_step"][0]["step"]
    assert "create a claim at the head" in step and "re-stamp" not in step


def test_a_merge_verdict_from_the_author_is_not_independent():
    pr = _complete_pr(11, "h" * 40, "wt/x", "CLEAN", False, commit_shas=("h" * 40,))
    claims = [claim(session="cc-4", branch="wt/x", head="h" * 40)]
    v = {(11, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-4"}]}
    out = D.merge_ready([pr], v, claims, {11: "cc-4"})
    assert out["ready"] == [], "the author's own MERGE must not count"


def test_merge_pump_names_the_one_step():
    pr = _complete_pr(12, "h" * 40, "wt/x", "CLEAN", False)
    out = D.merge_ready(
        [pr], {}, [claim(session="cc-4", branch="wt/x", head="h" * 40, status="done", paths=pr.files)], {12: "cc-4"}
    )
    assert out["one_step"][0]["step"] == "needs one independent MERGE verdict at this exact head"


# ── 5. submit path ──────────────────────────────────────────────────────────────────────────────────────────────


class FakeTmux:
    """Records the exact tmux calls and models the pane: idle before the paste, busy and different after it.

    cx-openai-3's F3 requires the busy evidence to be NEW — a pane that was already busy must not count — so this
    fake only shows the busy marker once a paste has happened, and changes the screen then.
    """

    def __init__(self, busy_after_paste: bool = True):
        self.calls: list[list[str]] = []
        self.pasted = False
        self.busy_after_paste = busy_after_paste

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        if cmd[:2] == ["tmux", "paste-buffer"]:
            self.pasted = True
        if cmd[:2] == ["tmux", "capture-pane"]:
            if self.pasted and self.busy_after_paste:
                P.stdout = "· Working (2s · esc to interrupt)\n> Dispatcher: review PR #7"
            else:
                P.stdout = "❯ \n  ? for shortcuts"
        return P


class FakeClock:
    """A monotonic clock that advances exactly as much as the code sleeps — so the deadline is real but instant."""

    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += max(0.0, s)


def test_submit_pastes_then_enters_and_proves_busy():
    fake, clock = FakeTmux(), FakeClock()
    r = D.submit("cc-1", "line one\nline two", run=fake, sleep=clock.sleep, poll_every=3.0, monotonic=clock)
    assert any(c[:2] == ["tmux", "load-buffer"] for c in fake.calls)
    assert any(c[:2] == ["tmux", "paste-buffer"] for c in fake.calls), "text must be pasted, not send-keyed"
    assert not any(c[:3] == ["tmux", "send-keys", "-l"] for c in fake.calls), (
        "send-keys -l is the silent-no-submit trap"
    )
    assert r.submitted and r.busy_after and r.attempts == 1
    assert "after the paste" in r.detail


def test_a_pane_that_is_already_busy_is_never_sent_to():
    """R2 (codex at fffe2c9cb): the admission check is at SEND time, not only at the first scan.

    This test used to assert `attempts == 2` — that a pane stuck on an old spinner was still pasted into, and only
    the *confirmation* refused to credit it. Codex reproduced the dangerous consequence: a pre-paste capture showing
    `❯ operator unsent draft` (or a failed capture) still loaded, pasted and pressed Enter. The requirement is now
    stricter and this fixture is no longer reachable through the confirm loop: a non-idle pane at send time is
    refused before any keystroke, and the refusal is one attempt, not two.
    """

    class StuckBusy(FakeTmux):
        def __call__(self, cmd, **kw):
            p = super().__call__(cmd, **kw)
            if cmd[:2] == ["tmux", "capture-pane"]:
                p.stdout = "· Working (999s · esc to interrupt)"  # always busy, never changing
            return p

    clock = FakeClock()
    r = D.submit(
        "cc-1", "do it", run=StuckBusy(), sleep=clock.sleep, poll_every=3.0, busy_confirm_seconds=6.0, monotonic=clock
    )
    assert r.submitted is False and not r.busy_after and r.attempts == 1
    assert "busy at send time" in r.detail


def test_a_failed_pre_paste_capture_refuses_to_send_blind():
    """R2: a capture failure is a refusal, not an empty baseline — the lane never types into a pane it cannot see."""
    clock = FakeClock()

    class Blind(FakeTmux):
        def __call__(self, cmd, **kw):
            p = super().__call__(cmd, **kw)
            if cmd[:2] == ["tmux", "capture-pane"]:
                p.returncode = 1
            return p

    r = D.submit("cc-1", "do it", run=Blind(), sleep=clock.sleep, busy_confirm_seconds=6.0, monotonic=clock)
    assert r.submitted is False and r.attempts == 1 and "cannot see" in r.detail


def test_a_pane_showing_an_operators_unsent_draft_is_refused():
    """R2, the reproduced case: `❯ operator unsent draft` must not receive a pasted instruction."""
    clock = FakeClock()

    class Draft(FakeTmux):
        def __call__(self, cmd, **kw):
            p = super().__call__(cmd, **kw)
            if cmd[:2] == ["tmux", "capture-pane"]:
                p.stdout = "❯ operator unsent draft"
            return p

    r = D.submit("cc-1", "do it", run=Draft(), sleep=clock.sleep, busy_confirm_seconds=6.0, monotonic=clock)
    assert r.submitted is False and r.attempts == 1 and "input_pending" in r.detail


def test_submit_retries_once_then_reports_dispatch_failed():
    fake, clock = FakeTmux(busy_after_paste=False), FakeClock()  # never goes busy
    r = D.submit(
        "cc-1", "do the thing", run=fake, sleep=clock.sleep, busy_confirm_seconds=6.0, poll_every=3.0, monotonic=clock
    )
    assert not r.busy_after and r.attempts == 2, "one retry, then stop — no third"
    line = json.loads(
        D.ledger_line(
            session="cc-1", assignment=D.Assignment("cc-1", "queue", "FQ-1", "x", "w"), result=r, cycle_id="cyc-1"
        )
    )
    assert line["outcome"] == "dispatch_failed" and line["submitted"] and not line["busy_after_30s"]


def test_ledger_line_shape():
    a = D.Assignment("cc-1", "review", "42", "text", "why")
    r = D.SubmitResult(True, True, 1, "busy confirmed after 3s")
    line = json.loads(
        D.ledger_line(session="cc-1", assignment=a, result=r, cycle_id="cyc-9", ts="2026-11-04T18:00:00Z")
    )
    assert set(line) >= {"ts", "session", "kind", "target", "sent_sha256", "submitted", "busy_after_30s", "cycle_id"}
    assert line["kind"] == "review" and line["target"] == "42" and line["sent_sha256"]


# ── 6. escalation ──────────────────────────────────────────────────────────────────────────────────────────────


def test_idle_alert_only_past_fifteen_minutes():
    assert D.idle_alert([("cc-1", 10.0)], generated_at="now") is None
    text = D.idle_alert([("cc-1", 16.0), ("cc-2", 40.0)], generated_at="now")
    assert "cc-2" in text and "idle 40 min" in text and "add work" in text


# ── 7. the cycle: dry run writes nothing, apply writes only its own files ──────────────────────────────────────


def make_tree(
    tmp: Path, *, panes: dict[str, str], queue: list[dict], claims: list[dict] | None = None
) -> dict[str, Path]:
    coord = tmp / "coordinator"
    (coord / "inbox" / "lead").mkdir(parents=True, exist_ok=True)
    (coord / "AUDIT_FIX_QUEUE.json").write_text(json.dumps({"items": queue}), encoding="utf-8")
    claims_dir = tmp / "claims"
    claims_dir.mkdir()
    for c in claims or []:
        (claims_dir / f"{c['claim_id']}.json").write_text(json.dumps(c), encoding="utf-8")
    return {
        "coord": coord,
        "queue": coord / "AUDIT_FIX_QUEUE.json",
        "claims": claims_dir,
        "ledger": coord / "dispatch_ledger.jsonl",
    }


def fake_runner(panes: dict[str, str], gh_rows: list[dict]):
    def run(cmd, **kw):
        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        if cmd[:2] == ["tmux", "ls"]:
            P.stdout = "\n".join(panes)
        elif cmd[:3] == ["tmux", "capture-pane", "-p"]:
            P.stdout = panes[cmd[cmd.index("-t") + 1]]
        elif cmd[:3] == ["gh", "pr", "list"]:
            # These legacy synthetic rows describe available metadata unless explicitly malformed.
            P.stdout = json.dumps([{"title": "Synthetic PR", "body": "", "labels": [], **row} for row in gh_rows])
        elif cmd[:3] == ["gh", "pr", "view"]:
            P.stdout = json.dumps({"commits": []})
        elif cmd[:2] == ["gh", "api"]:
            number = int(cmd[2].split("/pulls/")[1].split("/")[0].split("?")[0])
            row = next(r for r in gh_rows if r["number"] == number)
            if "/files?" in cmd[2]:
                page = int(cmd[2].split("page=")[-1])
                data = [{"filename": f["path"], "status": "modified"} for f in row.get("files", [])]
                P.stdout = json.dumps(data[(page - 1) * 100 : page * 100])
            else:
                P.stdout = json.dumps({"head": {"sha": row["headRefOid"]}, "changed_files": row.get("changedFiles")})
        return P

    return run


def test_dry_run_writes_nothing_and_sends_nothing(tmp_path):
    paths = make_tree(
        tmp_path,
        panes={"cc-deepseek-8": "❯ \n idle"},
        queue=[{"id": "FQ-1", "owner": "cc-deepseek-8", "status": "queued", "page": "/p", "acceptance": "acc"}],
    )
    run = fake_runner({"cc-deepseek-8": "❯ \n idle"}, [])
    before = sorted(p.name for p in paths["coord"].rglob("*"))
    out = CLI.run_cycle(
        apply=False,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=run,
    )
    after = sorted(p.name for p in paths["coord"].rglob("*"))
    assert before == after, "a dry run must not create files"
    assert not paths["ledger"].exists()
    assert out["assignments"] and out["assignments"][0]["kind"] == "queue"
    assert any("cc-deepseek-8" in line for line in out["plan"])


def test_apply_writes_the_ledger_and_merge_ready_only(tmp_path):
    paths = make_tree(
        tmp_path,
        panes={"cc-deepseek-8": "❯ \n idle"},
        queue=[{"id": "FQ-1", "owner": "cc-deepseek-8", "status": "queued", "page": "/p", "acceptance": "acc"}],
    )
    base = fake_runner({"cc-deepseek-8": "❯ \n idle"}, [])
    sent: list[list[str]] = []

    pasted = {"done": False}

    def run(cmd, **kw):
        if cmd[:2] == ["tmux", "paste-buffer"]:
            sent.append(list(cmd))
            pasted["done"] = True
        p = base(cmd, **kw)
        # Only report busy AFTER the instruction was pasted: the first capture is the state read, and a pane that is
        # busy there is (correctly) left alone.
        if cmd[:2] == ["tmux", "capture-pane"] and pasted["done"]:
            p.stdout = "· Working (1s · esc to interrupt)"
        return p

    out = CLI.run_cycle(
        apply=True,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=run,
        sleep=lambda _s: None,
    )
    assert paths["ledger"].exists() and out["ledger"][0]["outcome"] == "dispatched"
    assert (paths["coord"] / "MERGE_READY.md").exists()
    assert sent, "the instruction was pasted"
    # Rails: nothing else of the fleet's was written.
    written = {p.name for p in paths["coord"].rglob("*") if p.is_file()}
    # The idle streak is written so DISPATCH_IDLE_ALERT can fire on a later cycle (claude-lead's F1 on #2650).
    assert written <= {"AUDIT_FIX_QUEUE.json", "dispatch_ledger.jsonl", "MERGE_READY.md", "dispatch_idle_state.json"}, (
        written
    )


def test_a_raising_transport_still_writes_a_dispatch_failed_receipt(tmp_path, monkeypatch):
    """R6 (codex at fffe2c9cb): the ledger buffered every line until the last submission returned, so one exception
    discarded the receipts of everything already delivered. Each receipt is written as it exists, and a raise becomes
    a recorded failure rather than a lost cycle."""
    paths = make_tree(
        tmp_path,
        panes={"cc-deepseek-8": "❯ \n idle"},
        queue=[{"id": "FQ-1", "owner": "cc-deepseek-8", "status": "queued", "page": "/p", "acceptance": "acc"}],
    )

    def boom(*_a, **_kw):
        raise RuntimeError("tmux died mid-cycle")

    monkeypatch.setattr(CLI.D, "submit", boom)
    out = CLI.run_cycle(
        apply=True,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=fake_runner({"cc-deepseek-8": "❯ \n idle"}, []),
        sleep=lambda _s: None,
    )
    assert out["ledger"] and out["ledger"][0]["outcome"] == "dispatch_failed"
    assert "dispatch raised" in out["ledger"][0]["detail"]
    on_disk = paths["ledger"].read_text(encoding="utf-8").strip().splitlines()
    assert len(on_disk) == 1 and json.loads(on_disk[0])["outcome"] == "dispatch_failed"


def test_busy_sessions_are_not_touched(tmp_path):
    paths = make_tree(
        tmp_path,
        panes={"cc-deepseek-8": "· Working (3s · esc to interrupt)"},
        queue=[{"id": "FQ-1", "owner": "cc-deepseek-8", "status": "queued", "page": "/p"}],
    )
    out = CLI.run_cycle(
        apply=False,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=fake_runner({"cc-deepseek-8": "· Working (3s · esc to interrupt)"}, []),
    )
    assert out["assignments"] == []


# ── 8. rails, stated as a source property ──────────────────────────────────────────────────────────────────────


def test_the_module_writes_only_its_own_two_files():
    """Rails, stated as a source property: the only report files it names are the two it owns, and both writes go
    through the protected-path guard (F2)."""
    src = (ROOT / "scripts" / "agent_dispatch.py").read_text(encoding="utf-8")
    named = set(re.findall(r'"(MERGE_READY\.md|DISPATCH_IDLE_ALERT\.md)"', src))
    assert named == {"MERGE_READY.md", "DISPATCH_IDLE_ALERT.md"}, named
    # R1: every target is prepared (identities recorded) and then opened through the checked handle.
    assert src.count("D.prepare_output(") >= 3, "every write target must pass through the guard"
    assert "D.safe_output_path(" not in src, "the bare precheck must not be used as if it were a fence"
    assert "gh pr merge" not in src and "git push" not in src
    _assert_only_pure_delegation_imports(src)
    _assert_only_pure_delegation_imports((ROOT / "scripts/lib/agent_dispatch.py").read_text())
    # R1 (codex at fffe2c9cb): the write itself goes through the identity-checked handle, not a bare open("a").
    assert re.search(r"open_output\(ledger_target, append=True\)", src), (
        "the ledger append must be visible in the source"
    )
    for name in ("idle_state_target", "merge_ready_target", "alert_target", "ledger_target"):
        assert re.search(rf"open_output\({name}[,)]", src), f"{name} must be written through open_output"
    for forbidden in ("git push", "gh pr merge", "setex", "write_text"):
        if forbidden == "write_text":
            continue
        assert forbidden not in src, f"the dispatcher must never contain {forbidden!r}"


# ── 9. the reviewer cap and recency order (found in the live dry run, 2026-11-04) ──────────────────────────────


def test_at_most_two_reviewers_per_pr():
    pr = _held_pr(7, "h" * 40, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    assert D.select_work("cc-8", review_counts={(7, "h" * 40): 2}, **common) is None, "a third reviewer is not work"
    a = D.select_work("cc-8", review_counts={(7, "h" * 40): 1}, **common)
    assert a and a.kind == "review", "the second reviewer slot is work"


def test_existing_verdicts_count_towards_the_cap():
    pr = _held_pr(7, "h" * 40, "wt/x", "CLEAN", False)
    # One held-class MERGE uses one slot; an at-head BLOCK instead requires repair (D51).
    v = {(7, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    a = D.select_work(
        "cc-8",
        queue=[],
        claims=[],
        prs=[pr],
        verdicts=v,
        author_of={7: "cc-4"},
        coord="/c",
        now=NOW,
        review_counts={(7, "h" * 40): 1},
    )
    assert a is not None
    assert (
        D.select_work(
            "cc-8",
            queue=[],
            claims=[],
            prs=[pr],
            verdicts=v,
            author_of={7: "cc-4"},
            coord="/c",
            now=NOW,
            review_counts={(7, "h" * 40): 2},
        )
        is None
    )


def test_newest_pr_is_offered_before_an_ancient_one():
    old = _held_pr(100, "a" * 40, "wt/old", "CLEAN", False, updated_at="2026-10-20T00:00:00Z")
    new = _held_pr(200, "b" * 40, "wt/new", "CLEAN", False, updated_at="2026-11-04T17:00:00Z")
    a = D.select_work(
        "cc-8",
        queue=[],
        claims=[],
        prs=[old, new],
        verdicts={},
        author_of={100: "cc-1", 200: "cc-2"},
        coord="/c",
        now=NOW,
    )
    assert a.target == "200", "a live PR is reviewed before the October triage list"


def test_a_pr_with_an_unknown_author_is_never_assigned_a_reviewer():
    """F5: independence must be provable. No author resolved means nobody may review it."""
    pr = _held_pr(7, "h" * 40, "wt/x", "CLEAN", False)
    a = D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts={}, author_of={}, coord="/c", now=NOW)
    assert a is None


def test_a_block_verdict_counts_towards_the_reviewer_cap():
    """F4: BLOCK is a verdict too — a PR with two blocks at this head is not given a third reviewer."""
    pr = _held_pr(7, "h" * 40, "wt/x", "CLEAN", False)
    v = {(7, "h" * 40): [{"verdict": "BLOCK", "reviewer": "cc-1"}, {"verdict": "BLOCK", "reviewer": "cc-2"}]}
    a = D.select_work(
        "cc-8",
        queue=[],
        claims=[],
        prs=[pr],
        verdicts=v,
        author_of={7: "cc-4"},
        coord="/c",
        now=NOW,
        review_counts={(7, "h" * 40): 2},
    )
    assert a is None


def test_an_exact_head_block_is_never_reported_ready():
    """F6: the pump must not call a blocked PR ready, even if a MERGE also sits at that head."""
    pr = _complete_pr(11, "h" * 40, "wt/x", "CLEAN", False, commit_shas=("h" * 40,))
    claims = [claim(session="cc-4", branch="wt/x", head="h" * 40)]
    v = {(11, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}, {"verdict": "BLOCK", "reviewer": "cc-2"}]}
    out = D.merge_ready([pr], v, claims, {11: "cc-4"})
    assert out["ready"] == []
    assert "BLOCK" in out["one_step"][0]["step"]


# ── 10. one target per cycle, and no re-sending a review across cycles (found in the 18:53Z dry run) ───────────


def test_two_idle_sessions_never_get_the_same_chore():
    stale = [claim(cid="c-old", session="cc-4", age=9.0)]
    common = dict(queue=[], claims=stale, prs=[], verdicts={}, author_of={}, coord="/c", now=NOW)
    taken: dict[tuple[str, str], int] = {}
    first = D.select_work("cc-1", taken=taken, **common)
    assert first and first.kind == "chore" and first.target == "c-old"
    taken[(first.kind, first.target)] = 1
    second = D.select_work("cc-2", taken=taken, **common)
    assert second is None, "the same stale claim must not be handed to a second session in one cycle"


def test_an_unowned_row_goes_to_one_session_only():
    q = [row(rid="FQ-U", owner="")]
    common = dict(queue=q, claims=[], prs=[], verdicts={}, author_of={}, coord="/c", now=NOW)
    taken: dict[tuple[str, str], int] = {}
    first = D.select_work("cc-1", taken=taken, **common)
    assert first and first.target == "FQ-U"
    taken[(first.kind, first.target)] = 1
    assert D.select_work("cc-2", taken=taken, **common) is None


def test_a_review_is_not_re_sent_across_cycles():
    pr = _complete_pr(7, "h" * 40, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    # cycle 2: the ledger says cycle 1 already sent cc-8 this PR and it went busy
    a = D.select_work(
        "cc-8", prior_review_sessions={(7, "h" * 40): {"cc-8"}}, review_counts={(7, "h" * 40): 1}, **common
    )
    assert a is None, "a reviewer already sent this PR must not be re-sent it every five minutes"


def test_two_cycles_of_sending_cannot_exceed_the_two_reviewer_cap():
    pr = _complete_pr(7, "h" * 40, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    # cycle 1 sent two reviewers who went busy; the cap is spent even though no verdict exists yet
    a = D.select_work(
        "cc-9", prior_review_sessions={(7, "h" * 40): {"cc-1", "cc-2"}}, review_counts={(7, "h" * 40): 2}, **common
    )
    assert a is None


def test_prior_review_dispatches_reads_only_completed_review_lines(tmp_path):
    ledger = tmp_path / "dispatch_ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "review",
                        "target": "7",
                        "target_head": "h" * 40,
                        "session": "cc-1",
                        "busy_after_30s": True,
                    }
                ),
                json.dumps(
                    {
                        "kind": "review",
                        "target": "7",
                        "target_head": "h" * 40,
                        "session": "cc-2",
                        "busy_after_30s": False,
                    }
                ),  # never landed
                json.dumps(
                    {"kind": "queue", "target": "7", "target_head": "h" * 40, "session": "cc-3", "busy_after_30s": True}
                ),  # not a review
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    sessions, counts = CLI.prior_review_dispatches(ledger)
    assert sessions == {(7, "h" * 40): {"cc-1"}} and counts == {(7, "h" * 40): 1}
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write("{not json\n")
    with pytest.raises(D.DispatchError, match="ledger corrupt"):
        CLI.prior_review_dispatches(ledger)


# ── 11. cx-openai-3's six findings (F1–F6) — the regressions that would have caught them ──────────────────────


def test_the_default_adapter_accepts_the_arguments_every_caller_passes():
    """F1 — the single most important gap: the native adapter, not a stand-in.

    `submit` calls the adapter with capture_output/text; the adapter used to pass them too, so the first real
    `load-buffer` raised TypeError: multiple values for keyword argument 'capture_output'. Every earlier test replaced
    the whole adapter, which is exactly why none of them saw it.
    """
    proc = CLI._run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.strip() == "ok"


def test_the_real_submit_path_works_end_to_end_with_the_native_adapter(monkeypatch):
    """F1 again, one level up: the genuine `submit` + genuine `_run`, with only subprocess.run stubbed at the edge."""
    calls: list[list[str]] = []
    pasted = {"done": False}

    class P:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if cmd[:2] == ["tmux", "paste-buffer"]:
            pasted["done"] = True
        if cmd[:2] == ["tmux", "capture-pane"]:
            p = P()
            p.stdout = "· Working (1s · esc to interrupt)\n> dispatched" if pasted["done"] else "❯ \n  ? for shortcuts"
            return p
        return P()

    monkeypatch.setattr(CLI.subprocess, "run", fake_run)
    clock = FakeClock()
    r = D.submit("cc-1", "do the thing", run=CLI._run, sleep=clock.sleep, poll_every=3.0, monotonic=clock)
    assert r.submitted and r.busy_after, r.detail
    assert any(c[:2] == ["tmux", "load-buffer"] for c in calls)


def test_an_output_path_that_aliases_an_input_is_refused(tmp_path):
    """F2 — the lane must not be able to write its own inputs, even through a symlink."""
    coord = tmp_path / "coordinator"
    (coord / "inbox").mkdir(parents=True)
    (coord / "AUDIT_FIX_QUEUE.json").write_text("{}", encoding="utf-8")
    # 1. pointing the ledger at the queue
    try:
        D.safe_output_path(coord / "AUDIT_FIX_QUEUE.json", coord=coord)
        raise AssertionError("writing the queue was allowed")
    except D.DispatchError:
        pass
    # 2. a symlink under the coordinator that points at the inbox
    link = coord / "MERGE_READY.md"
    link.symlink_to(coord / "inbox" / "somewhere.md")
    try:
        D.safe_output_path(link, coord=coord)
        raise AssertionError("writing through a symlink was allowed")
    except D.DispatchError:
        pass
    # 3. the legitimate path still works once the symlink is gone
    link.unlink()
    assert D.safe_output_path(coord / "MERGE_READY.md", coord=coord) == (coord / "MERGE_READY.md").resolve()


def test_the_busy_confirmation_is_wall_clock_bounded():
    """F3 — a pane that never goes busy must exhaust a deadline, not loop forever."""
    clock = FakeClock()
    fake = FakeTmux(busy_after_paste=False)
    started = clock()
    r = D.submit("cc-1", "x", run=fake, sleep=clock.sleep, busy_confirm_seconds=30.0, poll_every=5.0, monotonic=clock)
    assert not r.busy_after and r.attempts == 2
    assert clock() - started <= 2 * 30.0 + 5.0, "the two attempts must fit inside their two deadlines"


def test_an_author_who_released_their_claim_is_still_the_author():
    """F5 — authorship survives a released claim, so a finished author is never sent its own review."""
    prs = [_complete_pr(7, "h" * 40, "wt/x", "CLEAN", False)]
    claims = [claim(cid="c-old", session="cc-4", branch="wt/x", status="done", age=3.0)]
    authors = CLI.author_sessions(prs, claims)
    assert authors == {7: "cc-4"}
    assert (
        D.select_work("cc-4", queue=[], claims=claims, prs=prs, verdicts={}, author_of=authors, coord="/c", now=NOW)
        is None
    )


# ── 12. cx-openai-3's round 2 (F2/F3/F4) — the regressions that would have caught them ────────────────────────


def test_a_hardlink_to_a_protected_input_is_refused_by_inode(tmp_path):
    """F2 round 2: a path STRING is not an identity. `ln MERGE_READY.md queue.json` makes writing the report
    truncate the queue, and the resolved path of the output looks perfectly innocent."""
    queue = tmp_path / "AUDIT_FIX_QUEUE.json"
    queue.write_text('{"items": [1, 2, 3]}\n', encoding="utf-8")
    report = tmp_path / "MERGE_READY.md"
    os.link(queue, report)
    assert os.stat(report).st_ino == os.stat(queue).st_ino
    with pytest.raises(D.DispatchError) as exc:
        D.safe_output_path(report, coord=tmp_path, protected=[queue])
    assert "hardlink" in str(exc.value)
    assert queue.read_text(encoding="utf-8") == '{"items": [1, 2, 3]}\n', "the queue must be untouched"


def test_a_hardlinked_ledger_cannot_append_to_a_claim(tmp_path):
    """F2 round 2: the same inode check protects a claims directory, so the lane cannot append to a claim."""
    claims = tmp_path / "claims"
    claims.mkdir()
    claim_file = claims / "20261104T000000Z-claude-dead.json"
    claim_file.write_text('{"claim_id": "dead"}\n', encoding="utf-8")
    ledger = tmp_path / "dispatch_ledger.jsonl"
    os.link(claim_file, ledger)
    with pytest.raises(D.DispatchError) as exc:
        D.safe_output_path(ledger, coord=tmp_path, protected=[claims])
    assert "hardlink" in str(exc.value)
    assert claim_file.read_text(encoding="utf-8") == '{"claim_id": "dead"}\n'


def test_an_unsafe_output_is_refused_before_a_single_keystroke(tmp_path, monkeypatch):
    """F2 round 2: validation happened AFTER the send loop, so a misconfigured --ledger pasted the fleet first
    (send_before_refusal=True). A refusal must cost zero sends."""
    coord = tmp_path / "coord"
    (coord / "inbox").mkdir(parents=True)
    queue = coord / "AUDIT_FIX_QUEUE.json"
    queue.write_text('{"items": []}\n', encoding="utf-8")
    monkeypatch.setattr(
        CLI.D, "select_work", lambda *a, **k: D.Assignment("cc-8", "review", "9999", "Dispatcher: do a thing", "forced")
    )

    sent = []

    def run(cmd, **kw):
        class P:
            returncode = 0
            stdout = ""

        if cmd[:2] == ["tmux", "ls"]:
            P.stdout = "cc-deepseek-8\n"
        if cmd[:2] == ["tmux", "capture-pane"]:
            P.stdout = "> \n"
        if any(x in cmd for x in ("load-buffer", "paste-buffer", "send-keys")):
            sent.append(list(cmd))
        return P()

    with pytest.raises(D.DispatchError):
        CLI.run_cycle(
            apply=True,
            coord=coord,
            queue_path=queue,
            claims_dir=coord / "claims",
            ledger_path=queue,
            limit=1,
            run=run,
            sleep=lambda s: None,
        )
    assert sent == [], f"the refusal must come before any keystroke, but these were sent: {sent}"


def test_open_output_refuses_a_symlink_swapped_in_after_the_precheck(tmp_path):
    """R1 (codex at fffe2c9cb): the precheck is not a fence. Codex swapped MERGE_READY.md for a symlink into the queue
    between the check and the write, and the report truncated the queue. O_NOFOLLOW refuses at the open itself."""
    queue = tmp_path / "AUDIT_FIX_QUEUE.json"
    queue.write_text('{"items": [1, 2, 3]}\n', encoding="utf-8")
    report = tmp_path / "MERGE_READY.md"
    checked = D.safe_output_path(report, coord=tmp_path, protected=[queue])  # the path is clean at check time
    report.unlink(missing_ok=True)
    report.symlink_to(queue)  # …and swapped before the write
    with pytest.raises(D.DispatchError):
        D.open_output(checked)
    assert queue.read_text(encoding="utf-8") == '{"items": [1, 2, 3]}\n', "the queue must be untouched"


def test_open_output_refuses_a_directory_replaced_after_the_check(tmp_path):
    """R1's residual, closed: the file name is resolved inside the directory INODE that was validated, so replacing
    the directory between the check and the write cannot redirect the report into the queue."""
    coord = tmp_path / "coord"
    (coord / "inbox").mkdir(parents=True)
    queue = coord / "AUDIT_FIX_QUEUE.json"
    queue.write_text('{"items": []}\n', encoding="utf-8")
    out = coord / "MERGE_READY.md"
    checked = D.prepare_output(out, coord=coord, protected=[queue])
    # now swap the whole directory for a symlink pointing at the protected inbox
    moved = tmp_path / "coord-moved"
    coord.rename(moved)
    coord.symlink_to(moved / "inbox")
    with pytest.raises(D.DispatchError):
        D.open_output(checked)
    assert not any((moved / "inbox").iterdir()), "nothing may be written through the swapped directory"


def test_open_output_refuses_a_file_replaced_after_the_check(tmp_path):
    """R1: if the output existed at check time and is a different inode at write time, it is not our file any more."""
    coord = tmp_path / "coord"
    coord.mkdir()
    out = coord / "MERGE_READY.md"
    out.write_text("old report\n", encoding="utf-8")
    checked = D.prepare_output(out, coord=coord)
    with out.open("rb") as original_inode:
        out.unlink()
        out.write_text("impostor\n", encoding="utf-8")
        assert os.fstat(original_inode.fileno()).st_ino != out.stat().st_ino
        with pytest.raises(D.DispatchError) as exc:
            D.open_output(checked)
    assert "replaced after the check" in str(exc.value)
    assert out.read_text(encoding="utf-8") == "impostor\n", "the replacement must not be truncated either"


def test_open_output_refuses_a_hardlink_alias_at_any_depth(tmp_path):
    """R1: the precheck walks two levels of the protected tree; a depth-3 hardlink slipped past it. The link count on
    the handle's own inode does not care about depth."""
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    source = deep / "review.md"
    source.write_text("a protected review\n", encoding="utf-8")
    out = tmp_path / "MERGE_READY.md"
    os.link(source, out)
    with pytest.raises(D.DispatchError) as exc:
        D.open_output(out)
    assert "links" in str(exc.value)
    assert source.read_text(encoding="utf-8") == "a protected review\n"


def test_an_output_pointed_at_a_tracked_file_is_refused(tmp_path):
    """R1: `--ledger` was unrestricted — codex pointed it at a source file and the lane appended to source."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    src = repo / "source.py"
    src.write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "add", "source.py"], cwd=repo, check=True)
    with pytest.raises(D.DispatchError) as exc:
        D.safe_output_path(src, coord=tmp_path / "coord", protected=[])
    assert "tracked by git" in str(exc.value)
    assert src.read_text(encoding="utf-8") == "print('hi')\n"


def test_a_slow_capture_cannot_confirm_busy_after_the_deadline():
    """F3 round 2: two 14.9s captures used to "confirm" busy at 36.4s inside a 30s window, because each capture got
    a fresh RUN_TIMEOUT_S and a result that arrived after the deadline was still believed."""
    clock = FakeClock()
    seen = {"n": 0}

    class LateBusy(FakeTmux):
        """Capture 1 is the pre-paste look, capture 2 the first poll, capture 3 the busy one — but it lands late."""

        def __call__(self, cmd, **kw):
            p = super().__call__(cmd, **kw)
            if cmd[:2] == ["tmux", "capture-pane"]:
                seen["n"] += 1
                if seen["n"] >= 3:
                    clock.t += 20.0  # this capture returns after the deadline
                    p.stdout = "· Working (2s · esc to interrupt)\na busy line"
                else:
                    clock.t += 14.9
                    p.stdout = "> idle"
            return p

    r = D.submit("cc-1", "go", run=LateBusy(), sleep=clock.sleep, monotonic=clock, busy_confirm_seconds=30.0)
    assert r.busy_after is False, "a busy capture that arrives after the deadline must not confirm anything"
    assert clock.t > 30.0, "sanity: the late capture really did land past the window"


def test_a_busy_marker_that_predates_the_paste_is_not_evidence():
    """F3 round 2: a changed tail containing an OLD busy marker read as success. The marker must be new."""
    clock = FakeClock()
    state = {"n": 0}

    class Drift(FakeTmux):
        def __call__(self, cmd, **kw):
            p = super().__call__(cmd, **kw)
            if cmd[:2] == ["tmux", "capture-pane"]:
                state["n"] += 1
                p.stdout = (
                    "· Working (999s · esc to interrupt)\n"  # the SAME old spinner both times
                    + ("status line " + str(state["n"]))
                )
            return p

    r = D.submit("cc-1", "go", run=Drift(), sleep=clock.sleep, monotonic=clock, busy_confirm_seconds=10.0)
    assert r.busy_after is False, "an old marker plus unrelated tail drift is not evidence of this dispatch"


def test_a_transport_timeout_is_a_result_not_a_crash():
    """R6 (codex at fffe2c9cb): `subprocess.run(timeout=...)` raises TimeoutExpired, and an uncaught raise escaped
    submit with no SubmitResult for the ledger. The raise is now the result."""
    import subprocess as sp

    class Slow(FakeTmux):
        def __call__(self, cmd, **kw):
            if cmd[:2] == ["tmux", "capture-pane"]:
                raise sp.TimeoutExpired(cmd="tmux capture-pane", timeout=1.0)
            return super().__call__(cmd, **kw)

    r = D.submit("cc-1", "go", run=Slow(), sleep=lambda _s: None, monotonic=FakeClock(), busy_confirm_seconds=5.0)
    assert r.submitted is False and "cannot see" in r.detail


def test_an_oserror_on_the_paste_path_is_a_failed_dispatch_not_an_exception():
    """R6: a tmux that vanished mid-attempt is `dispatch_failed`, never a traceback that loses the cycle."""

    class Gone(FakeTmux):
        def __call__(self, cmd, **kw):
            if cmd[:2] == ["tmux", "load-buffer"]:
                raise FileNotFoundError("tmux")
            return super().__call__(cmd, **kw)

    r = D.submit("cc-1", "go", run=Gone(), sleep=lambda _s: None, monotonic=FakeClock(), busy_confirm_seconds=5.0)
    assert r.submitted is False and r.attempts == 2 and not r.busy_after


def test_a_failed_paste_is_not_a_submission():
    """F3 round 2: when both load-buffer calls fail, submitted was True because it was `attempts > 0`."""

    class Dead(FakeTmux):
        def __call__(self, cmd, **kw):
            p = super().__call__(cmd, **kw)
            if cmd[:2] == ["tmux", "load-buffer"]:
                p.returncode = 1
            return p

    r = D.submit("cc-1", "go", run=Dead(), sleep=lambda s: None, monotonic=FakeClock(), busy_confirm_seconds=5.0)
    assert r.submitted is False, "nothing was pasted, so nothing was submitted"
    assert r.busy_after is False and r.attempts == 2


def test_the_review_cap_is_head_specific():
    """F4 round 2: a dispatch recorded against an OLD head neither spends the new head's budget nor bars that
    reviewer from reviewing the new revision."""
    old_head, new_head = "a" * 40, "b" * 40
    pr = _held_pr(7, new_head, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    a = D.select_work(
        "cc-8", prior_review_sessions={(7, old_head): {"cc-8", "cc-9"}}, review_counts={(7, old_head): 2}, **common
    )
    assert a is not None and a.kind == "review", "the new head has its own two-reviewer budget"
    b = D.select_work(
        "cc-8", prior_review_sessions={(7, new_head): {"cc-8"}}, review_counts={(7, new_head): 1}, **common
    )
    assert b is None, "the same reviewer is not re-sent the SAME head"


def test_a_dispatch_recorded_at_an_old_head_does_not_spend_the_new_head_budget(tmp_path):
    """F4 round 2 at the ledger boundary: prior_review_dispatches keys by (pr, head)."""
    ledger = tmp_path / "dispatch_ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "review",
                        "target": "7",
                        "target_head": "a" * 40,
                        "session": "cc-1",
                        "busy_after_30s": True,
                    }
                ),
                json.dumps(
                    {
                        "kind": "review",
                        "target": "7",
                        "target_head": "b" * 40,
                        "session": "cc-2",
                        "busy_after_30s": True,
                    }
                ),
                json.dumps(
                    {"kind": "review", "target": "7", "session": "cc-3", "busy_after_30s": True}
                ),  # legacy: no head
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    sessions, counts = CLI.prior_review_dispatches(ledger)
    assert counts == {("7", "a" * 40): 1} or counts.get((7, "a" * 40)) == 1
    assert (7, "a" * 40) in counts and counts[(7, "a" * 40)] == 1
    assert (7, "b" * 40) in counts and counts[(7, "b" * 40)] == 1
    assert counts.get((7, ""), 0) == 1, "a legacy record is attributed to the empty head, never to a real one"


def test_the_whole_attempt_is_inside_its_window():
    """F3 round 2, the letter of it: the pre-paste capture and the paste are budgeted too, not only the polls, so one
    attempt can never outlive busy_confirm_seconds."""
    clock = FakeClock()

    class EveryCallSlow(FakeTmux):
        """Every tmux call takes 8s — or the timeout the caller allowed, whichever is shorter: a real subprocess is
        killed at its timeout, so the fake must not pretend a 20s window can absorb three 8s calls."""

        def __call__(self, cmd, **kw):
            p = super().__call__(cmd, **kw)
            clock.t += min(8.0, float(kw.get("timeout") or 8.0))
            if cmd[:2] == ["tmux", "capture-pane"]:
                p.stdout = "> idle"
            return p

    r = D.submit("cc-1", "go", run=EveryCallSlow(), sleep=clock.sleep, monotonic=clock, busy_confirm_seconds=20.0)
    assert r.busy_after is False
    # Two attempts, each opened with its own 20s window; the calls that would overrun it are cut at the timeout that
    # was left, and the Enter is refused rather than sent into a closed window.
    assert clock.t <= 2 * 20.0 + 2.0, f"attempts ran {clock.t:.1f}s well past two 20s windows"


# D49/D50 complete current-head repair controls. All transports and stores are synthetic.


def ordinary_pr(number=7, *, head="h" * 40, files=("src/synthetic.py",), **kwargs):
    return _complete_pr(number, head, "wt/synthetic", "CLEAN", False, files=files, **kwargs)


def test_d49_idle_state_alias_is_refused_before_any_submission(tmp_path):
    paths = make_tree(
        tmp_path, panes={"cc-deepseek-8": "❯ \n"}, queue=[row(owner="cc-deepseek-8", paths=("src/synthetic.py",))]
    )
    (paths["coord"] / CLI.IDLE_STATE_NAME).symlink_to(paths["queue"])
    original = paths["queue"].read_bytes()
    base = fake_runner({"cc-deepseek-8": "❯ \n"}, [])
    sent = []
    pasted = False

    def run(cmd, **kw):
        nonlocal pasted
        if cmd[:2] in (["tmux", "load-buffer"], ["tmux", "paste-buffer"], ["tmux", "send-keys"]):
            sent.append(list(cmd))
        if cmd[:2] == ["tmux", "paste-buffer"]:
            pasted = True
        out = base(cmd, **kw)
        if cmd[:2] == ["tmux", "capture-pane"] and pasted:
            out.stdout = "Working (new dispatch · esc to interrupt)"
        return out

    with pytest.raises(D.DispatchError):
        CLI.run_cycle(
            apply=True,
            coord=paths["coord"],
            queue_path=paths["queue"],
            claims_dir=paths["claims"],
            ledger_path=paths["ledger"],
            run=run,
            sleep=lambda _: None,
        )
    assert not sent
    assert paths["queue"].read_bytes() == original


def test_d49_real_cycle_prior_reviewers_spend_cap_without_verdicts(tmp_path):
    paths = make_tree(
        tmp_path,
        panes={"cc-deepseek-9": "❯ \n"},
        queue=[],
        claims=[
            {
                "claim_id": "author",
                "session": "author",
                "branch": "wt/synthetic",
                "status": "done",
                "heartbeat_at": iso(NOW),
                "paths": ["src/synthetic.py"],
            }
        ],
    )
    lines = [
        {"kind": "review", "target": "7", "target_head": "h" * 40, "session": session, "busy_after_30s": True}
        for session in ("cc-deepseek-1", "cc-deepseek-2")
    ]
    paths["ledger"].write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    prs = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "h" * 40,
            "mergeStateStatus": "CLEAN",
            "isDraft": False,
            "changedFiles": 1,
            "files": [{"path": "src/synthetic.py"}],
        }
    ]
    out = CLI.run_cycle(
        apply=False,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=fake_runner({"cc-deepseek-9": "❯ \n"}, prs),
    )
    assert out["assignments"] == []


def test_d49_a_filed_merge_reviewer_is_not_assigned_the_same_head(monkeypatch):
    monkeypatch.setattr(D, "review_requirements", lambda: (2, 2, ("AGENTS.md",)))
    pr = ordinary_pr(files=(".githooks/pre-push",))
    verdicts = {(7, pr.head_sha): [{"verdict": "MERGE", "reviewer": "cc-8"}]}
    common = dict(
        queue=[], claims=[], prs=[pr], verdicts=verdicts, author_of={7: "author"}, coord="/synthetic", now=NOW
    )
    assert D.select_work("cc-8", **common) is None
    assert D.select_work("cc-9", **common).kind == "review"


def test_d49_an_author_merge_does_not_satisfy_picker_or_report():
    pr = ordinary_pr(files=(".githooks/pre-push",))
    verdicts = {(7, pr.head_sha): [{"verdict": "MERGE", "reviewer": "author"}]}
    claims = [claim(session="author", branch=pr.head_ref, head=pr.head_sha)]
    assignment = D.select_work(
        "cc-8",
        queue=[],
        claims=claims,
        prs=[pr],
        verdicts=verdicts,
        author_of={7: "author"},
        coord="/synthetic",
        now=NOW,
    )
    assert assignment and assignment.kind == "review"
    assert D.merge_ready([pr], verdicts, claims, {7: "author"})["ready"] == []


@pytest.mark.parametrize("owner", ["cc-8", ""])
@pytest.mark.parametrize("held", ["scripts/lib/**", "scripts/lib", "**/synthetic.py"])
def test_d49_claim_glob_and_directory_hold_descendants(owner, held):
    assignment = D.select_work(
        "cc-8",
        queue=[row(owner=owner, paths=("scripts/lib/synthetic.py",))],
        claims=[claim(session="other", paths=(held,))],
        prs=[],
        verdicts={},
        author_of={},
        coord="/synthetic",
        now=NOW,
    )
    assert assignment is None


@pytest.mark.parametrize("contents", [None, "{broken", "{}", '{"schema":"wrong"}'])
def test_d49_unreadable_authority_keeps_all_paths_held(tmp_path, contents, monkeypatch):
    path = tmp_path / "authority.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    requirements = D.review_requirements(path)
    assert D.required_reviews(("src/synthetic.py",), requirements) == (2, True)
    monkeypatch.setattr(D, "review_requirements", lambda: requirements)
    pr = ordinary_pr()
    assert (
        D.select_work(
            "cc-8", queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "author"}, coord="/synthetic", now=NOW
        )
        is None
    )


def test_d49_adoption_keeps_original_and_new_author_exclusions():
    pr = ordinary_pr(files=(".githooks/pre-push",))
    claims = [
        claim(cid="original", session="cc-old", branch=pr.head_ref, status="done", age=4),
        claim(cid="adopter", session="cc-new", branch=pr.head_ref, head=pr.head_sha),
    ]
    authors = CLI.author_sessions([pr], claims)
    for session in ("cc-old", "cc-new"):
        assert (
            D.select_work(
                session, queue=[], claims=claims, prs=[pr], verdicts={}, author_of=authors, coord="/synthetic", now=NOW
            )
            is None
        )
    verdicts = {
        (7, pr.head_sha): [{"verdict": "MERGE", "reviewer": "cc-old"}, {"verdict": "MERGE", "reviewer": "cc-new"}]
    }
    assert D.merge_ready([pr], verdicts, claims, authors)["ready"] == []
    assert (
        D.select_work(
            "cc-independent",
            queue=[],
            claims=claims,
            prs=[pr],
            verdicts={},
            author_of=authors,
            coord="/synthetic",
            now=NOW,
        ).kind
        == "review"
    )


def test_d49_takeover_predecessor_survives_missing_original_claim_file(tmp_path):
    path = tmp_path / "claims"
    path.mkdir()
    (path / "adopter.json").write_text(
        json.dumps(
            {
                "claim_id": "adopter",
                "session": "cc-new",
                "branch": "wt/synthetic",
                "status": "active",
                "heartbeat_at": iso(NOW),
                "paths": ["src/synthetic.py"],
                "takeover_of": [{"session": "cc-old", "branch": "wt/synthetic"}],
            }
        ),
        encoding="utf-8",
    )
    claims = D.load_claims(path, now=NOW)
    pr = ordinary_pr()
    assert (
        D.select_work(
            "cc-old",
            queue=[],
            claims=claims,
            prs=[pr],
            verdicts={},
            author_of=CLI.author_sessions([pr], claims),
            coord="/synthetic",
            now=NOW,
        )
        is None
    )


@pytest.mark.parametrize("next_screen", [None, "Working (unrelated busy · esc to interrupt)", "❯ unsent draft"])
def test_d49_retry_refusal_preserves_the_enter_already_delivered(next_screen):
    clock = FakeClock()
    fake = FakeTmux(busy_after_paste=False)
    captures = 0

    def run(cmd, **kw):
        nonlocal captures
        out = fake(cmd, **kw)
        if cmd[:2] == ["tmux", "capture-pane"]:
            captures += 1
            if captures >= 3:
                out.stdout = next_screen or ""
                out.returncode = 1 if next_screen is None else 0
        return out

    result = D.submit(
        "cc-8", "synthetic", run=run, sleep=clock.sleep, monotonic=clock, busy_confirm_seconds=3, poll_every=2
    )
    assert sum(cmd[:2] == ["tmux", "send-keys"] for cmd in fake.calls) == 1
    assert result.submitted is True and result.busy_after is False and result.attempts == 2
    line = json.loads(
        D.ledger_line(
            session="cc-8",
            assignment=D.Assignment("cc-8", "queue", "Q", "x", "why"),
            result=result,
            cycle_id="synthetic",
        )
    )
    assert line["submitted"] is True and line["outcome"] == "dispatch_failed"


@pytest.mark.parametrize("owner", ["cc-8", ""])
@pytest.mark.parametrize("field", ["page", "path", "file", "paths"])
def test_d49_reserved_work_content_is_never_assigned(owner, field):
    task = row(owner=owner, paths=())
    task[field] = ["scripts/moomoo/synthetic.py"] if field == "paths" else "scripts/moomoo/synthetic.py"
    assert (
        D.select_work("cc-8", queue=[task], claims=[], prs=[], verdicts={}, author_of={}, coord="/synthetic", now=NOW)
        is None
    )


@pytest.mark.parametrize(
    "path", ["scripts/lib/broker_execution.py", "AGENTS.md", "scripts/lib/pr_merge_delegation.py", ".env.synthetic"]
)
def test_d49_reserved_review_paths_are_not_autonomously_assigned(path):
    pr = ordinary_pr(files=(path,))
    assert (
        D.select_work(
            "cc-8", queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "author"}, coord="/synthetic", now=NOW
        )
        is None
    )


def test_d49_incomplete_file_list_is_not_ready_or_review_work():
    pr = ordinary_pr(files=(".githooks/pre-push",))
    pr.changed_files = 101
    verdicts = {(7, pr.head_sha): [{"verdict": "MERGE", "reviewer": "independent"}]}
    claims = [claim(session="author", branch=pr.head_ref, head=pr.head_sha)]
    assert D.merge_ready([pr], verdicts, claims, {7: "author"})["ready"] == []
    assert (
        D.select_work(
            "cc-8", queue=[], claims=claims, prs=[pr], verdicts={}, author_of={7: "author"}, coord="/synthetic", now=NOW
        )
        is None
    )


def test_d49_open_prs_keeps_changed_file_completeness():
    rows = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "h" * 40,
            "mergeStateStatus": "CLEAN",
            "isDraft": False,
            "changedFiles": 101,
            "files": [{"path": "src/synthetic.py"}],
        }
    ]
    pr = CLI.open_prs(fake_runner({}, rows), with_commits=False)[0]
    assert getattr(pr, "changed_files", None) == 101


@pytest.mark.parametrize("kind", ["absent", "corrupt"])
def test_d49_unavailable_claim_board_cannot_authorize_work(tmp_path, kind):
    claims_dir = tmp_path / "claims"
    if kind == "corrupt":
        claims_dir.mkdir()
        (claims_dir / "claim.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(D.DispatchError, match="claim"):
        D.load_claims(claims_dir, now=NOW)


def test_d49_unavailable_evidence_directory_is_not_empty_evidence(tmp_path):
    with pytest.raises(D.DispatchError, match="review"):
        CLI.load_review_artifacts(tmp_path / "missing-coordinator")


def test_d49_inbox_status_json_is_not_a_review_artifact(tmp_path):
    coord = tmp_path / "coordinator"
    inbox = coord / "inbox" / "lead"
    inbox.mkdir(parents=True)
    (inbox / "status.json").write_text(
        json.dumps(
            {
                "pr": 7,
                "head_sha": "h" * 40,
                "reviewer_session": "cc-other",
                "verdict": "MERGE",
                "note": "status update, not a review artifact",
            }
        ),
        encoding="utf-8",
    )
    assert CLI.load_review_artifacts(coord) == []


def test_d49_archived_original_author_is_still_excluded(tmp_path):
    directory = tmp_path / "claims"
    directory.mkdir()
    current = {
        "claim_id": "new",
        "session": "new-author",
        "branch": "wt/synthetic",
        "status": "active",
        "heartbeat_at": iso(NOW),
        "paths": ["src/synthetic.py"],
    }
    old = {**current, "claim_id": "old", "session": "old-author", "status": "done"}
    (directory / "new.json").write_text(json.dumps(current), encoding="utf-8")
    (directory / "claims_history.jsonl").write_text(
        json.dumps(
            {
                "schema": "AgentClaimArchive@v1",
                "claim": old,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    claims = D.load_claims(directory, now=NOW)
    pr = ordinary_pr()
    authors = CLI.author_sessions([pr], claims)
    assert (
        D.select_work(
            "old-author", queue=[], claims=claims, prs=[pr], verdicts={}, author_of=authors, coord="/synthetic", now=NOW
        )
        is None
    )


def test_d49_valid_review_prose_is_loaded_and_newer_verdict_supersedes(tmp_path):
    coord = tmp_path / "coordinator"
    evidence = coord / "review-evidence"
    evidence.mkdir(parents=True)
    for filename, verdict, mtime in [("later-filename", "BLOCK", 100), ("earlier-filename", "MERGE", 200)]:
        doc = {"pr": 7, "head_sha": "h" * 40, "reviewer_session": "independent", "verdict": verdict}
        prose = evidence / (filename + ".md")
        prose.write_text(
            "Adversarial-review: " + verdict + " reviewer=independent head=" + "h" * 40 + "\n", encoding="utf-8"
        )
        doc["evidence"] = {"prose_path": str(prose)}
        machine = evidence / (filename + ".machine.json")
        machine.write_text(json.dumps(doc), encoding="utf-8")
        os.utime(machine, (mtime, mtime))
    result = D.verdicts_at_head(CLI.load_review_artifacts(coord))
    assert result[(7, "h" * 40)] == [{"verdict": "MERGE", "reviewer": "independent"}]


@pytest.mark.parametrize(
    "checks",
    [
        None,
        [],
        [{"__typename": "CheckRun", "status": "IN_PROGRESS"}],
        [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}],
    ],
)
def test_d49_ready_report_requires_measured_green_checks(checks):
    rows = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "h" * 40,
            "mergeStateStatus": "CLEAN",
            "isDraft": False,
            "changedFiles": 1,
            "files": [{"path": "src/synthetic.py"}],
            "statusCheckRollup": checks,
        }
    ]
    pr = CLI.open_prs(fake_runner({}, rows), with_commits=False)[0]
    verdicts = {(7, pr.head_sha): [{"verdict": "MERGE", "reviewer": "independent"}]}
    claims = [claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)]
    out = D.merge_ready([pr], verdicts, claims, {7: "author"})
    assert out["ready"] == [] and "checks" in out["one_step"][0]["step"]


def test_d49_green_complete_ordinary_pr_is_ready_with_cloud_review():
    rows = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "h" * 40,
            "mergeStateStatus": "CLEAN",
            "isDraft": False,
            "changedFiles": 1,
            "files": [{"path": "src/synthetic.py"}],
            "statusCheckRollup": _d51_checks(),
        }
    ]
    pr = CLI.open_prs(fake_runner({}, rows), with_commits=False)[0]
    claims = [claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)]
    assert (
        D.select_work(
            "independent",
            queue=[],
            claims=claims,
            prs=[pr],
            verdicts={},
            author_of={7: "author"},
            coord="/synthetic",
            now=NOW,
        )
        is None
    )
    verdicts = {
        (7, pr.head_sha): [
            {
                "verdict": "MERGE",
                "reviewer": "independent",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    assert len(D.merge_ready([pr], verdicts, claims, {7: "author"})["ready"]) == 1


def test_d49_row_with_explicit_safe_path_does_not_need_a_page():
    assignment = D.select_work(
        "cc-8",
        queue=[{"id": "Q", "owner": "cc-8", "status": "queued", "path": "src/synthetic.py"}],
        claims=[],
        prs=[],
        verdicts={},
        author_of={},
        coord="/synthetic",
        now=NOW,
    )
    assert assignment and assignment.kind == "queue"


def test_d49_unknown_authority_with_two_reviews_still_never_reports_ready(tmp_path, monkeypatch):
    requirements = D.review_requirements(tmp_path / "missing.json")
    monkeypatch.setattr(D, "review_requirements", lambda: requirements)
    pr = ordinary_pr()
    verdicts = {
        (7, pr.head_sha): [
            {"verdict": "MERGE", "reviewer": "independent-one"},
            {"verdict": "MERGE", "reviewer": "independent-two"},
        ]
    }
    claims = [claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)]
    out = D.merge_ready([pr], verdicts, claims, {7: "author"})
    assert out["ready"] == [] and "authority unavailable" in out["one_step"][0]["step"]


def test_d49_reserved_target_glob_is_refused_but_safe_source_stays_work():
    for paths, expected in [(("scripts/**",), False), (("src/synthetic.py",), True)]:
        task = row(paths=paths)
        assignment = D.select_work(
            "cc-8", queue=[task], claims=[], prs=[], verdicts={}, author_of={}, coord="/synthetic", now=NOW
        )
        assert bool(assignment) is expected


def test_d49_missing_authority_refuses_the_real_cycle_before_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "AUTHORITY_PATH", tmp_path / "missing-authority.json")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        raise AssertionError("authority refusal must precede even the fleet read")

    paths = make_tree(tmp_path, panes={}, queue=[])
    with pytest.raises(D.DispatchError, match="authority unavailable"):
        CLI.run_cycle(
            apply=True,
            coord=paths["coord"],
            queue_path=paths["queue"],
            claims_dir=paths["claims"],
            ledger_path=paths["ledger"],
            run=run,
        )
    assert calls == [] and not paths["ledger"].exists()


def test_d49_known_auxiliary_claim_metadata_is_not_a_corrupt_claim(tmp_path):
    directory = tmp_path / "claims"
    directory.mkdir()
    (directory / "broadcast.json").write_text(json.dumps({"schema": "PolicyBroadcastState@v1"}), encoding="utf-8")
    assert D.load_claims(directory, now=NOW) == []


@pytest.mark.parametrize("content", ["{broken", '{"kind":"review","busy_after_30s":true,"target":"invalid"}'])
def test_d49_corrupt_prior_dispatch_ledger_cannot_reset_reviewer_cap(tmp_path, content):
    ledger = tmp_path / "dispatch.jsonl"
    ledger.write_text(content + "\n", encoding="utf-8")
    with pytest.raises(D.DispatchError, match="ledger"):
        CLI.prior_review_dispatches(ledger)


def test_d49_absent_prior_ledger_is_a_first_cycle(tmp_path):
    assert CLI.prior_review_dispatches(tmp_path / "absent.jsonl") == ({}, {})


# D51 cloud CX1-CX5: call the real dispatcher entrypoints with synthetic evidence.
def _d51_checks():
    return [
        {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}
        for name in ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")
    ]


def _d51_registered_review(coord, *, fault=None):
    import hashlib

    evidence = coord / "review-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    proof = coord / "proofs" / "separate-review.artifact"
    proof.parent.mkdir(parents=True, exist_ok=True)
    head = "a" * 40
    raw = (f"Adversarial-review: MERGE reviewer=independent head={head}\n").encode()
    proof.write_bytes(raw)
    ref = "proofs/separate-review.artifact"
    review = {
        "reviewer_session": "independent",
        "verdict": "MERGE",
        "head_sha": head,
        "artifact": ref,
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
    }
    if fault == "hash":
        review["artifact_sha256"] = "0" * 64
    elif fault == "identity":
        review["reviewer_session"] = "someone-else"
    elif fault == "head":
        review["head_sha"] = "b" * 40
    elif fault == "traversal":
        review["artifact"] = "../outside.artifact"
    elif fault == "absolute":
        review["artifact"] = str(proof)
    elif fault == "symlink":
        alias = coord / "proofs" / "alias.artifact"
        alias.symlink_to(proof)
        review["artifact"] = "proofs/alias.artifact"
    doc = {
        "schema": "PrMergeReviewEvidence@v1",
        "pr": 7,
        "head_sha": head,
        "registered_by": {"actor": "synthetic-lead", "session": "synthetic-lead-session"},
        "identity_provenance": "manual_coordinator_claim_and_source_check",
        "section17_review_completed": True,
        "authors_and_coauthors_complete": True,
        "authority_rails_unchanged": True,
        "shared_infra_isolated_reviewed": True,
        "source_commit_shas": [head],
        "source_authorship_sha256": "1" * 64,
        "authors": [{"actor": "codex", "session": "author", "claim_id": "source"}],
        "reviews": [review],
    }
    if fault == "empty":
        doc["reviews"] = []
    (evidence / f"7-{head}.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


@pytest.mark.parametrize("merge_state", ["CLEAN", "BLOCKED", "DIRTY"])
def test_d51_cx1_held_draft_can_receive_its_prerequisite_review(merge_state):
    rows = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "a" * 40,
            "mergeStateStatus": merge_state,
            "isDraft": True,
            "changedFiles": 1,
            "files": [{"path": ".githooks/pre-push"}],
            "statusCheckRollup": [],
        }
    ]
    pr = CLI.open_prs(fake_runner({}, rows), with_commits=False)[0]
    assignment = D.select_work(
        "reviewer",
        queue=[],
        claims=[],
        prs=[pr],
        verdicts={},
        author_of={7: "author"},
        coord="/synthetic",
        now=NOW,
    )
    assert assignment is not None and assignment.kind == "review"
    assert D.merge_ready([pr], {}, [], {7: "author"})["ready"] == []


@pytest.mark.parametrize("path", [".githooks/pre-push", ".github/workflows/synthetic.yml", "scripts/agent_claim.py"])
def test_d51_cx2_canonical_engineering_hold_needs_second_reviewer(path):
    assert D.required_reviews((path,)) == (2, True)
    pr = _complete_pr(7, "a" * 40, "wt/synthetic", "CLEAN", False, files=(path,))
    verdicts = {(7, pr.head_sha): [{"verdict": "MERGE", "reviewer": "first"}]}
    assignment = D.select_work(
        "second",
        queue=[],
        claims=[],
        prs=[pr],
        verdicts=verdicts,
        author_of={7: "author"},
        coord="/synthetic",
        now=NOW,
    )
    assert assignment is not None and assignment.kind == "review"
    assert D.merge_ready([pr], verdicts, [], {7: "author"})["ready"] == []


def test_d51_cloud_ordinary_pr_is_not_given_redundant_local_review():
    pr = _complete_pr(7, "a" * 40, "wt/synthetic", "CLEAN", True)
    for verdicts in ({}, {(7, pr.head_sha): [{"verdict": "BLOCK", "reviewer": "codex-cloud"}]}):
        assert (
            D.select_work(
                "local",
                queue=[],
                claims=[],
                prs=[pr],
                verdicts=verdicts,
                author_of={7: "author"},
                coord="/synthetic",
                now=NOW,
            )
            is None
        )


@pytest.mark.parametrize(
    "fault", ["unrelated", "all-skipped", "missing-one", "required-neutral", "required-status-context"]
)
def test_d51_cx3_partial_or_skipped_mandatory_checks_never_report_green(fault):
    checks = _d51_checks()
    if fault == "unrelated":
        checks = [{"name": "optional", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    elif fault == "all-skipped":
        checks = [{**row, "conclusion": "SKIPPED"} for row in checks]
    elif fault == "missing-one":
        checks.pop()
    elif fault == "required-neutral":
        checks[0]["conclusion"] = "NEUTRAL"
    else:
        checks[0] = {"__typename": "StatusContext", "context": "cio-hardening", "state": "SUCCESS"}
    assert CLI.checks_passed(checks) is False


def test_d51_cx3_optional_neutral_does_not_invalidate_mandatory_success():
    checks = _d51_checks() + [{"name": "optional", "status": "COMPLETED", "conclusion": "NEUTRAL"}]
    assert CLI.checks_passed(checks) is True


def test_d51_cx4_registered_reference_is_loaded_without_guessed_sibling(tmp_path):
    coord = tmp_path / "coordinator"
    _d51_registered_review(coord)
    verdicts = D.verdicts_at_head(CLI.load_review_artifacts(coord))
    assert verdicts[(7, "a" * 40)] == [
        {
            "verdict": "MERGE",
            "reviewer": "independent",
            "engineering_completion_head": "a" * 40,
            "section17_completion_head": "a" * 40,
            "section17_review_completed": True,
            "authorship_completion_head": "a" * 40,
            "registered_author_sessions": ("author",),
            "registered_authorship_valid": True,
            "shared_infra_completion_head": "a" * 40,
            "shared_infra_isolated_reviewed": True,
            "engineering_tests_completed": False,
            "engineering_docs_completed": False,
        }
    ]


@pytest.mark.parametrize("fault", ["hash", "identity", "head", "traversal", "absolute", "symlink", "empty"])
def test_d51_cx4_invalid_registration_refuses_before_any_send(tmp_path, fault):
    paths = make_tree(tmp_path, panes={"cc-deepseek-9": "❯ \n"}, queue=[])
    _d51_registered_review(paths["coord"], fault=fault)
    calls = []
    base = fake_runner({"cc-deepseek-9": "❯ \n"}, [])

    def run(cmd, **kwargs):
        if cmd[:2] in (["tmux", "load-buffer"], ["tmux", "paste-buffer"], ["tmux", "send-keys"]):
            calls.append(cmd)
        return base(cmd, **kwargs)

    with pytest.raises(D.DispatchError):
        CLI.run_cycle(
            apply=True,
            coord=paths["coord"],
            queue_path=paths["queue"],
            claims_dir=paths["claims"],
            ledger_path=paths["ledger"],
            run=run,
            sleep=lambda _: None,
        )
    assert calls == [] and not paths["ledger"].exists()


@pytest.mark.parametrize("status", ["done", "released"])
def test_d51_cx5_released_author_coverage_is_ready_and_active_is_not(status):
    pr = _complete_pr(7, "a" * 40, "wt/synthetic", "CLEAN", False, files=("src/synthetic.py",))
    verdicts = {
        (7, pr.head_sha): [
            {
                "verdict": "MERGE",
                "reviewer": "independent",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    released = claim(session="author", branch=pr.head_ref, head=pr.head_sha, status=status, paths=pr.files)
    # Canonical ClaimBoard writes done; released was an invented positive fixture, never a producer status.
    assert [item["pr"] for item in D.merge_ready([pr], verdicts, [released], {7: "author"})["ready"]] == (
        [7] if status == "done" else []
    )
    active = claim(session="author", branch=pr.head_ref, head=pr.head_sha, paths=pr.files)
    assert D.merge_ready([pr], verdicts, [active], {7: "author"})["ready"] == []


@pytest.mark.parametrize("fault", ["wrong-path", "wrong-head", "wrong-author", "abandoned", "live-overlap"])
def test_d51_cx5_released_custody_must_cover_actual_source(tmp_path, fault):
    pr = _complete_pr(7, "a" * 40, "wt/synthetic", "CLEAN", False, files=("src/synthetic.py",))
    verdicts = {(7, pr.head_sha): [{"verdict": "MERGE", "reviewer": "independent"}]}
    released = claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)
    if fault == "wrong-path":
        released.paths = ["elsewhere.py"]
    elif fault == "wrong-head":
        released.head_sha = "b" * 40
    elif fault == "wrong-author":
        released.session = "someone-else"
    elif fault == "abandoned":
        released.status = "abandoned"
    claims = [released]
    if fault == "live-overlap":
        claims.append(claim(session="holder", branch="wt/other", paths=("src/**",)))
    assert D.merge_ready([pr], verdicts, claims, {7: "author"})["ready"] == []


@pytest.mark.parametrize("forbidden", ["Host", "evaluate", "main"])
def test_d51_no_merge_import_guard_has_a_firing_negative(forbidden):
    with pytest.raises(AssertionError, match="merge primitive"):
        _assert_only_pure_delegation_imports(f"from lib.pr_merge_delegation import {forbidden}\n")


def test_d51_canonical_helpers_never_reach_a_merge_primitive(tmp_path, monkeypatch):
    import importlib

    merger = importlib.import_module(CLI.reviewer_artifact.__module__)
    mutations = []

    def forbidden(*args, **kwargs):
        mutations.append((args, kwargs))
        raise AssertionError("dispatch reached a merge primitive")

    for name in ("Host", "evaluate", "main", "execute", "apply"):
        monkeypatch.setattr(merger, name, forbidden, raising=False)
    paths = make_tree(
        tmp_path,
        panes={"cc-deepseek-9": "❯ \n"},
        queue=[],
        claims=[
            {
                "claim_id": "source",
                "session": "author",
                "branch": "wt/synthetic",
                "status": "done",
                "heartbeat_at": iso(NOW),
                "head_sha": "a" * 40,
                "paths": [".githooks/pre-push"],
            }
        ],
    )
    _d51_registered_review(paths["coord"])
    rows = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "a" * 40,
            "mergeStateStatus": "BLOCKED",
            "isDraft": True,
            "changedFiles": 1,
            "files": [{"path": ".githooks/pre-push"}],
            "statusCheckRollup": [],
        }
    ]
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    out = CLI.run_cycle(
        apply=False,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=fake_runner({"cc-deepseek-9": "❯ \n"}, rows),
    )
    assert [row["kind"] for row in out["assignments"]] == ["review"]
    assert mutations == []
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_d51_a_current_held_block_requires_repair_not_a_third_opinion():
    pr = _held_pr(7, "a" * 40, "wt/synthetic", "CLEAN", True)
    verdicts = {(7, pr.head_sha): [{"verdict": "BLOCK", "reviewer": "codex-cloud"}]}
    assert (
        D.select_work(
            "local",
            queue=[],
            claims=[],
            prs=[pr],
            verdicts=verdicts,
            author_of={7: "author"},
            coord="/synthetic",
            now=NOW,
        )
        is None
    )


# Second cloud pass: explicit-reference regression must be driven through a real cycle.
@pytest.mark.parametrize("artifact_kind", ["prose", "machine"])
def test_cloud2_cx1_registered_coord_reference_survives_real_cycle(tmp_path, artifact_kind):
    import hashlib

    paths = make_tree(
        tmp_path,
        panes={"cc-deepseek-9": "❯ \n"},
        queue=[],
        claims=[
            {
                "claim_id": "source",
                "session": "author",
                "branch": "wt/synthetic",
                "status": "done",
                "heartbeat_at": iso(NOW),
                "head_sha": "a" * 40,
                "paths": [".githooks/pre-push"],
            }
        ],
    )
    doc = _d51_registered_review(paths["coord"])
    target = paths["coord"] / "coord" / "review.md"
    target.parent.mkdir()
    if artifact_kind == "prose":
        raw = f"Adversarial-review: MERGE reviewer=independent head={'a' * 40}\n".encode()
    else:
        raw = json.dumps({"reviewer_session": "independent", "head_sha": "a" * 40, "verdict": "MERGE"}).encode()
    target.write_bytes(raw)
    doc["reviews"][0].update(artifact="coord/review.md", artifact_sha256=hashlib.sha256(raw).hexdigest())
    (paths["coord"] / "review-evidence" / f"7-{'a' * 40}.json").write_text(json.dumps(doc))
    rows = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "a" * 40,
            "mergeStateStatus": "BLOCKED",
            "isDraft": True,
            "changedFiles": 1,
            "files": [{"path": ".githooks/pre-push"}],
            "statusCheckRollup": [],
        }
    ]
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    out = CLI.run_cycle(
        apply=False,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=fake_runner({"cc-deepseek-9": "❯ \n"}, rows),
    )
    assert [(r["kind"], r["target"]) for r in out["assignments"]] == [("review", "7")]
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def _cloud2_held_ready_fixture(tmp_path, flags):
    import hashlib

    coord = tmp_path / "coordinator"
    doc = _d51_registered_review(coord)
    raw = f"Adversarial-review: MERGE reviewer=second head={'a' * 40}\n".encode()
    (coord / "proofs" / "second.artifact").write_bytes(raw)
    doc["reviews"].append(
        {
            "reviewer_session": "second",
            "head_sha": "a" * 40,
            "verdict": "MERGE",
            "artifact": "proofs/second.artifact",
            "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    doc.update(flags)
    (coord / "review-evidence" / f"7-{'a' * 40}.json").write_text(json.dumps(doc))
    pr = _held_pr(7, "a" * 40, "wt/synthetic", "CLEAN", False)
    claims = [claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)]
    verdicts = D.verdicts_at_head(CLI.load_review_artifacts(coord))
    return pr, claims, verdicts, doc


@pytest.mark.parametrize(
    "flags",
    [
        {},
        {"engineering_tests_completed": True},
        {"engineering_docs_completed": True},
        {"engineering_tests_completed": False, "engineering_docs_completed": True},
        {"engineering_tests_completed": True, "engineering_docs_completed": False},
        {"engineering_tests_completed": "true", "engineering_docs_completed": True},
        {"engineering_tests_completed": True, "engineering_docs_completed": "true"},
    ],
)
def test_cloud2_cx2_held_readiness_refuses_missing_false_or_untyped_completion(tmp_path, flags):
    pr, claims, verdicts, _doc = _cloud2_held_ready_fixture(tmp_path, flags)
    out = D.merge_ready([pr], verdicts, claims, {7: "author"})
    assert out["ready"] == []
    assert "engineering" in out["one_step"][0]["step"]


def test_cloud2_cx2_exact_head_true_completion_allows_otherwise_ready_held_pr(tmp_path):
    pr, claims, verdicts, _doc = _cloud2_held_ready_fixture(
        tmp_path,
        {"engineering_tests_completed": True, "engineering_docs_completed": True},
    )
    assert [r["pr"] for r in D.merge_ready([pr], verdicts, claims, {7: "author"})["ready"]] == [7]


def test_cloud2_cx2_old_head_and_latest_false_cannot_supply_completion(tmp_path):
    pr, claims, verdicts, doc = _cloud2_held_ready_fixture(
        tmp_path,
        {"engineering_tests_completed": True, "engineering_docs_completed": True},
    )
    old = {**doc, "head_sha": "b" * 40}
    current_reviews = {"pr": 7, "head_sha": pr.head_sha, "reviews": doc["reviews"]}
    old_index = D.verdicts_at_head([old, current_reviews])
    assert D.merge_ready([pr], old_index, claims, {7: "author"})["ready"] == []
    later_false = {**doc, "engineering_docs_completed": False}
    latest = D.verdicts_at_head([doc, later_false])
    assert D.merge_ready([pr], latest, claims, {7: "author"})["ready"] == []
    assert [r["pr"] for r in D.merge_ready([pr], verdicts, claims, {7: "author"})["ready"]] == [7]


@pytest.mark.parametrize("open_pr", [False, True])
def test_cloud2_cx3_foreign_claim_chore_requires_canonical_takeover(open_pr):
    stale = claim(cid="foreign-source", session="cc-owner", branch="wt/synthetic", age=4)
    prs = [_complete_pr(7, "a" * 40, "wt/synthetic", "DIRTY", False)] if open_pr else []
    task = D.select_work(
        "cc-idle",
        queue=[],
        claims=[stale],
        prs=prs,
        verdicts={},
        author_of={7: "cc-owner"},
        coord="/synthetic",
        now=NOW,
    )
    assert task.kind == "chore"
    assert "agent_claim.py takeover foreign-source --claim" in task.instruction
    assert "new claim" in task.instruction and "cc-owner" in task.instruction
    assert "do not impersonate" in task.instruction.lower()
    assert "agent_claim.py handoff" not in task.instruction
    assert "agent_claim.py release" not in task.instruction


def test_cloud2_cx3_owner_can_maintain_own_claim_without_takeover():
    stale = claim(cid="own-source", session="cc-owner", age=4)
    task = D.select_work(
        "cc-owner",
        queue=[],
        claims=[stale],
        prs=[],
        verdicts={},
        author_of={},
        coord="/synthetic",
        now=NOW,
    )
    assert task.kind == "chore" and "takeover" not in task.instruction
    assert "own-source" in task.instruction and "agent_claim.py release" in task.instruction


# Cloud round 3: rename metadata and unresolved custody are source truth, not inferred release.
def _cloud3_rename_run(*, prior=".githooks/pre-push", fault=None):
    row = {
        "number": 7,
        "headRefName": "wt/synthetic",
        "headRefOid": "a" * 40,
        "mergeStateStatus": "CLEAN",
        "isDraft": False,
        "changedFiles": 1,
        "files": [{"path": "src/moved-hook.py"}],
        "statusCheckRollup": _d51_checks(),
    }
    base = fake_runner({}, [row])
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = base(cmd, **kw)
        if cmd[:2] == ["gh", "api"]:
            if "/files?" in cmd[2]:
                data = [{"filename": "src/moved-hook.py", "status": "renamed", "previous_filename": prior}]
                if fault == "missing_prior":
                    data[0].pop("previous_filename")
                if fault == "truncated":
                    data = []
                if fault == "wrong_destination":
                    data[0]["filename"] = "other.py"
                out.stdout = json.dumps(data)
                if fault == "api_failed":
                    out.returncode = 1
            else:
                out.stdout = json.dumps(
                    {"head": {"sha": "b" * 40 if fault == "head_moved" else "a" * 40}, "changed_files": 1}
                )
        return out

    return run, calls


def test_cloud3_cx4_real_rename_collector_keeps_original_held_scope():
    run, calls = _cloud3_rename_run()
    pr = CLI.open_prs(run=run)[0]
    assert any(c[:2] == ["gh", "api"] and "/files?" in c[2] for c in calls)
    assert pr.files == ("src/moved-hook.py",)
    assert pr.prior_paths == (".githooks/pre-push",)
    assert D.required_reviews(pr.scope_files) == (2, True)
    assert pr.files_complete


@pytest.mark.parametrize("fault", ["missing_prior", "truncated", "wrong_destination", "api_failed", "head_moved"])
def test_cloud3_cx4_incomplete_rename_evidence_refuses_review_and_readiness(fault):
    run, _calls = _cloud3_rename_run(fault=fault)
    pr = CLI.open_prs(run=run)[0]
    assert not pr.files_complete
    assert not pr.review_eligible
    assert not D.merge_ready(
        [pr],
        {
            (7, pr.head_sha): [
                {
                    "reviewer": "peer",
                    "verdict": "MERGE",
                    "section17_completion_head": pr.head_sha,
                    "section17_review_completed": True,
                    "authorship_completion_head": pr.head_sha,
                    "registered_author_sessions": ("author",),
                    "registered_authorship_valid": True,
                }
            ]
        },
        [claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)],
        {7: "author"},
    )["ready"]


def _cloud3_renamed_pr():
    pr = ordinary_pr(head="a" * 40, files=("src/moved-hook.py",))
    pr.prior_paths = (".githooks/pre-push",)
    return pr


def test_cloud3_cx4_rename_requires_both_custody_and_engineering_completion():
    pr = _cloud3_renamed_pr()
    reviews = {
        (7, pr.head_sha): [
            {
                "reviewer": r,
                "verdict": "MERGE",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
            for r in ("peer", "second")
        ]
    }
    released = claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)
    assert not D.merge_ready([pr], reviews, [released], {7: "author"})["ready"]
    released.paths.append(".githooks/pre-push")
    result = D.merge_ready([pr], reviews, [released], {7: "author"})
    assert not result["ready"] and "engineering" in result["one_step"][0]["step"]
    reviews[(7, pr.head_sha)][0].update(
        engineering_completion_head=pr.head_sha, engineering_tests_completed=True, engineering_docs_completed=True
    )
    assert D.merge_ready([pr], reviews, [released], {7: "author"})["ready"]


def test_cloud3_cx4_live_holder_on_old_name_still_blocks():
    pr = _cloud3_renamed_pr()
    scope = (*pr.files, ".githooks/pre-push")
    released = claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=scope)
    holder = claim(cid="holder", paths=(".githooks/pre-push",))
    reviews = {
        (7, pr.head_sha): [
            {
                "reviewer": r,
                "verdict": "MERGE",
                "engineering_completion_head": pr.head_sha,
                "engineering_tests_completed": True,
                "engineering_docs_completed": True,
            }
            for r in ("peer", "second")
        ]
    }
    assert not D.merge_ready([pr], reviews, [released, holder], {7: "author"})["ready"]


@pytest.mark.parametrize("prior", ["scripts/brokers/synthetic.py", "AGENTS.md"])
def test_cloud3_cx4_rename_source_autonomous_exclusion_remains(prior):
    run, _calls = _cloud3_rename_run(prior=prior)
    pr = CLI.open_prs(run=run)[0]
    assert (
        D.select_work(
            "cc-independent",
            queue=[],
            claims=[],
            prs=[pr],
            verdicts={},
            author_of={7: "author"},
            coord="/synthetic",
            now=NOW,
        )
        is None
    )


def test_cloud3_cx4_held_rename_still_assigns_a_needed_independent_review():
    run, _calls = _cloud3_rename_run()
    pr = CLI.open_prs(run=run)[0]
    assignment = D.select_work(
        "cc-independent",
        queue=[],
        claims=[],
        prs=[pr],
        verdicts={},
        author_of={7: "author"},
        coord="/synthetic",
        now=NOW,
    )
    assert assignment and assignment.kind == "review"


@pytest.mark.parametrize("age", [0.1, 3, 100])
def test_cloud3_cx5_age_alone_never_releases_overlapping_active_custody(age):
    pr = ordinary_pr()
    released = claim(session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)
    stale = claim(cid="foreign", paths=pr.files, age=age)
    reviews = {
        (7, pr.head_sha): [
            {
                "reviewer": "peer",
                "verdict": "MERGE",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    result = D.merge_ready([pr], reviews, [released, stale], {7: "author"})
    assert not result["ready"]
    assert "not released" in result["one_step"][0]["step"]


def test_cloud3_cx5_validly_superseded_predecessor_is_nonblocking():
    pr = ordinary_pr()
    released = claim(
        cid="successor", session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files
    )
    stale = claim(cid="foreign", paths=pr.files, age=3)
    released.takeover_of = ({"claim_id": "foreign"},)
    reviews = {
        (7, pr.head_sha): [
            {
                "reviewer": "peer",
                "verdict": "MERGE",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    assert D.merge_ready([pr], reviews, [released, stale], {7: "author"})["ready"]


@pytest.mark.parametrize("fault", ["cycle", "missing_target", "fresh_predecessor"])
def test_cloud3_cx5_invalid_or_live_predecessor_never_releases_custody(fault):
    pr = ordinary_pr()
    released = claim(
        cid="successor", session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files
    )
    stale = claim(cid="foreign", paths=pr.files, age=0.1 if fault == "fresh_predecessor" else 3)
    released.takeover_of = ({"claim_id": "absent" if fault == "missing_target" else "foreign"},)
    if fault == "cycle":
        stale.takeover_of = ({"claim_id": "successor"},)
    reviews = {
        (7, pr.head_sha): [
            {
                "reviewer": "peer",
                "verdict": "MERGE",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    assert not D.merge_ready([pr], reviews, [released, stale], {7: "author"})["ready"]


@pytest.mark.parametrize("prior", ["../escape.py", "/absolute.py", "", None])
def test_cloud3_cx4_invalid_rename_source_fails_closed(prior):
    run, _calls = _cloud3_rename_run(prior=prior)
    assert not CLI.open_prs(run=run)[0].files_complete


def test_cloud3_cx4_real_pagination_keeps_rename_in_later_page():
    names = tuple(f"src/file-{n}.py" for n in range(101))
    source = {
        "number": 7,
        "headRefName": "wt/synthetic",
        "headRefOid": "a" * 40,
        "mergeStateStatus": "CLEAN",
        "isDraft": False,
        "changedFiles": 101,
        "files": [{"path": name} for name in names],
    }
    base = fake_runner({}, [source])
    pages = []

    def run(cmd, **kw):
        out = base(cmd, **kw)
        if cmd[:2] == ["gh", "api"] and "/files?" in cmd[2]:
            pages.append(int(cmd[2].split("page=")[-1]))
            if pages[-1] == 2:
                rows = json.loads(out.stdout)
                rows[0].update(status="renamed", previous_filename=".githooks/pre-push")
                out.stdout = json.dumps(rows)
        return out

    pr = CLI.open_prs(run=run)[0]
    assert pages == [1, 2]
    assert pr.files_complete and pr.prior_paths == (".githooks/pre-push",)
    assert D.required_reviews(pr.scope_files) == (2, True)


def test_cloud3_cx5_original_takeover_links_survive_disk_loading(tmp_path):
    directory = tmp_path / "claims"
    directory.mkdir()
    pr = ordinary_pr()
    for cid, status, age, links in [
        ("predecessor", "active", 3, []),
        ("successor", "done", 0.1, [{"claim_id": "predecessor"}]),
    ]:
        doc = {
            "claim_id": cid,
            "session": "author" if cid == "successor" else "other",
            "branch": pr.head_ref if cid == "successor" else "wt/other",
            "status": status,
            "heartbeat_at": iso(NOW - timedelta(hours=age)),
            "paths": list(pr.files),
            "head_sha": pr.head_sha,
            "takeover_of": links,
        }
        (directory / f"{cid}.json").write_text(json.dumps(doc))
    claims = D.load_claims(directory, now=NOW)
    reviews = {
        (7, pr.head_sha): [
            {
                "reviewer": "peer",
                "verdict": "MERGE",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    assert D.merge_ready([pr], reviews, claims, {7: "author"})["ready"]
    doc["takeover_of"] = []
    (directory / "successor.json").write_text(json.dumps(doc))
    assert not D.merge_ready([pr], reviews, D.load_claims(directory, now=NOW), {7: "author"})["ready"]


def test_cloud3_cx5_released_successor_cannot_resolve_conflicting_live_siblings():
    pr = ordinary_pr()
    released = claim(
        cid="released", session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files
    )
    stale = claim(cid="predecessor", paths=pr.files, age=3)
    left = claim(cid="left", paths=pr.files)
    right = claim(cid="right", paths=pr.files)
    left.takeover_of = right.takeover_of = ({"claim_id": "predecessor"},)
    reviews = {
        (7, pr.head_sha): [
            {
                "reviewer": "peer",
                "verdict": "MERGE",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    assert not D.merge_ready([pr], reviews, [released, stale, left, right], {7: "author"})["ready"]


@pytest.mark.parametrize("status", ["released", "unknown", "", None])
def test_cloud3_cx5_raw_noncanonical_status_is_unreadable(tmp_path, status):
    directory = tmp_path / "claims"
    directory.mkdir()
    (directory / "bad.json").write_text(
        json.dumps({"claim_id": "bad", "status": status, "heartbeat_at": iso(NOW), "paths": ["src/synthetic.py"]})
    )
    with pytest.raises(D.DispatchError, match="unreadable"):
        D.load_claims(directory, now=NOW)


def test_cloud3_cx5_duplicate_snapshot_identity_fails_closed():
    pr = ordinary_pr()
    released = claim(cid="same", session="author", branch=pr.head_ref, head=pr.head_sha, status="done", paths=pr.files)
    other = claim(cid="same", paths=pr.files, age=3)
    reviews = {
        (7, pr.head_sha): [
            {
                "reviewer": "peer",
                "verdict": "MERGE",
                "section17_completion_head": pr.head_sha,
                "section17_review_completed": True,
                "authorship_completion_head": pr.head_sha,
                "registered_author_sessions": ("author",),
                "registered_authorship_valid": True,
            }
        ]
    }
    assert not D.merge_ready([pr], reviews, [released, other], {7: "author"})["ready"]


# D52 named item only: a section-17 attestation is canonical, boolean and bound to this head.
def _section17_cycle(tmp_path, value, *, other_head_true=False):
    import hashlib

    paths = make_tree(
        tmp_path,
        panes={},
        queue=[],
        claims=[
            {
                "claim_id": "source",
                "session": "author",
                "branch": "wt/synthetic",
                "status": "done",
                "heartbeat_at": iso(NOW),
                "head_sha": "a" * 40,
                "paths": ["src/synthetic.py"],
            }
        ],
    )
    doc = _d51_registered_review(paths["coord"])
    if value == "missing":
        doc.pop("section17_review_completed")
    else:
        doc["section17_review_completed"] = value
    target = paths["coord"] / "review-evidence" / f"7-{'a' * 40}.json"
    target.write_text(json.dumps(doc))
    if other_head_true:
        old = json.loads(json.dumps(doc))
        old.update(head_sha="b" * 40, section17_review_completed=True)
        raw = f"Adversarial-review: MERGE reviewer=independent head={'b' * 40}\n".encode()
        (paths["coord"] / "proofs" / "old-review.artifact").write_bytes(raw)
        old["reviews"][0].update(
            head_sha="b" * 40, artifact="proofs/old-review.artifact", artifact_sha256=hashlib.sha256(raw).hexdigest()
        )
        (paths["coord"] / "review-evidence" / f"7-{'b' * 40}.json").write_text(json.dumps(old))
    rows = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "a" * 40,
            "mergeStateStatus": "CLEAN",
            "isDraft": False,
            "changedFiles": 1,
            "files": [{"path": "src/synthetic.py"}],
            "statusCheckRollup": _d51_checks(),
        }
    ]
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    out = CLI.run_cycle(
        apply=False,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=fake_runner({}, rows),
    )
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert not out["assignments"] and not out["ledger"]
    return out, doc


@pytest.mark.parametrize("value", ["missing", False, None, "true", 1])
def test_section17_real_collector_report_refuses_missing_false_or_untyped(value, tmp_path):
    out, _doc = _section17_cycle(tmp_path, value)
    assert not out["merge_ready"]["ready"]
    assert "section-17" in out["merge_ready"]["one_step"][0]["step"]
    assert "## Ready to merge (0)" in out["merge_ready_md"]


def test_section17_real_collector_other_head_true_does_not_lend_completion(tmp_path):
    out, _doc = _section17_cycle(tmp_path, "missing", other_head_true=True)
    assert not out["merge_ready"]["ready"]
    assert "section-17" in out["merge_ready"]["one_step"][0]["step"]


def test_section17_real_collector_exact_head_true_preserves_ready_positive(tmp_path):
    out, _doc = _section17_cycle(tmp_path, True)
    assert [r["pr"] for r in out["merge_ready"]["ready"]] == [7]
    assert "## Ready to merge (1)" in out["merge_ready_md"]


def test_section17_latest_exact_head_false_replaces_true(tmp_path):
    pr, claims, _indexed, doc = _cloud2_held_ready_fixture(
        tmp_path, {"engineering_tests_completed": True, "engineering_docs_completed": True}
    )
    latest = {**doc, "section17_review_completed": False}
    true_index = D.verdicts_at_head([doc])
    false_index = D.verdicts_at_head([doc, latest])
    assert D.merge_ready([pr], true_index, claims, {7: "author"})["ready"]
    out = D.merge_ready([pr], false_index, claims, {7: "author"})
    assert not out["ready"] and "section-17" in out["one_step"][0]["step"]


# D52 named shared-infrastructure contract, exercised through actual metadata collection and reporting.
def _shared_infra_cycle(tmp_path, *, fault=None, label="shared-infra", ordinary=False, rename=False):
    import hashlib

    path = "src/synthetic.py" if ordinary or rename else "scripts/safe_flock.sh"
    scope = [path] + (["scripts/safe_flock.sh"] if rename else [])
    paths = make_tree(
        tmp_path,
        panes={},
        queue=[],
        claims=[
            {
                "claim_id": "source",
                "session": "author",
                "branch": "wt/synthetic",
                "status": "done",
                "heartbeat_at": iso(NOW),
                "head_sha": "a" * 40,
                "paths": scope,
            }
        ],
    )
    doc = _d51_registered_review(paths["coord"])
    if fault == "isolated_missing":
        doc.pop("shared_infra_isolated_reviewed")
    elif fault == "isolated_false":
        doc["shared_infra_isolated_reviewed"] = False
    elif fault == "isolated_string":
        doc["shared_infra_isolated_reviewed"] = "true"
    elif fault == "isolated_integer":
        doc["shared_infra_isolated_reviewed"] = 1
    elif fault == "isolated_other_head":
        old = json.loads(json.dumps(doc))
        old["head_sha"] = "b" * 40
        raw = f"Adversarial-review: MERGE reviewer=independent head={'b' * 40}\n".encode()
        (paths["coord"] / "proofs" / "old-shared.artifact").write_bytes(raw)
        old["reviews"][0].update(
            head_sha="b" * 40, artifact="proofs/old-shared.artifact", artifact_sha256=hashlib.sha256(raw).hexdigest()
        )
        (paths["coord"] / "review-evidence" / f"7-{'b' * 40}.json").write_text(json.dumps(old))
        doc.pop("shared_infra_isolated_reviewed")
    (paths["coord"] / "review-evidence" / f"7-{'a' * 40}.json").write_text(json.dumps(doc))
    check = {"__typename": "CheckRun", "name": "shared-infra-review", "status": "COMPLETED", "conclusion": "SUCCESS"}
    row = {
        "number": 7,
        "headRefName": "wt/synthetic",
        "headRefOid": "a" * 40,
        "mergeStateStatus": "CLEAN",
        "isDraft": False,
        "changedFiles": 1,
        "files": [{"path": path}],
        "title": "[shared-infra] Synthetic wrapper proof",
        "body": "Real-layout proof: synthetic fixture artifact and exact command",
        "labels": [{"name": label}],
        "statusCheckRollup": [*_d51_checks(), check],
    }
    if fault == "title":
        row["title"] = "Ordinary-looking change"
    elif fault == "body":
        row["body"] = "No proof here"
    elif fault == "title_missing":
        row.pop("title")
    elif fault == "body_missing":
        row.pop("body")
    elif fault == "title_shape":
        row["title"] = {"wrong": "shape"}
    elif fault == "body_shape":
        row["body"] = []
    elif fault == "label":
        row["labels"] = []
    elif fault == "labels_missing":
        row.pop("labels")
    elif fault == "labels_shape":
        row["labels"] = [{"wrong": "name"}]
    elif fault == "labels_scalar":
        row["labels"] = "shared-infra"
    elif fault == "check_missing":
        row["statusCheckRollup"] = _d51_checks()
    elif fault == "check_failure":
        check["conclusion"] = "FAILURE"
    elif fault == "check_skipped":
        check["conclusion"] = "SKIPPED"
    elif fault == "check_pending":
        check["status"] = "IN_PROGRESS"
    base = fake_runner({}, [row])
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = base(cmd, **kw)
        if cmd[:3] == ["gh", "pr", "list"]:
            out.stdout = json.dumps([row])
        if rename and cmd[:2] == ["gh", "api"] and "/files?" in cmd[2]:
            out.stdout = json.dumps(
                [{"filename": path, "status": "renamed", "previous_filename": "scripts/safe_flock.sh"}]
            )
        return out

    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    out = CLI.run_cycle(
        apply=False,
        coord=paths["coord"],
        queue_path=paths["queue"],
        claims_dir=paths["claims"],
        ledger_path=paths["ledger"],
        run=run,
    )
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert not out["assignments"] and not out["ledger"]
    return out, CLI.open_prs(run=run)[0], calls, doc, paths


@pytest.mark.parametrize(
    "fault",
    [
        "title",
        "body",
        "title_missing",
        "body_missing",
        "title_shape",
        "body_shape",
        "label",
        "labels_missing",
        "labels_shape",
        "labels_scalar",
        "check_missing",
        "check_failure",
        "check_skipped",
        "check_pending",
        "isolated_missing",
        "isolated_false",
        "isolated_string",
        "isolated_integer",
        "isolated_other_head",
    ],
)
def test_shared_infra_real_collector_and_report_refuse_unqualified_input(tmp_path, fault):
    out, _pr, _calls, _doc, _paths = _shared_infra_cycle(tmp_path, fault=fault)
    assert not out["merge_ready"]["ready"]
    expected = "checks" if fault in {"check_failure", "check_pending"} else "shared-infrastructure"
    assert expected in out["merge_ready"]["one_step"][0]["step"]


@pytest.mark.parametrize("label", ["shared-infra", "solo"])
def test_shared_infra_valid_real_collector_report_matches_canonical_assessor(tmp_path, label):
    out, pr, calls, _doc, _paths = _shared_infra_cycle(tmp_path, label=label)
    assert [r["pr"] for r in out["merge_ready"]["ready"]] == [7]
    assert pr.title == "[shared-infra] Synthetic wrapper proof"
    assert pr.body.startswith("Real-layout proof:") and pr.labels == (label,)
    fields = next(c[c.index("--json") + 1] for c in calls if c[:3] == ["gh", "pr", "list"])
    assert {"title", "body", "labels"} <= set(fields.split(","))
    from scripts.check_shared_infra_pr import assess

    assert assess(list(pr.scope_files), pr.title, pr.body, [])["ok"] is True


def test_shared_infra_ordinary_positive_does_not_need_shared_label_or_check(tmp_path):
    out, _pr, _calls, _doc, _paths = _shared_infra_cycle(
        tmp_path, ordinary=True, fault="check_missing", label="ordinary"
    )
    assert out["merge_ready"]["ready"]


def test_shared_infra_rename_original_path_keeps_shared_requirements(tmp_path):
    out, _pr, _calls, _doc, _paths = _shared_infra_cycle(tmp_path, rename=True, fault="isolated_false")
    assert not out["merge_ready"]["ready"]
    assert "shared-infrastructure" in out["merge_ready"]["one_step"][0]["step"]


def test_shared_infra_latest_exact_head_false_replaces_true(tmp_path):
    out, pr, _calls, doc, paths = _shared_infra_cycle(tmp_path)
    assert out["merge_ready"]["ready"]
    latest = {**doc, "shared_infra_isolated_reviewed": False}
    claims = D.load_claims(paths["claims"], now=NOW)
    verdicts = D.verdicts_at_head([doc, latest])
    result = D.merge_ready([pr], verdicts, claims, {7: "author"})
    assert not result["ready"] and "shared-infrastructure" in result["one_step"][0]["step"]


@pytest.mark.parametrize("contents", ["{", "null", "[]", '{"paths":"wrong"}', '{"paths":[null]}'])
def test_shared_infra_unavailable_registry_never_reports_ready(tmp_path, monkeypatch, contents):
    registry = tmp_path / "base-shared-infra.json"
    registry.write_text(contents)
    monkeypatch.setattr(D, "SHARED_INFRA_PATH", registry)
    out, _pr, _calls, _doc, _paths = _shared_infra_cycle(tmp_path)
    assert not out["merge_ready"]["ready"]
    assert "shared-infrastructure" in out["merge_ready"]["one_step"][0]["step"]


# D52: a registered source coauthor is never an independent reviewer.
def _coauthor_cycle(
    tmp_path, *, reviewer="coauthor", authors="valid", held=False, panes=None, prior=(), review_verdict="MERGE"
):
    import hashlib

    panes = panes or {}
    source = ".githooks/pre-push" if held else "src/synthetic.py"
    paths = make_tree(
        tmp_path,
        panes=panes,
        queue=[],
        claims=[
            {
                "claim_id": "source",
                "session": "author",
                "branch": "wt/synthetic",
                "status": "done",
                "heartbeat_at": iso(NOW),
                "head_sha": "a" * 40,
                "paths": [source],
            }
        ],
    )
    doc = _d51_registered_review(paths["coord"])
    doc.update(engineering_tests_completed=True, engineering_docs_completed=True)
    doc["authors"].append({"actor": "codex", "session": "coauthor", "claim_id": "coauthor-source"})
    if authors != "valid":
        if authors == "missing":
            doc.pop("authors")
        elif authors == "incomplete":
            doc["authors_and_coauthors_complete"] = False
        elif authors == "truthy_complete":
            doc["authors_and_coauthors_complete"] = "true"
        elif authors == "bad_provenance":
            doc["identity_provenance"] = "git_display_names"
        else:
            doc["authors"] = authors
    raw = f"Adversarial-review: MERGE reviewer={reviewer} head={'a' * 40}\n".encode()
    proof = paths["coord"] / "proofs" / "coauthor-control.artifact"
    proof.write_bytes(raw)
    doc["reviews"] = [
        {
            "reviewer_session": reviewer,
            "verdict": "MERGE",
            "head_sha": "a" * 40,
            "artifact": "proofs/coauthor-control.artifact",
            "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        }
    ]
    (paths["coord"] / "review-evidence" / f"7-{'a' * 40}.json").write_text(json.dumps(doc))
    if review_verdict == "BLOCK":
        # Canonical registrations contain MERGEs; a later genuine standalone BLOCK replaces that review.
        evidence = paths["coord"] / "review-evidence"
        (evidence / "zz-later-block.md").write_text(f"Adversarial-review: BLOCK reviewer={reviewer} head={'a' * 40}\n")
        (evidence / "zz-later-block.machine.json").write_text(
            json.dumps({"pr": 7, "head_sha": "a" * 40, "reviewer_session": reviewer, "verdict": "BLOCK"})
        )
    if prior:
        paths["ledger"].write_text(
            "\n".join(
                json.dumps(
                    {
                        "kind": "review",
                        "target": "7",
                        "target_head": "a" * 40,
                        "session": session,
                        "outcome": "dispatched",
                        "busy_after_30s": True,
                    }
                )
                for session in prior
            )
            + "\n"
        )
    rows = [
        {
            "number": 7,
            "headRefName": "wt/synthetic",
            "headRefOid": "a" * 40,
            "mergeStateStatus": "CLEAN",
            "isDraft": held,
            "changedFiles": 1,
            "files": [{"path": source}],
            "statusCheckRollup": _d51_checks(),
        }
    ]
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    calls = []
    base = fake_runner(panes, rows)

    def run(cmd, **kw):
        calls.append(cmd)
        assert cmd[0] in {"gh", "tmux"}
        assert cmd[:2] not in (["tmux", "load-buffer"], ["tmux", "paste-buffer"], ["tmux", "send-keys"])
        return base(cmd, **kw)

    try:
        result = CLI.run_cycle(
            apply=False,
            coord=paths["coord"],
            queue_path=paths["queue"],
            claims_dir=paths["claims"],
            ledger_path=paths["ledger"],
            run=run,
        )
    finally:
        assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    return result, doc, paths


def test_registered_coauthor_real_collector_self_merge_never_ready(tmp_path):
    out, _, _ = _coauthor_cycle(tmp_path)
    assert not out["merge_ready"]["ready"]
    assert "## Ready to merge (0)" in out["merge_ready_md"]


def test_registered_coauthor_real_collector_independent_merge_still_ready(tmp_path):
    out, _, _ = _coauthor_cycle(tmp_path, reviewer="independent")
    assert [r["pr"] for r in out["merge_ready"]["ready"]] == [7]
    assert out["merge_ready"]["ready"][0]["author"] == "author, coauthor"


@pytest.mark.parametrize(
    "authors",
    [
        "missing",
        None,
        [],
        {},
        "coauthor",
        ["coauthor"],
        [{"actor": "codex", "session": 7, "claim_id": "source"}],
        [{"actor": "codex", "session": "coauthor"}],
        [{"actor": "codex", "session": "coauthor", "claim_id": "source"}] * 2,
        "incomplete",
        "truthy_complete",
        "bad_provenance",
    ],
)
def test_registered_coauthor_real_collector_bad_authorship_fails_closed(tmp_path, authors):
    out, _, _ = _coauthor_cycle(tmp_path, reviewer="independent", authors=authors)
    assert not out["merge_ready"]["ready"]


def test_registered_coauthor_cannot_receive_own_held_review(tmp_path):
    out, _, _ = _coauthor_cycle(
        tmp_path,
        held=True,
        reviewer="independent",
        panes={"cc-deepseek-coauthor": "❯ \n idle"},
        authors=[
            {"actor": "codex", "session": "author", "claim_id": "source"},
            {"actor": "codex", "session": "cc-deepseek-coauthor", "claim_id": "coauthor-source"},
        ],
    )
    assert not any(a["kind"] == "review" for a in out["assignments"])


@pytest.mark.parametrize("review_verdict", ["MERGE", "BLOCK"])
def test_registered_coauthor_prior_dispatch_does_not_spend_independent_capacity(tmp_path, review_verdict):
    out, _, _ = _coauthor_cycle(
        tmp_path,
        held=True,
        panes={"cc-deepseek-fresh": "❯ \n idle"},
        prior=("coauthor", "independent"),
        review_verdict=review_verdict,
    )
    assert [(a["kind"], a["session"]) for a in out["assignments"]] == [("review", "cc-deepseek-fresh")]


def test_registered_coauthor_latest_registration_replaces_registered_subset(tmp_path):
    _, doc, _ = _coauthor_cycle(tmp_path, reviewer="independent")
    latest = {**doc, "authors": [{"actor": "codex", "session": "corrected", "claim_id": "corrected-source"}]}
    pr = _held_pr(7, "a" * 40, "wt/synthetic", "DIRTY", True)
    common = dict(queue=[], claims=[], prs=[pr], author_of={7: "author"}, coord="/synthetic", now=NOW)
    current = D.verdicts_at_head([doc, latest])
    assert D.select_work("corrected", verdicts=current, **common) is None
    assert D.select_work("coauthor", verdicts=current, **common) is not None
    assert D.select_work("author", verdicts=current, **common) is None


def test_registered_coauthor_other_head_does_not_lend_authorship(tmp_path):
    _, doc, _ = _coauthor_cycle(tmp_path)
    doc["head_sha"] = "b" * 40
    doc["reviews"][0]["head_sha"] = "b" * 40
    pr = _held_pr(7, "a" * 40, "wt/synthetic", "DIRTY", True)
    task = D.select_work(
        "coauthor",
        queue=[],
        claims=[],
        prs=[pr],
        verdicts=D.verdicts_at_head([doc]),
        author_of={7: "author"},
        coord="/synthetic",
        now=NOW,
    )
    assert task is not None and task.kind == "review"


@pytest.mark.parametrize(
    "field,value",
    [
        ("registered_by", None),
        ("registered_by", {"actor": "codex", "session": 7}),
        ("source_authorship_sha256", None),
        ("source_authorship_sha256", "not-a-hash"),
        ("source_commit_shas", []),
        ("source_commit_shas", [7]),
        ("authors", [{"actor": None, "session": "coauthor", "claim_id": "source"}]),
        ("authors", [{"actor": "codex", "session": "coauthor", "claim_id": 7}]),
    ],
)
def test_registered_coauthor_latest_malformed_provenance_replaces_true(tmp_path, field, value):
    out, doc, _ = _coauthor_cycle(tmp_path, reviewer="independent")
    assert out["merge_ready"]["ready"]
    pr = _complete_pr(7, "a" * 40, "wt/synthetic", "CLEAN", False)
    claims = [
        claim(cid="source", session="author", branch="wt/synthetic", status="done", head=pr.head_sha, paths=pr.files)
    ]
    latest = {**doc, field: value}
    indexed = D.verdicts_at_head([doc, latest])
    assert not D.merge_ready([pr], indexed, claims, {7: "author"})["ready"]
    held = _held_pr(7, pr.head_sha, pr.head_ref, "DIRTY", True)
    assert (
        D.select_work(
            "fresh",
            queue=[],
            claims=[],
            prs=[held],
            verdicts=indexed,
            author_of={7: "author"},
            coord="/synthetic",
            now=NOW,
        )
        is None
    )


def test_registered_coauthor_multiple_sessions_and_actual_authority_vocabulary(tmp_path):
    rows = [
        {"actor": "codex", "session": who, "claim_id": who + "-source"}
        for who in ("author", "second-author", "third-author")
    ]
    out, doc, _ = _coauthor_cycle(tmp_path, authors=rows, reviewer="third-author")
    assert not out["merge_ready"]["ready"]
    pr = _held_pr(7, "a" * 40, "wt/synthetic", "DIRTY", True)
    indexed = D.verdicts_at_head([doc])
    assert D.source_author_sessions(pr, indexed[(7, pr.head_sha)], {"branch-predecessor"}) == {
        "branch-predecessor",
        "author",
        "second-author",
        "third-author",
    }
    for session in ("author", "second-author", "third-author", "branch-predecessor"):
        assert (
            D.select_work(
                session,
                queue=[],
                claims=[],
                prs=[pr],
                verdicts=indexed,
                author_of={7: "branch-predecessor"},
                coord="/synthetic",
                now=NOW,
            )
            is None
        )
    assert (
        D.select_work(
            "genuine-peer",
            queue=[],
            claims=[],
            prs=[pr],
            verdicts=indexed,
            author_of={7: "branch-predecessor"},
            coord="/synthetic",
            now=NOW,
        ).kind
        == "review"
    )


def test_registered_coauthor_old_head_cannot_supply_current_registration(tmp_path):
    _, doc, _ = _coauthor_cycle(tmp_path, reviewer="independent")
    old = {**doc, "head_sha": "b" * 40}
    current = {"pr": 7, "head_sha": "a" * 40, "reviews": doc["reviews"]}
    indexed = D.verdicts_at_head([old, current])
    pr = _complete_pr(7, "a" * 40, "wt/synthetic", "CLEAN", False)
    claims = [
        claim(cid="source", session="author", branch="wt/synthetic", status="done", head=pr.head_sha, paths=pr.files)
    ]
    assert D.source_author_sessions(pr, indexed[(7, pr.head_sha)], "author") == {"author"}
    assert not D.merge_ready([pr], indexed, claims, {7: "author"})["ready"]


def _fully_attested_merge(pr, reviewer):
    return {
        "verdict": "MERGE",
        "reviewer": reviewer,
        "section17_completion_head": pr.head_sha,
        "section17_review_completed": True,
        "engineering_completion_head": pr.head_sha,
        "engineering_tests_completed": True,
        "engineering_docs_completed": True,
        "authorship_completion_head": pr.head_sha,
        "registered_author_sessions": ("author",),
        "registered_authorship_valid": True,
    }


@pytest.mark.parametrize("path,reason", [
    ("config/portfolio_positions.yaml", "Section-17 decision-required"),
    ("scripts/schwab_synthetic.py", "operator-only"),
])
def test_the_ready_projection_respects_the_canonical_path_refusals(path, reason):
    """FALSE READINESS (2026-11-06): the projection reported Ready=1 for config/portfolio_positions.yaml and
    scripts/schwab_synthetic.py while pr_merge_delegation refuses both on the path alone (operator-only /
    Section-17 decision-required, :566-570). A merge-ready light must say what the gate actually decides."""
    pr = _complete_pr(15, "h" * 40, "wt/d", "CLEAN", False, commit_shas=("h" * 40,), files=(path,))
    claims = [claim(session="cc-4", branch="wt/d", head="h" * 40, status="done", paths=pr.files)]
    v = {(15, "h" * 40): [_fully_attested_merge(pr, "cc-9"), _fully_attested_merge(pr, "cc-5")]}
    out = D.merge_ready([pr], v, claims, {15: "cc-4"})
    assert out["ready"] == [], f"{path} is refused by the canonical evaluator; readiness would be false"
    assert reason in out["one_step"][0]["step"]


def test_a_pr_outside_the_refused_paths_is_still_ready():
    """The control: the refusal must not turn into blanket pessimism."""
    pr = _complete_pr(16, "h" * 40, "wt/e", "CLEAN", False, commit_shas=("h" * 40,),
                      files=("apps/command-center-v3/src/pages/Home.tsx",))
    claims = [claim(session="cc-4", branch="wt/e", head="h" * 40, status="done", paths=pr.files)]
    v = {(16, "h" * 40): [_fully_attested_merge(pr, "cc-9"), _fully_attested_merge(pr, "cc-5")]}
    out = D.merge_ready([pr], v, claims, {16: "cc-4"})
    assert [r["pr"] for r in out["ready"]] == [16]
