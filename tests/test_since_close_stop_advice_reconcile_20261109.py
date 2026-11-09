"""LQ-20261107-1644 — the "Your actions" stop advice is reconciled against the newest broker stop read.

The live defect (2026-11-09): the card rendered a 12:01 ET brief while the header said AS OF 1:17 (the time the card
was checked), and all three rows it still asked for had been placed at Schwab by 2:00 PM ET. The advice is built once
per brief run; the stop book moves without it. These tests pin the reconcile rules, the honest as-of (the STOPS
source's clock, never the check time), and the rebuild trigger. Synthetic ZZ/AAA rows only — the repo is public.
"""
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import since_close_card as c  # noqa: E402

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
NOW = datetime(2026, 11, 10, 5, 55, tzinfo=ET)
CAP_1800 = "2026-11-09T18:00:00+00:00"
CAP_1900 = "2026-11-09T19:00:18+00:00"


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.rows


class _Conn:
    """A stub read-only connection; fetch_stops issues one SELECT and takes its rows."""

    def __init__(self, rows):
        self.cur = _Cur(rows)

    def cursor(self):
        return self.cur


def _order(symbol="AAA", account="Brokerage", stop=12.0, qty=100.0, status="working", at=CAP_1900):
    return (symbol, account, "o-1", stop, qty, status, at)


def _read(rows, symbols=("AAA",)):
    return c.fetch_stops(_Conn(rows), list(symbols))


def _row(symbol="AAA", account="Brokerage", answer="RAISE", held=100.0, qty=0.0, suggested=12.0):
    return {"symbol": symbol, "account": account, "answer": answer, "held_qty": held, "stop_qty": qty,
            "suggested_stop": suggested, "as_of": "2026-11-09T17:01:06Z"}


def _brief(*rows):
    return {"run_id": "r1", "generated_at": "2026-11-09T17:01:06Z", "stop_advice": list(rows or [_row()])}


def _states(rec):
    return [(r["symbol"], r["answer"], r["state"]) for r in rec["rows"]]


TICKERS = {"tickers": {"AAA": {"quote": {"price": 10.0, "change_pct": 1.0}, "performance": {"perf_week": 1.0},
                                "holdings_context": {"shares_total": 100.0, "market_value_total": 1000.0}}},
           "_meta": {"generated_at": "2026-11-09T17:00:00"}}


def _snap(**kw):
    kw.setdefault("llm", None)
    return c.build_snapshot(now=NOW, ticker_snapshot=TICKERS, articles=[], futures=None, **kw)


# ---------------------------------------------------------------------------------------- the status set


def test_the_working_status_set_matches_the_briefer_s():
    """The card cannot import the script, so the set is mirrored here — and a drift would grade a cancelled stop as
    coverage, marking the operator's action done while nothing rests at the broker."""
    src = Path(__file__).resolve().parent.parent / "scripts" / "cio_overnight_brief.py"
    m = re.search(r"WORKING_STOP_STATUSES\s*=\s*frozenset\(\s*\{([^}]*)\}", src.read_text())
    assert m, "the brief's WORKING_STOP_STATUSES literal moved; update this pin"
    assert c.WORKING_STOP_STATUSES == set(re.findall(r'"([^"]+)"', m.group(1)))


# ---------------------------------------------------------------------------------------- the read


def test_only_working_orders_cover_and_the_newest_capture_is_the_read_clock():
    read = _read([
        _order(status="working", at=CAP_1800),
        _order(account="IRA", status="canceled", at=CAP_1900),   # history: covers nothing, but proves the read
        _order(account="Roth", stop=0.0, qty=0.0, status="working", at=CAP_1900),  # no level, no shares
    ])
    assert [s["account"] for s in read["stops"]["AAA"]] == ["Brokerage"]
    assert read["as_of"] == datetime.fromisoformat(CAP_1900)
    assert read["rows"] == 3


def test_the_read_asks_for_the_named_symbols_only():
    read = _read([_order()], symbols=["aaa", "ZZZ"])
    assert read["status"] == "read"
    assert set(read["stops"]) == {"AAA"}


def test_the_api_path_reads_the_same_book_through_a_query_callable():
    seen = {}

    def query(sql, params):
        seen["sql"], seen["params"] = sql, params
        return [{"symbol": "AAA", "account": "Brokerage", "order_id": "o-9", "stop_price": 12.0, "qty": 100.0,
                 "status": "working", "captured_at": CAP_1900}]

    read = c.fetch_stops_query(query, ["AAA"])
    assert read["status"] == "read" and read["stops"]["AAA"][0]["order_id"] == "o-9"
    assert read["as_of"] == datetime.fromisoformat(CAP_1900) and "stop_last_known" in seen["sql"]


def test_a_query_that_returns_nothing_is_unread_and_the_route_cannot_claim_done():
    """_db_query returns None on any failure; a card built on that would look fresh while nothing was checked."""
    rec = c.reconcile_stop_advice(_brief(), c.fetch_stops_query(lambda sql, params: None, ["AAA"]), now=NOW)
    assert rec["read"]["status"] == "unread" and rec["read"]["as_of"] is None
    assert _states(rec) == [("AAA", "RAISE", "unread")]


# ---------------------------------------------------------------------------------------- the rules


def test_a_raise_the_book_already_answers_is_done():
    rec = c.reconcile_stop_advice(_brief(), _read([_order(stop=12.0, qty=100.0)]), now=NOW)
    assert _states(rec) == [("AAA", "RAISE", "done")]
    ev = rec["rows"][0]["stop_evidence"]
    assert ev["done"] is True and ev["covered_qty"] == 100.0 and ev["best_stop"] == 12.0
    assert ev["orders"][0]["stop"] == 12.0


def test_a_raise_below_the_suggested_level_stays_open():
    rec = c.reconcile_stop_advice(_brief(_row(suggested=12.5)), _read([_order(stop=12.0, qty=100.0)]), now=NOW)
    assert _states(rec) == [("AAA", "RAISE", "open")]


def test_a_raise_with_no_suggested_level_is_never_done():
    rec = c.reconcile_stop_advice(_brief(_row(suggested=None)), _read([_order(stop=20.0, qty=100.0)]), now=NOW)
    assert _states(rec) == [("AAA", "RAISE", "open")]


def test_coverage_below_the_holding_is_not_done_and_one_share_of_rounding_is():
    half = c.reconcile_stop_advice(_brief(), _read([_order(qty=50.0)]), now=NOW)
    assert _states(half) == [("AAA", "RAISE", "open")]   # 50 of 100 sh covered
    rough = c.reconcile_stop_advice(_brief(_row(held=100.4)), _read([_order(qty=100.0)]), now=NOW)
    assert _states(rough) == [("AAA", "RAISE", "done")]  # fractional-remnant rounding, the brief's own tolerance


def test_add_stop_is_done_when_a_stop_covers_the_shares():
    rec = c.reconcile_stop_advice(_brief(_row(answer="ADD_STOP", suggested=None)), _read([_order(stop=9.5)]), now=NOW)
    assert _states(rec) == [("AAA", "ADD_STOP", "done")]


def test_fix_qty_is_done_only_while_a_stop_still_rests():
    fixed = c.reconcile_stop_advice(_brief(_row(answer="FIX_QTY", qty=200.0, held=100.0)), _read([_order(qty=100.0)]), now=NOW)
    assert _states(fixed) == [("AAA", "FIX_QTY", "done")]
    gone = c.reconcile_stop_advice(_brief(_row(answer="FIX_QTY", qty=200.0, held=100.0)), _read([]), now=NOW)
    assert _states(gone) == [("AAA", "FIX_QTY", "open")]   # cutting the stop to zero does not answer "cut the qty"
    still_big = c.reconcile_stop_advice(_brief(_row(answer="FIX_QTY", qty=200.0, held=100.0)), _read([_order(qty=200.0)]), now=NOW)
    assert _states(still_big) == [("AAA", "FIX_QTY", "open")]


def test_rows_in_another_account_do_not_answer_this_account_s_ask():
    rec = c.reconcile_stop_advice(_brief(_row(account="Brokerage")), _read([_order(account="IRA")]), now=NOW)
    assert _states(rec) == [("AAA", "RAISE", "open")]
    assert rec["rows"][0]["stop_evidence"]["covered_qty"] == 0.0


def test_quiet_rows_are_neither_asked_nor_done():
    rec = c.reconcile_stop_advice(_brief(_row(answer="HOLD")), _read([]), now=NOW)
    assert _states(rec) == [("AAA", "HOLD", "quiet")]
    assert rec["rows"][0]["stop_evidence"] is None


def test_an_unread_book_marks_every_actionable_row_unread_and_claims_no_as_of():
    rec = c.reconcile_stop_advice(_brief(), c.unread_stop_read("OperationalError: down"), now=NOW)
    assert _states(rec) == [("AAA", "RAISE", "unread")]
    assert rec["read"] == {"status": "unread", "as_of": None, "as_of_text": "stops unread", "rows": None,
                           "checked_at": "2026-11-10T10:55:00Z", "error": "OperationalError: down"}


def test_the_read_block_is_the_stop_time_and_the_check_time_is_kept_separate():
    read = c.reconcile_stop_advice(_brief(), _read([_order()]), now=NOW)["read"]
    assert read["status"] == "read"
    assert read["as_of"] == "2026-11-09T19:00:18Z"
    assert read["as_of_text"] == "Mon 11-09 · 2:00 PM ET"     # the stop read, not 05:42 ET (the build)
    assert read["checked_at"] == "2026-11-10T10:55:00Z"
    assert read["rows"] == 1


def test_reconcile_copies_the_brief_rows_and_never_mutates_them():
    brief = _brief()
    c.reconcile_stop_advice(brief, _read([_order()]), now=NOW)
    assert "state" not in brief["stop_advice"][0]


# ---------------------------------------------------------------------------------------- the card + trigger


def test_the_card_embeds_the_reconciled_rows_and_the_stop_clock():
    snap = _snap(cio_brief=_brief(), stop_rows=_read([_order()]))
    row = snap["cio_brief"]["stop_advice"][0]
    assert row["state"] == "done" and row["stop_evidence"]["best_stop"] == 12.0
    assert snap["cio_brief"]["stop_read"]["as_of"] == "2026-11-09T19:00:18Z"
    assert snap["cio_brief"]["stop_read"]["as_of_text"] == "Mon 11-09 · 2:00 PM ET"


def test_a_caller_without_a_stop_read_gets_the_brief_untouched():
    snap = _snap(cio_brief=_brief())
    assert "stop_read" not in snap["cio_brief"]
    assert "state" not in snap["cio_brief"]["stop_advice"][0]


def test_a_newer_broker_stop_read_rebuilds_without_a_model_call():
    def boom(_p):  # the rebuild must not reach the model: a broker read changes no words
        raise AssertionError("a stop-read rebuild spent a model call")

    first = _snap(cio_brief=_brief(), stop_rows=_read([_order(at=CAP_1800)]), llm=boom)
    second = c.build_snapshot(now=NOW, ticker_snapshot=TICKERS, articles=[], futures=None, llm=boom,
                              prior=first, if_changed=True, cio_brief=_brief(), stop_rows=_read([_order(at=CAP_1900)]))
    assert second is not None
    assert second["cio_brief"]["stop_read"]["as_of"] == "2026-11-09T19:00:18Z"
    assert second["summary"].get("llm_called") is not True


def test_an_unchanged_stop_read_does_not_rebuild():
    first = _snap(cio_brief=_brief(), stop_rows=_read([_order()]))
    again = c.build_snapshot(now=NOW, ticker_snapshot=TICKERS, articles=[], futures=None, llm=None,
                             prior=first, if_changed=True, cio_brief=_brief(), stop_rows=_read([_order()]))
    assert again is None


def test_a_prior_without_a_stop_clock_rebuilds_once_to_establish_it():
    read = _read([_order()])
    assert c.stop_change_decision({"cio_brief": {}}, read) == {
        "changed": True, "material": False, "kind": "stops", "symbol": None,
        "reason": "rebuilt to establish the stop read"}
    assert c.stop_change_decision({"cio_brief": {"stop_read": {"as_of": "2026-11-09T20:00:00Z"}}}, read)["changed"] is False
    unread = c.stop_change_decision({"cio_brief": {}}, c.unread_stop_read("down"))
    assert unread["changed"] is False and unread["reason"] == "stop read unavailable"
