"""ANCHOR: LQ1478_CALIBRATION_TRUNCATION_20261109. LQ-20261107-1478.

A configured row cap must name how many eligible recommendations it did not score.
eligible_recommendations used to be only the rows read, so a 2000-row cap looked like
the whole set. Synthetic pages only: no database.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ace = importlib.import_module("agent_calibration_engine")


def _row(rec_id, when=None):
    return (
        rec_id, "maria", "NVDA", "swing", "buy", 0.7,
        when or datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc),
        "paper_trade", 11, None, 0.9,
    )


class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))
        text = " ".join(sql.split())
        if "count(*)" in text and "agent_recommendation_registry" in text:
            self._rows = [(self.conn.eligible_total,)]
        elif "JOIN LATERAL" in text:
            self._rows = self.conn.pages.pop(0) if self.conn.pages else []
        else:
            self._rows = []

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _Conn:
    def __init__(self, pages, eligible_total):
        self.pages = pages
        self.eligible_total = eligible_total
        self.statements = []

    def cursor(self):
        return _Cur(self)


def test_a_cap_reports_how_many_eligible_rows_were_not_scored():
    pages = [[_row("R1"), _row("R2")], [_row("R3")]]
    conn = _Conn(pages, eligible_total=5)
    _events, stats = ace.score_recommendations(
        conn, config={"page_rows": 2, "max_rows_per_run": 3, "window_days": 90, "path": "<t>"},
    )
    assert stats["eligible_total"] == 5
    assert stats["events_scored"] == 3
    assert stats["rows_truncated"] == 2
    assert stats["capped"] is True


def test_a_cap_that_covers_the_eligible_set_is_not_a_truncation():
    conn = _Conn([[_row("R1"), _row("R2")], [_row("R3")]], eligible_total=3)
    _events, stats = ace.score_recommendations(
        conn, config={"page_rows": 2, "max_rows_per_run": 3, "window_days": 90, "path": "<t>"},
    )
    assert stats["rows_truncated"] == 0
    assert stats["capped"] is False


def test_an_uncapped_walk_truncates_nothing():
    conn = _Conn([[_row("R1"), _row("R2")], [_row("R3")]], eligible_total=3)
    _events, stats = ace.score_recommendations(
        conn, config={"page_rows": 2, "max_rows_per_run": 0, "window_days": 90, "path": "<t>"},
    )
    assert stats["events_scored"] == 3
    assert stats["rows_truncated"] == 0
    assert stats["capped"] is False
