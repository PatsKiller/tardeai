"""Protection count floor and policy exemptions: one reader for every surface (LQ-20261113-3047, Home/Portfolio A05).

Operator policy, design/pages/portfolio/v002/DECISIONS-20261111.md §Exemptions:
  * exempt by default: cash, money-market funds, sweep vehicles;
  * never exempt: ETFs, closed-end funds, mutual funds, stocks;
  * a position under $100 is listed, not counted, not hidden;
  * one config owner.

The floor's one owner is ``config/position_count_authority.json`` ``min_position_usd`` (LQ-20261107-1820, $100),
read through ``portfolio_total_contract.current_floor()``, which falls back loudly to $100 when the file is
unreadable. No reader keeps a floor of its own: cio_truth, home_status_verdict, stop_coverage_incidents and
desk_truth_monitor (and numbers_truth_audit through it) all call :func:`count_floor_usd`. The $1,000
``min_position_value_usd`` that config/desk_truth_monitors.json carried (8d7d6263f, 2026-10-22) pre-dated the policy
and contradicted it; it is gone, and a stale copy of that key in a cfg dict is ignored.
"""
from __future__ import annotations

from typing import Any

try:  # repo root on sys.path (tests, the API) vs scripts/ on sys.path (host lanes)
    from scripts.lib.portfolio_total_contract import FALLBACK_FLOOR_USD, current_floor
except ImportError:  # pragma: no cover - import shape depends on the caller
    from lib.portfolio_total_contract import FALLBACK_FLOOR_USD, current_floor  # type: ignore[no-redef]

FLOOR_CONFIG = "config/position_count_authority.json:min_position_usd"
POLICY_EXEMPT_ASSET_TYPES = ("CASH", "MONEY_MARKET", "MONEY_MARKET_FUND", "SWEEP", "SWEEP_VEHICLE")
NEVER_EXEMPT_ASSET_TYPES = ("ETF", "CEF", "CLOSED_END_FUND", "MUTUAL_FUND", "EQUITY", "STOCK")

__all__ = ["FALLBACK_FLOOR_USD", "FLOOR_CONFIG", "NEVER_EXEMPT_ASSET_TYPES", "POLICY_EXEMPT_ASSET_TYPES",
           "count_floor_usd", "exempt_reason", "source"]


def count_floor_usd() -> float:
    """The protection count floor in USD (policy: $100). Under it, a priced, non-exempt row is listed, not counted."""
    return float(current_floor()[0])


def source() -> dict[str, Any]:
    """The floor and where it came from (``config`` or ``config_unreadable:<why>``), for a receipt or Diagnostics."""
    floor, src = current_floor()
    return {"count_floor_usd": float(floor), "config": FLOOR_CONFIG, "source": src}


def exempt_reason(*, is_cash: Any = False, asset_type: Any = None) -> str | None:
    """The policy exemption for a held row, or None: cash / money-market fund / sweep vehicle.

    ETF, CEF, MUTUAL_FUND and stock are never exempt here (policy). Whether a mutual fund can carry a stop is a
    different question (LQ-2964's not-stop-protectable label), answered by the stop-coverage config, not by policy.
    """
    if is_cash:
        return "cash"
    t = str(asset_type or "").strip().upper().replace(" ", "_")
    if not t or t in NEVER_EXEMPT_ASSET_TYPES or t not in POLICY_EXEMPT_ASSET_TYPES:
        return None
    return "sweep vehicle" if t.startswith("SWEEP") else ("cash" if t == "CASH" else "money-market fund")
