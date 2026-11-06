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


# ── QS2 (cx-openai BLOCK at 9a6cc70d2): the same catch-up for a PR closed WITHOUT merging ──────────────────────


@pytest.mark.parametrize("status", ["queued", "assigned", "fix_in_review"])
def test_a_row_whose_pr_was_closed_without_merging_is_parked_whatever_it_started_as(status):
    rep = S.sync(queue(row("FQ-031", status=status, **({"pr": 2640} if status != "queued" else {}))),
                 [pr(2640, state="CLOSED", branch="wt/fq031-example", body="Closes FQ-031.")], now=NOW)
    item = rep["queue"]["items"][0]
    assert item["status"] == "parked", (status, rep["changes"])
    assert item["pr"] == 2640
    assert item["history"][-1]["from"] == status and item["history"][-1]["to"] == "parked"


def test_the_closed_catch_up_is_idempotent():
    first = S.sync(queue(row("FQ-031")),
                   [pr(2640, state="CLOSED", branch="wt/fq031-example", body="Closes FQ-031.")], now=NOW)
    assert first["changed"] == 1
    again = S.sync(first["queue"],
                   [pr(2640, state="CLOSED", branch="wt/fq031-example", body="Closes FQ-031.")], now=NOW)
    assert again["changed"] == 0, again["changes"]


def test_a_decision_is_still_never_overwritten_by_a_closed_pr():
    rep = S.sync(queue(row("FQ-031", status="delivered", pr=2640)),
                 [pr(2640, state="CLOSED", branch="wt/fq031-example", body="Closes FQ-031.")], now=NOW)
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


# ── QS3 / QS4 (cx-openai-2 and cx-openai-5 at 0c2614145) ────────────────────────────────────────────────────────


def test_a_mention_only_pr_does_not_deliver_an_unassociated_row():
    """QS3: 'FQ-021 came up in passing' in an unrelated, merged PR must not close or move the row."""
    rep = S.sync(queue(row("FQ-021")),
                 [pr(2700, state="MERGED", branch="wt/unrelated-cleanup", body="FQ-021 came up in passing.",
                     merge="f" * 40)], now=NOW)
    assert rep["changed"] == 0, rep["changes"]
    assert rep["queue"]["items"][0]["status"] == "queued"


def test_a_mention_only_pr_does_not_park_an_unassociated_row():
    rep = S.sync(queue(row("FQ-021", status="assigned")),
                 [pr(2700, state="CLOSED", branch="wt/unrelated-cleanup", body="FQ-021 came up in passing.")],
                 now=NOW)
    assert rep["changed"] == 0, rep["changes"]


def test_an_apply_refuses_when_the_queue_changed_during_collection(tmp_path, monkeypatch):
    """QS4: a concurrent writer's decision (e.g. an operator HELD_*) must not be overwritten by a stale snapshot."""
    p = tmp_path / "q.json"
    p.write_text(json.dumps(queue(row("FQ-021"), row("FQ-099", status="queued"))), encoding="utf-8")

    def concurrent_collector(*_a, **_k):
        # another session decides FQ-099 while this run is waiting on GitHub
        doc = json.loads(p.read_text(encoding="utf-8"))
        for item in doc["items"]:
            if item["id"] == "FQ-099":
                item["status"] = "HELD_operator_decision"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return [pr(2700, branch="wt/fq021-example", body="Closes FQ-021.")]

    monkeypatch.setattr(S, "gh_pr_list", concurrent_collector)
    rc = S.main(["--queue", str(p), "--apply"])
    assert rc == 2, "an apply must refuse rather than overwrite a concurrent write"
    after = {i["id"]: i["status"] for i in json.loads(p.read_text(encoding="utf-8"))["items"]}
    assert after["FQ-099"] == "HELD_operator_decision", "the concurrent operator decision was overwritten"
    assert after["FQ-021"] == "queued", "the refused run must not have applied its own change either"


def test_an_apply_still_writes_when_nothing_else_changed(tmp_path, monkeypatch):
    p = tmp_path / "q.json"
    p.write_text(json.dumps(queue(row("FQ-021"))), encoding="utf-8")
    monkeypatch.setattr(S, "gh_pr_list", lambda *a, **k: [pr(2700, branch="wt/fq021-example", body="Closes FQ-021.")])
    assert S.main(["--queue", str(p), "--apply"]) == 0
    assert json.loads(p.read_text(encoding="utf-8"))["items"][0]["status"] == "fix_in_review"


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


# ── #2640 B1 (cc-deepseek-5 P2): negation is scoped to the row it governs, not the whole line ───────────────────
# "Closes FQ-022; not closing FQ-033." used to drop the line, so FQ-022 was never claimed and a queued row stayed
# dispatchable — the duplicate-work failure the tool exists to prevent. Rule 3 tells authors to name rows they are
# not closing, so mixed claim/disclaimer lines are a natural authoring form.


@pytest.mark.parametrize("body, claimed, named", [
    ("Closes FQ-022; not closing FQ-033.", {"FQ-022"}, {"FQ-022"}),
    ("Closes FQ-022 and is not touching FQ-033.", {"FQ-022"}, {"FQ-022"}),
    ("Closes FQ-058. Does not close FQ-002 (the `MISSING MARKET` label) — that is #2637.",
     {"FQ-058"}, {"FQ-058"}),
    # a negation binds the first verb after it; it must not bleed onto a later claim in the same sentence
    ("Not closing FQ-033 but closes FQ-022.", {"FQ-022"}, {"FQ-022"}),
])
def test_a_negation_only_removes_the_row_it_governs(body, claimed, named):
    cand = pr(2622, branch="wt/elsewhere", body=body)
    assert S.rows_claimed_by(cand) == claimed
    assert S.rows_named_by(cand) == named


@pytest.mark.parametrize("body", [
    "Does not close FQ-021 or fix FQ-022.",
    "does not fix FQ-022 or close FQ-023.",
    "Never closed FQ-021 and did not fix FQ-022.",
])
def test_a_negation_carries_across_coordinated_action_verbs(body):
    """cx-openai D52 refresh at 13ee582e4 (the ONE remaining item): a negation governs a coordinated continuation too.

    "Does not close FQ-021 or fix FQ-022" negates BOTH verbs, so neither row is claimed and neither is treated as
    delivered. Before this, FQ-022 came back claimed from a sentence that disclaims it.
    """
    cand = pr(2622, branch="wt/elsewhere", body=body)
    assert S.rows_claimed_by(cand) == set(), S.rows_claimed_by(cand)
    assert S.rows_named_by(cand) == set(), S.rows_named_by(cand)


def test_a_contrast_still_breaks_the_negation_carry():
    """The control: "but" is not a coordinator here, so the later claim survives (the B1 rule, kept)."""
    cand = pr(2622, branch="wt/elsewhere", body="Not closing FQ-033 but closes FQ-022.")
    assert S.rows_claimed_by(cand) == {"FQ-022"}


def test_a_claim_on_a_mixed_line_still_moves_its_queued_row():
    rep = S.sync(queue(row("FQ-022")), [pr(2622, body="Closes FQ-022; not closing FQ-033.")], now=NOW)
    assert rep["changed"] == 1, rep["changes"]
    assert rep["queue"]["items"][0]["status"] == "fix_in_review"


def test_the_live_2622_mixed_line_claims_fq058_and_not_fq002():
    """The corpus instance from the review: a real dropped claim, not a synthetic shape."""
    body = "Closes FQ-058. Does not close FQ-002 (the `MISSING MARKET` label) — that is #2637."
    cand = pr(2622, branch="wt/elsewhere", body=body)
    assert S.rows_claimed_by(cand) == {"FQ-058"}
    assert "FQ-002" not in S.rows_named_by(cand)


# ── #2640 B2 (cc-deepseek-5 P2): a full window is not the whole PR universe ─────────────────────────────────────


def _rest_pr(number, *, state="open", merged_at=None, merge_sha=None, branch="wt/unrelated", body=""):
    return {"number": number, "state": state, "merged_at": merged_at, "merge_commit_sha": merge_sha,
            "head": {"ref": branch, "sha": "b" * 40}, "body": body}


def test_a_full_gh_window_is_paged_through_the_rest_census():
    window = [pr(2600 + i) for i in range(3)]
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[:3] == ["gh", "pr", "list"]:
            return json.dumps(window)
        return json.dumps([_rest_pr(2200, state="closed", merged_at="2026-11-01T00:00:00Z", merge_sha="c" * 40)])

    rows = S.gh_pr_list(runner, limit=3)
    assert calls[1][:2] == ["gh", "api"], calls
    assert {r["number"] for r in rows} == {2600, 2601, 2602, 2200}, "the older PR outside the window was lost"
    older = next(r for r in rows if r["number"] == 2200)
    assert older["state"] == "MERGED" and older["mergeCommit"] == {"oid": "c" * 40}


def test_a_census_that_exceeds_the_pagination_cap_is_refused_not_truncated():
    window = [pr(2600 + i) for i in range(3)]
    full_page = [_rest_pr(4000 + i) for i in range(S.REST_PAGE_SIZE)]

    def runner(argv):
        return json.dumps(window if argv[:3] == ["gh", "pr", "list"] else full_page)

    with pytest.raises(S.FetchIncomplete):
        S.gh_pr_list(runner, limit=3)


def test_an_incomplete_census_refuses_apply_without_writing(tmp_path, monkeypatch):
    p = tmp_path / "q.json"
    p.write_text(json.dumps(queue(row("FQ-021"))), encoding="utf-8")

    def boom(*_a, **_k):
        raise S.FetchIncomplete("truncated census")

    monkeypatch.setattr(S, "gh_pr_list", boom)
    assert S.main(["--queue", str(p), "--apply"]) == 2
    assert json.loads(p.read_text(encoding="utf-8"))["items"][0]["status"] == "queued"


# ── #2640 N2 (cc-deepseek-5 P3): a non-list payload is unknown, not "0 change(s)" ────────────────────────────────


def test_a_non_list_gh_payload_is_unknown_not_zero_changes():
    with pytest.raises(S.FetchIncomplete):
        S.gh_pr_list(lambda argv: json.dumps({"message": "API rate limit exceeded"}))


# ── #2640 QS4 residual / N1 (cx-openai-5 P1, cx-openai-2, cc-deepseek-5 P3): a peer write after the comparison ──
# The pre-backup comparison is not enough on its own: a writer landing between it and the replacement used to be
# overwritten. The write boundary now re-checks after the backup I/O and replaces atomically under an exclusive lock.


def test_an_apply_refuses_a_peer_write_between_the_comparison_and_the_write(tmp_path, monkeypatch):
    p = tmp_path / "q.json"
    p.write_text(json.dumps(queue(row("FQ-021"), row("FQ-099", status="queued"))), encoding="utf-8")
    real_backup = S._backup
    injected = {"done": False}

    def injecting_backup(path):
        if not injected["done"]:
            injected["done"] = True
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            for item in doc["items"]:
                if item["id"] == "FQ-099":
                    item["status"] = "HELD_operator_decision"
            Path(path).write_text(json.dumps(doc), encoding="utf-8")
        return real_backup(path)

    monkeypatch.setattr(S, "_backup", injecting_backup)
    monkeypatch.setattr(S, "gh_pr_list",
                        lambda *a, **k: [pr(2700, branch="wt/fq021-example", body="Closes FQ-021.")])
    assert S.main(["--queue", str(p), "--apply"]) == 2
    after = {i["id"]: i["status"] for i in json.loads(p.read_text(encoding="utf-8"))["items"]}
    assert after["FQ-099"] == "HELD_operator_decision", "a peer write during the write boundary was overwritten"
    assert after["FQ-021"] == "queued", "the refused run must not have applied its own change either"


# ── #2640 N4 (cc-deepseek-5 P3): a refused --json --apply must not print a report ───────────────────────────────


def test_a_refused_json_apply_prints_no_report(tmp_path, monkeypatch, capsys):
    p = tmp_path / "q.json"
    p.write_text(json.dumps(queue(row("FQ-021"), row("FQ-099", status="queued"))), encoding="utf-8")

    def concurrent_collector(*_a, **_k):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for item in doc["items"]:
            if item["id"] == "FQ-099":
                item["status"] = "HELD_operator_decision"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return [pr(2700, branch="wt/fq021-example", body="Closes FQ-021.")]

    monkeypatch.setattr(S, "gh_pr_list", concurrent_collector)
    assert S.main(["--queue", str(p), "--apply", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "", "a stdout-only consumer must not see a report for a write that did not happen"
    assert "REFUSED" in captured.err


# ── #2640 CX1..CX3 (codex-cloud BLOCK at 7a0d5a0f7): declaration reach, recorded association, mention ranking ───


def test_a_multi_row_closing_declaration_claims_every_row_it_governs():
    """CX1: 'Closes FQ-021 and FQ-022.' declares both rows, not only the first one the regex touches."""
    cand = pr(2622, branch="wt/elsewhere", body="Closes FQ-021 and FQ-022.")
    assert S.rows_claimed_by(cand) == {"FQ-021", "FQ-022"}
    rep = S.sync(queue(row("FQ-021"), row("FQ-022")),
                 [pr(2622, state="MERGED", branch="wt/elsewhere", body="Closes FQ-021 and FQ-022.",
                     merge="e" * 40)], now=NOW)
    status = {i["id"]: i["status"] for i in rep["queue"]["items"]}
    assert status == {"FQ-021": "delivered", "FQ-022": "delivered"}, rep["changes"]


def test_a_row_local_negation_disclaims_only_the_row_it_names():
    """cx-openai triage on f0ae3822f: "Closes FQ-021, not FQ-022." claims FQ-021 and must NOT claim FQ-022."""
    assert S.rows_claimed_by(pr(2700, branch="wt/elsewhere", body="Closes FQ-021, not FQ-022.")) == {"FQ-021"}
    assert S.rows_claimed_by(pr(2700, branch="wt/elsewhere",
                                body="Closes FQ-021, FQ-023 and not FQ-022.")) == {"FQ-021", "FQ-023"}
    assert S.rows_claimed_by(pr(2700, branch="wt/elsewhere",
                                body="Closes FQ-021 and FQ-022.")) == {"FQ-021", "FQ-022"}


def test_a_row_local_negation_does_not_park_or_deliver_the_disclaimed_row():
    rep = S.sync(queue(row("FQ-022", status="fix_in_review", pr=2600)),
                 [pr(2600, state="MERGED", branch="wt/elsewhere", body="Closes FQ-021, not FQ-022.", merge="a" * 40)],
                 now=NOW)
    assert rep["changed"] == 0, rep["changes"]


def test_a_multi_row_declaration_still_negates_the_row_it_disclaims():
    """CX1 remedy: the later rows are claimed without losing the per-row negation check."""
    cand = pr(2622, branch="wt/elsewhere", body="Closes FQ-021 and FQ-022; not closing FQ-033.")
    assert S.rows_claimed_by(cand) == {"FQ-021", "FQ-022"}
    assert "FQ-033" not in S.rows_named_by(cand)


def test_a_recorded_pr_decides_after_its_body_stops_naming_the_row():
    """CX2: the queue's recorded association is evidence even when the PR body/branch no longer name the row."""
    rep = S.sync(queue(row("FQ-021", status="queued", pr=100)),
                 [pr(100, state="MERGED", branch="wt/generic-cleanup", body="Refactor only.", merge="e" * 40)],
                 now=NOW)
    item = rep["queue"]["items"][0]
    assert item["status"] == "delivered" and item["pr"] == 100, rep["changes"]


def test_a_recorded_pr_closed_without_merge_parks_the_row_after_its_body_changes():
    """CX2: the same recorded association carries rule 4, not only rule 3."""
    rep = S.sync(queue(row("FQ-031", status="fix_in_review", pr=100)),
                 [pr(100, state="CLOSED", branch="wt/generic-cleanup", body="Refactor only.")], now=NOW)
    item = rep["queue"]["items"][0]
    assert item["status"] == "parked" and item["pr"] == 100, rep["changes"]


def test_an_open_mention_does_not_outrank_the_recorded_pr():
    """CX3: with no claimant, filter mention-only rows to the recorded association before ranking."""
    rep = S.sync(queue(row("FQ-021", status="fix_in_review", pr=100)),
                 [pr(100, state="MERGED", branch="wt/generic-cleanup", body="FQ-021", merge="e" * 40),
                  pr(101, state="OPEN", branch="wt/unrelated-cleanup", body="FQ-021 came up in passing.")],
                 now=NOW)
    item = rep["queue"]["items"][0]
    assert item["status"] == "delivered" and item["pr"] == 100, rep["changes"]


def test_a_replacement_pr_at_the_same_commit_takes_the_association():
    """Cloud at b53cd7bb1: #101 replaces #100 at the same commit. `choose_pr` picks #101, but `plan` kept the
    association on #100 because the head had not changed; when #101 merged, the closed #100 won the
    recorded-association tie-break and the row parked instead of delivering."""
    rep = S.sync(
        queue(row("FQ-022", status="fix_in_review", pr=100, head="a" * 40)),
        [pr(100, state="OPEN", branch="wt/generic-100", body="Refactor only.", head="a" * 40),
         pr(101, state="OPEN", branch="wt/generic-101", body="Closes FQ-022.", head="a" * 40)],
        now=NOW,
    )
    item = rep["queue"]["items"][0]
    assert item["pr"] == 101, rep["changes"]
    merged = S.sync(
        rep["queue"],
        [pr(100, state="CLOSED", branch="wt/generic-100", body="Refactor only."),
         pr(101, state="MERGED", branch="wt/generic-101", body="Closes FQ-022.", head="a" * 40, merge="b" * 40)],
        now=NOW,
    )
    delivered = merged["queue"]["items"][0]
    assert delivered["status"] == "delivered" and delivered["pr"] == 101, merged["changes"]


def test_a_verb_level_disclaimer_stops_the_recorded_pr_closing_the_row():
    """Cloud at b53cd7bb1: `Not closing FQ-022.` was refused by `rows_named_by`, but `sync` re-added the row's
    recorded PR and `_disclaimed_rows` only saw a row-level negation — so that PR delivered a row it says it is not
    closing."""
    for body in ("Not closing FQ-022.", "Does not close FQ-022."):
        rep = S.sync(
            queue(row("FQ-022", status="fix_in_review", pr=100)),
            [pr(100, state="MERGED", branch="wt/generic-cleanup", body=body, merge="c" * 40)],
            now=NOW,
        )
        assert rep["changed"] == 0, (body, rep["changes"])
    assert S._disclaimed_rows(pr(1, branch="wt/generic-cleanup", body="Does not close FQ-022.")) == {"FQ-022"}
    # the row-level form still works, and an ordinary declaration still claims
    assert S._disclaimed_rows(pr(1, branch="wt/generic-cleanup", body="Closes FQ-021, not FQ-022.")) == {"FQ-022"}
    assert S._disclaimed_rows(pr(1, branch="wt/generic-cleanup", body="Closes FQ-022.")) == set()


def test_the_default_queue_path_follows_the_persistent_state_root(monkeypatch, tmp_path):
    """Cloud at b53cd7bb1: DEFAULT_QUEUE was built from `Path.home()`, so a non-default
    TRADEAI_PERSISTENT_STATE_ROOT moved the queue the served reader uses and left this CLI on another file."""
    monkeypatch.delenv("AUDIT_FIX_QUEUE_PATH", raising=False)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    assert S._default_queue_path() == tmp_path / "data" / "coordination" / "coordinator" / "AUDIT_FIX_QUEUE.json"
    monkeypatch.setenv("AUDIT_FIX_QUEUE_PATH", str(tmp_path / "custom.json"))
    assert S._default_queue_path() == tmp_path / "custom.json"


# ── #2640 B1 (post-merge): a row the PR's own text calls OPEN is disclaimed, and the filter applies to a CLAIM ──
# The merged tool delivered FQ-104 via #2673 although #2673's body says "FQ-104 stays open: this makes the
# opinions available, it does not yet render them", and it will deliver FQ-114 (#2657 "remains open pending
# independent and served acceptance") and FQ-076 (#2606 "remains open until served acceptance") on their merges.
# Two defects, one live class: the disclaimer grammar knew only negation words, and `choose_pr` applied the
# disclaimer filter only to the recorded association, never to a candidate that CLAIMS the row (a branch name
# claims unconditionally). "delivered" is a decision state that is never re-derived, so each wrong delivery
# removes real work from dispatch permanently.


@pytest.mark.parametrize("row,body", [
    # the three live rows, verbatim
    ("FQ-104", "- FQ-104 stays open: this makes the opinions available, it does not yet render them."),
    ("FQ-114", "FQ-114 remains open pending independent and served acceptance."),
    ("FQ-076", "FQ-076 remains open until served acceptance."),
    # the same declaration in the other common forms
    ("FQ-077", "FQ-077 is still open; the render half lands in a follow-up PR."),
    ("FQ-078", "FQ-078 is not yet complete: the second half is a separate PR."),
    ("FQ-079", "The visible cutover is the next step of FQ-079, not this one."),
])
def test_a_row_the_body_calls_open_is_disclaimed_and_not_claimed(row, body):
    cand = pr(2673, branch="wt/unrelated", body=body)
    assert row in S._disclaimed_rows(cand), body
    assert row not in S.rows_claimed_by(cand), body


def test_a_merged_pr_does_not_deliver_a_row_its_own_text_calls_open():
    """The live FQ-104 shape at #2673: the branch names the row, the body says the row stays open."""
    body = (
        "The per-symbol aggregate now keeps both opinions instead of only the winner's.\n\n"
        "The visible cutover is the next step of FQ-104, not this one.\n"
        "- FQ-104 stays open: this makes the opinions available, it does not yet render them."
    )
    cand = pr(2673, state="MERGED", branch="wt/fq104-per-account-opinions-20261104", body=body, merge="f" * 40)
    rep = S.sync(queue(row("FQ-104", status="fix_in_review", pr=2673)), [cand], now=NOW)
    assert rep["changed"] == 0, rep["changes"]
    assert rep["queue"]["items"][0]["status"] == "fix_in_review"


def test_the_open_declaration_filters_a_candidate_that_claims_the_row():
    """The mechanism: a branch-name claim must not outrun the PR's own sentence that the row is open."""
    cand = pr(2673, state="MERGED", branch="wt/fq104-per-account-opinions-20261104",
              body="FQ-104 stays open: the next half is a separate PR.", merge="f" * 40)
    assert S.choose_pr(row("FQ-104", status="fix_in_review", pr=2673), [cand]) is None


def test_an_ordinary_claim_still_delivers_the_row():
    """The control: no open declaration, so a merged claiming PR still delivers (over-tightening would freeze the queue)."""
    cand = pr(2700, state="MERGED", branch="wt/fq104-finish", body="Closes FQ-104.", merge="f" * 40)
    rep = S.sync(queue(row("FQ-104")), [cand], now=NOW)
    assert rep["queue"]["items"][0]["status"] == "delivered"


def test_prose_that_merely_says_open_pr_is_not_a_declaration():
    """An 'open PR' in a sentence about the tool is prose, not a statement about the row."""
    cand = pr(2701, branch="wt/unrelated", body="An open PR that names FQ-104 still moves it to fix_in_review.")
    assert S._disclaimed_rows(cand) == set()
    assert "FQ-104" in S.rows_named_by(cand)


@pytest.mark.parametrize("fq,prn,branch,body", [
    ("FQ-104", 2673, "wt/fq104-per-account-opinions-20261104",
     "- FQ-104 stays open: this makes the opinions available, it does not yet render them."),
    ("FQ-114", 2657, "wt/fq114-top-eligibility-20261104",
     "FQ-114 remains open pending independent and served acceptance."),
    ("FQ-076", 2606, "wt/fq076-watchlist-reasons",
     "FQ-076 remains open until served acceptance."),
])
def test_each_live_instance_survives_its_pr_merging(fq, prn, branch, body):
    """The three live rows, end to end and with their real branch names: MERGED at the head that named them.

    Reverting the claim filter must redden all three — before the fix, the branch name claimed the row and
    `choose_pr` never consulted the disclaimer, so `plan()` delivered it (#2640 B1).
    """
    cand = pr(prn, state="MERGED", branch=branch, body=body, merge="f" * 40)
    rep = S.sync(queue(row(fq, status="fix_in_review", pr=prn)), [cand], now=NOW)
    assert rep["changed"] == 0, (fq, rep["changes"])
    assert rep["queue"]["items"][0]["status"] == "fix_in_review"
