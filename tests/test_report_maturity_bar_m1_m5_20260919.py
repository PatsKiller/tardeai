"""Maturity bar M1–M5 reporter reads consult/persist artifacts honestly."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load():
    key = "_tested_report_maturity_bar_m1_m5"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        key, ROOT / "scripts" / "report_maturity_bar_m1_m5.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_m5_observed_when_unattended_consult_honors_disposition():
    M = _load()
    consult = {
        "unattended": True,
        "as_of": "2026-09-19T19:40:02+00:00",
        "entrypoint": "cron: */5",
        "subject_resolved": 5,
        "record_found": 5,
        "decisions_changed_by_record": 5,
        "skipped_cadence_not_due": 5,
    }
    v, note = M._m5_from_consult(consult)
    assert v == "OBSERVED"
    assert "honored a prior disposition" in note


def test_m5_candidate_when_load_works_but_no_skip_this_cycle():
    M = _load()
    v, _ = M._m5_from_consult(
        {
            "unattended": True,
            "subject_resolved": 5,
            "record_found": 5,
            "decisions_changed_by_record": 0,
            "skipped_cadence_not_due": 0,
        }
    )
    assert v == "CANDIDATE"


def test_m1_candidate_on_unattended_persist_without_field_diff():
    M = _load()
    v, note = M._m1_from_persist(
        {
            "current": {
                "persisted": 2,
                "unattended": True,
                "as_of": "2026-09-19T18:01:36+00:00",
            },
            "hits": [],
        }
    )
    assert v == "CANDIDATE"
    assert "field diff" in note


def test_m1_observed_when_named_cognition_fields_present():
    M = _load()
    v, note = M._m1_from_persist(
        {
            "current": {
                "persisted": 2,
                "unattended": True,
                "as_of": "2026-09-19T19:47:19+00:00",
                "persist": [
                    {
                        "subject_key": "HELD:CSWC",
                        "persisted": True,
                        "changed": ["next_eligible_at", "cc_narrative"],
                    }
                ],
            },
            "hits": [],
        }
    )
    assert v == "OBSERVED"
    assert "next_eligible_at" in note and "cc_narrative" in note


def test_m1_observed_via_wake_log_when_hits_omit_field_changes(tmp_path):
    M = _load()
    log = tmp_path / "cio_wake_dispatcher.log"
    log.write_text(
        "2026-09-19 15:45:48 [x] cognition_persist subject=HELD:CSWC "
        "persisted=True reason=persisted changed=next_eligible_at,cc_narrative\n",
        encoding="utf-8",
    )
    persist = {
        "current": {"persisted": 0, "unattended": True},
        "hits": [
            {
                "as_of": "2026-09-19T19:47:19+00:00",
                "persisted": 3,
                "unattended": True,
                "subjects": ["HELD:CSWC", "HELD:BND", "HELD:BAH"],
            }
        ],
    }
    v, note = M._m1_from_persist(persist, log_path=log)
    assert v == "OBSERVED"
    assert "next_eligible_at" in note and "cc_narrative" in note
    assert "via=wake_dispatcher_log" in note


def test_m5_observed_when_instrument_enqueue_honors_cadence():
    M = _load()
    v, note = M._m5_from_consult(
        {
            "unattended": True,
            "as_of": "2026-09-19T19:55:08+00:00",
            "entrypoint": "cron: */5",
            "subject_resolved": 5,
            "record_found": 5,
            "decisions_changed_by_record": 0,
            "skipped_cadence_not_due": 0,
            "instrument_enqueue": {"skipped_cadence_count": 12},
        }
    )
    assert v == "OBSERVED"
    assert "instrument_enqueue_skipped_cadence=12" in note


def test_m2_observed_from_applied_writeback(tmp_path):
    M = _load()
    art = tmp_path / "wake_critique_question.jsonl"
    art.write_text(
        json.dumps(
            {
                "applied": True,
                "unattended": True,
                "as_of": "2026-09-19T20:15:00Z",
                "subject_key": "HELD:CSWC",
                "critique_verdict": "revise",
                "critique_id": "crit-1",
                "before": "old",
                "after": "new question",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    v, note = M._m2_from_writeback(tmp_path)
    assert v == "OBSERVED"
    assert "critique changed next_research_question" in note
    assert "crit-1" in note


def test_m2_not_observed_without_artifact(tmp_path):
    M = _load()
    v, note = M._m2_from_writeback(tmp_path)
    assert v == "NOT_OBSERVED"
    assert "next_research_question" in note

