"""SchwabOrderAdapter — DORMANT stub (this phase). Every mutating method raises ExecutionBlocked
UNCONDITIONALLY, before and independent of guard/config. Reads delegate to the read-only transport.
This module intentionally performs ZERO order-endpoint I/O; the schwab_transport write fence
(NotProvenWrite, 12/12) remains the authoritative lower layer."""
from __future__ import annotations

from .execution_guard import ExecutionBlocked

_BLOCK = ("Schwab order execution is disabled this phase (BROKER_DISABLED). Translation previews are "
          "available via /api/v2/broker-orders/preview. Live enablement is governed by the release gating "
          "checklist in docs/brokers/execution-safety-guards.md and is OUT OF SCOPE.")


class SchwabOrderAdapter:
    broker = "schwab"

    # ── mutating surface: blocked unconditionally ───────────────────────────
    def submit(self, intent, translation):          raise ExecutionBlocked(_BLOCK)
    def replace(self, intent, broker_order_id):     raise ExecutionBlocked(_BLOCK)
    def cancel(self, broker_order_id):              raise ExecutionBlocked(_BLOCK)

    # ── read-only surface: existing fence-guarded transport ────────────────
    def get_status(self, account_key, order_id):
        import schwab_transport
        return schwab_transport.get_orders(account_key)

    def get_positions(self, account_key):
        import schwab_transport
        return schwab_transport.get_positions(account_key)
