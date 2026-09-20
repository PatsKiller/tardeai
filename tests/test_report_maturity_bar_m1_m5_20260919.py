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


def test_m3_observed_when_turn_changed_decision(tmp_path):
    M = _load()
    art = tmp_path / "wake_turn_effects.jsonl"
    art.write_text(
        json.dumps(
            {
                "schema": "WakeTurnEffect@v1",
                "at": "2026-09-08T19:08:48.960091+00:00",
                "subject_key": "HELD:SCHD",
                "turn": {"intent": "defer", "plan_id": "plan_x", "note": "wait"},
                "with_turn": {
                    "next_research_question": "Has a catalyst changed the defer (wait)?"
                },
                "without_turn": {
                    "next_research_question": "Has a catalyst changed the deferred condition?"
                },
                "turn_changed_decision": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    v, note = M._m3_from_effects(art)
    assert v == "OBSERVED"
    assert "HELD:SCHD" in note
    assert "with=" in note and "without=" in note


def test_m3_candidate_when_file_present_but_no_change(tmp_path):
    M = _load()
    art = tmp_path / "wake_turn_effects.jsonl"
    art.write_text(
        json.dumps(
            {
                "turn_changed_decision": False,
                "with_turn": {"next_research_question": "same"},
                "without_turn": {"next_research_question": "same"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    v, _ = M._m3_from_effects(art)
    assert v == "CANDIDATE"

def test_m5_observed_via_wake_log_when_latest_consult_clean(tmp_path):
    M = _load()
    log = tmp_path / "cio_wake_dispatcher.log"
    log.write_text(
        "2026-09-19 16:55:07,746 [x] record_consult: wakes=5 subject_resolved=5 "
        "record_found=5 changed_by_record=5 skipped_cadence_not_due=5 no_subject=0\n",
        encoding="utf-8",
    )
    clean = {
        "unattended": True,
        "subject_resolved": 5,
        "record_found": 5,
        "decisions_changed_by_record": 0,
        "skipped_cadence_not_due": 0,
    }
    assert M._m5_from_consult(clean)[0] == "CANDIDATE"
    v, note = M._m5_from_wake_log(log_path=log)
    assert v == "OBSERVED"
    assert "via=wake_dispatcher_log" in note
    assert "changed_by_record=5" in note

def test_m4_observed_when_soak_ready_and_census_ok(tmp_path):
    M = _load()
    soak = tmp_path / "bridge_pin_soak.jsonl"
    rows = [
        {"as_of": f"2026-09-19T{h:02d}:00:00Z", "pins_match": True}
        for h in range(17, 21)
    ]
    soak.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    census = tmp_path / "operator_number_census.json"
    census.write_text(
        json.dumps(
            {
                "schema": "OperatorNumberCensus@v1",
                "as_of": "2026-09-19T23:30:00Z",
                "pass": 9,
                "warn": 2,
                "fail": 0,
                "ok": True,
            }
        ),
        encoding="utf-8",
    )
    v, note = M._m4_from_soak(tmp_path, soak_path=soak, census_paths=[census])
    assert v == "OBSERVED"
    assert "soak_ready=YES" in note
    assert "fail=0" in note


def test_m4_partial_when_census_missing(tmp_path):
    M = _load()
    soak = tmp_path / "bridge_pin_soak.jsonl"
    soak.write_text(
        json.dumps({"as_of": "2026-09-19T20:00:00Z", "pins_match": True}) + "\n",
        encoding="utf-8",
    )
    v, note = M._m4_from_soak(tmp_path, soak_path=soak, census_paths=[tmp_path / "missing.json"])
    assert v == "PARTIAL"
    assert "census not run" in note


def test_m4_soak_paths_prefer_local_state():
    M = _load()
    paths = M._m4_soak_paths(ROOT)
    assert paths[0].name == "bridge_pin_soak.jsonl"
    assert ".local/state/tradeai" in str(paths[0])
    assert "persistent-state" in str(paths[1])
