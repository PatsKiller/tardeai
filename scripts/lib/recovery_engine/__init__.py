"""Recovery & Re-Entry Engine — piece A (operator directive 2026-11-03P0).

The engine exists because the operator's largest stop-out (SPCX, ~$140k, five exits, the last at −$12,770 on 2026-10-30)
went unanswered: no case was opened, the re-entry path declared the symbol "held" because a 200-share taxable residual
survived, and nothing told him the name was recovering.

Piece A owns the *facts*: the ``recovery_cases`` row, the fills consumer that opens it, the residual-aware held rule, and
the materiality tiers. Nothing here notifies, evaluates market state (piece B), renders a card (piece D) or taps a
button. The state machine's inputs are supplied by B; this package stores and validates them.

RAILS: read-only against the broker, no order path, no size/stop/order value hard-coded (house rule), every threshold in
``config/recovery_policy.yaml``. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

__all__ = [
    "CaseStore",
    "Eligibility",
    "Policy",
    "RecoveryCase",
    "consume_fills",
    "residual_display",
    "load_policy",
    "materiality_tier",
]
