"""broker_adapter.py — vendor-neutral broker confirmation contract.

This module defines the broker-agnostic interface the phantom-confirmation gate depends on.
It names NO broker: the broker for an account comes from config, and the concrete
implementation is discovered by name (broker_confirm_<name>.py). Adding a new broker later
is a drop-in file; this module and the gate never change.

HARD RULE: this file contains zero vendor string literals. The only place a broker is named
is config (the accounts table) and the per-broker implementation files. (Audit finding L4,
docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md: an earlier version of this docstring named two
real vendors as an illustrative example, one paragraph after claiming to name none — fixed for
internal consistency; the claim was already true in the actual dispatch code, grep-verified.)
"""
import importlib
import os
import sys
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@dataclass
class FillConfirmation:
    """The broker's authoritative answer about an order. Returned by every adapter."""
    confirmed: bool                       # broker affirms the order is filled
    broker_order_id: Optional[str] = None
    filled_qty: Optional[float] = None
    filled_price: Optional[float] = None
    fill_time: Optional[str] = None       # ISO; broker's fill timestamp
    status: str = "unknown"               # filled | partial | pending | canceled | rejected | unknown | no_order_id
    raw: Optional[dict] = None


@runtime_checkable
class BrokerAdapter(Protocol):
    """The contract every broker implements. Callers depend on this, never on a vendor."""
    broker_name: str

    def submit_order(self, **kwargs) -> FillConfirmation: ...
    def get_order_status(self, order_id: str) -> FillConfirmation: ...
    def confirm_fill(self, order_id: str) -> FillConfirmation: ...
    def get_positions(self) -> list: ...
    def get_open_orders(self) -> list: ...
    def get_account(self) -> dict: ...
    def get_status(self) -> dict: ...


def _normalize(account_label: str) -> str:
    return (account_label or "").strip()


def adapter_for(account_label: str) -> BrokerAdapter:
    """Resolve the broker adapter for an account WITHOUT naming any broker.

    The broker name is read from config (accounts table); the implementation is imported by
    name (broker_confirm_<broker>.py) and constructed via its make_adapter(account_label).
    """
    from broker_config import get_account_broker
    label = _normalize(account_label)
    broker = get_account_broker(label)
    if (not broker or broker == "unknown") and label != label.lower():
        broker = get_account_broker(label.lower())   # paper_trades.account is sometimes upper-cased
    if not broker or broker == "unknown":
        raise ValueError(f"no broker configured for account '{account_label}'")
    try:
        mod = importlib.import_module(f"broker_confirm_{broker}")
    except ModuleNotFoundError as e:
        raise NotImplementedError(f"no confirm-adapter for broker '{broker}' (broker_confirm_{broker}.py)") from e
    return mod.make_adapter(label)
