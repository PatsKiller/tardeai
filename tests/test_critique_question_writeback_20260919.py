"""M2 critique → InstrumentRecord next_research_question writeback (hermetic)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_instrument_record import (  # noqa: E402
    InstrumentRecordStore,
    new_record,
)
from scripts.lib.critique_question_writeback import (  # noqa: E402
    SOURCE_INSTRUMENT_RECORD,
    apply_critique_question_writeback,
    extract_question_delta,
    latest_applied_writeback,
)


def test_extract_question_delta_from_field_changes():
    delta = extract_question_delta(
        {
            "verdict": "revise",
            "critique_id": "c-1",
            "field_changes": [
                {
                    "field": "next_research_question",
                    "before": "old q",
                    "after": "new q",
                }
            ],
        },
        {},
    )
    assert delta["verdict"] == "revise"
    assert delta["before"] == "old q"
    assert delta["after"] == "new q"
    assert delta["critique_id"] == "c-1"


def test_extract_accept_uses_author_next_question():
    delta = extract_question_delta(
        {"verdict": "accept", "critique_id": "c-2"},
        {"next_research_question": "author q"},
    )
    assert delta["after"] == "author q"


def test_writeback_persists_next_research_question(tmp_path: Path):
    store_path = tmp_path / "records.jsonl"
    art = tmp_path / "wake_critique_question.jsonl"
    store = InstrumentRecordStore(store_path)
    rec = new_record("HELD", "CSWC", next_research_question="old question")
    store.upsert(rec)

    wb = apply_critique_question_writeback(
        subject_guid="ignored",
        selection={
            "source": SOURCE_INSTRUMENT_RECORD,
            "source_id": "HELD:CSWC",
        },
        critique={
            "verdict": "revise",
            "critique_id": "crit-99",
            "field_changes": [
                {
                    "field": "next_research_question",
                    "before": "old question",
                    "after": "what moved CSWC earnings?",
                }
            ],
        },
        author={},
        store=store,
        artifact_path=art,
        unattended=True,
    )
    assert wb["applied"] is True
    assert wb["reason"] == "persisted"
    assert wb["before"] == "old question"
    assert wb["after"] == "what moved CSWC earnings?"
    assert store.load("HELD:CSWC")["next_research_question"] == "what moved CSWC earnings?"

    latest = latest_applied_writeback(art)
    assert latest is not None
    assert latest["critique_id"] == "crit-99"
    assert latest["applied"] is True
    # durable artifact is one JSON line
    assert len(art.read_text(encoding="utf-8").strip().splitlines()) == 1
    json.loads(art.read_text(encoding="utf-8").strip())


def test_writeback_skips_reject_verdict(tmp_path: Path):
    store = InstrumentRecordStore(tmp_path / "r.jsonl")
    store.upsert(new_record("WATCH", "AAA", next_research_question="keep"))
    wb = apply_critique_question_writeback(
        subject_guid=None,
        selection={"source": SOURCE_INSTRUMENT_RECORD, "source_id": "WATCH:AAA"},
        critique={
            "verdict": "reject",
            "critique_id": "c-x",
            "field_changes": [
                {
                    "field": "next_research_question",
                    "before": "keep",
                    "after": "should not land",
                }
            ],
        },
        store=store,
        artifact_path=tmp_path / "a.jsonl",
    )
    assert wb["applied"] is False
    assert "verdict_not_writeback" in str(wb["reason"])
    assert store.load("WATCH:AAA")["next_research_question"] == "keep"
