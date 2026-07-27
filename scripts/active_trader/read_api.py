"""Active Trader Stage 0 read API — health/status/sessions only."""
from __future__ import annotations

from typing import Any, Mapping

from .flags import Stage0Flags, load_flags

READ_API_CONTRACT = "active-trader-stage0-read-api-v1"
STAGE = 0


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
            "ok": True,
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
            "note": "Stage 0: no session schema yet; empty list is honest",
        }
