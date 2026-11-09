"""LQ-20261107-1690: one VIX accessor, wrapping the shipped single VIX read.

``scripts/lib/vix_quote.py`` is now a thin typed adapter over
``vix_headline.vix_headline`` (which reads ``market_regime.vix_complex`` under the shipped
``session_fresh_after_minutes`` / ``fresh_after_hours`` rule, LQ-1610/1669). It re-implements no
store and no staleness clock: ``from_headline`` is a pure conversion of the headline dict, and
``read`` delegates to ``vix_headline`` and never raises.

Operator rule (2026-11-09): a value is measured only in state FRESH; a stale or undated print is
NEVER read as the current VIX ("never calm on a stale value"), and a failed read is UNAVAILABLE
with its exception type named.

Synthetic dicts only: no DB, no network, no clock side effects, no sleeps.
"""

from datetime import datetime, timezone

from scripts.lib import vix_quote

FIELDS = {"value", "as_of", "source", "state", "age_hours", "measured", "reason"}
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)  # a synthetic Monday, 10:00 ET


def _headline(**overrides):
    """A complete vix_headline.vix_headline() shaped dict; overrides win."""
    h = {
        "schema": "VixHeadline@v1",
        "vix": 24.4,
        "vix_source": "schwab",
        "vix_observation_time": "2026-11-09T14:55:00+00:00",
        "vix_age_hours": 0.08,
        "vix_state": "FRESH",
        "vix_stale": False,
        "vix_reason": None,
    }
    h.update(overrides)
    return h


# --- 1. FRESH is the one measured state ----------------------------------------------------------


def test_fresh_headline_is_measured_with_its_value_and_source():
    q = vix_quote.from_headline(_headline(), now=NOW)
    assert q.measured is True
    assert q.state == "FRESH"
    assert q.value == 24.4
    assert q.source == "schwab"
    assert q.as_of == "2026-11-09T14:55:00+00:00"
    assert q.reason


# --- 2. STALE keeps the value but carries the stale sentence, not a measurement -------------------


def test_stale_headline_is_not_measured_and_keeps_the_reason():
    stale_reason = "last print 10:00 ET 11-09, 45 min ago, past the 30 min line"
    q = vix_quote.from_headline(
        _headline(vix_state="STALE", vix_stale=True, vix_age_hours=0.75, vix_reason=stale_reason),
        now=NOW,
    )
    assert q.measured is False
    assert q.state == "STALE"
    assert q.value == 24.4
    assert "45 min" in q.reason
    assert "past the 30 min line" in q.reason


# --- 3. operator rule: a stale value is NEVER "calm" ---------------------------------------------


def test_stale_headline_is_never_measured():
    for age in (0.75, 26.0, 100.0):
        q = vix_quote.from_headline(
            _headline(vix_state="STALE", vix_stale=True, vix_age_hours=age,
                      vix_reason="observed 26.0 h ago, past the 26 h line")
        )
        assert q.measured is False, f"a stale VIX ({age} h) must never be reported as measured/calm"
        assert q.state == "STALE"


# --- 4. UNDATED is not a measurement -------------------------------------------------------------


def test_undated_headline_is_not_measured():
    q = vix_quote.from_headline(
        _headline(vix_state="UNDATED", vix_stale=True, vix_age_hours=None,
                  vix_observation_time=None, vix_reason="observation time unreadable: None")
    )
    assert q.measured is False
    assert q.state == "UNDATED"
    assert q.as_of is None
    assert q.reason


# --- 5. UNAVAILABLE / no value is not a measurement -----------------------------------------------


def test_unavailable_headline_has_no_value_and_is_not_measured():
    q = vix_quote.from_headline(
        _headline(vix=None, vix_source=None, vix_observation_time=None, vix_age_hours=None,
                  vix_state="UNAVAILABLE", vix_stale=True,
                  vix_reason="vix_complex read failed: RuntimeError")
    )
    assert q.measured is False
    assert q.state == "UNAVAILABLE"
    assert q.value is None
    assert q.as_of is None


# --- 6. read() delegates and never raises ---------------------------------------------------------


def test_read_reports_a_failed_query_and_never_raises():
    def query(sql, params=None):
        raise RuntimeError("ledger unavailable")

    q = vix_quote.read(query=query, now=NOW)
    assert isinstance(q, vix_quote.VixQuote)
    assert q.measured is False
    assert q.state == "UNAVAILABLE"
    assert q.value is None
    # vix_complex classifies a failed leg itself: the query exception becomes the typed refusal
    # ``vix_close_unavailable:not_collected`` rather than naming the type here.
    assert "vix_close_unavailable" in q.reason


def test_read_names_the_exception_when_the_handle_itself_fails():
    class _Broken:
        def cursor(self):
            raise RuntimeError("ledger unavailable")

        def rollback(self):
            pass

    q = vix_quote.read(conn=_Broken(), now=NOW)
    assert isinstance(q, vix_quote.VixQuote)
    assert q.measured is False
    assert q.state == "UNAVAILABLE"
    assert q.value is None
    assert "RuntimeError" in q.reason


# --- 7. the serialized shape is exactly the documented fields -------------------------------------


def test_to_dict_and_evidence_carry_exactly_the_documented_fields():
    q = vix_quote.from_headline(_headline(), now=NOW)
    assert set(q.to_dict()) == FIELDS
    assert q.evidence() == q.to_dict()
    assert set(q.evidence()) == FIELDS


# --- 8. replay: the Volatility category grades the CURRENT quote, never a stale daily close --------

_FRESH_QUOTE = vix_quote.VixQuote(
    value=31.5, as_of="2026-11-09T14:55:00+00:00", source="schwab", state="FRESH",
    age_hours=0.08, measured=True, reason="measured: VIX 31.50 from schwab at 2026-11-09T14:55:00+00:00",
)
_STALE_QUOTE = vix_quote.VixQuote(
    value=31.5, as_of="2026-11-09T03:45:00-05:00", source="schwab", state="STALE",
    age_hours=5.25, measured=False,
    reason="last print 03:45 ET 11-09 predates today's 09:30 ET open; no intraday VIX print since",
)
_DAILY_CLOSES = [15.0, 15.1, 15.2, 15.1, 15.0, 15.1, 15.2, 15.0]


class _ReplayReader:
    """Synthetic bars + one synthesized quote: no DB, no network. The daily series says CALM throughout."""

    def __init__(self, quote):
        self._quote = quote

    def daily_bars(self, symbols, *, sessions, end):
        from datetime import date, timedelta

        rows, last = [], date(2026, 11, 6)
        days = []
        d = last
        while len(days) < len(_DAILY_CLOSES):
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        for sym, level in (("^VIX", _DAILY_CLOSES), ("QQQ", [500.0 + i for i in range(8)]), ("SPY", [600.0] * 8)):
            for day, close in zip(days[::-1], level):
                if sym in symbols:
                    rows.append({"symbol": sym, "date": day.isoformat(), "close": close, "source": "fixture"})
        return rows

    def vix_quote(self, *, end):
        return self._quote


def _evaluate(quote):
    from scripts.lib.market_risk.categories import volatility
    from scripts.lib.market_risk.contract import EvalContext
    from scripts.lib.market_risk.policy import load_policy

    return volatility.evaluate(EvalContext(now=NOW, reader=_ReplayReader(quote), policy=load_policy()))


def test_replay_a_measured_quote_sets_the_level_even_when_the_daily_close_says_calm():
    o = _evaluate(_FRESH_QUOTE)
    # The daily closes are all ~15 (CALM); the current quote is 31.5, so the category must grade the quote.
    assert o.state in {"WARN", "STRESS"}, o.headline
    assert "VIX 31.5" in o.headline, o.headline
    assert any("VIX 31.5" in str(e.detail) for e in o.evidence), [e.detail for e in o.evidence]


def test_replay_a_stale_quote_is_unknown_never_calm():
    for quote in (_STALE_QUOTE, vix_quote.from_headline(
        _headline(vix=None, vix_state="STALE", vix_stale=True, vix_age_hours=12.5,
                  vix_observation_time="2026-11-09T03:45:00-05:00",
                  vix_reason="last print 03:45 ET 11-09, 12.5 h ago, past the 30 min line")
    )):
        o = _evaluate(quote)
        assert o.state == "UNKNOWN", (o.state, o.headline)
        assert "not measured" in o.headline, o.headline
        assert "calm" not in o.headline.lower()


class _BrokenAccessorReader(_ReplayReader):
    """A production reader whose accessor raises: the answer is not measured, never the daily close."""

    def vix_quote(self, *, end):
        raise RuntimeError("ledger unavailable")


def test_replay_an_unreadable_accessor_is_unknown_not_a_daily_close():
    from scripts.lib.market_risk.categories import volatility
    from scripts.lib.market_risk.contract import EvalContext
    from scripts.lib.market_risk.policy import load_policy

    reader = _BrokenAccessorReader(_FRESH_QUOTE)
    o = volatility.evaluate(EvalContext(now=NOW, reader=reader, policy=load_policy()))
    assert o.state == "UNKNOWN", o.headline
    assert "RuntimeError" in o.headline, o.headline
    # The same failure makes the base-rate conditions drop VIX instead of bucketing a stale close.
    from scripts.lib.market_risk import deep_brief_facts as d

    q = d._vix_quote(reader, NOW)
    assert q is not None and q.measured is False and "RuntimeError" in q.reason

