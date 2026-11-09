"""PORTFOLIO_FRESH_NEEDED must not fire on a holding stored as a CUSIP (LQ-20261107-1626).

Three of the live holdings rows carry the broker's CUSIP as their ``symbol`` (delisted positions with no active
ticker). ``watchlist_agent_results`` is keyed by ticker, so no analysis of them can ever exist: each run fired for
them, the event could never clear, and the detector's three-per-run cap was spent on rows that can never be fixed —
so a genuinely stale holding behind them was never reported.

The rule is "skip the identifier, keep the holding set honest": the row is counted in one log line and never named.

Synthetic fixtures only; no store is read.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from scripts import event_detector

CUSIP = "123ZQ4567"          # CUSIP-shaped: nine alnum chars, not all alpha (synthetic)
CUSIP2 = "456ZQ8901"


class _Cursor:
    def __init__(self, analysis_times):
        self._analysis_times = analysis_times
        self._rows = []

    def execute(self, sql, params=None):
        if "watchlist_agent_results" in sql:
            self._rows = [{"symbol": s, "last_analysis": t} for s, t in self._analysis_times.items()]
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
    state = tmp_path / "state"
    state.mkdir()
    payload = state / "holdings_payload.json"
    payload.write_text(json.dumps({"holdings": [{"symbol": s} for s in symbols]}))
    os.replace(payload, state / "holdings.json")
    return state


def _aware(hours_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def test_a_cusip_holding_never_fires_and_does_not_crowd_out_a_real_one(tmp_path, monkeypatch, capsys):
    """The live harm: a never-analyzed CUSIP sorts first, takes a slot, and a stale real holding misses the cap.

    The CUSIP has no analysis (so it is the first stale row), and three real holdings are 70h/60h/50h old. With the
    identifier in the set only two of them fit in three fires; without it all three do.
    """
    state = _holdings(tmp_path, [CUSIP, "ZQAA", "ZQAB", "ZQAC"])
    monkeypatch.setattr(event_detector, "STATE_DIR", state)

    fired = event_detector.check_portfolio_fresh_needed(
        _Conn({"ZQAA": _aware(50), "ZQAB": _aware(60), "ZQAC": _aware(70)}), dry_run=True)

    assert fired == 3, "the cap goes to the real holdings, not to the identifier"
    out = capsys.readouterr().out
    assert CUSIP not in out.split("skipped")[1], "the identifier is counted, never named"
    assert f"PORTFOLIO_FRESH_NEEDED {CUSIP}" not in out
    for sym in ("ZQAA", "ZQAB", "ZQAC"):
        assert f"PORTFOLIO_FRESH_NEEDED {sym}" in out, f"{sym} is stale and must not lose its slot to a CUSIP"
    assert "1 CUSIP identifier(s) skipped" in out
    assert "3 stale of 3 holdings" in out, "the denominator is holdings, not identifiers"


def test_every_cusip_row_is_counted_in_one_line(tmp_path, monkeypatch, capsys):
    state = _holdings(tmp_path, [CUSIP, CUSIP2, "ZQAA"])
    monkeypatch.setattr(event_detector, "STATE_DIR", state)

    event_detector.check_portfolio_fresh_needed(_Conn(), dry_run=True)

    out = capsys.readouterr().out
    assert "2 CUSIP identifier(s) skipped" in out
    assert out.count("CUSIP identifier(s) skipped") == 1


def test_a_digits_in_a_ticker_and_a_letter_only_nine_are_not_cusips(tmp_path, monkeypatch, capsys):
    """The predicate is the shared one, not "looks odd": a real ticker with a digit and a 9-letter name stay."""
    state = _holdings(tmp_path, ["ZQ1", "ZQABCDEFG"])
    monkeypatch.setattr(event_detector, "STATE_DIR", state)

    fired = event_detector.check_portfolio_fresh_needed(_Conn(), dry_run=True)

    out = capsys.readouterr().out
    assert fired == 2 and "CUSIP identifier(s) skipped" not in out
    assert "PORTFOLIO_FRESH_NEEDED ZQ1" in out and "PORTFOLIO_FRESH_NEEDED ZQABCDEFG" in out


def test_a_book_of_only_cusips_still_reports_skipping_then_no_holdings(tmp_path, monkeypatch, capsys):
    state = _holdings(tmp_path, [CUSIP, CUSIP2])
    monkeypatch.setattr(event_detector, "STATE_DIR", state)

    assert event_detector.check_portfolio_fresh_needed(_Conn(), dry_run=True) == 0
    out = capsys.readouterr().out
    assert "2 CUSIP identifier(s) skipped" in out
    assert "no holdings — skipping" in out
