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


# ── rules 3 and 4: merged, and closed without merging ───────────────────────────────────────────────────────────


def test_a_merged_pr_marks_the_row_delivered_with_its_merge_commit():
    rep = S.sync(queue(row("FQ-022", status="fix_in_review", pr=2610)),
                 [pr(2610, state="MERGED", merge="b" * 40)], now=NOW)
    item = rep["queue"]["items"][0]
    assert item["status"] == "delivered" and item["head"] == "b" * 40


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
