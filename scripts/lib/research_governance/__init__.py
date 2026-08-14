"""Trade AI — research governance subsystem (PR-R1, additive-only).

This package implements the research-promotion and statistical-governance layer
for the book/research knowledge infusion workstream. It is READ_ONLY_ADVISORY:
nothing here grants broker/order/stop authority, and nothing here touches the
live CIO/retrieval engines (deferred to R4).

Public surface:
  enums, models, source_catalog, trial_registry, multiple_testing,
  deflated_sharpe, pbo, bootstrap_reality_check, cv, promotion_gate,
  retrieval_contract, acceptance, acceptance_checks, pr_scope_guard.
"""
from __future__ import annotations

__all__ = [
    "enums",
    "models",
    "source_catalog",
    "trial_registry",
    "multiple_testing",
    "deflated_sharpe",
    "pbo",
    "bootstrap_reality_check",
    "cv",
    "promotion_gate",
    "retrieval_contract",
    "acceptance",
    "acceptance_checks",
    "pr_scope_guard",
]
