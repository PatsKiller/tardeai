# Source: scripts/lib/journal_learning.py (1713 bytes)
```python
"""journal_learning.py — Read-only helpers for journal/learning/backtesting lifecycle queries."""
import json, logging
from decimal import Decimal

log = logging.getLogger("journal_learning")

GHOST_EXIT_REASONS = {
    'duplicate_submit_race', 'cancelled_never_submitted_to_broker',
    'bogus_duplicate_no_exit_price', 'duplicate_of_22',
    'orphan_duplicate_from_partial_fill_race', 'order_canceled_by_alpaca',
    'phantom_never_filled', 'tos_paper_counterpart_closed',
    'closed_on_different_trade_id', 'duplicate_unsubmitted_to_broker',
}

STRATEGY_FAMILIES = {
    "momentum_scalp": "momentum", "gap_and_go": "momentum",
    "swing_breakout": "swing", "swing_trade": "swing", "earnings_catalyst": "swing",
    "earnings_pre_buildup": "swing", "earnings_post_momentum": "swing",
    "fib_retracement_bounce": "swing", "speculative_growth": "swing",
    "dividend_growth_compounder": "income", "reit_income": "income",
    "high_yield_income_bdc": "income", "bond_income": "income",
    "covered_call_income": "income", "income_add": "income",
    "international_dividend": "income",
    "core_growth_compounder": "position", "core_index": "position",
    "defense_thesis": "position", "tax_loss_harvest": "position",
    "sector_rotation": "position", "recovery_watch": "income",
}


def safe_float(v):
    if v is None: return None
    try: return float(Decimal(str(v)))
    except: return None


def safe_json(obj):
    try: return json.dumps(obj, default=str)
    except: return "{}"


def is_ghost(row):
    er = (row.get("exit_reason") or "").strip()
    return er in GHOST_EXIT_REASONS


def is_clean_closed(row):
    return (row.get("exit_time") or row.get("exit_reason")) and not is_ghost(row)
```
