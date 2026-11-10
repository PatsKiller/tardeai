"""ANCHOR: CIO_BRIEF_UNCOVERED_STOP_ADVICE_LQ1699_LQ1700_20261109 — the stop card must not depend on the tape.

LQ-20261107-1699 + LQ-20261107-1700.

1699 (P0): ``select_names()`` answers "what deserves a briefing" — a move of 3% or more, or news.
``stop_advice`` was built only for those names, so a held position with no stop that simply did not
move was invisible: it is unprotected tonight whatever it did today. Every held name at or above
``MIN_POSITION_MARKET_VALUE`` with uncovered shares in an account now gets an ADD_STOP row for that
account, and ``counts.uncovered_positions`` counts the HOLDINGS, not the briefed items.

1731 (P0): the uncovered count now names the book it counts and lists its members, and each stop
row dates the broker read behind it (``stops_as_of``) instead of leaving a 16:15 "no stop" to be
read as a 19:00 fact.

1700 (P1): a ``stop_last_known`` row with ``status='expired'`` captured today is a Day order that
lapsed at the close and covers nothing afterwards. The ADD_STOP row for that symbol and account now
says so and says to re-enter it as GTC, instead of reading like a stop that was never placed.

Every fixture is synthetic (Z-prefixed symbols, invented prices); the repo is public.
COVERS = ["scripts/cio_overnight_brief.py"]
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.cio_overnight_brief as B  # noqa: E402

ET = ZoneInfo("America/New_York")
#: Monday after the close: today's captures are on this ET date, the last close is today's.
AS_OF = datetime(2026, 11, 9, 17, 40, tzinfo=ET)
TODAY = "2026-11-09T15:59:00-05:00"
YESTERDAY = "2026-11-06T15:59:00-05:00"


# ── the synthetic book ───────────────────────────────────────────────────────────────────────


def holdings() -> list[dict]:
    return [
        # a quiet, unstopped position: no move, no news — the LQ-1699 case
        {"symbol": "ZSLEEP", "account": "acct_a", "broker_shares": 100, "market_value": 5000},
        # a quiet name whose stop expired at today's close — the LQ-1700 case
        {"symbol": "ZLAPSE", "account": "acct_a", "broker_shares": 79, "market_value": 15000},
        # quiet but fully covered: nothing to ask
        {"symbol": "ZCOVER", "account": "acct_a", "broker_shares": 100, "market_value": 10000},
        # covered in one account, uncovered in the other: one row, for the uncovered account only
        {"symbol": "ZSPLIT", "account": "acct_a", "broker_shares": 100, "market_value": 10000},
        {"symbol": "ZSPLIT", "account": "acct_b", "broker_shares": 50, "market_value": 5000},
        # below the position floor: a remnant, never advised
        {"symbol": "ZTINY", "account": "acct_a", "broker_shares": 1, "market_value": 50},
    ]


QUOTES = {
    "ZSLEEP": {"price": 50.0, "change_pct": 0.3, "source": "fixture"},
    "ZLAPSE": {"price": 190.0, "change_pct": 6.1, "source": "fixture"},
    "ZCOVER": {"price": 100.0, "change_pct": 0.2, "source": "fixture"},
    "ZSPLIT": {"price": 100.0, "change_pct": 0.1, "source": "fixture"},
    "ZTINY": {"price": 50.0, "change_pct": 0.0, "source": "fixture"},
}

#: stop_last_known rows, every status. ``stop`` is the writer's column name through working_stops.
STOP_ROWS = [
    {"symbol": "ZLAPSE", "account": "acct_a", "order_id": "E1", "stop_price": 170.0, "qty": 79,
     "status": "expired", "captured_at": TODAY, "origin": "schwab"},
    {"symbol": "ZCOVER", "account": "acct_a", "order_id": "C1", "stop_price": 90.0, "qty": 100,
     "status": "working", "captured_at": TODAY, "origin": "schwab"},
    {"symbol": "ZSPLIT", "account": "acct_a", "order_id": "S1", "stop_price": 90.0, "qty": 100,
     "status": "working", "captured_at": TODAY, "origin": "schwab"},
]


def working(rows=None):
    """working_stops wants ``stop``; the DB gives ``stop_price``. Map it here, as load_stops' caller does."""
    return B.working_stops([{**r, "stop": r["stop_price"]} for r in (rows if rows is not None else STOP_ROWS)])


def build(as_of: datetime = AS_OF, *, rows=None, **over):
    rows = STOP_ROWS if rows is None else rows
    kw = dict(
        as_of=as_of,
        holdings_doc={"holdings": holdings()},
        quotes=QUOTES,
        news_by_symbol={},
        filings_by_symbol={},
        stops_by_symbol=working(rows),
        bars_by_symbol={},
        decisions={},
        risk={"regime_label": "risk_on", "regime_score": 0.2},
        calendar={"macro": [], "earnings": [], "notes": []},
        research_fn=None,
        narrative_fn=None,
        budget=None,
        stop_rows=rows,
    )
    kw.update(over)
    # On the pre-fix base ``build_brief`` has no ``stop_rows`` argument. Dropping it there lets the
    # SAME scenarios run against the old builder, so the fail-before is behavioural (no row for the
    # quiet name; an expired stop read as one never placed), not a TypeError on a new keyword.
    if "stop_rows" not in inspect.signature(B.build_brief).parameters:
        kw.pop("stop_rows", None)
    return B.build_brief(**kw)


def advice(doc, symbol, account=None):
    return [
        r for r in doc["stop_advice"]
        if r["symbol"] == symbol and (account is None or r["account"] == account)
    ]


# ── LQ-1699: a stop is not news ─────────────────────────────────────────────────────────────


def test_a_quiet_unstopped_holding_gets_an_add_stop_row():
    """Fail-before: on the selection-only build this name has no row at all."""
    doc = build()
    rows = advice(doc, "ZSLEEP")
    assert len(rows) == 1
    assert rows[0]["answer"] == "ADD_STOP"
    assert rows[0]["held_qty"] == 100.0
    assert rows[0]["stop_qty"] == 0.0
    assert "have no working stop" in rows[0]["reason"]


def test_the_quiet_name_is_advised_without_being_briefed():
    """Research and news stay gated by the selection: no holdings item, but a stop row."""
    doc = build()
    assert "ZSLEEP" not in [h["symbol"] for h in doc["holdings"]]
    assert doc["counts"]["held_names"] == 5
    assert doc["counts"]["selected"] == len(doc["holdings"])


def test_uncovered_positions_counts_holdings_not_briefed_items():
    """ZSLEEP (quiet, unstopped), ZLAPSE (expired) and ZSPLIT (uncovered in one account only) —
    ZCOVER is covered and ZTINY is below the floor. The old count read the briefed items, so a quiet
    name could never appear here."""
    doc = build()
    assert doc["counts"]["uncovered_positions"] == 3
    uncovered = {r["symbol"] for r in doc["stop_advice"] if r["stop_qty"] < r["held_qty"]}
    assert "ZSLEEP" in uncovered


def test_a_fully_covered_quiet_holding_is_not_advised():
    doc = build()
    assert advice(doc, "ZCOVER") == []


# ── LQ-20261107-1731: a count that says which book it counts, and a row that dates its read ──


def test_the_uncovered_count_publishes_the_book_it_counts_and_its_members():
    """The page showed 2 unprotected where the held book had 3, and the artifact recorded neither the
    population nor the members — so a count of briefed names and a count of holdings were
    indistinguishable. Fail-before: the base publishes only the bare number."""
    doc = build()
    counts = doc["counts"]
    assert counts["uncovered_population"] == "held"
    assert counts["uncovered_symbols"] == ["ZLAPSE", "ZSLEEP", "ZSPLIT"]
    assert counts["uncovered_positions"] == len(counts["uncovered_symbols"]) == 3


def test_a_no_stop_row_carries_when_its_stops_were_read():
    """XAR's row said "no stop" with no read time, so a 16:15 artifact was read as a 19:00 fact after
    the stop had been placed and captured. The row now dates its evidence: the capture time of the
    working stops it was built from, and None when it had none — never the run time, which would
    assert a check that did not happen. Fail-before: the base row carries no such field."""
    # ZCOVER is partly covered here (40 of 100 shares): it earns an ADD_STOP row that carries a
    # working stop, so both directions of the field are exercised — a dated read and an absent one.
    rows = [r for r in STOP_ROWS if r["symbol"] != "ZCOVER"] + [
        {"symbol": "ZCOVER", "account": "acct_a", "order_id": "C2", "stop_price": 90.0, "qty": 40,
         "status": "working", "captured_at": TODAY, "origin": "schwab"},
    ]
    doc = build(rows=rows)
    partial = advice(doc, "ZCOVER")
    assert partial and partial[0]["stop_qty"] == 40.0 and partial[0]["stops_as_of"] == TODAY
    quiet = advice(doc, "ZSLEEP")
    assert quiet and quiet[0]["stop_now"] is None and quiet[0]["stops_as_of"] is None


def test_a_holding_below_the_position_floor_is_not_advised():
    doc = build()
    assert advice(doc, "ZTINY") == []


def test_only_the_uncovered_account_gets_a_row():
    doc = build()
    rows = advice(doc, "ZSPLIT")
    assert [(r["account"], r["held_qty"]) for r in rows] == [("acct_b", 50.0)]
    assert rows[0]["answer"] == "ADD_STOP"
    assert rows[0]["stop_qty"] == 0.0


def test_a_name_that_moved_is_still_briefed_once_and_advised_once():
    """ZLAPSE moved +6.1%: one holdings item, one stop row — the quiet pass must not duplicate it."""
    doc = build()
    assert [h["symbol"] for h in doc["holdings"]].count("ZLAPSE") == 1
    assert len(advice(doc, "ZLAPSE")) == 1


# ── LQ-1700: a Day stop that expired at the close ────────────────────────────────────────────


def test_an_expired_day_stop_is_named_as_expired_and_the_fix_is_gtc():
    doc = build()
    row = advice(doc, "ZLAPSE", "acct_a")[0]
    assert row["answer"] == "ADD_STOP"
    assert "expired at the close" in row["reason"]
    assert "Day order" in row["reason"]
    assert "GTC" in row["reason"]
    assert row["expired_stop"] == {
        "stop": 170.0,
        "qty": 79.0,
        "order_id": "E1",
        "captured_at": TODAY,
    }


def test_an_expiry_captured_yesterday_is_history_not_this_afternoon():
    rows = [{**r, "captured_at": YESTERDAY} if r["symbol"] == "ZLAPSE" else r for r in STOP_ROWS]
    doc = build(rows=rows)
    row = advice(doc, "ZLAPSE", "acct_a")[0]
    assert row["answer"] == "ADD_STOP"
    assert row["expired_stop"] is None
    assert "expired" not in row["reason"]


def test_an_expiry_in_another_account_does_not_decorate_this_one():
    # acct_a's only stop expired (it covers nothing); acct_b never had one. Both are uncovered, and
    # only acct_a's row may say "expired" — the account is the key, not the symbol.
    rows = [r for r in STOP_ROWS if r["symbol"] not in ("ZLAPSE", "ZSPLIT")]
    rows.append({"symbol": "ZSPLIT", "account": "acct_a", "order_id": "X1", "stop_price": 90.0, "qty": 100,
                 "status": "expired", "captured_at": TODAY, "origin": "schwab"})
    doc = build(rows=rows)
    assert {r["account"] for r in advice(doc, "ZSPLIT")} == {"acct_a", "acct_b"}
    assert advice(doc, "ZSPLIT", "acct_a")[0]["expired_stop"] is not None
    assert advice(doc, "ZSPLIT", "acct_b")[0]["expired_stop"] is None


def test_another_terminal_status_is_not_read_as_an_expiry():
    rows = [{**r, "status": "canceled"} if r["symbol"] == "ZLAPSE" else r for r in STOP_ROWS]
    doc = build(rows=rows)
    row = advice(doc, "ZLAPSE", "acct_a")[0]
    assert row["answer"] == "ADD_STOP"
    assert row["expired_stop"] is None
    assert "expired" not in row["reason"]


def test_without_the_raw_rows_the_card_says_only_what_it_knows():
    """A caller that passes working stops only cannot tell an expiry from a stop never placed."""
    doc = build(stop_rows=None)
    row = advice(doc, "ZLAPSE", "acct_a")[0]
    assert row["expired_stop"] is None
    assert "expired" not in row["reason"]


@pytest.mark.parametrize("status", ["expired", "Expired", " EXPIRED "])
def test_the_expiry_status_match_ignores_case_and_padding(status):
    rows = [{**r, "status": status} if r["symbol"] == "ZLAPSE" else r for r in STOP_ROWS]
    doc = build(rows=rows)
    assert advice(doc, "ZLAPSE", "acct_a")[0]["expired_stop"] is not None


def test_an_expired_stop_with_no_quantity_states_no_quantity():
    """tq-py-missing-as-zero: a qty the row never carried stays null, and the reason does not
    claim a stop "for 0 sh" — the operator placed a quantity, or the read did not capture it."""
    rows = [{k: v for k, v in r.items() if k != "qty"} if r["symbol"] == "ZLAPSE" else r for r in STOP_ROWS]
    doc = build(rows=rows)
    row = advice(doc, "ZLAPSE", "acct_a")[0]
    assert row["answer"] == "ADD_STOP"
    assert row["expired_stop"] == {"stop": 170.0, "qty": None, "order_id": "E1", "captured_at": TODAY}
    # the only quantity wording in the reason is the holding's ("cover 79 sh in ..."), never the stop's
    assert " for " not in row["reason"]
    assert "expired at the close" in row["reason"] and "GTC" in row["reason"]
