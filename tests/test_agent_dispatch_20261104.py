"""P0 BUILD — automatic agent dispatch (operator ~13:10 ET, 2026-11-04).

Hermetic: fake tmux/gh runners, temp directories, no network, no fleet. Every decision the dispatcher makes is a
function of the data handed in, and these tests exercise the order (a)…(e), the rails, the submit path and the
"dry run writes nothing" promise.
"""
from __future__ import annotations

import json
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
    """Records the exact tmux calls and lets a test decide when the pane looks busy."""

    def __init__(self, busy_on_poll: int = 1):
        self.calls: list[list[str]] = []
        self.busy_on_poll = busy_on_poll
        self.polls = 0

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        class P:
            returncode = 0
            stdout = ""
            stderr = ""
        if cmd[:2] == ["tmux", "capture-pane"]:
            self.polls += 1
            P.stdout = "· Working (2s · esc to interrupt)" if self.polls >= self.busy_on_poll else "❯ "
        return P


def test_submit_pastes_then_enters_and_proves_busy():
    fake = FakeTmux(busy_on_poll=1)
    sleeps: list[float] = []
    r = D.submit("cc-1", "line one\nline two", run=fake, sleep=sleeps.append, poll_every=3.0)
    verbs = [c[1] for c in fake.calls if c[:2] == ["tmux", c[1]] or True]
    assert ["tmux", "load-buffer"][0:2] in [c[0:2] for c in fake.calls]
    assert any(c[:2] == ["tmux", "paste-buffer"] for c in fake.calls), "text must be pasted, not send-keyed"
    assert not any(c[:3] == ["tmux", "send-keys", "-l"] for c in fake.calls), "send-keys -l is the silent-no-submit trap"
    assert r.submitted and r.busy_after and r.attempts == 1


def test_submit_retries_once_then_reports_dispatch_failed():
    fake = FakeTmux(busy_on_poll=10_000)  # never busy
    r = D.submit("cc-1", "do the thing", run=fake, sleep=lambda _s: None, busy_confirm_seconds=6.0, poll_every=3.0)
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
    src = (ROOT / "scripts" / "agent_dispatch.py").read_text(encoding="utf-8")
    targets = set(re.findall(r"\(\s*coord\s*/\s*\"([A-Za-z_.]+)\"\s*\)\.write_text", src))
    assert targets == {"MERGE_READY.md", "DISPATCH_IDLE_ALERT.md"}, targets
    ledger_targets = re.findall(r"ledger_path[^\n]*open\(\"a\"", src)
    assert ledger_targets, "the ledger append must be visible in the source"
    for forbidden in ("pr_merge_delegation", "git push", "gh pr merge", "setex", "write_text" ):
        if forbidden == "write_text":
            continue
        assert forbidden not in src, f"the dispatcher must never contain {forbidden!r}"


# ── 9. the reviewer cap and recency order (found in the live dry run, 2026-11-04) ──────────────────────────────


def test_at_most_two_reviewers_per_pr():
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    common = dict(queue=[], claims=[], prs=[pr], verdicts={}, author_of={7: "cc-4"}, coord="/c", now=NOW)
    assert D.select_work("cc-8", review_counts={7: 2}, **common) is None, "a third reviewer is not work"
    a = D.select_work("cc-8", review_counts={7: 1}, **common)
    assert a and a.kind == "review", "the second reviewer slot is work"


def test_existing_verdicts_count_towards_the_cap():
    pr = D.PullRequest(7, "h" * 40, "wt/x", "CLEAN", False)
    # one BLOCK already filed at this head: that is one reviewer spent, so one slot remains
    v = {(7, "h" * 40): [{"verdict": "BLOCK", "reviewer": "cc-9"}]}
    a = D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts=v, author_of={7: "cc-4"}, coord="/c",
                      now=NOW, review_counts={7: 1})
    assert a is not None
    assert D.select_work("cc-8", queue=[], claims=[], prs=[pr], verdicts=v, author_of={7: "cc-4"}, coord="/c",
                         now=NOW, review_counts={7: 2}) is None


def test_newest_pr_is_offered_before_an_ancient_one():
    old = D.PullRequest(100, "a" * 40, "wt/old", "CLEAN", False, updated_at="2026-10-20T00:00:00Z")
    new = D.PullRequest(200, "b" * 40, "wt/new", "CLEAN", False, updated_at="2026-11-04T17:00:00Z")
    a = D.select_work("cc-8", queue=[], claims=[], prs=[old, new], verdicts={}, author_of={}, coord="/c", now=NOW)
    assert a.target == "200", "a live PR is reviewed before the October triage list"
