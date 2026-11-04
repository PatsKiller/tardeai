"""P0 BUILD — automatic agent dispatch (operator ~13:10 ET, 2026-11-04).

Hermetic: fake tmux/gh runners, temp directories, no network, no fleet. Every decision the dispatcher makes is a
function of the data handed in, and these tests exercise the order (a)…(e), the rails, the submit path and the
"dry run writes nothing" promise.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import agent_dispatch as D  # noqa: E402
import agent_dispatch as CLI  # noqa: E402

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
    return D.Claim(claim_id=cid, session=session, branch=branch, paths=list(paths), head_sha=head,
                   status=status, age_h=age)


def row(rid="FQ-1", owner="cc-8", status="queued", paths=("a.tsx",), **kw):
    return {"id": rid, "owner": owner, "status": status, "page": "/p", "severity": "P2", "paths": list(paths),
            "acceptance": {"what": "w", "expected": "e", "actual": "a", "evidence": "ev"}, **kw}


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
    ok, why = D.row_workable(row(paths=("src/page.tsx",)), "cc-8", [claim(session="cc-4", paths=("src/page.tsx",))], now=NOW)
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
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    a = D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    assert a.kind == "review" and a.target == "7"
    assert "review PR #7" in a.instruction and "Do not push, do not merge" in a.instruction
    assert "Adversarial-review: MERGE reviewer=cc-8 head=" + "h" * 40 in a.instruction


def test_never_assigns_a_review_of_your_own_pr():
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    assert D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-8"}, coord="/c", now=NOW) is None


def test_a_pr_with_a_merge_verdict_at_head_needs_no_second_review():
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    v = {(7, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    assert D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts=v, author_of={7: "cc-4"}, coord="/c", now=NOW) is None


def test_a_dirty_or_draft_pr_is_not_review_work():
    draft = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", True)
    dirty = D.PullRequest(8, "h" * 40, "wt/y", "BLOCKED", False)
    assert D.select_work("cc-8", queue=[], claims=[], prs=[draft, dirty], verdicts={}, author_of={}, coord="/c", now=NOW) is None


def test_c_merge_prep_when_the_author_claim_carries_another_head():
    pr = D.PullRequest(9, "a" * 40, "wt/x", "CLEAN", False, commit_shas=("b" * 40, "c" * 40))
    v = {(9, pr.head_sha): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    claims = [claim(session="cc-4", branch="wt/x", head="d" * 40)]  # not in [head] + commits
    a = D.select_work("cc-4", queue=[], claims=claims, prs=[pr], verdicts=v, author_of={9: "cc-4"}, coord="/c", now=NOW)
    assert a.kind == "merge_prep" and a.target == "9"
    assert "Re-stamp the claim" in a.instruction and "Do not push or merge" in a.instruction


def test_c_does_not_fire_when_the_claim_head_is_among_the_pr_commits():
    pr = D.PullRequest(9, "new" + "h" * 37, "wt/x", "CLEAN", False, commit_shas=("old" + "h" * 37,))
    v = {(9, pr.head_sha): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    claims = [claim(session="cc-4", branch="wt/x", head="old" + "h" * 37)]
    assert D.select_work("cc-4", queue=[], claims=claims, prs=[pr], verdicts=v, author_of={9: "cc-4"}, coord="/c", now=NOW) is None


def test_d_oldest_unowned_row_when_nothing_of_its_own():
    a = D.select_work("cc-8", queue=[row(owner=""), row(rid="FQ-2", owner="cc-4")], claims=[], prs=[], verdicts={},
                      author_of={}, coord="/c", now=NOW)
    assert a.kind == "unowned_queue" and a.target == "FQ-1"


def test_e_chore_for_a_stale_claim():
    a = D.select_work("cc-8", queue=[], claims=[claim(session="cc-4", age=6.0)], prs=[], verdicts={}, author_of={},
                      coord="/c", now=NOW)
    assert a.kind == "chore" and "has not been heartbeated for 6.0h" in a.instruction


def test_nothing_to_do_returns_none():
    assert D.select_work("cc-8", queue=[], claims=[claim(age=0.2)], prs=[], verdicts={}, author_of={}, coord="/c", now=NOW) is None


# ── 4. verdicts and the merge pump ─────────────────────────────────────────────────────────────────────────────


def test_verdicts_are_read_from_both_artifact_shapes():
    companion = {"pr": 1, "head_sha": "a" * 40, "verdict": "MERGE", "reviewer_session": "cc-9"}
    registered = {"pr": 1, "head_sha": "a" * 40, "reviews": [{"verdict": "MERGE", "reviewer_session": "cc-4"}]}
    index = D.verdicts_at_head([companion, registered])
    assert {e["reviewer"] for e in index[(1, "a" * 40)]} == {"cc-9", "cc-4"}


def test_merge_pump_separates_ready_from_one_step_and_never_merges():
    pr = D.PullRequest(11, "h" * 40, "wt/x", "CLEAN", False, commit_shas=("h" * 40,))
    claims = [claim(session="cc-4", branch="wt/x", head="h" * 40)]
    v = {(11, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-9"}]}
    out = D.merge_ready([pr], v, claims, {11: "cc-4"})
    assert [r["pr"] for r in out["ready"]] == [11] and out["one_step"] == []
    text = D.render_merge_ready(out, generated_at="now")
    assert "report only" in text and "#11" in text


def test_a_merge_verdict_from_the_author_is_not_independent():
    pr = D.PullRequest(11, "h" * 40, "wt/x", "CLEAN", False, commit_shas=("h" * 40,))
    claims = [claim(session="cc-4", branch="wt/x", head="h" * 40)]
    v = {(11, "h" * 40): [{"verdict": "MERGE", "reviewer": "cc-4"}]}
    out = D.merge_ready([pr], v, claims, {11: "cc-4"})
    assert out["ready"] == [], "the author's own MERGE must not count"


def test_merge_pump_names_the_one_step():
    pr = D.PullRequest(12, "h" * 40, "wt/x", "CLEAN", False)
    out = D.merge_ready([pr], {}, [claim(session="cc-4", branch="wt/x", head="h" * 40)], {12: "cc-4"})
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
    assert not any(c[:3] == ["tmux", "send-keys", "-l"] for c in fake.calls), "send-keys -l is the silent-no-submit trap"
    assert r.submitted and r.busy_after and r.attempts == 1
    assert "after the paste" in r.detail


def test_a_pane_that_was_already_busy_is_not_evidence_of_this_dispatch():
    """F3: busy must be NEW. A stale spinner that never changes must not confirm a dispatch."""
    class StuckBusy(FakeTmux):
        def __call__(self, cmd, **kw):
            p = super().__call__(cmd, **kw)
            if cmd[:2] == ["tmux", "capture-pane"]:
                p.stdout = "· Working (999s · esc to interrupt)"   # always busy, never changing
            return p
    clock = FakeClock()
    r = D.submit("cc-1", "do it", run=StuckBusy(), sleep=clock.sleep, poll_every=3.0, busy_confirm_seconds=6.0,
                 monotonic=clock)
    assert not r.busy_after and r.attempts == 2


def test_submit_retries_once_then_reports_dispatch_failed():
    fake, clock = FakeTmux(busy_after_paste=False), FakeClock()   # never goes busy
    r = D.submit("cc-1", "do the thing", run=fake, sleep=clock.sleep, busy_confirm_seconds=6.0, poll_every=3.0,
                 monotonic=clock)
    assert not r.busy_after and r.attempts == 2, "one retry, then stop — no third"
    line = json.loads(D.ledger_line(session="cc-1", assignment=D.Assignment("cc-1", "queue", "FQ-1", "x", "w"),
                                    result=r, cycle_id="cyc-1"))
    assert line["outcome"] == "dispatch_failed" and line["submitted"] and not line["busy_after_30s"]


def test_ledger_line_shape():
    a = D.Assignment("cc-1", "review", "42", "text", "why")
    r = D.SubmitResult(True, True, 1, "busy confirmed after 3s")
    line = json.loads(D.ledger_line(session="cc-1", assignment=a, result=r, cycle_id="cyc-9", ts="2026-11-04T18:00:00Z"))
    assert set(line) >= {"ts", "session", "kind", "target", "sent_sha256", "submitted", "busy_after_30s", "cycle_id"}
    assert line["kind"] == "review" and line["target"] == "42" and line["sent_sha256"]


# ── 6. escalation ──────────────────────────────────────────────────────────────────────────────────────────────


def test_idle_alert_only_past_fifteen_minutes():
    assert D.idle_alert([("cc-1", 10.0)], generated_at="now") is None
    text = D.idle_alert([("cc-1", 16.0), ("cc-2", 40.0)], generated_at="now")
    assert "cc-2" in text and "idle 40 min" in text and "add work" in text


# ── 7. the cycle: dry run writes nothing, apply writes only its own files ──────────────────────────────────────


def make_tree(tmp: Path, *, panes: dict[str, str], queue: list[dict], claims: list[dict] | None = None) -> dict[str, Path]:
    coord = tmp / "coordinator"
    (coord / "inbox" / "lead").mkdir(parents=True, exist_ok=True)
    (coord / "AUDIT_FIX_QUEUE.json").write_text(json.dumps({"items": queue}), encoding="utf-8")
    claims_dir = tmp / "claims"
    claims_dir.mkdir()
    for c in claims or []:
        (claims_dir / f"{c['claim_id']}.json").write_text(json.dumps(c), encoding="utf-8")
    return {"coord": coord, "queue": coord / "AUDIT_FIX_QUEUE.json", "claims": claims_dir,
            "ledger": coord / "dispatch_ledger.jsonl"}


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
            P.stdout = json.dumps(gh_rows)
        elif cmd[:3] == ["gh", "pr", "view"]:
            P.stdout = json.dumps({"commits": []})
        return P
    return run


def test_dry_run_writes_nothing_and_sends_nothing(tmp_path):
    paths = make_tree(tmp_path, panes={"cc-deepseek-8": "❯ \n idle"},
                      queue=[{"id": "FQ-1", "owner": "cc-deepseek-8", "status": "queued", "page": "/p", "acceptance": "acc"}])
    run = fake_runner({"cc-deepseek-8": "❯ \n idle"}, [])
    before = sorted(p.name for p in paths["coord"].rglob("*"))
    out = CLI.run_cycle(apply=False, coord=paths["coord"], queue_path=paths["queue"],
                        claims_dir=paths["claims"], ledger_path=paths["ledger"], run=run)
    after = sorted(p.name for p in paths["coord"].rglob("*"))
    assert before == after, "a dry run must not create files"
    assert not paths["ledger"].exists()
    assert out["assignments"] and out["assignments"][0]["kind"] == "queue"
    assert any("cc-deepseek-8" in line for line in out["plan"])


def test_apply_writes_the_ledger_and_merge_ready_only(tmp_path):
    paths = make_tree(tmp_path, panes={"cc-deepseek-8": "❯ \n idle"},
                      queue=[{"id": "FQ-1", "owner": "cc-deepseek-8", "status": "queued", "page": "/p", "acceptance": "acc"}])
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

    out = CLI.run_cycle(apply=True, coord=paths["coord"], queue_path=paths["queue"],
                        claims_dir=paths["claims"], ledger_path=paths["ledger"], run=run, sleep=lambda _s: None)
    assert paths["ledger"].exists() and out["ledger"][0]["outcome"] == "dispatched"
    assert (paths["coord"] / "MERGE_READY.md").exists()
    assert sent, "the instruction was pasted"
    # Rails: nothing else of the fleet's was written.
    written = {p.name for p in paths["coord"].rglob("*") if p.is_file()}
    assert written <= {"AUDIT_FIX_QUEUE.json", "dispatch_ledger.jsonl", "MERGE_READY.md"}, written


def test_busy_sessions_are_not_touched(tmp_path):
    paths = make_tree(tmp_path, panes={"cc-deepseek-8": "· Working (3s · esc to interrupt)"}, queue=[{"id": "FQ-1", "owner": "cc-deepseek-8", "status": "queued", "page": "/p"}])
    out = CLI.run_cycle(apply=False, coord=paths["coord"], queue_path=paths["queue"], claims_dir=paths["claims"],
                        ledger_path=paths["ledger"], run=fake_runner({"cc-deepseek-8": "· Working (3s · esc to interrupt)"}, []))
    assert out["assignments"] == []


# ── 8. rails, stated as a source property ──────────────────────────────────────────────────────────────────────


def test_the_module_writes_only_its_own_two_files():
    """Rails, stated as a source property: the only report files it names are the two it owns, and both writes go
    through the protected-path guard (F2)."""
    src = (ROOT / "scripts" / "agent_dispatch.py").read_text(encoding="utf-8")
    named = set(re.findall(r'"(MERGE_READY\.md|DISPATCH_IDLE_ALERT\.md)"', src))
    assert named == {"MERGE_READY.md", "DISPATCH_IDLE_ALERT.md"}, named
    assert src.count("D.safe_output_path(") >= 3, "every write target must pass through the guard"
    assert "pr_merge_delegation" not in src and "gh pr merge" not in src and "git push" not in src
    ledger_targets = re.findall(r"ledger_target[^\n]*open\(\"a\"", src)
    assert ledger_targets, "the ledger append must be visible in the source"
    for forbidden in ("pr_merge_delegation", "git push", "gh pr merge", "setex", "write_text" ):
        if forbidden == "write_text":
            continue
        assert forbidden not in src, f"the dispatcher must never contain {forbidden!r}"


# ── 9. the reviewer cap and recency order (found in the live dry run, 2026-11-04) ──────────────────────────────


def test_at_most_two_reviewers_per_pr():
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    assert D.select_work("cc-8", review_counts={(7, "h" * 40): 2}, **common) is None, "a third reviewer is not work"
    a = D.select_work("cc-8", review_counts={(7, "h" * 40): 1}, **common)
    assert a and a.kind == "review", "the second reviewer slot is work"


def test_existing_verdicts_count_towards_the_cap():
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    # one BLOCK already filed at this head: that is one reviewer spent, so one slot remains
    v = {(7, "h" * 40): [{"verdict": "BLOCK", "reviewer": "cc-9"}]}
    a = D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts=v, author_of={7: "cc-4"}, coord="/c",
                      now=NOW, review_counts={(7, "h" * 40): 1})
    assert a is not None
    assert D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts=v, author_of={7: "cc-4"}, coord="/c",
                         now=NOW, review_counts={(7, "h" * 40): 2}) is None


def test_newest_pr_is_offered_before_an_ancient_one():
    old = D.PullRequest(100, "a" * 40, "wt/old", "CLEAN", False, updated_at="2026-10-20T00:00:00Z")
    new = D.PullRequest(200, "b" * 40, "wt/new", "CLEAN", False, updated_at="2026-11-04T17:00:00Z")
    a = D.select_work("cc-8", queue=[], claims=[], prs=[old, new], verdicts={},
                      author_of={100: "cc-1", 200: "cc-2"}, coord="/c", now=NOW)
    assert a.target == "200", "a live PR is reviewed before the October triage list"


def test_a_pr_with_an_unknown_author_is_never_assigned_a_reviewer():
    """F5: independence must be provable. No author resolved means nobody may review it."""
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    a = D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts={}, author_of={}, coord="/c", now=NOW)
    assert a is None


def test_a_block_verdict_counts_towards_the_reviewer_cap():
    """F4: BLOCK is a verdict too — a PR with two blocks at this head is not given a third reviewer."""
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    v = {(7, "h" * 40): [{"verdict": "BLOCK", "reviewer": "cc-1"}, {"verdict": "BLOCK", "reviewer": "cc-2"}]}
    a = D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts=v, author_of={7: "cc-4"}, coord="/c",
                      now=NOW, review_counts={(7, "h" * 40): 2})
    assert a is None


def test_an_exact_head_block_is_never_reported_ready():
    """F6: the pump must not call a blocked PR ready, even if a MERGE also sits at that head."""
    pr = D.PullRequest(11, "h" * 40, "wt/x", "CLEAN", False, commit_shas=("h" * 40,))
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
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    # cycle 2: the ledger says cycle 1 already sent cc-8 this PR and it went busy
    a = D.select_work("cc-8", prior_review_sessions={(7, "h" * 40): {"cc-8"}}, review_counts={(7, "h" * 40): 1}, **common)
    assert a is None, "a reviewer already sent this PR must not be re-sent it every five minutes"


def test_two_cycles_of_sending_cannot_exceed_the_two_reviewer_cap():
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    # cycle 1 sent two reviewers who went busy; the cap is spent even though no verdict exists yet
    a = D.select_work("cc-9", prior_review_sessions={(7, "h" * 40): {"cc-1", "cc-2"}}, review_counts={(7, "h" * 40): 2}, **common)
    assert a is None


def test_prior_review_dispatches_reads_only_completed_review_lines(tmp_path):
    ledger = tmp_path / "dispatch_ledger.jsonl"
    ledger.write_text("\n".join([
        json.dumps({"kind": "review", "target": "7", "target_head": "h" * 40, "session": "cc-1", "busy_after_30s": True}),
        json.dumps({"kind": "review", "target": "7", "target_head": "h" * 40, "session": "cc-2", "busy_after_30s": False}),  # never landed
        json.dumps({"kind": "queue", "target": "7", "target_head": "h" * 40, "session": "cc-3", "busy_after_30s": True}),     # not a review
        "{not json",
    ]) + "\n", encoding="utf-8")
    sessions, counts = CLI.prior_review_dispatches(ledger)
    assert sessions == {(7, "h" * 40): {"cc-1"}} and counts == {(7, "h" * 40): 1}


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
            p.stdout = ("· Working (1s · esc to interrupt)\n> dispatched" if pasted["done"]
                        else "❯ \n  ? for shortcuts")
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
    prs = [D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)]
    claims = [claim(cid="c-old", session="cc-4", branch="wt/x", status="done", age=3.0)]
    authors = CLI.author_sessions(prs, claims)
    assert authors == {7: "cc-4"}
    assert D.select_work("cc-4", queue=[], claims=claims, prs=prs, verdicts={}, author_of=authors,
                         coord="/c", now=NOW) is None


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
    monkeypatch.setattr(CLI.D, "select_work",
                        lambda *a, **k: D.Assignment("cc-8", "review", "9999", "Dispatcher: do a thing", "forced"))

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
        CLI.run_cycle(apply=True, coord=coord, queue_path=queue, claims_dir=coord / "claims",
                      ledger_path=queue, limit=1, run=run, sleep=lambda s: None)
    assert sent == [], f"the refusal must come before any keystroke, but these were sent: {sent}"


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
                    clock.t += 20.0   # this capture returns after the deadline
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
                p.stdout = ("· Working (999s · esc to interrupt)\n"     # the SAME old spinner both times
                            + ("status line " + str(state["n"])))
            return p

    r = D.submit("cc-1", "go", run=Drift(), sleep=clock.sleep, monotonic=clock, busy_confirm_seconds=10.0)
    assert r.busy_after is False, "an old marker plus unrelated tail drift is not evidence of this dispatch"


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
    pr = D.PullRequest(7, new_head, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    a = D.select_work("cc-8", prior_review_sessions={(7, old_head): {"cc-8", "cc-9"}},
                      review_counts={(7, old_head): 2}, **common)
    assert a is not None and a.kind == "review", "the new head has its own two-reviewer budget"
    b = D.select_work("cc-8", prior_review_sessions={(7, new_head): {"cc-8"}},
                      review_counts={(7, new_head): 1}, **common)
    assert b is None, "the same reviewer is not re-sent the SAME head"


def test_a_dispatch_recorded_at_an_old_head_does_not_spend_the_new_head_budget(tmp_path):
    """F4 round 2 at the ledger boundary: prior_review_dispatches keys by (pr, head)."""
    ledger = tmp_path / "dispatch_ledger.jsonl"
    ledger.write_text("\n".join([
        json.dumps({"kind": "review", "target": "7", "target_head": "a" * 40, "session": "cc-1",
                    "busy_after_30s": True}),
        json.dumps({"kind": "review", "target": "7", "target_head": "b" * 40, "session": "cc-2",
                    "busy_after_30s": True}),
        json.dumps({"kind": "review", "target": "7", "session": "cc-3", "busy_after_30s": True}),  # legacy: no head
    ]) + "\n", encoding="utf-8")
    sessions, counts = CLI.prior_review_dispatches(ledger)
    assert counts == {("7", "a" * 40): 1} or counts.get((7, "a" * 40)) == 1
    assert (7, "a" * 40) in counts and counts[(7, "a" * 40)] == 1
    assert (7, "b" * 40) in counts and counts[(7, "b" * 40)] == 1
    assert counts.get((7, ""), 0) == 1, "a legacy record is attributed to the empty head, never to a real one"
