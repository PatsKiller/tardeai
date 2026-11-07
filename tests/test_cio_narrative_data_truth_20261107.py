"""Data-truth audit (2026-11-07), defect 7: the CIO desk must not show an old record as today.

Captured read-only on 2026-11-06: `/api/v3/cio/home` served the SPCX "Trim" narrative dated
2026-10-07 with evidence from 2026-08-29, and `instrument_narratives` carried `HELD:ARKX`
while ARKX was not in holdings at all.

Covered here:
  * a HELD record for a symbol the book no longer holds is dropped and counted;
  * a record narrative outside the age bound is reported as expired (with its date and age)
    instead of rendered as the current view, and the old prose is kept under
    ``superseded_narrative``;
  * the coverage object counts expired rows, so the page can show the gap;
  * an unknown book (no holdings document) is not read as "nothing is held".

Synthetic fixtures only — the repository is PUBLIC.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import cio_command_center as cc  # noqa: E402
from lib import cio_record_narrative as rn  # noqa: E402

NOW = datetime(2026, 11, 7, 0, 0, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, records):
        self.records = records

    def all(self):
        return list(self.records)

    def load(self, key):
        for r in self.records:
            if r.get("subject_key") == key:
                return r
        return None


def _rec(key, as_of, what="Under desk@v5: concentration/disposition. Observation only.", **kw):
    return {"subject_key": key, "kind": key.split(":", 1)[0],
            "cc_narrative": {"what": what, "as_of": as_of, "writer": "cio_run_worker"}, **kw}


STORE = FakeStore([
    _rec("HELD:SPCX", "2026-10-07T00:35:57+00:00", what="SPCX trim narrative from October."),
    _rec("HELD:ARKX", "2026-11-06T00:12:26+00:00", what="ARKX held narrative (phantom)."),
    _rec("WATCH:ARKX", "2026-10-24T01:51:11+00:00", what="ARKX watch narrative."),
    _rec("HELD:NVDA", "2026-11-06T00:05:52+00:00", what="NVDA holds, add on weakness."),
])


# ── the narrative block ───────────────────────────────────────────────────────

def test_a_held_record_for_a_symbol_nobody_holds_is_dropped_and_counted():
    report = rn.record_narratives_report(STORE, held_symbols={"SPCX", "NVDA"}, now=NOW)
    assert "HELD:ARKX" not in report["narratives"]
    assert report["phantom_held"] == ["HELD:ARKX"]
    assert report["counts"]["phantom_held"] == 1
    # A watch record for the same symbol is not a holding claim and survives.
    assert "WATCH:ARKX" in report["narratives"]


def test_unknown_book_does_not_drop_anything():
    report = rn.record_narratives_report(STORE, held_symbols=None, now=NOW)
    assert "HELD:ARKX" in report["narratives"]
    assert report["phantom_held"] == []
    # Backward-compatible single-return form still lists everything.
    rows = rn.record_narratives(STORE, now=NOW)
    assert set(rows) == {"HELD:SPCX", "HELD:ARKX", "WATCH:ARKX", "HELD:NVDA"}


def test_every_narrative_carries_its_age_and_freshness():
    report = rn.record_narratives_report(STORE, held_symbols={"SPCX", "NVDA"}, now=NOW)
    spcx = report["narratives"]["HELD:SPCX"]
    assert spcx["freshness"] == "EXPIRED"
    assert spcx["age_days"] == 31.0
    # 24h fresh / 7d expired boundary comes from holding_intel_freshness.
    assert report["narratives"]["HELD:NVDA"]["freshness"] == "STALE"
    assert "HELD:SPCX" in report["expired"]


# ── the row the page renders ──────────────────────────────────────────────────

def test_an_expired_record_is_not_rendered_as_the_current_view():
    nar = cc._row_narrative(
        STORE, ("HELD:SPCX", "EXIT:SPCX"),
        "SPCX: Trim. No record narrative attached yet.",
        label="SPCX: Trim", now=NOW)
    assert nar["from_record"] is False
    assert nar["narrative_source"] == "record_expired"
    assert nar["record_as_of"] == "2026-10-07T00:35:57+00:00"
    assert nar["record_age_days"] == 31.0
    assert "31 days old" in nar["what"] and "2026-10-07" in nar["what"]
    assert "October" not in nar["what"]                    # the stale claim is not served
    assert nar["superseded_narrative"] == "SPCX trim narrative from October."


def test_a_current_record_is_still_rendered_from_the_record():
    nar = cc._row_narrative(
        STORE, ("HELD:NVDA", "EXIT:NVDA"),
        "NVDA: Re-enter. No record narrative attached yet.",
        label="NVDA: Re-enter", now=NOW)
    assert nar["from_record"] is True and nar["narrative_source"] == "record"
    assert nar["what"] == "NVDA holds, add on weakness."
    assert nar["record_age_days"] == 1.0


def test_a_held_key_for_a_since_sold_symbol_is_skipped_for_its_exit_record():
    store = FakeStore([
        _rec("HELD:TDG", "2026-11-06T00:00:00+00:00", what="HELD narrative for a sold name."),
        _rec("EXIT:TDG", "2026-11-06T00:00:00+00:00", what="EXIT narrative."),
    ])
    nar = cc._row_narrative(store, ("HELD:TDG", "EXIT:TDG"),
                            "TDG: Exit. No record narrative attached yet.",
                            label="TDG: Exit", now=NOW, held_symbols={"SPCX"})
    assert nar["what"] == "EXIT narrative."


def test_coverage_counts_the_expired_row_and_keeps_its_section_tally():
    home = {"cio_now": {"decisions": [
        {"symbol": "SPCX", "stance": "Trim"},
        {"symbol": "NVDA", "stance": "Re-enter"},
    ]}}
    cov = cc.attach_record_narratives(home, STORE, now=NOW, held_symbols={"SPCX", "NVDA"})
    assert cov["sections"]["book"]["rows"] == 2
    assert cov["sections"]["book"]["from_record"] == 1
    assert cov["sections"]["book"]["record_expired"] == 1
    assert cov["record_expired"] == 1
    assert cov["held_symbols_known"] is True
    assert "not shown as current" in home["cio_now"]["decisions"][0]["cc_narrative"]["what"]


# ── the book as holdings.json sees it ────────────────────────────────────────

def test_held_symbols_ignores_cash_and_unknown_book_is_none():
    assert cc._held_symbols({}) is None
    assert cc._held_symbols({"holdings": []}) is None
    got = cc._held_symbols({"holdings": [
        {"symbol": "spcx", "is_cash": False},
        {"symbol": "CASH", "is_cash": True},
        {"symbol": "NVDA"},
    ]})
    assert got == {"SPCX", "NVDA"}
