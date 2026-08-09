"""Rockville Watchlist Intelligence + CIO synthesis (CC v3 /v3/watch).

Advisory LLM only. Deterministic failure cannot become READY/WAIT/proposal-eligible.
Exact DeepSeek models only — no silent fallback.
"""

from .model_policy import (
    EXACT_FLASH,
    EXACT_PRO,
    FORBIDDEN_MODELS,
    PolicyId,
    get_policy,
    resolve_policy,
    validate_exact_model,
)
from .decision_projection import (
    INVALID_MECHANICS_STATES,
    PRIMARY_STATES,
    project_watch_decision,
)
from .material_fingerprint import (
    build_symbol_material_fingerprint,
    build_watchlist_material_hash,
)
from .cio_scheduler import evaluate_cio_trigger, market_date_et

__all__ = [
    "EXACT_FLASH",
    "EXACT_PRO",
    "FORBIDDEN_MODELS",
    "PolicyId",
    "get_policy",
    "resolve_policy",
    "validate_exact_model",
    "INVALID_MECHANICS_STATES",
    "PRIMARY_STATES",
    "project_watch_decision",
    "build_symbol_material_fingerprint",
    "build_watchlist_material_hash",
    "evaluate_cio_trigger",
    "market_date_et",
]
