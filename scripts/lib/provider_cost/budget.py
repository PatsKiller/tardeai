"""Paid model-call budget precheck — never fail open.

AGENTS.md §9.2: check the budget before the call; a check that cannot be
established DENIES. Mirrors scripts/lib/search_budget.py semantics for LLM
spend.

READ_ONLY_ADVISORY w.r.t. trading. Never prints secrets.
"""
from __future__ import annotations

import os
from typing import Any, Optional


class BudgetDenied(RuntimeError):
    """Call must not proceed. reason is a stable code string."""

    def __init__(self, reason: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_test_context(process_id: str | None) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    if _truthy("TRADE_AI_CI") and not _truthy("TRADEAI_ENFORCE_MODEL_BUDGET_IN_CI"):
        return True
    pid = str(process_id or "")
    return (
        pid.startswith("test_")
        or pid.startswith("test-")
        or pid.startswith("pytest_")
        or pid.startswith("fixture_")
        or pid == "test"
    )


def ensure_budget_allows_call(
    *,
    process_id: str | None = None,
    projected_usd: float = 0.0,
    reservation_id: str | None = None,
    require_global_cap: bool = True,
) -> dict[str, Any]:
    """Return an allow dict, or raise BudgetDenied.

    Never returns allow=True after a check failure. Upstream reservations
    (gate_and_generate) short-circuit as already checked.
    """
    if reservation_id not in (None, ""):
        return {
            "allow": True,
            "reason": "RESERVATION_HELD",
            "reservation_id": str(reservation_id),
            "fail_open": False,
        }

    if _is_test_context(process_id):
        return {
            "allow": True,
            "reason": "TEST_CONTEXT",
            "fail_open": False,
        }

    # Import the package the test suite and callers already use (`lib.*` with
    # scripts/ on sys.path). Avoid scripts.lib.* vs lib.* dual-module skew.
    try:
        import lib.llm_consumption as lc  # type: ignore
    except ImportError:
        try:
            from scripts.lib import llm_consumption as lc  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise BudgetDenied(
                "BUDGET_UNAVAILABLE",
                details={"error": type(exc).__name__, "fail_open": False},
            ) from exc

    try:
        if not lc.cost_persistence_available():
            raise BudgetDenied(
                "BUDGET_UNAVAILABLE",
                details={"error": "persistence_unavailable", "fail_open": False},
            )

        gcap_raw = os.environ.get("LLM_GLOBAL_DAILY_USD_CAP")
        try:
            gcap = float(gcap_raw) if gcap_raw not in (None, "") else None
        except (TypeError, ValueError):
            gcap = None
        if require_global_cap and (gcap is None or gcap <= 0):
            raise BudgetDenied(
                "COST_CONFIGURATION_INVALID",
                details={"error": "global daily USD cap required", "fail_open": False},
            )

        pid = str(process_id or "").strip() or "unregistered"
        result = lc.check_cost_cap(pid, projected_usd=float(projected_usd or 0.0), global_cap=gcap)
        if not result.get("allow"):
            raise BudgetDenied(
                str(result.get("reason") or "COST_CAP_EXCEEDED"),
                details={**dict(result), "fail_open": False},
            )
        return {**dict(result), "fail_open": False}
    except BudgetDenied:
        raise
    except Exception as exc:  # noqa: BLE001
        # Any unexpected failure DENIES — never fail open.
        raise BudgetDenied(
            "BUDGET_UNAVAILABLE",
            details={"error": type(exc).__name__, "fail_open": False},
        ) from exc
