"""Cross-asset decision intelligence — canonical v2 and legacy compatibility.

READ_ONLY_ADVISORY. Never submits broker orders.
"""
from __future__ import annotations

from .canonical_decision import (
    SCHEMA as CANONICAL_SCHEMA,
    adapt_decision,
    build_decision,
    process_decision_batch,
    validate_decision,
)
from .decision_store import DecisionStore
from .symbol_decision_object import (
    SCHEMA,
    AUTHORITY,
    new_symbol_decision,
    validate_symbol_decision,
)
from .persistence import append_symbol_decision, load_latest_by_symbol
from .assemble import assemble_symbol_decision
from .expression_router import route_expressions, SIGNAL_EXPRESSIONS
from .security_research_spine import (
    CONSUMER_SILOS,
    empty_spine,
    upsert_from_hermes,
    upsert_research_memory,
    view_for_silo,
    spine_rows_for_options_universe,
)

__all__ = [
    "CANONICAL_SCHEMA", "adapt_decision", "build_decision", "process_decision_batch", "validate_decision",
    "DecisionStore",
    "SCHEMA",
    "AUTHORITY",
    "new_symbol_decision",
    "validate_symbol_decision",
    "append_symbol_decision",
    "load_latest_by_symbol",
    "assemble_symbol_decision",
    "route_expressions",
    "SIGNAL_EXPRESSIONS",
    "CONSUMER_SILOS",
    "empty_spine",
    "upsert_from_hermes",
    "upsert_research_memory",
    "view_for_silo",
    "spine_rows_for_options_universe",
]
