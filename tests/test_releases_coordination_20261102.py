"""Releases coordination view: head-bound evidence only, no inference, source time kept separate.

The Releases board gains one additive envelope. These tests pin the four rules that matter: evidence is
bound to an exact head, nothing is inferred from `merge_state`/`is_draft`, `as_of` is the source's own
time rather than when we read, and every entry is labelled as reported evidence rather than approval.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import releases_coordination as rc  # noqa: E402

HEAD = "a" * 40
OTHER = "b" * 40
NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)


def _ledger(tmp_path: Path, *rows: dict) -> Path:
    p = tmp_path / "ledger.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _review(pr=2474, head=HEAD, verdict="MERGE", session="cc3", at="2026-11-02T17:00:00Z"):
    return {"kind": rc.REVIEW_KIND, "pr_number": pr, "head_sha": head, "verdict": verdict,
            "reviewer_session": session, "evidence_class": rc.EVIDENCE_CLASS,
            "receipt_path": "inbox/cc3/r.md", "receipt_sha256": "deadbeef", "observed_at": at}


def _ci(pr=2474, head=HEAD, state="GREEN", at="2026-11-02T17:30:00Z"):
    return {"kind": rc.CI_KIND, "pr_number": pr, "head_sha": head, "state": state,
            "observed_at": at, "source": "GitHub Actions", "workflows": [{"name": "ci-gate", "status": "success"}]}


def _pr(number=2474, head=HEAD, branch="wt/x", state="CLEAN", draft=False):
    return {"number": number, "head_sha": head, "branch": branch, "merge_state": state, "is_draft": draft}


def _claims(tmp_path: Path, *docs: dict) -> Path:
    d = tmp_path / "claims"
    d.mkdir(exist_ok=True)
    for i, doc in enumerate(docs):
        (d / f"c{i}.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


# ------------------------------------------------------------------ head binding
def test_evidence_for_another_head_is_a_gap_not_a_green(tmp_path):
    ledger = _ledger(tmp_path, _review(head=OTHER), _ci(head=OTHER, state="GREEN"))
    out = rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)
    work = out["work"][2474]
    assert work["review"]["state"] == "UNKNOWN" and work["review"]["gap"] == "stale_review_for_other_head"
    assert work["ci"]["state"] == "UNKNOWN" and work["ci"]["gap"] == "stale_ci_for_other_head"


def test_matching_head_attaches_the_evidence(tmp_path):
    ledger = _ledger(tmp_path, _review(), _ci())
    work = rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]
    assert work["review"]["state"] == "MERGE" and work["review"]["head_sha"] == HEAD
    assert work["ci"]["state"] == "GREEN" and work["ci"]["head_sha"] == HEAD
    assert work["review"]["evidence_class"] == rc.EVIDENCE_CLASS
    assert work["ci"]["evidence_class"] == rc.EVIDENCE_CLASS


# ------------------------------------------------------------------ no inference
def test_a_clean_merge_state_is_not_ci_evidence_and_a_ready_pr_is_not_a_review(tmp_path):
    ledger = _ledger(tmp_path)  # no typed records at all
    work = rc.build(ledger, _claims(tmp_path), [_pr(state="CLEAN", draft=False)], now=NOW)["work"][2474]
    assert work["ci"]["state"] == "UNKNOWN" and work["ci"]["gap"] == "no_ci_observation"
    assert work["review"]["state"] == "UNKNOWN" and work["review"]["gap"] == "no_review_record"


def test_a_freeform_ledger_note_is_not_evidence(tmp_path):
    note = {"ts": "2026-11-02T17:00:00Z", "by": "codex", "kind": "dispatch", "detail": "PR 2474 lookgreen"}
    out = rc.build(_ledger(tmp_path, note), _claims(tmp_path), [_pr()], now=NOW)["work"][2474]
    assert out["ci"]["state"] == "UNKNOWN" and out["review"]["state"] == "UNKNOWN"


def test_an_unrecognised_ci_state_falls_back_to_unknown(tmp_path):
    out = rc.build(_ledger(tmp_path, _ci(state="OK")), _claims(tmp_path), [_pr()], now=NOW)["work"][2474]
    assert out["ci"]["state"] == "UNKNOWN"


# ------------------------------------------------------------------ source time vs read time
def test_as_of_is_the_source_time_and_captured_at_is_the_read_time(tmp_path):
    ledger = _ledger(tmp_path, _ci(at="2026-11-02T17:30:00Z"))
    claims = _claims(tmp_path, {"session": "s1", "branch": "wt/x", "task": "t", "status": "pr_open",
                                "heartbeat_at": "2026-11-02T17:10:00Z"})
    out = rc.build(ledger, claims, [_pr()], now=NOW)
    assert out["captured_at"] == "2026-11-02T18:00:00Z"
    assert out["as_of"] == "2026-11-02T17:30:00Z"       # the newest SOURCE time, not the read time
    assert out["as_of"] != out["captured_at"]


# ------------------------------------------------------------------ missing stores
def test_absent_stores_are_reported_not_faked(tmp_path):
    out = rc.build(tmp_path / "nope.jsonl", tmp_path / "no-claims", [_pr()], now=NOW)
    assert out["status"] == "UNAVAILABLE"
    assert {"ledger_absent", "claims_absent", "board_absent"} <= set(out["gaps"])
    assert out["work"][2474]["owner"] == "UNKNOWN"
    assert out["work"][2474]["publication_state"] == "UNKNOWN"


# ------------------------------------------------------------------ ownership / publication
def test_owner_and_a_head_difference_is_unknown_not_unpublished(tmp_path):
    """codex review of d14ffa86b: a stale claim head is not proof the work is unpublished."""
    claims = _claims(tmp_path, {"session": "s1", "branch": "wt/x", "task": "fix releases", "status": "claimed",
                                "head_sha": OTHER, "heartbeat_at": "2026-11-02T17:40:00Z",
                                "blocker": "needs grant", "next": "push"})
    work = rc.build(_ledger(tmp_path, _ci()), claims, [_pr()], now=NOW)["work"][2474]
    assert work["owner"] == "s1" and work["current_task"] == "fix releases"
    assert work["publication_state"] == "UNKNOWN"          # never inferred from a head difference alone
    assert work["local_head"] == OTHER and work["published_head"] == HEAD
    assert work["claim_head_recorded_at"] == "2026-11-02T17:40:00Z"   # the age a reader can judge
    assert work["blockers"] == ["needs grant"]


def test_an_equal_head_is_the_only_proof_of_publication(tmp_path):
    claims = _claims(tmp_path, {"session": "s1", "branch": "wt/x", "task": "t", "status": "claimed",
                                "head_sha": HEAD, "heartbeat_at": "2026-11-02T17:40:00Z"})
    assert rc.build(_ledger(tmp_path), claims, [_pr()], now=NOW)["work"][2474]["publication_state"] == "published"


def test_ended_and_done_claims_are_not_current_agents(tmp_path):
    claims = _claims(tmp_path,
                     {"session": "done1", "branch": "wt/y", "task": "old", "status": "done"},
                     {"session": "gone1", "branch": "wt/z", "task": "older", "status": "claimed",
                      "ended_at": "2026-11-02T10:00:00Z"},
                     {"session": "live1", "branch": "wt/x", "task": "now", "status": "active"})
    out = rc.build(_ledger(tmp_path), claims, [_pr()], now=NOW)
    assert [a["session"] for a in out["agents"]] == ["live1"]


def test_one_session_holding_two_claims_is_summarised_once_but_owns_both(tmp_path):
    """codex review 2026-11-02: per-PR ownership keeps every claim; only the primary summary dedupes."""
    claims = _claims(tmp_path,
                     {"session": "s1", "branch": "wt/a", "task": "one", "status": "active",
                      "heartbeat_at": "2026-11-02T17:00:00Z"},
                     {"session": "s1", "branch": "wt/b", "task": "two", "status": "active",
                      "heartbeat_at": "2026-11-02T17:50:00Z"})
    out = rc.build(_ledger(tmp_path), claims, [_pr()], now=NOW)
    # the agent list shows the session once, with its NEWEST claim
    rows = [a for a in out["agents"] if a["session"] == "s1"]
    assert len(rows) == 1 and rows[0]["branch"] == "wt/b"
    # ...but a PR on either branch still finds its owner
    for branch in ("wt/a", "wt/b"):
        work = rc.build(_ledger(tmp_path), claims, [_pr(branch=branch)], now=NOW)["work"][2474]
        assert work["owner"] == "s1", branch


def test_two_reviewers_count_as_two_independent_sessions(tmp_path):
    ledger = _ledger(tmp_path, _review(session="cc3"), _review(session="cc6", at="2026-11-02T17:05:00Z"))
    review = rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["review"]
    assert review["independent_reviewers"] == 2 and review["reviewers"] == ["cc3", "cc6"]


def test_one_reviewer_twice_is_still_one_session(tmp_path):
    ledger = _ledger(tmp_path, _review(session="cc3"), _review(session="cc3", at="2026-11-02T17:05:00Z"))
    assert rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["review"]["independent_reviewers"] == 1


# ───────────────────────────── review aggregation (codex review of d14ffa86b, 2026-11-02)
def test_all_block_is_block(tmp_path):
    ledger = _ledger(tmp_path, _review(session="cc3", verdict="BLOCK"), _review(session="cc6", verdict="BLOCK"))
    assert rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["review"]["state"] == "BLOCK"


def test_one_block_dominates_a_merge(tmp_path):
    ledger = _ledger(tmp_path, _review(session="cc3", verdict="MERGE"), _review(session="cc6", verdict="BLOCK"))
    assert rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["review"]["state"] == "BLOCK"


def test_a_later_reversal_counts(tmp_path):
    ledger = _ledger(tmp_path,
                     _review(session="cc3", verdict="MERGE", at="2026-11-02T16:00:00Z"),
                     _review(session="cc3", verdict="BLOCK", at="2026-11-02T17:00:00Z"))
    review = rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["review"]
    assert review["state"] == "BLOCK" and review["independent_reviewers"] == 1
    assert review["all_verdicts"] == ["MERGE", "BLOCK"]


def test_an_unknown_verdict_never_reads_as_merge(tmp_path):
    ledger = _ledger(tmp_path, _review(session="cc3", verdict="LOOKS-GOOD"))
    assert rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["review"]["state"] == "UNKNOWN"


def test_ci_evidence_carries_the_contract_as_of_field(tmp_path):
    ci = rc.build(_ledger(tmp_path, _ci(at="2026-11-02T17:30:00Z")), _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["ci"]
    assert ci["as_of"] == "2026-11-02T17:30:00Z" and ci["observed_at"] == ci["as_of"]


# ───────────────────────────── BOARD primary agents + worklog (codex, 2026-11-02)
BOARD_MD = """# COORDINATION BOARD

Updated: 2026-11-02T18:08:30Z by **codex** (x).

## Agents (tmux sessions)

| session | task now | branch / PR | next |
|---|---|---|---|
| cc-deepseek-2 | Releases status backend | local 7f76a6030 | finish join |
| cc-deepseek-4 | Releases frontend | #2484 | cards |

## Open PRs
"""


def _board(tmp_path: Path, text: str = BOARD_MD) -> Path:
    """BOARD.md sits beside ledger.jsonl in the real layout, so the fixtures do too."""
    p = tmp_path / "BOARD.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_the_primary_agent_list_comes_from_the_board_table(tmp_path):
    board = _board(tmp_path)
    out = rc.build(tmp_path / "ledger.jsonl", tmp_path / "no-claims", [_pr()], now=NOW)
    sessions = [a["session"] for a in out["agents"]]
    assert sessions == ["cc-deepseek-2", "cc-deepseek-4"]      # exactly the BOARD rows, no hardcoded list
    assert all(a["execution_state"] == "UNKNOWN" for a in out["agents"])  # assigned is not working
    assert all(a["as_of"] == "2026-11-02T18:08:30Z" for a in out["agents"])  # BOARD's own updated time


def test_historical_claims_are_not_listed_as_agents(tmp_path):
    board = _board(tmp_path)
    claims = _claims(tmp_path, *[{"session": f"s{i}", "branch": f"wt/{i}", "task": "t", "status": "active"}
                                 for i in range(145)])
    out = rc.build(tmp_path / "ledger.jsonl", claims, [_pr()], now=NOW)
    assert [a["session"] for a in out["agents"]] == ["cc-deepseek-2", "cc-deepseek-4"]


def test_a_board_session_with_a_live_claim_shows_working(tmp_path):
    board = _board(tmp_path)
    claims = _claims(tmp_path, {"session": "cc-deepseek-2", "branch": "wt/x", "task": "t", "status": "active",
                                "claim_id": "c0", "heartbeat_at": "2026-11-02T17:40:00Z"})
    agents = {a["session"]: a for a in rc.build(tmp_path / "ledger.jsonl", claims, [_pr()], now=NOW)["agents"]}
    assert agents["cc-deepseek-2"]["execution_state"] == "working"
    assert agents["cc-deepseek-4"]["execution_state"] == "UNKNOWN"


def test_a_worklog_supplies_blocker_and_next_when_the_claim_doc_does_not(tmp_path):
    board = _board(tmp_path)
    claims = _claims(tmp_path, {"session": "cc-deepseek-2", "branch": "wt/x", "task": "t", "status": "active",
                                "claim_id": "c0", "head_sha": HEAD})
    # The CANONICAL shape (codex, 2026-11-02): blockers under "## Blockers", next under "## Handoff"
    # as "- Next step:". A "next:" token anywhere is not the format and must not parse.
    (claims / "c0.worklog.md").write_text(
        "# Worklog\n\n## Blockers\n- waiting on grant\n\n## Handoff\n- Next step: push then review\n"
        "- Branch: wt/x\n", encoding="utf-8")
    work = rc.build(tmp_path / "ledger.jsonl", claims, [_pr()], now=NOW)["work"][2474]
    assert work["blockers"] == ["waiting on grant"]
    assert work["next_action"].startswith("push then review")


def test_a_word_containing_blocker_outside_the_blockers_section_is_not_a_blocker(tmp_path):
    claims = _claims(tmp_path, {"session": "s", "branch": "wt/x", "task": "t", "status": "active",
                                "claim_id": "c0", "head_sha": HEAD})
    (claims / "c0.worklog.md").write_text(
        "# W\n\n## Changes made\n- removed a blocker-shaped string from tests\n\n## Blockers\n(empty)\n",
        encoding="utf-8")
    work = rc.build(tmp_path / "ledger.jsonl", claims, [_pr()], now=NOW)["work"][2474]
    assert work["blockers"] == []


def test_a_worklog_outside_the_coordination_root_is_refused(tmp_path):
    root = tmp_path / "coord"; root.mkdir()
    outside = tmp_path / "elsewhere.md"; outside.write_text("Next: push\n", encoding="utf-8")
    data, gap = rc.read_worklog(outside, root)
    assert gap == "worklog_unsafe_path" and data["next_action"] is None


def test_a_truncated_worklog_says_so(tmp_path):
    root = tmp_path / "coord"; root.mkdir()
    big = root / "c0.worklog.md"
    big.write_text("# w\n" + ("x" * (rc.WORKLOG_TAIL_BYTES + 10)) + "\nNext: push\n", encoding="utf-8")
    data, gap = rc.read_worklog(big, root)
    assert data["truncated"] is True and gap == "worklog_truncated"


# ─────────────────────── BOARD `Open PRs` fallback (codex, 2026-11-02: "currently e508 missing")
BOARD_WITH_PRS = BOARD_MD.replace("## Open PRs\n", """## Open PRs

| PR | state | owner | what is needed |
|---|---|---|---|
| #2474 the approval form | READY fabebc077 | autoheal-5 | final CI then operator merge |
""")


def test_the_open_prs_table_supplies_next_and_owner_when_there_is_no_worklog(tmp_path):
    _board(tmp_path, BOARD_WITH_PRS)
    out = rc.build(tmp_path / "ledger.jsonl", tmp_path / "no-claims", [_pr(number=2474)], now=NOW)
    work = out["work"][2474]
    assert work["next_action"] == "final CI then operator merge"
    assert work["next_action_source"] == "board_open_prs"
    assert work["board_owner"] == "autoheal-5"
    assert work["as_of"] == "2026-11-02T18:08:30Z"


def test_the_board_fallback_never_supplies_a_review_verdict(tmp_path):
    _board(tmp_path, BOARD_WITH_PRS)
    work = rc.build(tmp_path / "ledger.jsonl", tmp_path / "no-claims", [_pr(number=2474)], now=NOW)["work"][2474]
    assert work["review"]["state"] == "UNKNOWN" and work["ci"]["state"] == "UNKNOWN"


def test_a_worklog_next_step_wins_over_the_board_row(tmp_path):
    _board(tmp_path, BOARD_WITH_PRS)
    claims = _claims(tmp_path, {"session": "s", "branch": "wt/x", "task": "t", "status": "active",
                                "claim_id": "c0", "head_sha": HEAD})
    (claims / "c0.worklog.md").write_text("## Handoff\n- Next step: the worklog answer\n", encoding="utf-8")
    work = rc.build(tmp_path / "ledger.jsonl", claims, [_pr(number=2474)], now=NOW)["work"][2474]
    assert work["next_action"] == "the worklog answer" and work["next_action_source"] == "worklog"


# ─────────────── cc6 joint review (2026-11-02): stale claim and absent-source invariants
def test_a_five_day_old_active_claim_keeps_ownership_but_is_never_working(tmp_path):
    """Ownership and context persist; execution is UNKNOWN because the heartbeat is stale."""
    _board(tmp_path, BOARD_MD.replace("cc-deepseek-2", "cc-deepseek-2"))
    stale = "2026-10-28T18:00:00Z"                     # five days before NOW
    claims = _claims(tmp_path, {"session": "cc-deepseek-2", "branch": "wt/x", "task": "t", "status": "active",
                                "claim_id": "c0", "head_sha": HEAD, "heartbeat_at": stale})
    agents = {a["session"]: a for a in rc.build(tmp_path / "ledger.jsonl", claims, [_pr()], now=NOW)["agents"]}
    row = agents["cc-deepseek-2"]
    assert row["execution_state"] == "UNKNOWN"          # never "working" on a stale heartbeat
    assert row["branch"] == "wt/x"                      # ownership/context retained
    assert row["claim_as_of"] == stale


def test_a_recent_heartbeat_is_working(tmp_path):
    _board(tmp_path, BOARD_MD)
    claims = _claims(tmp_path, {"session": "cc-deepseek-2", "branch": "wt/x", "task": "t", "status": "active",
                                "claim_id": "c0", "heartbeat_at": "2026-11-02T17:30:00Z"})  # 30 min
    agents = {a["session"]: a for a in rc.build(tmp_path / "ledger.jsonl", claims, [_pr()], now=NOW)["agents"]}
    assert agents["cc-deepseek-2"]["execution_state"] == "working"


def test_absent_sources_leave_the_row_as_of_null_not_captured_now(tmp_path):
    """The empty stores case: nothing was observed, so the row's date is null rather than the read time."""
    out = rc.build(tmp_path / "nope.jsonl", tmp_path / "no-claims", [_pr()], now=NOW)
    work = out["work"][2474]
    assert work["as_of"] is None
    assert out["captured_at"] == "2026-11-02T18:00:00Z"   # the read time lives only on the envelope


# ───────────── adversarial regressions (codex review of 9a0ae89e, 2026-11-02)
def test_future_heartbeat_is_not_working(tmp_path):
    """A heartbeat five days in the FUTURE is clock skew or forgery, never proof of work."""
    p_future = _claims(tmp_path, {"session": "cc-deepseek-2", "branch": "wt/x", "task": "t", "status": "active",
                                  "claim_id": "c0", "heartbeat_at": "2026-11-07T18:00:00Z"})
    agents = {a["session"]: a for a in rc.build(tmp_path / "ledger.jsonl", p_future, [_pr()], now=NOW)["agents"]}
    assert agents["cc-deepseek-2"]["execution_state"] == "UNKNOWN"


def test_with_no_board_the_fallback_does_not_hardcode_working(tmp_path):
    """BOARD absent: the claim fallback must use the same freshness rule, not a literal 'working'."""
    stale = _claims(tmp_path, {"session": "s1", "branch": "wt/x", "task": "t", "status": "active",
                               "claim_id": "c0", "heartbeat_at": "2026-10-28T18:00:00Z"})
    a = {x["session"]: x for x in rc.build(tmp_path / "L.jsonl", stale, [_pr()], now=NOW)["agents"]}
    assert a["s1"]["execution_state"] == "UNKNOWN"

    no_beat = _claims(tmp_path, {"session": "s2", "branch": "wt/x", "task": "t", "status": "active", "claim_id": "c9"})
    b = {x["session"]: x for x in rc.build(tmp_path / "L.jsonl", no_beat, [_pr()], now=NOW)["agents"]}
    assert b["s2"]["execution_state"] == "UNKNOWN"

    fresh = _claims(tmp_path, {"session": "s3", "branch": "wt/x", "task": "t", "status": "active",
                               "claim_id": "c1", "heartbeat_at": "2026-11-02T17:45:00Z"})
    c = {x["session"]: x for x in rc.build(tmp_path / "L.jsonl", fresh, [_pr()], now=NOW)["agents"]}
    assert c["s3"]["execution_state"] == "working"


def test_an_empty_target_head_yields_no_evidence(tmp_path):
    ledger = _ledger(tmp_path, _review(head=""), _ci(head="", state="GREEN"))
    work = rc.build(ledger, _claims(tmp_path), [_pr(head="")], now=NOW)["work"][2474]
    assert work["review"]["state"] == "UNKNOWN" and work["review"]["gap"] == "target_head_missing"
    assert work["ci"]["state"] == "UNKNOWN" and work["ci"]["gap"] == "target_head_missing"


def test_a_record_without_a_head_never_matches_a_real_head(tmp_path):
    ledger = _ledger(tmp_path, _review(head="", verdict="MERGE"), _ci(head="", state="GREEN"))
    work = rc.build(ledger, _claims(tmp_path), [_pr(head=HEAD)], now=NOW)["work"][2474]
    assert work["review"]["state"] == "UNKNOWN" and work["ci"]["state"] == "UNKNOWN"
