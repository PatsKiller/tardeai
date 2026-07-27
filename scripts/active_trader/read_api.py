"""Active Trader Stage 0 read API — health/status/sessions only."""
from __future__ import annotations

from typing import Any, Mapping

from .flags import Stage0Flags, load_flags

READ_API_CONTRACT = "active-trader-stage0-read-api-v1"
STAGE = 0

# Product intent venues (2026-07-27). Stage 0: inventory only — all live flags false.
VENUE_IDS = ("schwab", "moomoo", "alpaca")


def venue_inventory(flags: Stage0Flags | None = None) -> dict[str, dict[str, Any]]:
    """Read-only venue matrix. data/execution always false at Stage 0."""
    _ = flags
    out: dict[str, dict[str, Any]] = {}
    roles = {
        "schwab": "primary_execution_when_eligible",
        "moomoo": "augment_on_schwab_block_plus_l2_tape",
        "alpaca": "augment_execution_alternate",
    }
    for vid in VENUE_IDS:
        out[vid] = {
            "data": False,
            "execution": False,
            "read_only_inventory": True,
            "order_path": False,
            "role_intent": roles[vid],
        }
    return out


class ReadOnlyActiveTraderAPI:
    """Framework-neutral Stage 0 read surface. No create/update/delete/order methods."""

    def __init__(self, flags: Stage0Flags | None = None) -> None:
        self._flags = flags or load_flags()

    def health(self) -> dict[str, Any]:
        return {
            "contract": READ_API_CONTRACT,
            "stage": STAGE,
            "write": False,
            "canary": False,
            "read_only": True,
            "live_orders": False,
            "session_authorize": False,
            "venues": venue_inventory(self._flags),
            "ok": True,
            "product_intent": {
                "multi_broker": True,
                "schwab_primary": True,
                "operator_opt_in_required": True,
                "unattended_discover_and_fire": False,
            },
        }

    def status(self) -> dict[str, Any]:
        body = self.health()
        body["feature_flags"] = {
            k: bool(v) for k, v in self._flags.flags.items()
        }
        # Force hard offs even if misconfigured file somehow loaded (assert already ran)
        body["feature_flags"]["live_canary"] = False
        body["feature_flags"]["order_routes"] = False
        body["mode"] = "read_only_baseline"
        body["authority"] = {
            "mutation": False,
            "order": False,
            "session_authorize": False,
            "canary": False,
            "financial_action": False,
        }
        return body

    def list_sessions(self) -> dict[str, Any]:
        return {
            "contract": READ_API_CONTRACT,
            "stage": STAGE,
            "write": False,
            "canary": False,
            "sessions": [],
            "venues": venue_inventory(self._flags),
            "note": "Stage 0: no session schema yet; empty list is honest",
        }
