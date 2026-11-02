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
    assert set(out["gaps"]) == {"ledger_absent", "claims_absent"}
    assert out["work"][2474]["owner"] == "UNKNOWN"
    assert out["work"][2474]["publication_state"] == "UNKNOWN"


# ------------------------------------------------------------------ ownership / publication
def test_owner_and_local_vs_published_head(tmp_path):
    claims = _claims(tmp_path, {"session": "s1", "branch": "wt/x", "task": "fix releases", "status": "claimed",
                                "head_sha": OTHER, "heartbeat_at": "2026-11-02T17:40:00Z",
                                "blocker": "needs grant", "next": "push"})
    work = rc.build(_ledger(tmp_path, _ci()), claims, [_pr()], now=NOW)["work"][2474]
    assert work["owner"] == "s1" and work["current_task"] == "fix releases"
    assert work["publication_state"] == "local_only"
    assert work["local_head"] == OTHER and work["published_head"] == HEAD
    assert work["blockers"] == ["needs grant"]


def test_two_reviewers_count_as_two_independent_sessions(tmp_path):
    ledger = _ledger(tmp_path, _review(session="cc3"), _review(session="cc6", at="2026-11-02T17:05:00Z"))
    review = rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["review"]
    assert review["independent_reviewers"] == 2 and review["reviewers"] == ["cc3", "cc6"]


def test_one_reviewer_twice_is_still_one_session(tmp_path):
    ledger = _ledger(tmp_path, _review(session="cc3"), _review(session="cc3", at="2026-11-02T17:05:00Z"))
    assert rc.build(ledger, _claims(tmp_path), [_pr()], now=NOW)["work"][2474]["review"]["independent_reviewers"] == 1
