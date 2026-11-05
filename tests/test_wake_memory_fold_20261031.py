"""Persistent wake refused one subject every hour as MEMORY_MALFORMED (2026-10-31 stuck sweep).

agent_durable_memory re-appends a whole record when it is confirmed, disputed or re-linked; the wake loader called
any repeated memory_id a duplicate and refused the subject. Versions now fold (last wins); a real content conflict
still fails closed, but only for the subject that loads that record. A subject that is still malformed is
quarantined (P2 once) and skipped until the store changes. Hermetic: temp store, patched sender.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts import run_persistent_wake as runner
from scripts.lib import persistent_agent_wake as w

COVERS = ["scripts/run_persistent_wake.py"]

SUBJ = "11111111-1111-5111-8111-111111111111"
OTHER = "22222222-2222-5222-8222-222222222222"


def _row(mid, subject, **kw):
    r = {
        "memory_id": mid,
        "subject_guid": subject,
        "as_of": "2026-10-29T03:33:13+00:00",
        "status": "CANDIDATE",
        "content": f"fact {mid}",
        "relevant": True,
        "last_confirmed_at": None,
    }
    r.update(kw)
    return r


def _store(tmp_path, rows):
    p = tmp_path / "mem.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_reconfirmed_record_folds_to_latest_version(tmp_path):
    rows = [_row("m1", SUBJ), _row("m1", SUBJ, last_confirmed_at="2026-10-31T14:18:50+00:00"), _row("m2", SUBJ)]
    snap = w.MemoryLoader(_store(tmp_path, rows)).load(SUBJ)
    assert not snap.malformed and sorted(f.fact_id for f in snap.facts) == ["m1", "m2"]


def test_backfilled_subject_is_a_version_not_a_conflict(tmp_path):
    rows = [_row("m1", None), _row("m1", SUBJ, subject_guids=[SUBJ])]
    assert not w.MemoryLoader(_store(tmp_path, rows)).load(SUBJ).malformed


def test_real_conflict_fails_closed_only_for_its_subject(tmp_path):
    rows = [_row("bad", OTHER, content="A"), _row("bad", OTHER, content="B"), _row("ok", SUBJ)]
    p = _store(tmp_path, rows)
    assert w.MemoryLoader(p).load(OTHER).malformed
    assert not w.MemoryLoader(p).load(SUBJ).malformed


def test_malformed_subject_is_quarantined_alerted_once_and_skipped(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("scripts.telegram_alert.send_telegram", lambda msg, **kw: sent.append((msg, kw)) or True)
    mem = _store(tmp_path, [_row("x", SUBJ)])
    when = datetime(2026, 10, 31, 14, tzinfo=timezone.utc)
    runner._quarantine_subject(tmp_path, SUBJ, "duplicate memory identity x with conflicting content", mem, when)
    runner._quarantine_subject(tmp_path, SUBJ, "duplicate memory identity x with conflicting content", mem, when)
    assert len(sent) == 1 and sent[0][1]["priority"] == "P2"
    assert runner._quarantined_subjects(tmp_path, mem) == {SUBJ}
    mem.write_text(mem.read_text() + json.dumps(_row("y", SUBJ)) + "\n")  # store changed -> retried
    import os

    os.utime(mem, (when.timestamp() + 60, when.timestamp() + 60))
    assert runner._quarantined_subjects(tmp_path, mem) == set()
