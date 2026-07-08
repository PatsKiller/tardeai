"""trade_outcome_helpers.py — Single source of truth for trade outcome utilities.

Used by all paper trade paths:
  Verdict:  classify_verdict() — consistent WIN/LOSS/BREAKEVEN labels
  Stop:     validate_and_recalc_stop() — ensures stop is on correct side of entry
"""


def classify_verdict(pnl, tolerance=0.01):
    """Single source of truth for verdict classification.

    Args:
        pnl: float or None. Trade P&L in dollars.
        tolerance: float. Absolute dollar tolerance for breakeven.

    Returns:
        str: 'WIN' | 'LOSS' | 'BREAKEVEN' | 'UNKNOWN'
    """
    if pnl is None:
        return 'UNKNOWN'
    try:
        pnl = float(pnl)
    except (TypeError, ValueError):
        return 'UNKNOWN'
    if pnl > tolerance:
        return 'WIN'
    elif pnl < -tolerance:
        return 'LOSS'
    else:
        return 'BREAKEVEN'


def validate_and_recalc_stop(entry_price, stop_loss, direction='long', fallback_pct=0.05):
    """Ensure stop_loss is on the correct side of entry_price.

    For longs: stop must be BELOW entry. For shorts: stop must be ABOVE entry.
    If invalid or missing, returns a recalculated stop at fallback_pct distance.

    Returns:
        tuple: (effective_stop, was_recalculated, reason)
    """
    if entry_price is None:
        return (stop_loss, False, 'no_entry_price')
    try:
        ep = float(entry_price)
    except (TypeError, ValueError):
        return (stop_loss, False, 'invalid_entry_price')

    if stop_loss is None:
        if direction == 'long':
            return (round(ep * (1 - fallback_pct), 2), True, 'generated_missing_stop')
        else:
            return (round(ep * (1 + fallback_pct), 2), True, 'generated_missing_stop')

    try:
        sl = float(stop_loss)
    except (TypeError, ValueError):
        if direction == 'long':
            return (round(ep * (1 - fallback_pct), 2), True, 'invalid_stop_recalculated')
        else:
            return (round(ep * (1 + fallback_pct), 2), True, 'invalid_stop_recalculated')

    if direction == 'long' and sl >= ep:
        return (round(ep * (1 - fallback_pct), 2), True, f'stop_above_entry_{sl}_vs_{ep}')
    if direction == 'short' and sl <= ep:
        return (round(ep * (1 + fallback_pct), 2), True, f'stop_below_entry_short_{sl}_vs_{ep}')

    return (sl, False, 'valid')


def get_order_status_for(account):
    """Resolve a vendor-neutral get_order_status(order_id) -> FillConfirmation for an account via the
    broker_adapter registry (the broker is read from config, never named here). Returns None if the
    account has no resolvable/implemented broker adapter — callers must treat None as "cannot verify".
    """
    try:
        from broker_adapter import adapter_for
        return adapter_for(account).get_order_status
    except Exception:
        return None


def reconcile_broker_exit(get_order_status, broker_oid, stop_oid, tp_oid, entry_price, shares,
                          dollar_risk=None, direction='long'):
    """Broker-AGNOSTIC classification of a DB-open trade whose position is gone from the broker. Depends
    ONLY on the vendor-neutral FillConfirmation returned by `get_order_status(order_id)` (broker_adapter.py),
    so it works for ANY broker whose adapter implements it — Alpaca today, Schwab/IBKR as drop-in
    broker_confirm_<name>.py. No vendor endpoints, no vendor field names, no vendor string literals.

    Single source of truth: used by paper_trade_monitor (phantom sweep) and alpaca_paper_adapter
    (close-sync), and reusable by any real-broker close path. `direction` ('long'/'buy' vs 'short'/'sell')
    sets the P&L sign and comes from the trade record, not the broker.

    Returns {"kind": ...}:
      - "phantom"        : entry order terminally NOT filled (canceled/rejected/expired) or nothing to
                           verify → caller may void to $0 (a position that never existed).
      - "reconciled", …  : entry filled + an OCO exit leg (target|stop) filled → REAL exit booked with
                           canonical exit_reason (broker_target_hit_reconciled / broker_stop_hit_reconciled).
      - "filled_no_exit" : filled/indeterminate but exit not resolvable → caller must NOT void (leave open;
                           fall back to a generic close lookup / next cycle).
    """
    if not broker_oid or entry_price is None or not shares:
        return {"kind": "phantom"}            # never submitted / nothing to verify → legacy phantom
    if get_order_status is None:
        return {"kind": "filled_no_exit"}     # no broker adapter to verify against → never void

    def _status(oid):
        try:
            return get_order_status(oid)
        except Exception:
            return None

    entry = _status(broker_oid)
    st = (getattr(entry, "status", "") or "").lower()
    if st != "filled":
        # Only a TERMINAL not-filled state is a real phantom; unknown/pending/partial must not void.
        if st in ("canceled", "cancelled", "rejected", "expired"):
            return {"kind": "phantom"}
        return {"kind": "filled_no_exit"}
    ep = float(getattr(entry, "filled_price", None) or entry_price)
    sign = -1 if str(direction or "long").lower() in ("short", "sell") else 1
    for oid, kind in ((tp_oid, "target"), (stop_oid, "stop")):
        if not oid:
            continue
        o = _status(oid)
        if (getattr(o, "status", "") or "").lower() == "filled" and getattr(o, "filled_price", None):
            xp = float(o.filled_price)
            pnl = round(sign * (xp - ep) * shares, 2)
            pnl_pct = round(sign * (xp - ep) / ep * 100, 4) if ep else 0
            r_mult = round(pnl / dollar_risk, 3) if dollar_risk else 0
            lbl = "target_hit" if kind == "target" else "stop_hit"
            return {"kind": "reconciled", "exit_price": round(xp, 4), "pnl": pnl,
                    "pnl_pct": pnl_pct, "r_multiple": r_mult, "verdict": classify_verdict(pnl),
                    "exit_reason": f"broker_{lbl}_reconciled"}
    return {"kind": "filled_no_exit"}
