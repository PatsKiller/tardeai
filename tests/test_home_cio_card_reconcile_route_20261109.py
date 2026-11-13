"""LQ-20261107-1687: Home's CIO card may not count stopped-but-answered work as still to do.

Measured on the served snapshot at 21:01Z (2026-11-09): `cio_brief.stop_advice` already carries the reconciler's
states — four asks `done` at Schwab, one `open` (XAR) — while `synopsis.do_now` still reads
"10 stop item(s), **5** needing a decision; first: SKYD". The writer computes that block from the *answers*
(`cio_overnight_brief.py:1024` counts RAISE/ADD_STOP/FIX_QTY and never looks at a state), so the sentence is
stale by construction and never self-heals, however fresh the snapshot is. Home's card prints it verbatim:
the chip says "Stops 5 to decide" while Do-now lists the one real decision, XAR.

`since_close_card.served_since_close()` already recomputes the block from the rows; the routes never called it.
The read must not mutate the writer's file, and an UNREAD book must settle nothing: unknown is not "done".
"""
import json
from datetime import datetime, timedelta, timezone

import api_v2
import pytest

from lib import since_close_card as C

NOW = datetime.now(timezone.utc)
BRIEF_AT = (NOW - timedelta(minutes=90)).isoformat()      # the session's own build, still inside the 3 h window
STOPCLOCK = (NOW - timedelta(minutes=4)).isoformat()      # the broker read that answers four of the five asks

ROLLOVER, TAXABLE, ROTH = "schwab_rollover_ira", "schwab_taxable", "schwab_roth"


def _row(symbol, account, answer, state, *, suggested=None, stop_now=None, stop_qty=None, held=None, src="1"):
    return {"symbol": symbol, "account": account, "answer": answer, "state": state, "state_reason": None,
            "as_of": BRIEF_AT,
            "suggested_stop": suggested, "stop_now": stop_now, "stop_qty": stop_qty, "held_qty": held,
            "source_ids": [f"news:{src}"]}


# Ten rows, exactly the live shape: five quiet (nothing asked), four asks the book already answers, XAR still open.
ADVICE = [
    _row("SKYD", ROLLOVER, "RAISE", "done", suggested=7.97, stop_now=7.07, stop_qty=1000, held=1000, src="388564"),
    _row("SPCX", ROLLOVER, "RAISE", "done", suggested=132.65, stop_now=129.12, stop_qty=600, held=600, src="382436"),
    _row("ANET", ROLLOVER, "RAISE", "done", suggested=174.38, stop_now=164.27, stop_qty=200, held=200, src="388102"),
    _row("SPCX", TAXABLE, "RAISE", "done", suggested=132.65, stop_now=129.00, stop_qty=200, held=200, src="374500"),
    _row("XAR", ROLLOVER, "ADD_STOP", "open", suggested=228.12, stop_now=None, stop_qty=0, held=100, src="374501"),
    _row("T", ROLLOVER, "HOLD", "quiet", stop_now=20.26, stop_qty=2000, held=2000),
    _row("PFE", ROLLOVER, "HOLD", "quiet", stop_now=26.68, stop_qty=1000, held=1000),
    _row("V", ROLLOVER, "HOLD", "quiet", stop_now=407.72, stop_qty=100, held=100.7963),
    _row("BAH", TAXABLE, "HOLD", "quiet", stop_now=59.99, stop_qty=9, held=9),
    _row("V", ROTH, "NO_ACTION", "quiet", stop_now=None, stop_qty=0, held=0.4985),
]

# What Schwab holds now: the four asks above, answered. XAR has no stop at the broker, so it stays to do.
BROKER_STOPS = [
    {"symbol": "SKYD", "account": ROLLOVER, "order_id": "o1", "stop_price": 7.97, "qty": 1000,
     "status": "pending_activation", "captured_at": STOPCLOCK},
    {"symbol": "SPCX", "account": ROLLOVER, "order_id": "o2", "stop_price": 132.65, "qty": 600,
     "status": "pending_activation", "captured_at": STOPCLOCK},
    {"symbol": "ANET", "account": ROLLOVER, "order_id": "o3", "stop_price": 174.38, "qty": 200,
     "status": "pending_activation", "captured_at": STOPCLOCK},
    {"symbol": "SPCX", "account": TAXABLE, "order_id": "o4", "stop_price": 132.65, "qty": 200,
     "status": "working", "captured_at": STOPCLOCK},
]


def _snapshot():
    """The writer's document as it is on disk: reconciled rows, but the do_now block still counts the answers."""
    return {
        "schema": "SinceClose@v1",
        "generated_at": BRIEF_AT,
        "window": C.window(NOW),
        "cio_brief": {
            "schema": "CIOBrief@v1",
            "as_of": BRIEF_AT,
            "generated_at": BRIEF_AT,
            "status": "ok",
            "stop_advice": [dict(r) for r in ADVICE],
            "synopsis": {
                "as_of": BRIEF_AT,
                "posture": "selective",
                "do_now": {
                    "line": "10 stop item(s), 5 needing a decision; first: SKYD in Schwab Rollover IRA — RAISE "
                            "(raise to 7.97)",
                    "stop_advice_count": 10,
                    "actionable_count": 5,
                    "first": {"symbol": "SKYD", "account": ROLLOVER, "answer": "RAISE",
                              "suggested_stop": 7.97, "source_ids": ["news:388564"]},
                    "source_ids": ["news:388564"],
                },
            },
        },
    }


@pytest.fixture
def served(tmp_path, monkeypatch):
    """A served snapshot on disk, a fresh market-risk record, and the module caches cleared."""
    (tmp_path / "since_close_latest.json").write_text(json.dumps(_snapshot()))
    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
    monkeypatch.setattr(api_v2, "_market_risk_latest_projection",
                        lambda: {"as_of": BRIEF_AT, "tier": "caution", "state": "evaluated"})
    api_v2._HOME_CIO_CARD_CACHE.clear()
    return tmp_path


def _query(rows):
    def query(sql, params=None, fetch="all", **kw):
        if "stop_last_known" not in " ".join(str(sql).split()):
            return []                       # the fixture holds no rotation symbols, so no bars are asked for
        return rows
    return query


def test_the_cio_card_counts_only_the_decisions_the_book_does_not_answer(served, monkeypatch):
    """Fail-before: the chip served the writer's '5 to decide' beside a Do-now list of one (XAR)."""
    monkeypatch.setattr(api_v2, "_db_query", _query(BROKER_STOPS))
    card = api_v2._home_cio_card_build()["card"]  # MEM-CONTAIN: the route serves SWR; the build is tested directly

    assert card["stops_total"]["value"] == 10          # every item is still shown
    assert card["stops_actionable"]["value"] == 1      # but only XAR still needs a decision
    assert card["do_now"]["symbol"] == "XAR"
    assert (card["do_now"]["n"], card["do_now"]["of"]) == (1, 1)
    assert [a["symbol"] for a in card["actions"]] == ["XAR"]
    # the route is a read: the writer's file is byte-identical after the render
    assert json.loads((served / "since_close_latest.json").read_text()) == _snapshot()


def test_the_since_close_route_serves_the_reconciled_do_now_but_not_the_stale_counts(served, monkeypatch):
    monkeypatch.setattr(api_v2, "_db_query", _query(BROKER_STOPS))
    doc = api_v2._home_since_close()

    assert doc["status"] == "ok"
    dn = doc["cio_brief"]["synopsis"]["do_now"]
    assert dn["actionable_count"] == 1
    assert dn["settled_count"] == 4
    assert dn["first"]["symbol"] == "XAR"
    assert "1 needing a decision" in dn["line"]
    assert doc["cio_brief"]["stop_read"]["status"] == "read"
    # the sections the stop read says nothing about are untouched
    assert doc["cio_brief"]["synopsis"]["posture"] == "selective"
    assert json.loads((served / "since_close_latest.json").read_text()) == _snapshot()


def test_an_unread_stop_book_settles_nothing(served, monkeypatch):
    """A read that did not happen is not an answer: every ask stays to do, and the card says the book is unread."""
    monkeypatch.setattr(api_v2, "_db_query", _query(None))
    card = api_v2._home_cio_card_build()["card"]  # MEM-CONTAIN: the route serves SWR; the build is tested directly

    assert card["stops_actionable"]["value"] == 5       # unknown is not 'done'
    assert [a["symbol"] for a in card["actions"]] == ["SKYD", "SPCX", "ANET", "SPCX", "XAR"]
    doc = api_v2._home_since_close()
    assert doc["cio_brief"]["stop_read"]["status"] == "unread"
    assert doc["cio_brief"]["synopsis"]["do_now"]["actionable_count"] == 5
    assert all(r["state"] == "unread" for r in doc["cio_brief"]["stop_advice"]
               if r["answer"] in ("RAISE", "ADD_STOP", "FIX_QTY"))
