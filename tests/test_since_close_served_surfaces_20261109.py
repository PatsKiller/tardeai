"""Every Home surface that renders a stop action shows the broker's answer, not the overnight brief's ask.

LQ-20261107-1672 (operator 14:39 ET): Home's "Your actions" (AS OF 2:16 PM), "Do now 1 of 5", "Protect 5 stop
changes" and "Stops 5 to decide" all told the operator to raise SPCX (IRA 129.12 -> 132.65), SPCX (taxable 129.00 ->
132.65), ANET 164.27 -> 174.38 and SKYD 7.07 -> 7.97 while stop_last_known showed exactly those stops WORKING. Every
surface reads the same overnight brief, so the reconcile has to be one function those surfaces share — never a second
copy of the rule per route.

Hermetic and pure: synthetic ZQ* fixtures, an injected read and clock. The real snapshot is never touched.
"""
from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import since_close_card as C  # noqa: E402

NOW = datetime(2026, 10, 21, 18, 27, 43, tzinfo=timezone.utc)          # 14:27:43 ET
BRIEF_AT = "2026-10-21T17:01:06+00:00"                                  # the 13:01 ET build
READ_AT = "2026-10-21T18:25:00+00:00"                                   # 14:25 ET broker read


def _advice(symbol, account, answer, held, suggested, state=None):
    row = {"symbol": symbol, "account": account, "answer": answer, "held_qty": held, "suggested_stop": suggested,
           "as_of": BRIEF_AT}
    if state is not None:
        row["state"] = state
    return row


def _snap(rows=None):
    return {
        "schema": "SinceCloseSnapshot@v1", "generated_at": BRIEF_AT,
        "cio_brief": {
            "verdict_owner": "cio", "synopsis": "synthetic test synopsis", "risk_tier": "moderate",
            "holdings": [{"symbol": "ZQAA", "qty": 100.0}],
            "stop_advice": rows if rows is not None else [
                _advice("ZQAA", "schwab_taxable", "RAISE", 100.0, 7.97),
                _advice("ZQAA", "schwab_rollover_ira", "RAISE", 600.0, 7.97),
                _advice("ZQAB", "schwab_rollover_ira", "RAISE", 200.0, 174.38),
                _advice("ZQAC", "schwab_rollover_ira", "RAISE", 1000.0, 7.97),
                _advice("ZQAD", "schwab_rollover_ira", "ADD_STOP", 100.0, 228.12),
                _advice("ZQAE", "schwab_rollover_ira", "HOLD", 2000.0, None),
            ],
        },
    }


def _read(*, status="read", working=True, as_of=READ_AT):
    stops = {}
    if working:
        stops = {
            "ZQAA": [{"account": "schwab_taxable", "order_id": "o-1", "stop": 7.97, "qty": 100.0, "status": "working",
                      "captured_at": as_of},
                     {"account": "schwab_rollover_ira", "order_id": "o-2", "stop": 7.97, "qty": 600.0,
                      "status": "working", "captured_at": as_of}],
            "ZQAB": [{"account": "schwab_rollover_ira", "order_id": "o-3", "stop": 174.38, "qty": 200.0,
                      "status": "working", "captured_at": as_of}],
            "ZQAC": [{"account": "schwab_rollover_ira", "order_id": "o-4", "stop": 7.97, "qty": 1000.0,
                      "status": "working", "captured_at": as_of}],
        }
    if status != "read":
        return C.unread_stop_read("ZQTEST")
    return {"status": "read", "stops": stops, "as_of": C._as_dt(as_of), "rows": sum(len(v) for v in stops.values()),
            "error": None}


# ── the 14:39 ET report, replayed ───────────────────────────────────────────────────────────────────────────────


def test_the_four_raises_home_still_asked_for_are_done_against_the_broker_read():
    doc = C.served_since_close(_snap(), _read(), now=NOW)
    rows = doc["cio_brief"]["stop_advice"]
    by = {(r["symbol"], r["account"]): r for r in rows}
    for key in (("ZQAA", "schwab_taxable"), ("ZQAA", "schwab_rollover_ira"), ("ZQAB", "schwab_rollover_ira"),
                ("ZQAC", "schwab_rollover_ira")):
        assert by[key]["state"] == "done", key
        assert by[key]["stop_evidence"]["best_stop"] == by[key]["suggested_stop"]
    # only the position with no stop at the broker is still an action; HOLD never was one
    assert by[("ZQAD", "schwab_rollover_ira")]["state"] == "open"
    assert by[("ZQAE", "schwab_rollover_ira")]["state"] == "quiet"


def test_the_served_document_changes_only_the_stop_rows_and_the_stop_clock():
    snap = _snap()
    before = copy.deepcopy(snap)
    doc = C.served_since_close(snap, _read(), now=NOW)
    assert snap == before                                            # the writer's document is never mutated
    assert {k: v for k, v in doc.items() if k != "cio_brief"} == {k: v for k, v in snap.items() if k != "cio_brief"}
    assert {k: v for k, v in doc["cio_brief"].items() if k not in ("stop_advice", "stop_read")} == {
        k: v for k, v in snap["cio_brief"].items() if k not in ("stop_advice", "stop_read")}
    assert doc["cio_brief"]["stop_read"]["status"] == "read"
    assert doc["cio_brief"]["stop_read"]["as_of_text"].startswith("Wed 10-21")


def test_an_unread_book_marks_every_ask_unread_and_claims_no_stop_time():
    doc = C.served_since_close(_snap(), _read(status="unread"), now=NOW)
    rows = doc["cio_brief"]["stop_advice"]
    assert [r["state"] for r in rows if r["answer"] != "HOLD"] == ["unread"] * 5
    assert doc["cio_brief"]["stop_read"]["status"] == "unread"
    assert doc["cio_brief"]["stop_read"]["as_of"] is None            # a check time is not a stop time


def test_a_snapshot_without_a_brief_is_served_unchanged():
    assert C.served_since_close({"status": "no_snapshot"}, None, now=NOW) == {"status": "no_snapshot"}
    assert C.served_since_close(None, None, now=NOW) == {}


# ── the counts and the one line every surface shows ─────────────────────────────────────────────────────────────


def test_the_counts_that_home_prints_come_from_the_reconciled_rows():
    got = C.reconcile_stop_surfaces(_snap(), _read(), now=NOW)
    c = got["counts"]
    assert (c["actions"], c["settled"], c["quiet"], c["total"]) == (1, 4, 1, 5)
    assert c["status"] == "open" and c["read_status"] == "read"
    assert c["as_of_text"].startswith("Wed 10-21")


def test_a_satisfied_ask_moves_to_the_done_line_with_the_stop_time():
    rows = [_advice("ZQAA", "schwab_taxable", "RAISE", 100.0, 7.97)]
    got = C.reconcile_stop_surfaces(_snap(rows), _read(), now=NOW)
    assert got["counts"]["status"] == "done" and got["counts"]["actions"] == 0
    line = got["settled_line"]
    assert line.startswith("No change needed — done at Schwab (Wed 10-21")
    assert "ZQAA RAISE 7.97 -> working 7.97 x 100" in line


def test_nothing_is_called_done_when_the_book_was_not_read():
    got = C.reconcile_stop_surfaces(_snap(), _read(status="unread"), now=NOW)
    assert got["counts"]["status"] == "unread" and got["counts"]["settled"] == 0
    assert got["settled_line"] is None                               # no line may claim a stop was placed


def test_the_surfaces_share_one_rule_with_the_writer():
    snap = _snap()
    got = C.reconcile_stop_surfaces(snap, _read(), now=NOW)
    direct = C.reconcile_stop_advice(snap["cio_brief"], _read(), now=NOW)
    assert got["rows"] == direct["rows"] and got["read"] == direct["read"]
