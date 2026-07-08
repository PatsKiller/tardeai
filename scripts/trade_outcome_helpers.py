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


def reconcile_broker_exit(api_get, broker_oid, stop_oid, tp_oid, entry_price, shares, dollar_risk=None):
    """Single source of truth for classifying a DB-open trade whose symbol is no longer in the broker's
    current positions. Shared by paper_trade_monitor (phantom sweep) and alpaca_paper_adapter
    (close-sync) so both classify identically. `api_get(path)->obj` is the caller's broker GET.

    Returns {"kind": ...}:
      - "phantom"        : entry order NOT filled (or nothing to verify) → caller may void to $0.
      - "reconciled", …  : entry filled + an OCO exit leg (target|stop) filled → REAL exit booked with
                           canonical exit_reason (broker_target_hit_reconciled / broker_stop_hit_reconciled),
                           price, pnl, pnl_pct, r_multiple, verdict.
      - "filled_no_exit" : entry filled but exit not resolvable via the OCO legs → caller must NOT void
                           (leave open / fall back to a generic close-order lookup).
    """
    if not broker_oid or entry_price is None or not shares:
        return {"kind": "phantom"}
    entry = api_get(f'/v2/orders/{broker_oid}')
    if not isinstance(entry, dict) or not entry.get('status'):
        return {"kind": "filled_no_exit"}        # broker unreachable → don't void
    if entry.get('status') != 'filled':
        return {"kind": "phantom"}               # order genuinely never filled
    ep = float(entry.get('filled_avg_price') or entry_price)
    sign = 1 if (entry.get('side') or 'buy') == 'buy' else -1
    for oid, kind in ((tp_oid, 'target'), (stop_oid, 'stop')):
        if not oid:
            continue
        o = api_get(f'/v2/orders/{oid}')
        if isinstance(o, dict) and o.get('status') == 'filled' and o.get('filled_avg_price'):
            xp = float(o['filled_avg_price'])
            pnl = round(sign * (xp - ep) * shares, 2)
            pnl_pct = round(sign * (xp - ep) / ep * 100, 4) if ep else 0
            r_mult = round(pnl / dollar_risk, 3) if dollar_risk else 0
            lbl = "target_hit" if kind == "target" else "stop_hit"
            return {"kind": "reconciled", "exit_price": round(xp, 4), "pnl": pnl,
                    "pnl_pct": pnl_pct, "r_multiple": r_mult, "verdict": classify_verdict(pnl),
                    "exit_reason": f"broker_{lbl}_reconciled"}
    return {"kind": "filled_no_exit"}
