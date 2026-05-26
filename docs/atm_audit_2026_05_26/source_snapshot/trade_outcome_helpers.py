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
