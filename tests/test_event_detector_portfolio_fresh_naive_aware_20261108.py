"""PORTFOLIO_FRESH_NEEDED must not die on a naive/aware datetime mix (LQ-20261107-691).

`watchlist_agent_results.created_at` is timestamptz, so psycopg2 returns aware
datetimes. The detector used to build its stale list from those aware values and
then sort it with a bare `datetime.min` sentinel, which is naive:

    stale.sort(key=lambda x: x[1] or datetime.min)

As soon as one holding had never been analyzed and another had any timestamp,
that sort raised `TypeError: can't compare offset-naive and offset-aware
datetimes`. The per-detector `try/except` only logged the error, so the lane
exited 0 with one of its ten detectors dead and nothing fired.

Synthetic fixtures only. No database is touched.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from scripts import event_detector


class _Cursor:
    """Minimal cursor: answers the analysis query, returns no prior events."""

    def __init__(self, analysis_times):
        self._analysis_times = analysis_times
        self._rows = []

    def execute(self, sql, params=None):
        if "watchlist_agent_results" in sql:
            self._rows = [
                {"symbol": symbol, "last_analysis": last}
                for symbol, last in self._analysis_times.items()
            ]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, analysis_times=None):
        self._analysis_times = analysis_times or {}

    def cursor(self, *args, **kwargs):
        return _Cursor(self._analysis_times)

    def commit(self):
        pass


def _holdings(tmp_path, symbols):
    """Synthetic state root. Written atomically like a real store."""
    state = tmp_path / "state"
    state.mkdir()
    payload = state / "holdings_payload.json"
    payload.write_text(json.dumps({"holdings": [{"symbol": s} for s in symbols]}))
    os.replace(payload, state / "holdings.json")
    return state


def _aware(hours_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def test_never_analyzed_plus_aware_holding_does_not_raise(tmp_path, monkeypatch, capsys):
    """The exact reported shape: one never-analyzed + one aware holding.

    Before the fix the sort raised TypeError here and the detector silently
    contributed zero events.
    """
    state = _holdings(tmp_path, ["APL", "MSFT", "NVDA"])
    monkeypatch.setattr(event_detector, "STATE_DIR", state)

    conn = _Conn({"MSFT": _aware(72), "NVDA": _aware(1)})  # APL has no row

    fired = event_detector.check_portfolio_fresh_needed(conn, dry_run=True)

    assert fired == 2, "APL (never analyzed) and MSFT (72h) are both stale"

    out = capsys.readouterr().out
    assert "ERROR" not in out
    # Never-analyzed is emitted first, then the oldest analysed holding.
    assert out.index("PORTFOLIO_FRESH_NEEDED APL") < out.index("PORTFOLIO_FRESH_NEEDED MSFT")
    assert "PORTFOLIO_FRESH_NEEDED NVDA" not in out


def test_naive_row_is_normalised_to_utc(tmp_path, monkeypatch, capsys):
    """A legacy naive timestamp is still classified correctly, not skipped."""
    state = _holdings(tmp_path, ["APL", "MSFT"])
    monkeypatch.setattr(event_detector, "STATE_DIR", state)

    naive_old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=72)
    conn = _Conn({"MSFT": naive_old})

    fired = event_detector.check_portfolio_fresh_needed(conn, dry_run=True)

    assert fired == 2
    out = capsys.readouterr().out
    assert "ERROR" not in out
    assert "2 stale of 2 holdings" in out


def test_fresh_aware_holding_is_not_stale(tmp_path, monkeypatch, capsys):
    """The 48h cutoff still works on aware values (guards a too-loose fix)."""
    state = _holdings(tmp_path, ["MSFT", "NVDA"])
    monkeypatch.setattr(event_detector, "STATE_DIR", state)

    conn = _Conn({"MSFT": _aware(49), "NVDA": _aware(1)})

    fired = event_detector.check_portfolio_fresh_needed(conn, dry_run=True)

    assert fired == 1
    out = capsys.readouterr().out
    assert "1 stale of 2 holdings" in out
    assert "PORTFOLIO_FRESH_NEEDED MSFT" in out
    assert "PORTFOLIO_FRESH_NEEDED NVDA" not in out
