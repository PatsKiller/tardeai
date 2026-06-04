"""broker_confirmation_gate.py — vendor-neutral fill-confirmation gate.

The single door every trade must pass to become COUNTED. It resolves the broker adapter from
the account and confirms the fill through the contract — it never names a broker.

STEP 2: confirm-only. apply=False (default) computes the confirmation + the intended
confirmation_state but does NOT mutate paper_trades. The live promotion/counting path is
unchanged until STEP 3 approval.

Confirmation states:
  BROKER_CONFIRMED          — broker affirms the order filled; qty/price captured
  PENDING_CONFIRMATION      — has an order id but broker hasn't confirmed (yet/ever)
  UNLINKED_BROKER_POSITION  — a position with no order id to confirm against (sync-recovered)
  QUARANTINED               — no order id and not a live broker position → not real, not counted
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from broker_adapter import adapter_for, FillConfirmation


def classify(trade: dict, fc: FillConfirmation, *, held_at_broker: bool) -> str:
    if fc.confirmed:
        return "BROKER_CONFIRMED"
    if trade.get("broker_order_id"):
        return "PENDING_CONFIRMATION"
    if held_at_broker:
        return "UNLINKED_BROKER_POSITION"
    return "QUARANTINED"


def confirm_and_finalize(trade: dict, *, apply: bool = False, held_at_broker: bool = False):
    """Confirm a trade's fill at its broker (whichever one) and classify it.

    Returns (FillConfirmation, confirmation_state). With apply=False (the STEP 2 default) this
    is side-effect-free: it does not write to paper_trades. apply=True is reserved for STEP 3.
    """
    order_id = trade.get("broker_order_id")
    if not order_id:
        fc = FillConfirmation(confirmed=False, status="no_order_id")
        return fc, classify(trade, fc, held_at_broker=held_at_broker)

    # An account with no broker mapping (e.g. a legacy paper source) can't be confirmed against
    # any broker — that's unverifiable, not a crash. Unverifiable => not BROKER_CONFIRMED.
    try:
        adapter = adapter_for(trade.get("account"))
    except (ValueError, NotImplementedError):
        fc = FillConfirmation(confirmed=False, broker_order_id=order_id, status="unverifiable_account")
        return fc, "PENDING_CONFIRMATION"
    fc = adapter.confirm_fill(order_id)
    state = classify(trade, fc, held_at_broker=held_at_broker)

    if apply and fc.confirmed:
        _stamp_confirmed(trade["id"], adapter.broker_name, fc, state)
    return fc, state


def _stamp_confirmed(trade_id, broker_name, fc: FillConfirmation, state: str):
    """STEP 3 ONLY — write the confirmation back to paper_trades (generic columns).
    Not called in STEP 2 (apply defaults to False)."""
    from db_adapter import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE paper_trades
           SET broker = %s,
               broker_order_id = COALESCE(broker_order_id, %s),
               broker_status = 'filled',
               broker_filled_at = COALESCE(broker_filled_at, %s),
               confirmation_state = %s
         WHERE id = %s
        """,
        [broker_name, fc.broker_order_id, fc.fill_time, state, trade_id],
    )
    conn.commit()
