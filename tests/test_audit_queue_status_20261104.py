"""AuditFixQueueStatusSync — the queue's status field follows GitHub, not memory.

Why: on 2026-11-04 eight delivered rows sat in `queued`/`pr=None` and were dispatched back to their author, and a HELD
row read `queued` and was worked for twenty minutes. Both were a status field nobody updated. These tests pin the rules
(AuditFixQueueStatusRules@v1) the sync implements, and — as importantly — the rows it must never touch.

Hermetic: a queue document and a list of PR dicts; `gh` is never run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import audit_queue_status as S  # noqa: E402

NOW = "2026-11-04T21:30:00Z"


def pr(number, *, state="OPEN", branch="wt/fq022-cio-tabs", body="", head="a" * 40, merge=None):
    return {"number": number, "state": state, "headRefName": branch, "headRefOid": head, "body": body,
            "mergedAt": None, "mergeCommit": {"oid": merge} if merge else None}


def queue(*items):
    return {"schema": "AuditFixQueue@v1", "as_of": "2026-11-04T17:30:12Z", "authority": "x",
            "counts": {}, "items": list(items)}


def row(id_, status="queued", **kw):
    base = {"id": id_, "severity": "P2", "page": "/p", "owner": "cc-deepseek-3", "status": status}
    base.update(kw)
    return base


def change(report, id_):
    return next((c for c in report["changes"] if c["id"] == id_), None)


# ── rule 1: an open PR naming the row ────────────────────────────────────────────────────────────────────────────


def test_an_open_pr_naming_the_row_moves_it_to_fix_in_review():
    rep = S.sync(queue(row("FQ-022")), [pr(2610, body="FQ-022 wraps the tab strip")], now=NOW)
    item = rep["queue"]["items"][0]
    assert item["status"] == "fix_in_review" and item["pr"] == 2610 and item["head"] == "a" * 40
    assert item["history"][-1]["from"] == "queued" and item["history"][-1]["to"] == "fix_in_review"
    assert item["history"][-1]["at"] == NOW


def test_the_branch_name_is_enough_when_the_body_is_silent():
    rep = S.sync(queue(row("FQ-022")), [pr(2610, branch="wt/fq022-cio-tabs", body="")], now=NOW)
    assert rep["queue"]["items"][0]["status"] == "fix_in_review"


def test_an_assigned_row_moves_too():
    rep = S.sync(queue(row("FQ-022", status="assigned")), [pr(2610, body="FQ-022")], now=NOW)
    assert rep["queue"]["items"][0]["status"] == "fix_in_review"


def test_a_negated_mention_is_not_a_claim():
    """Rule 3 tells authors to name the rows they are NOT closing; that must not move those rows."""
    rep = S.sync(queue(row("FQ-033")),
                 [pr(2610, branch="wt/elsewhere", body="Closes FQ-022.\nNot closing FQ-033 — work pipeline panel is cc6's.")],
                 now=NOW)
    assert rep["changed"] == 0


def test_a_row_with_no_pr_is_left_alone():
    rep = S.sync(queue(row("FQ-022")), [pr(2610, branch="wt/elsewhere", body="FQ-039")], now=NOW)
    assert rep["changed"] == 0 and rep["queue"]["items"][0]["status"] == "queued"


def test_the_newest_pr_wins_when_a_row_has_two():
    rep = S.sync(queue(row("FQ-022")), [pr(2600, body="FQ-022"), pr(2610, body="FQ-022")], now=NOW)
    assert rep["queue"]["items"][0]["pr"] == 2610


# ── #2640 F1: a passing mention may not park or deliver a row ────────────────────────────────────────────────────
# cc-deepseek's whole-head BLOCK (2026-11-05T02:42Z): rows_named_by() treated any `FQ-0NN` in a body as that PR
# claiming the row, and "newest PR wins" let an unrelated, newer, closed PR outrank the real one — parking a row whose
# work was still open and removing it from what the dispatcher sends. These four cases pin the repair.


def test_an_unrelated_closed_pr_that_merely_mentions_a_row_does_not_park_it():
    """The reviewer's exact probe: 'This supersedes the old FQ-045 approach and closes nothing.'"""
    rep = S.sync(
        queue(row("FQ-045", status="fix_in_review", pr=2628, head="a" * 40)),
        [pr(2628, branch="wt/fq045-journal-tabs", body="FQ-045"),
         pr(2700, state="CLOSED", branch="wt/unrelated-cleanup",
            body="This supersedes the old FQ-045 approach and closes nothing.")],
        now=NOW,
    )
    assert rep["changed"] == 0, rep["changes"]
    assert rep["queue"]["items"][0]["status"] == "fix_in_review"
    assert rep["queue"]["items"][0]["pr"] == 2628


def test_a_mention_only_pr_cannot_retake_a_row_that_already_has_a_pr():
    """No open candidate: the mention-only closed PR is the only one left, and it still may not move the row."""
    rep = S.sync(
        queue(row("FQ-045", status="fix_in_review", pr=2628)),
        [pr(2700, state="CLOSED", branch="wt/unrelated-cleanup", body="FQ-045 came up in passing.")],
        now=NOW,
    )
    assert rep["changed"] == 0, rep["changes"]
    assert rep["queue"]["items"][0]["status"] == "fix_in_review"


def test_an_open_claiming_pr_beats_a_newer_closed_mentioning_pr():
    rep = S.sync(
        queue(row("FQ-045")),
        [pr(2628, branch="wt/fq045-journal-tabs", body=""),
         pr(2700, state="CLOSED", branch="wt/unrelated-cleanup", body="Mentions FQ-045 in prose.")],
        now=NOW,
    )
    item = rep["queue"]["items"][0]
    assert item["status"] == "fix_in_review" and item["pr"] == 2628


def test_a_closed_pr_that_claims_the_row_still_parks_it():
    """Preferring claims must not disable rule 4: a closed PR that says it closes the row still parks it."""
    rep = S.sync(
        queue(row("FQ-045", status="fix_in_review", pr=2628)),
        [pr(2628, state="CLOSED", branch="wt/fq045-journal-tabs", body="Closes FQ-045.")],
        now=NOW,
    )
    assert rep["queue"]["items"][0]["status"] == "parked"


def test_the_declaration_and_the_branch_are_what_claim_a_row():
    assert S.rows_claimed_by(pr(1, branch="wt/fq045-journal-tabs", body="")) == {"FQ-045"}
    assert S.rows_claimed_by(pr(1, branch="wt/elsewhere", body="Closes FQ-045.")) == {"FQ-045"}
    assert S.rows_claimed_by(pr(1, branch="wt/elsewhere", body="FQ-045 came up in passing.")) == set()
    assert S.rows_named_by(pr(1, branch="wt/elsewhere", body="FQ-045 came up in passing.")) == {"FQ-045"}


# ── rules 3 and 4: merged, and closed without merging ───────────────────────────────────────────────────────────


def test_a_merged_pr_marks_the_row_delivered_with_its_merge_commit():
    rep = S.sync(queue(row("FQ-022", status="fix_in_review", pr=2610)),
                 [pr(2610, state="MERGED", merge="b" * 40)], now=NOW)
    item = rep["queue"]["items"][0]
    assert item["status"] == "delivered" and item["head"] == "b" * 40


# ── QS1 (cx-openai BLOCK at f10e73cb4): a first observation may be after the merge ───────────────────────────────
# The tool is the only writer of these statuses and it runs on demand, so a row can be seen for the first time once its
# PR has already merged. Handling MERGED only inside `fix_in_review` left such a row queued/assigned — dispatchable —
# for ever, which is the exact failure the tool exists to prevent.


@pytest.mark.parametrize("status", ["queued", "assigned", "fix_in_review"])
def test_a_row_whose_pr_already_merged_is_delivered_whatever_it_started_as(status):
    rep = S.sync(queue(row("FQ-021", status=status, **({"pr": 2620} if status != "queued" else {}))),
                 [pr(2620, state="MERGED", branch="wt/fq021-example", body="Closes FQ-021.", merge="e" * 40)],
                 now=NOW)
    item = rep["queue"]["items"][0]
    assert item["status"] == "delivered", (status, rep["changes"])
    assert item["pr"] == 2620 and item["head"] == "e" * 40, "the merge commit is the recorded head"
    assert item["history"][-1]["from"] == status and item["history"][-1]["to"] == "delivered"


def test_the_merged_catch_up_is_idempotent():
    first = S.sync(queue(row("FQ-021")),
                   [pr(2620, state="MERGED", branch="wt/fq021-example", body="Closes FQ-021.", merge="e" * 40)], now=NOW)
    assert first["changed"] == 1
    again = S.sync(first["queue"],
                   [pr(2620, state="MERGED", branch="wt/fq021-example", body="Closes FQ-021.", merge="e" * 40)], now=NOW)
    assert again["changed"] == 0, again["changes"]


def test_a_decision_is_still_never_overwritten_by_a_merged_pr():
    rep = S.sync(queue(row("FQ-021", status="HELD_pending_operator_mockup_approval")),
                 [pr(2620, state="MERGED", branch="wt/fq021-example", body="Closes FQ-021.", merge="e" * 40)], now=NOW)
    assert rep["changed"] == 0


def test_a_closed_pr_parks_the_row():
    rep = S.sync(queue(row("FQ-094", status="fix_in_review", pr=2636)),
                 [pr(2636, state="CLOSED", branch="wt/fq094-risk-verdict", body="FQ-094")], now=NOW)
    assert rep["queue"]["items"][0]["status"] == "parked"


def test_a_moved_head_is_recorded_once():
    rep = S.sync(queue(row("FQ-097", status="fix_in_review", pr=2612, head="c" * 40)),
                 [pr(2612, head="d" * 40, body="FQ-097")], now=NOW)
    item = rep["queue"]["items"][0]
    assert item["head"] == "d" * 40 and item["status"] == "fix_in_review"
    again = S.sync(rep["queue"], [pr(2612, head="d" * 40, body="FQ-097")], now=NOW)
    assert again["changed"] == 0, "an unchanged head must not append history every run"


# ── what it must never touch ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["HELD_pending_operator_mockup_approval", "delivered", "parked",
                                    "closed_no_longer_reproduces", "closed_wrong_premise", "blocked_holder"])
def test_a_decision_is_never_overwritten(status):
    rep = S.sync(queue(row("FQ-094", status=status)), [pr(2636, body="FQ-094")], now=NOW)
    assert rep["changed"] == 0 and rep["queue"]["items"][0]["status"] == status


def test_blocked_holder_is_not_cleared_by_an_unrelated_open_pr():
    rep = S.sync(queue(row("FQ-085", status="blocked_holder")), [pr(9999, body="FQ-085")], now=NOW)
    assert rep["changed"] == 0


# ── hygiene ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_input_document_is_not_mutated():
    q = queue(row("FQ-022"))
    S.sync(q, [pr(2610, body="FQ-022")], now=NOW)
    assert q["items"][0]["status"] == "queued" and "history" not in q["items"][0]


def test_the_document_clock_and_source_advance_only_on_a_change():
    q = queue(row("FQ-022"))
    same = S.sync(q, [], now=NOW)
    assert same["queue"]["as_of"] == q["as_of"]
    moved = S.sync(q, [pr(2610, body="FQ-022")], now=NOW)
    assert moved["queue"]["as_of"] == NOW and S.AUTHOR in moved["queue"]["status_source"]


def test_a_dry_run_writes_nothing(tmp_path, monkeypatch):
    p = tmp_path / "q.json"
    p.write_text(json.dumps(queue(row("FQ-022"))), encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    monkeypatch.setattr(S, "gh_pr_list", lambda *a, **k: [pr(2610, body="FQ-022")])
    assert S.main(["--queue", str(p)]) == 0
    assert p.read_text(encoding="utf-8") == before


def test_apply_writes_a_backup_before_the_queue(tmp_path, monkeypatch):
    p = tmp_path / "q.json"
    p.write_text(json.dumps(queue(row("FQ-022"))), encoding="utf-8")
    monkeypatch.setattr(S, "gh_pr_list", lambda *a, **k: [pr(2610, body="FQ-022")])
    assert S.main(["--queue", str(p), "--apply"]) == 0
    assert json.loads(p.read_text(encoding="utf-8"))["items"][0]["status"] == "fix_in_review"
    backups = [x for x in tmp_path.iterdir() if ".bak-audit_queue_status-" in x.name]
    assert len(backups) == 1, "an apply must leave the previous queue recoverable"


def test_it_reads_nothing_but_gh_pr_list():
    src = (ROOT / "scripts" / "audit_queue_status.py").read_text(encoding="utf-8")
    assert "subprocess.run(argv" in src
    assert "requests" not in src and "urllib" not in src
    assert '"gh", "pr", "list"' in src or "'gh', 'pr', 'list'" in src
