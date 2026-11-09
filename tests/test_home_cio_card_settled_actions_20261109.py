"""The CIO card's action list drops a stop the broker's book already answers (LQ-20261107-1672).

The card's ``_actions()`` filtered on the answer only (RAISE / ADD_STOP / FIX_QTY), so an advice row that
``since_close_card.reconcile_stop_advice`` had already marked ``state: done`` — the broker holds a working stop at or
above the suggested level for the whole holding — still appeared as an action and was still counted in "n of of".

The operator saw the result at 14:39 ET: Home told him to raise SPCX (IRA and taxable), ANET and SKYD while
``stop_last_known`` showed exactly those stops working.

Synthetic fixtures only; no store is read.
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib import home_cio_card as C


def _row(symbol, answer, state=None, suggested=7.97):
    row = {"symbol": symbol, "account": "ZQ_ACCT", "answer": answer, "as_of": "2026-10-21T17:01:06+00:00",
           "suggested_stop": suggested, "held_qty": 100.0}
    if state is not None:
        row["state"] = state
    return row


def _sc(rows):
    return {"cio_brief": {"generated_at": "2026-10-21T17:01:06+00:00", "stop_advice": rows,
                          "synopsis": {"do_now": {"line": "test", "stop_advice_count": len(rows),
                                                  "actionable_count": len(rows), "first": None}}}}


def test_a_done_row_is_not_an_action():
    acts = C._actions(_sc([_row("ZQAA", "RAISE", "done"), _row("ZQAB", "ADD_STOP", "open")]))
    assert [a["symbol"] for a in acts] == ["ZQAB"]
    assert acts[0]["n"] == 1                                      # numbering restarts over the real actions


def test_quiet_and_unread_follow_their_own_rule():
    acts = C._actions(_sc([_row("ZQAA", "HOLD", "quiet"), _row("ZQAB", "RAISE", "unread")]))
    assert [a["symbol"] for a in acts] == ["ZQAB"]                # an unread book is still a decision
    assert acts[0]["answer"] == "RAISE"


def test_a_row_with_no_state_is_still_an_action():
    """An old snapshot carries no `state`; it must not be silently dropped by the new guard."""
    acts = C._actions(_sc([_row("ZQAA", "RAISE")]))
    assert [a["symbol"] for a in acts] == ["ZQAA"]


def test_every_ask_done_leaves_no_action_and_no_do_now():
    sc = _sc([_row("ZQAA", "RAISE", "done"), _row("ZQAB", "RAISE", "done")])
    card = C.build_card({}, sc, datetime(2026, 10, 21, 17, 30, tzinfo=timezone.utc), True)
    assert card["actions"] == []
    assert card["do_now"] is None
