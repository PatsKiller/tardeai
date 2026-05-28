# Source: scripts/lib/trade_inspector.py (9031 bytes)
```python
"""trade_inspector.py — Read-only aggregate lifecycle inspector helper."""
import json, os
from datetime import datetime, timezone
from decimal import Decimal


def safe_float(v):
    if v is None: return None
    try: return float(Decimal(str(v)))
    except: return None

def safe_json(obj):
    try: return json.dumps(obj, default=str)
    except: return "{}"

def normalize_symbol(s):
    return (s or "").strip().upper()

GHOST_REASONS = {
    'duplicate_submit_race', 'cancelled_never_submitted_to_broker',
    'bogus_duplicate_no_exit_price', 'duplicate_of_22',
    'orphan_duplicate_from_partial_fill_race', 'order_canceled_by_alpaca',
    'phantom_never_filled', 'tos_paper_counterpart_closed',
    'closed_on_different_trade_id', 'duplicate_unsubmitted_to_broker',
}

FAMILIES = {
    "momentum_scalp": "momentum", "gap_and_go": "momentum",
    "swing_breakout": "swing", "swing_trade": "swing", "earnings_catalyst": "swing",
    "dividend_growth_compounder": "income", "reit_income": "income",
    "core_growth_compounder": "position", "defense_thesis": "position",
}


def resolve_identity(db_query, symbol=None, paper_trade_id=None, trace_id=None,
                     proposal_id=None, strategy_id=None, account=None):
    """Resolve a trade identity from any key. Returns dict with resolution details."""
    method = None; warnings = []
    sym = normalize_symbol(symbol)

    if paper_trade_id:
        method = "paper_trade_id"
        row = db_query("SELECT id, symbol, strategy_id, account FROM paper_trades WHERE id=%s", [paper_trade_id], fetch="one")
        if row:
            sym = row.get("symbol") or sym
            strategy_id = strategy_id or row.get("strategy_id")
            account = account or row.get("account")
    elif trace_id:
        method = "trace_id"
        row = db_query("SELECT symbol, strategy_id, paper_trade_id, proposal_id FROM lifecycle_trace WHERE trace_id=%s", [trace_id], fetch="one")
        if row:
            sym = row.get("symbol") or sym
            paper_trade_id = row.get("paper_trade_id")
            proposal_id = proposal_id or row.get("proposal_id")
            strategy_id = strategy_id or row.get("strategy_id")
    elif proposal_id:
        method = "proposal_id"
        row = db_query("SELECT symbol, strategy_id FROM paper_trade_proposals WHERE id=%s", [proposal_id], fetch="one")
        if row:
            sym = row.get("symbol") or sym
            strategy_id = strategy_id or row.get("strategy_id")
    elif sym and strategy_id:
        method = "symbol_strategy"
    elif sym:
        method = "symbol_fallback"
        warnings.append("Symbol-only resolution may return multiple trades")
    else:
        return {"resolution_method": "none", "symbol": None, "warnings": ["No identity key provided"]}

    return {
        "resolution_method": method,
        "symbol": sym,
        "paper_trade_id": int(paper_trade_id) if paper_trade_id else None,
        "trace_id": trace_id,
        "proposal_id": str(proposal_id) if proposal_id else None,
        "strategy_id": strategy_id,
        "account": account,
        "warnings": warnings,
    }


def build_trade_inspector(db_query, identity):
    """Build aggregate inspector payload. Read-only."""
    sym = identity.get("symbol")
    tid = identity.get("paper_trade_id")
    sid = identity.get("strategy_id")

    # Overview
    trade = None
    if tid:
        trade = db_query("SELECT * FROM paper_trades WHERE id=%s", [tid], fetch="one")
    elif sym:
        trade = db_query("SELECT * FROM paper_trades WHERE symbol=%s ORDER BY id DESC LIMIT 1", [sym], fetch="one")

    overview = {}
    if trade:
        er = trade.get("exit_reason") or ""
        is_ghost = er in GHOST_REASONS
        overview = {
            "paper_trade_id": trade.get("id"),
```
