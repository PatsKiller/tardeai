"""Provider spend attribution — observability / FinOps only.

READ_ONLY_ADVISORY. Never trading authority. Never logs raw API keys.
"""
from __future__ import annotations

SCHEMA_VERSION = "ProviderCostEvent@v1"

from .context import cost_attribution, current_attribution
from .emit import emit_attempt, emit_cost_event, emit_paid_call

__all__ = [
    "SCHEMA_VERSION",
    "cost_attribution",
    "current_attribution",
    "emit_attempt",
    "emit_cost_event",
    "emit_paid_call",
]
