"""trade_outcome_helpers.py — Single source of truth for verdict classification.

Used by all paper trade closing paths to ensure consistent WIN/LOSS/BREAKEVEN
labels across:
  - open_trade_monitor.py
  - paper_trade_closer.py
  - paper_trade_monitor.py
  - alpaca_paper_adapter.py
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
