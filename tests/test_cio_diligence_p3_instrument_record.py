"""P3 InstrumentRecord@v1 — persistence & versioning diligence drills.

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. No LLM.
Prefer tmp_path over mutating the live overlay.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.cio_instrument_record import (
    BEHAVIOR_FIELDS,
    BehaviorWriteRefused,
    InstrumentRecordStore,
    apply_cognition,
    cc_narrative,
    new_record,
    thesis_summary,
)


DIAGRAM_FIELDS = (
    "subject_key",
    "thesis_ref",          # thesis
    "cc_narrative",       # narrative
    "lessons",
    "last_artifact_id",   # artifacts (singular pointer on cognition store)
    "hashes",             # analyst / earnings / price / weight change hashes
    "next_eligible_at",
    "notify_priority",    # priority
    "last_operator_turn", # operator_turns (singular pointer)
)


def _mint_with_thesis(thesis_ref: str, what: str, *, q: str = "q1") -> dict:
    rec = new_record("HELD", "SCHD", symbols=["SCHD"], thesis_ref=thesis_ref)
    rec, _ = apply_cognition(
        rec,
        next_research_question=q,
        notify_priority="cc",
        narrative=cc_narrative(what=what, thesis_fit=f"fit:{thesis_ref}"),
    )
    return rec


def test_cold_start_reload_preserves_tip(tmp_path: Path):
    path = tmp_path / "cio_instrument_records.jsonl"
    store = InstrumentRecordStore(path)
    store.upsert(_mint_with_thesis("desk@v5", "Operator deferred: wait for buffer."))

    # New process / new reader — no shared cache.
    reloaded = InstrumentRecordStore(path).load("HELD:SCHD")
    assert reloaded is not None
    assert reloaded["thesis_ref"] == "desk@v5"
    assert reloaded["memory_behavior_influence"] == 0
    assert "deferred" in (reloaded["cc_narrative"] or {}).get("what", "").lower()


def test_append_version_and_history(tmp_path: Path):
    path = tmp_path / "cio_instrument_records.jsonl"
    store = InstrumentRecordStore(path)
    store.upsert(_mint_with_thesis("desk@v5", "Prior thesis summary A.", q="q-a"))

    tip = dict(store.load("HELD:SCHD") or {})
    tip["thesis_ref"] = "desk@v6"
    tip, _ = apply_cognition(
        tip,
        next_research_question="q-b",
        narrative=cc_narrative(what="Updated thesis summary B.", thesis_fit="fit:desk@v6"),
        notify_priority="digest",
    )
    store.upsert(tip)

    hist = store.history("HELD:SCHD")
    assert len(hist) == 2
    assert hist[0]["thesis_ref"] == "desk@v5"
    assert hist[-1]["thesis_ref"] == "desk@v6"
    assert store.load("HELD:SCHD")["notify_priority"] == "digest"
    # Raw file is append-only evidence.
    assert len([l for l in path.read_text().splitlines() if l.strip()]) == 2


def test_recover_prior_thesis_summary(tmp_path: Path):
    path = tmp_path / "cio_instrument_records.jsonl"
    store = InstrumentRecordStore(path)
    store.upsert(_mint_with_thesis("desk@v5", "Prior thesis: defer for price buffer."))
    tip = dict(store.load("HELD:SCHD") or {})
    tip["thesis_ref"] = "desk@v6"
    tip, _ = apply_cognition(
        tip,
        next_research_question="new-q",
        narrative=cc_narrative(what="New tip overwrites narrative.", thesis_fit="fit:v6"),
    )
    store.upsert(tip)

    prior = thesis_summary(store.history("HELD:SCHD")[0])
    assert prior["thesis_ref"] == "desk@v5"
    assert "defer" in (prior["what"] or "").lower()
    assert prior["thesis_fit"] == "fit:desk@v5"

    rolled = store.rollback("HELD:SCHD", to_index=0)
    assert rolled["thesis_ref"] == "desk@v5"
    assert thesis_summary(store.load("HELD:SCHD"))["what"]
    assert "defer" in (thesis_summary(store.load("HELD:SCHD"))["what"] or "").lower()
    # History retained; rollback is another append.
    assert len(store.history("HELD:SCHD")) == 3


def test_partial_write_does_not_lose_prior_tip(tmp_path: Path):
    path = tmp_path / "cio_instrument_records.jsonl"
    store = InstrumentRecordStore(path)
    store.upsert(_mint_with_thesis("desk@v5", "Complete row survives truncation."))
    # Simulate crash mid-line.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"subject_key":"HELD:SCHD","thesis_ref":"CORRUPT_PARTIAL"')
    tip = InstrumentRecordStore(path).load("HELD:SCHD")
    assert tip is not None
    assert tip["thesis_ref"] == "desk@v5"
    hist = InstrumentRecordStore(path).history("HELD:SCHD")
    assert all(r.get("thesis_ref") != "CORRUPT_PARTIAL" for r in hist)


@pytest.mark.parametrize("field", BEHAVIOR_FIELDS)
def test_refuse_mbi_behavior_fields(field: str):
    rec = new_record("HELD", "SCHD")
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(rec, next_research_question="q", **{field: 1})


def test_diagram_field_checklist_present_on_mint():
    rec = new_record("HELD", "SCHD", symbols=["SCHD"], thesis_ref="desk@v5")
    for field in DIAGRAM_FIELDS:
        assert field in rec, f"missing diagram field {field}"
    hashes = rec.get("hashes") or {}
    for hk in ("analyst", "earnings", "price", "weight"):
        assert hk in hashes
    assert rec["schema"] == "InstrumentRecord@v1"
    assert rec["authority"] == "READ_ONLY_ADVISORY"
    assert rec["memory_behavior_influence"] == 0


def test_restart_projection_last_write_wins(tmp_path: Path):
    """Restart after multiple appends still projects the tip only once."""
    path = tmp_path / "cio_instrument_records.jsonl"
    store = InstrumentRecordStore(path)
    store.upsert(_mint_with_thesis("desk@v1", "v1"))
    for i in range(2, 5):
        tip = dict(store.load("HELD:SCHD") or {})
        tip["thesis_ref"] = f"desk@v{i}"
        tip, _ = apply_cognition(
            tip,
            next_research_question=f"q{i}",
            narrative=cc_narrative(what=f"v{i}"),
        )
        store.upsert(tip)
    fresh = InstrumentRecordStore(path)
    assert len(fresh.all()) == 1
    assert fresh.load("HELD:SCHD")["thesis_ref"] == "desk@v4"
    assert len(fresh.history("HELD:SCHD")) == 4
