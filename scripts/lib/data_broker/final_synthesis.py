"""Final Synthesis — Data Broker read model for dual-LLM consensus synthesis.

Batch-reads watchlist_final_synthesis (recommendation, models_agree, dual_consensus_json,
CIO trust metadata). Normalized for decision desks, cio_trust_bundle, and entry planner consumers.
"""
from __future__ import annotations

from typing import Any


def get_final_synthesis(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {recommendation, models_agree, dual_consensus_json, decision_safety, ...}}
    for a batch, taking only the latest synthesis per symbol (excluding LLM-error rows).

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, recommendation, confidence, models_agree,
                  dual_consensus_json, model_used, decision_safety, conflicts,
                  unresolved, synthesis_narrative, updated_at
           FROM watchlist_final_synthesis
           WHERE upper(symbol) = ANY(%s)
             AND (synthesis_narrative IS NULL
                  OR synthesis_narrative NOT ILIKE 'LLM error:%%')
           ORDER BY upper(symbol), updated_at DESC NULLS LAST""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = {
                "recommendation": row.get("recommendation"),
                "confidence": row.get("confidence"),
                "models_agree": row.get("models_agree"),
                "dual_consensus_json": row.get("dual_consensus_json"),
                "model_used": row.get("model_used"),
                "decision_safety": row.get("decision_safety"),
                "conflicts": row.get("conflicts"),
                "unresolved": row.get("unresolved"),
                "synthesis_narrative": row.get("synthesis_narrative"),
                "updated_at": row.get("updated_at"),
            }
    return out
