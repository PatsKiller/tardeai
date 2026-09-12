"""A producer that writes zero rows must say WHY.

Live record from the 02:30Z run on 2026-09-12:

    {"changes_found": 25, "rows_produced": 0, ...}

Top-level keys were K, authority, by_kind, changes_found, model_calls,
not_evaluable, rows_produced, schema, universe. Not one of them distinguishes

    all 25 were already recorded earlier today   (correct, idempotent)
    the writes failed                            (broken)
    a gate suppressed them                       (refused)

The cause was established empirically rather than assumed: `persist()` uses
ON CONFLICT (change_guid) DO NOTHING, and MREO, OCS, IPDN, ODD, DNN and PYPL
each already carried a row dated 2026-09-11. So the detector was working
perfectly and had no way to say so.

This also breaks the lane signal declared for it in config/lane_registry.json,
which keys on db_max(material_changes.created_at): a correctly-idempotent run
never advances that column, so the lane reads SLOW and then SILENT while
running every 30 minutes exactly as designed.
"""

from __future__ import annotations

import inspect

import pytest

from scripts.material_change_detector import persist


class _FakeCursor:
    """Mimics psycopg2 rowcount semantics for ON CONFLICT DO NOTHING:
    1 when a row is inserted, 0 when the conflict target already exists."""

    def __init__(self, existing: set[str]):
        self.existing = existing
        self.rowcount = 0
        self.inserted: list[str] = []

    def execute(self, sql, params=None):
        if "INSERT INTO material_changes" in sql:
            guid = params[0]
            if guid in self.existing:
                self.rowcount = 0
            else:
                self.existing.add(guid)
                self.inserted.append(guid)
                self.rowcount = 1
        else:
            self.rowcount = 0


def _change(symbol: str):
    return {
        "symbol": symbol,
        "kind": "price_excursion",
        "magnitude": 3.5,
        "baseline": 1.0,
        "observed_value": 3.5,
        "observed_at": "2026-09-11T20:30:00Z",
        "universe_reason": "watchlist",
        "evidence": {},
        "precedence": 10,
    }


def test_persist_reports_how_many_were_already_present(monkeypatch):
    """DEFECT: persist() returns only the count it wrote. The caller cannot
    tell 'nothing new' from 'nothing worked'."""
    monkeypatch.setattr(
        "scripts.lib.cio_subject_guid.lookup_identity_envelope",
        lambda _s: {}, raising=False)
    monkeypatch.setattr(
        "scripts.lib.cio_narrative_subjects.build_links",
        lambda **_k: ([], []), raising=False)
    monkeypatch.setattr(
        "scripts.lib.cio_narrative_subjects.resolve_subject",
        lambda *_a: None, raising=False)

    changes = [_change("MREO"), _change("OCS"), _change("NEWSYM")]
    from scripts.material_change_detector import change_guid
    already = {change_guid(c["symbol"], c["kind"], c["observed_at"])
               for c in changes[:2]}
    cur = _FakeCursor(existing=set(already))

    out = persist(cur, changes, apply=True)
    assert isinstance(out, dict), (
        "persist() returns a bare int, so the run record cannot say why "
        "rows_produced was less than changes_found"
    )
    assert out["written"] == 1
    assert out["already_present"] == 2
    assert out["attempted"] == 3


def test_the_run_record_carries_a_disposition():
    """The RESULT line must name the outcome, not leave it to be inferred."""
    import scripts.material_change_detector as mcd

    src = inspect.getsource(mcd.main)
    assert "already_present" in src, "the result record does not report dedup"
    assert "write_disposition" in src, (
        "the result record has no field naming legitimate-empty vs failed"
    )


def test_a_fully_deduped_run_is_not_reported_as_empty():
    """25 found and 0 written is ALL_ALREADY_PRESENT, which is a healthy
    outcome. Reporting it the same way as a failed write is the defect."""
    from scripts.material_change_detector import classify_write_disposition

    assert classify_write_disposition(attempted=25, written=0, already=25) == "ALL_ALREADY_PRESENT"
    assert classify_write_disposition(attempted=25, written=25, already=0) == "ALL_WRITTEN"
    assert classify_write_disposition(attempted=25, written=7, already=18) == "PARTIAL_NEW"
    assert classify_write_disposition(attempted=0, written=0, already=0) == "NOTHING_DETECTED"


def test_zero_written_with_nothing_already_present_is_not_healthy():
    """The case that must NOT be confused with dedup: rows were attempted,
    none landed, and none were already there."""
    from scripts.material_change_detector import classify_write_disposition

    assert classify_write_disposition(attempted=25, written=0, already=0) == "WROTE_NOTHING_UNEXPLAINED"
