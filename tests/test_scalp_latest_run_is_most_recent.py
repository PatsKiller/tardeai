"""`latest` on the scalp scanner must mean MOST RECENT, not BIGGEST.

Cause (2026-09-01 09:45): the Market Opportunities panel showed
run_label "1730" -- a 17:30 run -- at 09:45, with latest_run_timestamp empty and
latest_run_symbols_scanned 0. The rank key was

    (heal, ticker_count, date, generated_at)

so raw ticker_count outranked date and a 38-ticker evening package beat the
morning's 10-ticker run. The variable was named `latest` and returned the largest.

The count term existed only to prefer real packages over empty session-heal
anchors, so it is now a boolean; date decides among real runs; size is the last
tiebreak where it cannot mask recency.
"""
import pytest


def rank(rs):
    """Mirror of api_v2._run_rank (the fixed shape)."""
    tc = int(rs.get("ticker_count") or len(rs.get("tickers") or []) or 0)
    lbl = str(rs.get("run_label") or "")
    heal = 0 if lbl == "HEALTH_AUTOHEAL" or rs.get("session_heal") else 1
    date = str(rs.get("date") or rs.get("run_date") or "")
    has_tickers = 1 if tc > 0 else 0
    return (heal, has_tickers, date, str(rs.get("generated_at") or ""), tc)


def pick(runs):
    return sorted(runs, key=rank, reverse=True)[0]


BIG_STALE = {"run_label": "1730", "date": "2026-08-31", "ticker_count": 38,
             "generated_at": "2026-08-31T17:30:00"}
SMALL_FRESH = {"run_label": "0930", "date": "2026-09-01", "ticker_count": 10,
               "generated_at": "2026-09-01T09:30:00"}


def test_a_small_fresh_run_beats_a_large_stale_one():
    """The exact 2026-09-01 failure: 38 tickers yesterday vs 10 today."""
    assert pick([BIG_STALE, SMALL_FRESH])["run_label"] == "0930"


def test_the_old_key_would_have_picked_the_stale_run():
    """Positive control -- proves this test detects the defect it describes."""
    def old_rank(rs):
        tc = int(rs.get("ticker_count") or 0)
        heal = 0 if rs.get("run_label") == "HEALTH_AUTOHEAL" else 1
        return (heal, tc, str(rs.get("date") or ""), str(rs.get("generated_at") or ""))
    worst = sorted([BIG_STALE, SMALL_FRESH], key=old_rank, reverse=True)[0]
    assert worst["run_label"] == "1730", "old key must reproduce the bug"


def test_empty_heal_anchors_never_win():
    """The behaviour the count term was actually there to protect."""
    heal = {"run_label": "HEALTH_AUTOHEAL", "date": "2026-09-02", "ticker_count": 0}
    assert pick([heal, SMALL_FRESH])["run_label"] == "0930"


def test_an_empty_run_never_beats_a_real_one_on_the_same_day():
    empty = {"run_label": "0935", "date": "2026-09-01", "ticker_count": 0,
             "generated_at": "2026-09-01T09:35:00"}
    assert pick([empty, SMALL_FRESH])["run_label"] == "0930"


def test_same_day_prefers_the_later_generated_at():
    later = dict(SMALL_FRESH, run_label="1000", generated_at="2026-09-01T10:00:00")
    assert pick([SMALL_FRESH, later])["run_label"] == "1000"


def test_size_still_breaks_a_genuine_tie():
    a = {"run_label": "A", "date": "2026-09-01", "generated_at": "2026-09-01T09:30:00",
         "ticker_count": 5}
    b = {"run_label": "B", "date": "2026-09-01", "generated_at": "2026-09-01T09:30:00",
         "ticker_count": 40}
    assert pick([a, b])["run_label"] == "B"
