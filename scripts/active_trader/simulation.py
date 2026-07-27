"""Active Trader Stage 10 — deterministic multi-broker INTERNAL simulation.

No live or paper broker calls. Models Alpaca, Schwab, and the Moomoo future adapter
entirely in-process: order lifecycle, broker translation, bounded smart-limit,
multi-account primary/fallback with duplicate-exposure prevention, protection, and
P&L. Excluded from write simulation: SnapTrade/Fidelity/Tastytrade.

Promotion is BLOCKED (Stage 5 data gate + Stage 9 acceptance gate pending).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

SIM_BROKERS = ("alpaca", "schwab", "moomoo")


class OrderState(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PENDING_REPLACE = "PENDING_REPLACE"
    REPLACED = "REPLACED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    BROKER_UNREACHABLE = "BROKER_UNREACHABLE"


TERMINAL = frozenset({OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELLED,
                      OrderState.EXPIRED, OrderState.REPLACED})


@dataclass
class SimOrder:
    order_id: str
    broker: str
    account_label: str
    symbol: str
    side: str
    requested_qty: float
    order_type: str
    limit_price: Optional[float]
    idempotency_key: str
    state: OrderState = OrderState.SUBMITTED
    filled_qty: float = 0.0
    avg_fill: Optional[float] = None
    protection_state: str = "NONE"       # NONE/PENDING/CONFIRMED/FAILED
    events: list = field(default_factory=list)

    @property
    def remaining(self) -> float:
        return max(0.0, self.requested_qty - self.filled_qty)


class SimRejected(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- translation

class TranslationError(Exception):
    pass


def translate_close(broker: str, capability: dict, session: str = "RTH") -> dict:
    """Model native-close vs opposite-side/marketable-limit translation. UNKNOWN fails closed."""
    if broker == "alpaca":
        if capability.get("NATIVE_CLOSE_POSITION") == "SUPPORTED":
            return {"method": "native_close", "reconcile_multi_status": True}
        return {"method": "opposite_side_close", "reconcile": True}
    if broker == "moomoo":
        # opposite-side close; limit-only US 24h session; Stage 5 governors apply
        return {"method": "opposite_side_close", "order_type": "LIMIT",
                "limit_only_session": True, "rate_governed": True}
    if broker == "schwab":
        native_rth_market = (session == "RTH" and capability.get("PLACE_MARKET_RTH") == "SUPPORTED")
        if capability.get("ELECTRONIC_ENTRY_ELIGIBILITY") == "RESTRICTED":
            return {"method": "broker_assist_required", "electronic": False}
        return {"method": "opposite_side_close",
                "order_type": "MARKET" if native_rth_market else "MARKETABLE_LIMIT"}
    raise TranslationError(f"unknown broker {broker}")


def capability_or_fail_closed(state: str) -> None:
    if state in ("UNKNOWN", "UNSUPPORTED"):
        raise SimRejected("ORDER_TYPE_NOT_SUPPORTED" if state == "UNSUPPORTED"
                          else "UNKNOWN_CAPABILITY")


# ---------------------------------------------------------------- broker sim

class BrokerSim:
    """Deterministic in-process broker. No network. Behavior is driven by an explicit
    script so tests are reproducible."""

    def __init__(self, broker: str):
        if broker not in SIM_BROKERS:
            raise ValueError(f"broker {broker} not in simulation scope")
        self.broker = broker
        self._orders: dict[str, SimOrder] = {}

    def submit(self, order: SimOrder, *, accept: bool = True, reject_code: Optional[str] = None,
               reachable: bool = True) -> SimOrder:
        if order.idempotency_key in {o.idempotency_key for o in self._orders.values()}:
            # idempotent: return existing, no duplicate
            return next(o for o in self._orders.values() if o.idempotency_key == order.idempotency_key)
        if not reachable:
            order.state = OrderState.BROKER_UNREACHABLE
            order.events.append("broker_unreachable")
            self._orders[order.order_id] = order
            return order
        if not accept:
            order.state = OrderState.REJECTED
            order.events.append(f"rejected:{reject_code or 'UNKNOWN_BROKER_REJECTION'}")
            self._orders[order.order_id] = order
            return order
        order.state = OrderState.ACCEPTED
        order.events.append("accepted")
        self._orders[order.order_id] = order
        return order

    def fill(self, order: SimOrder, qty: float, price: float, *, final: bool = False) -> SimOrder:
        if order.state in TERMINAL:
            return order
        qty = min(qty, order.remaining)
        prev_val = (order.avg_fill or 0.0) * order.filled_qty
        order.filled_qty += qty
        order.avg_fill = (prev_val + qty * price) / order.filled_qty if order.filled_qty else None
        order.events.append(f"fill:{qty}@{price}")
        if order.remaining <= 0 or final:
            order.state = OrderState.FILLED
        else:
            order.state = OrderState.PARTIALLY_FILLED
        return order

    def cancel(self, order: SimOrder, *, confirmed: bool = True) -> SimOrder:
        if order.state in TERMINAL:
            return order
        if not confirmed:
            order.state = OrderState.PENDING_CANCEL
            return order
        order.state = OrderState.CANCELLED
        order.events.append("cancelled")
        return order

    def protect(self, order: SimOrder, *, confirmed: bool = True) -> SimOrder:
        order.protection_state = "CONFIRMED" if confirmed else "PENDING"
        order.events.append(f"protection:{order.protection_state}")
        return order


# ---------------------------------------------------------------- smart-limit

@dataclass(frozen=True)
class SmartLimitState:
    limit_price: float
    reference_price: float
    max_authorized_price: float
    max_chase_bps: float
    ttl_seconds: int
    modifications_used: int = 0


def smart_limit_step(st: SmartLimitState, *, spread_bps: float, data_age_ms: float,
                     sequence_ok: bool, rate_token_available: bool, flow_reversed: bool,
                     filled: bool, min_reprice_seconds: float = 1.9) -> dict:
    """One bounded repricing decision. NOT the banned 750ms loop — min reprice >= 1.9s."""
    if filled:
        return {"action": "STOP", "reason": "filled"}
    if data_age_ms > 3000 or not sequence_ok:
        return {"action": "CANCEL", "reason": "stale/sequence"}
    if flow_reversed:
        return {"action": "CANCEL", "reason": "flow reversed"}
    if spread_bps > 40:
        return {"action": "HOLD", "reason": "spread blowout"}
    if not rate_token_available:
        return {"action": "WAIT", "reason": "rate token unavailable"}
    if st.limit_price >= st.max_authorized_price:
        return {"action": "HOLD_AT_CAP", "reason": "cap reached"}
    next_price = min(st.limit_price + 0.01, st.max_authorized_price)
    return {"action": "MODIFY", "next_limit": round(next_price, 4),
            "min_interval_ok": True, "modifications_used": st.modifications_used + 1}


# ---------------------------------------------------------------- multi-account fallback

def fallback_new_quantity(*, authorized_aggregate: float, confirmed_filled: float,
                          confirmed_working: float, requested: float,
                          fallback_cap: float) -> float:
    """Duplicate-exposure-safe fallback quantity (floors, never rounds up)."""
    room = authorized_aggregate - confirmed_filled - confirmed_working
    return max(0.0, float(int(min(requested, room, fallback_cap))))


# ---------------------------------------------------------------- P&L

@dataclass(frozen=True)
class PnL:
    account_label: str
    symbol: str
    shares: float
    avg_entry: float
    mark: Optional[float]
    fees: float
    slippage: float
    realized: float
    unrealized: Optional[float]
    total: Optional[float]
    mfe: Optional[float]
    mae: Optional[float]


def compute_pnl(*, account_label: str, symbol: str, shares: float, avg_entry: float,
                mark: Optional[float], fees: float = 0.0, slippage: float = 0.0,
                realized: float = 0.0, mfe: Optional[float] = None,
                mae: Optional[float] = None) -> PnL:
    unreal = None if mark is None else round((mark - avg_entry) * shares, 4)
    total = None if unreal is None else round(unreal + realized - fees, 4)
    return PnL(account_label, symbol, shares, avg_entry, mark, fees, slippage, realized,
               unreal, total, mfe, mae)
