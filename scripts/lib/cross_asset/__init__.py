"""Cross-asset decision intelligence — SymbolDecisionObject and shadow routing.

READ_ONLY_ADVISORY. Never submits broker orders.
"""
from __future__ import annotations

from .symbol_decision_object import (
    SCHEMA,
    AUTHORITY,
    new_symbol_decision,
    validate_symbol_decision,
)
from .persistence import append_symbol_decision, load_latest_by_symbol
from .assemble import assemble_symbol_decision
from .expression_router import route_expressions, SIGNAL_EXPRESSIONS

__all__ = [
    "SCHEMA",
    "AUTHORITY",
    "new_symbol_decision",
    "validate_symbol_decision",
    "append_symbol_decision",
    "load_latest_by_symbol",
    "assemble_symbol_decision",
    "route_expressions",
    "SIGNAL_EXPRESSIONS",
]
