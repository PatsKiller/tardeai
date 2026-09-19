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
