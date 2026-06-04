"""broker_confirm_alpaca.py — Alpaca implementation of the BrokerAdapter contract.

This is the ONLY file in the confirmation stack that names Alpaca. It wraps the existing
AlpacaPaperAdapter and adds the two contract methods the gate needs — get_order_status() and
confirm_fill() — by querying Alpaca's orders endpoint. It does not place orders in this pass.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from broker_adapter import FillConfirmation


class _AlpacaConfirmAdapter:
    broker_name = "alpaca"

    def __init__(self, account_label=None):
        from alpaca_paper_adapter import AlpacaPaperAdapter
        self.account_label = account_label
        self._a = AlpacaPaperAdapter()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._a, "enabled", False))

    def _to_confirmation(self, o: dict) -> FillConfirmation:
        status = (o or {}).get("status") or "unknown"
        try:
            filled_qty = float(o.get("filled_qty") or 0)
        except (TypeError, ValueError):
            filled_qty = 0.0
        fap = (o or {}).get("filled_avg_price")
        try:
            filled_price = float(fap) if fap not in (None, "") else None
        except (TypeError, ValueError):
            filled_price = None
        return FillConfirmation(
            confirmed=(status == "filled" and filled_qty > 0),
            broker_order_id=(o or {}).get("id"),
            filled_qty=filled_qty or None,
            filled_price=filled_price,
            fill_time=(o or {}).get("filled_at"),
            status=status,
            raw=o,
        )

    def get_order_status(self, order_id: str) -> FillConfirmation:
        if not order_id:
            return FillConfirmation(confirmed=False, status="no_order_id")
        if not self.enabled:
            return FillConfirmation(confirmed=False, broker_order_id=order_id, status="unknown")
        try:
            o = self._a._api_get(f"/v2/orders/{order_id}")
            return self._to_confirmation(o)
        except Exception:
            # order not found at broker, or transient error — treat as unconfirmed, not fabricated
            return FillConfirmation(confirmed=False, broker_order_id=order_id, status="unknown")

    def confirm_fill(self, order_id: str, *, attempts: int = 3, delay_s: float = 1.0) -> FillConfirmation:
        fc = FillConfirmation(confirmed=False, broker_order_id=order_id, status="unknown")
        for i in range(max(1, attempts)):
            fc = self.get_order_status(order_id)
            if fc.status in ("filled", "canceled", "cancelled", "rejected", "expired", "no_order_id"):
                return fc
            if i < attempts - 1:
                time.sleep(delay_s)
        return fc

    def submit_order(self, **kwargs) -> FillConfirmation:
        # Order submission stays on the existing submit_entry path; not wired in STEP 2.
        raise NotImplementedError("submit_order is not wired in STEP 2 (test-and-design only)")

    def get_positions(self):
        return self._a.get_positions()

    def get_open_orders(self):
        return self._a.get_open_orders()

    def get_account(self):
        return self._a.get_account()

    def get_status(self):
        return self._a.get_status()


def make_adapter(account_label=None):
    return _AlpacaConfirmAdapter(account_label)
