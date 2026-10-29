"""Ops Controls: the Missed note and evidence gaps are plain words, never codes or file paths (audit 2026-10-25).

The Jobs "Missed" gap note printed raw watchdog codes, including a secrets-script path
(``census_source_unreadable:scripts/secrets/…``) and lane ids. Synthetic codes only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import jobs_health as JH  # noqa: E402

CODES = [
    "census_source_unreadable:scripts/secrets/fixture_env.sh",
    "census_source_unreadable:scripts/fixture_two.sh",
    "fixture-lane-a:receipt_unavailable",
    "fixture-lane-b:receipt_unavailable",
    "fixture-lane-c:receipt_path_not_admitted",
    "journal_unavailable",
    "crontab_snapshot_stale",
    "weird_new_code:/home/fixture/.config/x.env",
]


def test_plain_gaps_never_show_codes_paths_or_lane_ids():
    words = JH.plain_collection_gaps(CODES)
    blob = " | ".join(words)
    for bad in ("scripts/", "secrets", ".sh", "/home", ".env", "fixture-lane", "receipt_unavailable",
                "census_source_unreadable", "journal_unavailable", "weird_new_code", "_"):
        assert bad not in blob, bad
    assert "2 schedule source files could not be read" in words
    assert "run receipt unavailable for 2 jobs" in words
    assert "run receipt kept in a location the monitor does not read for 1 job" in words
    assert "the run journal could not be read" in words
    assert "another evidence source could not be read" in words


def test_plain_sentence_from_an_in_process_reader_is_kept():
    assert JH.plain_collection_gaps(["run ledger unavailable"]) == ["run ledger unavailable"]
    assert JH.plain_collection_gaps([]) == []


def test_missed_note_uses_plain_words():
    m = JH._measurement(0, CODES)
    note = m["gap_reasons"]["missed"]
    assert note.startswith("execution evidence incomplete: ")
    assert "scripts/" not in note and "secrets" not in note and ":" not in note.split(": ", 1)[1]
    assert m["missed_measured"] is False
