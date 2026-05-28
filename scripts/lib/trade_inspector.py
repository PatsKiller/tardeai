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
            "symbol": trade.get("symbol"),
            "strategy_id": trade.get("strategy_id"),
            "strategy_family": FAMILIES.get(trade.get("strategy_id"), "other"),
            "account": trade.get("account"),
            "entry_price": safe_float(trade.get("entry_price")),
            "exit_price": safe_float(trade.get("exit_price")),
            "pnl": safe_float(trade.get("pnl")),
            "stop_loss": safe_float(trade.get("stop_loss")),
            "exit_reason": er,
            "is_ghost": is_ghost,
            "status": "closed" if trade.get("exit_time") or er else "open",
        }
        tid = trade.get("id")

    # Source / Signal
    signals = db_query("SELECT id, strategy_id, signal_score, signal_grade, fired_at FROM strategy_signals WHERE symbol=%s ORDER BY fired_at DESC LIMIT 5", [sym]) or [] if sym else []

    # Proposals
    proposals = db_query("SELECT id, symbol, strategy_id, signal_score, signal_decision, created_at FROM paper_trade_proposals WHERE symbol=%s ORDER BY created_at DESC LIMIT 5", [sym]) or [] if sym else []

    # Execution quality
    tca = None
    if tid:
        tca = db_query("SELECT * FROM paper_execution_quality WHERE paper_trade_id=%s ORDER BY id DESC LIMIT 1", [tid], fetch="one")

    # Stop/trailing
    stop_audit = db_query("SELECT event_type, payload, event_ts FROM lifecycle_events WHERE paper_trade_id=%s AND stage='stop_change' ORDER BY event_ts DESC LIMIT 10", [tid]) or [] if tid else []

    # Lifecycle trace
    trace = db_query("SELECT * FROM lifecycle_trace WHERE paper_trade_id=%s OR symbol=%s ORDER BY created_at DESC LIMIT 1", [tid, sym], fetch="one") if (tid or sym) else None
    trace_events = []
    if trace and trace.get("trace_id"):
        trace_events = db_query("SELECT stage, event_type, status, event_time FROM lifecycle_trace_events WHERE trace_id=%s ORDER BY event_time DESC LIMIT 20", [trace.get("trace_id")]) or []

    # All lifecycle events for this trade
    lc_events = db_query("SELECT stage, event_type, status, source_script, event_ts FROM lifecycle_events WHERE (paper_trade_id=%s OR symbol=%s) ORDER BY event_ts DESC LIMIT 30", [tid, sym]) or [] if (tid or sym) else []

    # LLM Review (v3.8 forward hook — read stored records only)
    llm_review = {
        "status": "not_configured",
        "close_analysis": None,
        "delayed_review": None,
        "monthly_meta": None,
        "model_calls_executed_by_endpoint": False,
        "data_quality_gaps": ["LLM backtesting jobs not yet deployed (v3.8 design only)"],
    }
    try:
        llm_row = db_query("SELECT * FROM trade_llm_reviews WHERE paper_trade_id=%s ORDER BY generated_at DESC LIMIT 1", [tid], fetch="one") if tid else None
        if llm_row:
            llm_review["status"] = "complete"
            llm_review["close_analysis"] = llm_row
    except Exception:
        pass  # Table doesn't exist yet

    # Data quality gaps
    gaps = []
    if not trade: gaps.append({"gap": "no_paper_trade", "detail": "No paper_trades row found for this identity"})
    if not trace: gaps.append({"gap": "no_lifecycle_trace", "detail": "No lifecycle_trace linked"})
    if not tca and trade: gaps.append({"gap": "no_tca", "detail": "No execution quality/TCA record"})
    if not stop_audit and trade and trade.get("stop_loss"): gaps.append({"gap": "no_stop_audit", "detail": "Stop exists but no stop-change audit events"})
    if trade and not trade.get("stop_order_id"): gaps.append({"gap": "no_stop_order_id", "detail": "No broker stop order ID stored"})

    return {
        "overview": overview,
        "source": {"signals": [_clean(s) for s in signals[:5]]},
        "proposal": {"proposals": [_clean(p) for p in proposals[:5]]},
        "risk_approval": {"gate_audit": "gate data from lifecycle API if available"},
        "execution": {"tca": _clean(tca) if tca else None, "trade": _clean(trade) if trade else None},
        "stops": {
            "db_stop": safe_float(trade.get("stop_loss")) if trade else None,
            "stop_order_id": trade.get("stop_order_id") if trade else None,
            "stop_verified_at": str(trade.get("stop_verified_at")) if trade and trade.get("stop_verified_at") else None,
            "change_audit": [_clean(e) for e in stop_audit],
        },
        "reconciliation": {"lifecycle_events_count": len(lc_events)},
        "journal": {"exit_reason": overview.get("exit_reason"), "pnl": overview.get("pnl"), "status": overview.get("status")},
        "learning": {"strategy_family": overview.get("strategy_family")},
        "backtest": {"status": "no_backtest_comparison_available"},
        "llm_review": llm_review,
        "data_quality_gaps": gaps,
        "lifecycle_events": [_clean(e) for e in lc_events[:20]],
        "lifecycle_trace": _clean(trace) if trace else None,
        "trace_events": [_clean(e) for e in trace_events[:10]],
    }


def _clean(row):
    if not row: return None
    if isinstance(row, dict):
        return {k: _clean_val(v) for k, v in row.items()}
    return row

def _clean_val(v):
    if v is None: return None
    if isinstance(v, datetime): return v.isoformat()
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, (dict, list)): return v
    return v
