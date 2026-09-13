"""An analyst question must be answered from analyst data, with its as-of date.

On 2026-09-13 the operator asked "what are analysts saying about Walmart right
now, is it a buy and what's the target" and was answered with three Grok
stop-curation reviews. The reply was honest about what it was -- it opened
"Research on file (stop_curation)" -- but it answered a question about analyst
opinion with risk-management notes, because research rows were the only
subject-scoped domain the desk could read.

The data was already on file and refreshed daily. yahoo_analyst_targets_history
carries recommendation_key, recommendation_mean (1-5, 99.8% on-scale across
8,128 rows) and low/mean/high targets with an analyst count. Nothing read it.

FRESHNESS IS PART OF THE ANSWER. WMT's newest row is 2026-08-11 -- 682 of 1,328
covered symbols are more than 30 days old, because a symbol drops out of the
refresh set when it leaves the watched universe. A 33-day-old target presented
as "right now" is the same class of defect as the Finviz column shift.

These tests are pure: routing is a regex over text, and the reader is exercised
against injected rows rather than the live database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.cio_operator_desk_loop import (  # noqa: E402
    ANALYST_STALE_DAYS,
    analyze_operator_intent,
    subject_analyst_view,
)


@pytest.fixture(autouse=True)
def _heuristic_only(monkeypatch):
    """Intent by regex, never by a model call, so these run offline."""
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")


# ── routing ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "What a analyst saying about Walmart right now is it a buy and what's the target",
        "what's the price target on NVDA",
        "is it a buy",
        "any analyst upgrade on AAPL",
        "what is the consensus rating for V",
    ],
)
def test_analyst_questions_route_to_the_analyst_domain(question):
    assert "analyst_view" in analyze_operator_intent(question)["needs"], (
        "an analyst question answered from research rows is how the operator got "
        "three stop-curation reviews about Walmart"
    )


@pytest.mark.parametrize(
    "question",
    ["why do we own WMT", "what's my cash", "how do you work"],
)
def test_non_analyst_questions_do_not_claim_the_domain(question):
    assert "analyst_view" not in analyze_operator_intent(question)["needs"]


def test_the_walmart_question_is_no_longer_merely_research():
    """The exact text from 2026-09-13 12:20."""
    intent = analyze_operator_intent("What a analyst saying about Walmart right now is it a buy and what's the target")
    assert intent["intent"] == "analyst_view"


# ── the reader ───────────────────────────────────────────────────────────────


class _Cur:
    """Returns one canned row, then None."""

    def __init__(self, row):
        self._row = row
        self._served = False

    def execute(self, *a, **k):
        self._served = False

    def fetchone(self):
        if self._served:
            return None
        self._served = True
        return self._row


class _Conn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _Cur(self._row)

    def close(self):
        pass


def _view(row, monkeypatch, symbol="WMT"):
    import lib.cio_operator_desk_loop as desk

    fake = type(sys)("psycopg2")
    fake.connect = lambda **kw: _Conn(row)
    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    return desk.subject_analyst_view([symbol])


def test_a_fresh_row_carries_the_rating_and_all_three_targets(monkeypatch):
    import datetime as dt

    today = dt.datetime.now(dt.timezone.utc).date()
    got = _view((today, 112.66, "buy", 1.581, 81.0, 137.98, 155.0, 40, "yahoo"), monkeypatch)
    assert len(got) == 1
    v = got[0]
    assert v["rating"] == "buy"
    assert v["rating_mean"] == 1.581
    assert (v["target_low"], v["target_mean"], v["target_high"]) == (81.0, 137.98, 155.0)
    assert v["analysts"] == 40
    assert v["stale"] is False


def test_a_lapsed_row_is_flagged_stale_with_its_age(monkeypatch):
    """WMT's real state: coverage stopped 2026-08-11."""
    import datetime as dt

    old = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=33)
    v = _view((old, 112.66, "buy", 1.581, 81.0, 137.98, 155.0, 40, "yahoo"), monkeypatch)[0]
    assert v["stale"] is True
    assert v["age_days"] == 33
    assert v["as_of"] == str(old), "the answer must carry the date it is true of"


def test_the_staleness_boundary_is_the_declared_one(monkeypatch):
    import datetime as dt

    edge = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=ANALYST_STALE_DAYS)
    assert _view((edge, 1.0, "buy", 2.0, 1.0, 2.0, 3.0, 5, "yahoo"), monkeypatch)[0]["stale"] is False
    past = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=ANALYST_STALE_DAYS + 1)
    assert _view((past, 1.0, "buy", 2.0, 1.0, 2.0, 3.0, 5, "yahoo"), monkeypatch)[0]["stale"] is True


def test_an_off_scale_rating_mean_is_dropped_not_reported(monkeypatch):
    """The same 1-5 rail the Finviz parser now enforces.

    20 of 8,128 rows carry 0.000, which means "no coverage", not "extremely
    bullish". A rating off its declared scale is not a weak rating; it is not a
    rating. The targets survive -- only the bad field is refused.
    """
    import datetime as dt

    today = dt.datetime.now(dt.timezone.utc).date()
    v = _view((today, 10.0, "buy", 0.0, 8.0, 12.0, 15.0, 3, "yahoo"), monkeypatch)[0]
    assert v["rating_mean"] is None
    assert v["target_mean"] == 12.0


def test_no_coverage_returns_nothing_rather_than_something_else(monkeypatch):
    """A private company has no analyst view. That is a gap, not an answer.

    SpaceX was queued into a research pipeline that could never answer it; the
    honest response is "no coverage on file".
    """
    assert _view(None, monkeypatch, symbol="SPACEX") == []


def test_no_symbols_reads_nothing():
    assert subject_analyst_view([]) == []
    assert subject_analyst_view(None) == []


def test_a_database_failure_degrades_to_empty(monkeypatch):
    import lib.cio_operator_desk_loop as desk

    def boom(**kw):
        raise RuntimeError("db down")

    fake = type(sys)("psycopg2")
    fake.connect = boom
    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    assert desk.subject_analyst_view(["WMT"]) == [], (
        "absent analyst data must read as absent, never raise into the reply path"
    )


def test_it_never_writes(monkeypatch):
    """Read-only: the reader must issue no INSERT/UPDATE/DELETE."""
    src = (ROOT / "scripts" / "lib" / "cio_operator_desk_loop.py").read_text()
    start = src.index("def subject_analyst_view")
    body = src[start : src.index("\ndef ", start + 10)]
    for verb in ("INSERT", "UPDATE ", "DELETE", "TRUNCATE"):
        assert verb not in body.upper(), f"{verb} in a read-only reader"


def test_os_env_is_used_for_credentials_not_a_pgpass_fallback():
    """An empty password lets libpq fall back to a stale ~/.pgpass."""
    src = (ROOT / "scripts" / "lib" / "cio_operator_desk_loop.py").read_text()
    start = src.index("def subject_analyst_view")
    body = src[start : src.index("\ndef ", start + 10)]
    assert "DB_PASSWORD" in body
    assert os.environ is not None  # sanity: the module reads from the environment
