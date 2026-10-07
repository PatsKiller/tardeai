"""Fire ledger: expected / fired / artifact / consumed from the journal and the output signal, never guessed."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import report_lane_fire_ledger as RL  # noqa: E402

NOW = dt.datetime(2026, 10, 7, 4, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
LANE = {"lane_id": "approval-package-reminder", "state": "ACTIVE", "expected_cadence_hours": 1.0,
        "scheduler": {"kind": "cron", "expression": "5 * * * *", "match": "approval_package_reminder.py"},
        "output_signal": {"kind": "file_mtime", "path": "data/runtime/approval_package_reminder_last.json"}}
JOURNAL = "\n".join(
    f"2026-10-06T{h:02d}:05:01.000000-04:00 ms01 CRON[1]: (johnclaw) CMD (cd $PROJ && $PY scripts/approval_package_reminder.py --send --record)"
    for h in range(6, 24)) + "\n2026-10-07T03:05:01.000000-04:00 ms01 CRON[2]: (johnclaw) CMD (cd $PROJ && $PY scripts/other.py)\n"


def _observe(sig, *, root):
    return {"last_output_at": NOW - dt.timedelta(minutes=30), "readable": True, "detail": "fixture"}


def test_counts_come_from_the_journal_and_the_signal(tmp_path):
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / "data" / "runtime" / "approval_reminder_reconcile_last.json").write_text(json.dumps(
        {"delivery_status": "NO_ACTION", "delivery_receipt_count": 0, "as_of": NOW.isoformat()}))
    rep = RL.build([LANE], journal_text=JOURNAL, now=NOW, days=1, observe=_observe, root=tmp_path,
                   served_sha="abc", source_sha="def")
    row = rep["lanes"][0]
    # the fixture journal starts at 06:05 the day before, so the window is bounded to ~21.9 h, not 24
    assert row["expected"] == 21 and row["fired"] == 18 and row["artifact"] == "IN_WINDOW"
    assert row["consumed"]["status"] == "MEASURED" and row["consumed"]["delivery_status"] == "NO_ACTION"
    assert row["missed_fire_rate"] == round(1 - 18 / 21, 3) and rep["served_sha"] == "abc"


def test_missing_journal_or_receipt_is_not_measured(tmp_path):
    rep = RL.build([LANE], journal_text=None, now=NOW, days=1, observe=_observe, root=tmp_path, served_sha=None, source_sha=None)
    row = rep["lanes"][0]
    assert row["fired"] == "NOT_MEASURED" and row["missed_fire_rate"] == "NOT_MEASURED"
    assert row["consumed"]["status"] == "NOT_MEASURED" and rep["journal_lines"] == "NOT_MEASURED"
    other = dict(LANE, lane_id="morning-brief-0730")
    assert RL.build([other], journal_text=JOURNAL, now=NOW, days=1, observe=_observe, root=tmp_path,
                    served_sha=None, source_sha=None)["lanes"][0]["consumed"]["status"] == "NOT_MEASURED"


def test_a_rotated_journal_shortens_the_window_instead_of_inventing_missed_fires(tmp_path):
    # the journal starts 12 h before NOW; a 7-day ask must not count 168 expected fires against it
    rep = RL.build([LANE], journal_text=JOURNAL, now=NOW, days=7, observe=_observe, root=tmp_path, served_sha=None, source_sha=None)
    assert rep["journal_covers_from"] is not None and rep["window_hours"] < 24
    row = rep["lanes"][0]
    assert row["expected"] == int(rep["window_hours"] // 1) and row["fired"] == 18
