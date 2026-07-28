"""L2 feature snapshots and deterministic T2 admission.

T2 is never inferred from an arm intent or a successful subscribe call.  It requires a
healthy provider, confirmed data subtypes, fresh book/tape observations, verified
sequence evidence, a matching reconnect epoch, and a coherent non-crossed book.
Read plane only; no order or trade-unlock path.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import scalp_t2_metrics as t2m  # noqa: E402

try:
    from .subscription_manager import L2State, SubscriptionManager, SUB_ORDER_BOOK, SUB_TICKER
    from .quote_gateway import QuoteGateway
except ImportError:  # pragma: no cover
    from subscription_manager import L2State, SubscriptionManager, SUB_ORDER_BOOK, SUB_TICKER  # type: ignore
    from quote_gateway import QuoteGateway  # type: ignore


@dataclass
class T2Decision:
    is_t2: bool
    reason: str
    freshness_state: str
    sequence_state: str
    confirmed_subtypes: tuple[str, ...] = ()
    feature: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_t2": self.is_t2,
            "reason": self.reason,
            "freshness_state": self.freshness_state,
            "sequence_state": self.sequence_state,
            "confirmed_subtypes": list(self.confirmed_subtypes),
            "feature": self.feature,
        }


class L2FeatureService:
    def __init__(self, gateway: QuoteGateway, manager: SubscriptionManager, *, levels: int = 5):
        self.gateway = gateway
        self.manager = manager
        self.levels = int(levels)

    def feature_snapshot(self, symbol: str, now: float, feature_at_iso: str) -> Optional[dict[str, Any]]:
        sym = symbol.upper()
        book = self.gateway.latest_book(sym)
        if book is None or not book.bids or not book.asks:
            return None
        bids, asks = book.bids, book.asks
        summary = t2m.book_summary(bids, asks, self.levels)
        best_bid, best_ask = summary["best_bid"], summary["best_ask"]
        spread_cents = (
            None
            if best_bid is None or best_ask is None
            else round((best_ask - best_bid) * 100.0, 4)
        )
        top_bid_depth = float(sum(float(size) for _price, size in bids[: self.levels]))
        top_ask_depth = float(sum(float(size) for _price, size in asks[: self.levels]))
        weighted_mid = None
        if best_bid is not None and best_ask is not None and top_bid_depth + top_ask_depth > 0:
            weighted_mid = (
                best_bid * top_ask_depth + best_ask * top_bid_depth
            ) / (top_bid_depth + top_ask_depth)

        prints = self.gateway.tape(sym)
        buys = sum(1 for print_ in prints if print_.side == "BUY")
        sells = sum(1 for print_ in prints if print_.side == "SELL")
        count = len(prints)
        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_cents": spread_cents,
            "spread_bps": summary["quoted_spread_bps"],
            "top_n_bid_depth": top_bid_depth,
            "top_n_ask_depth": top_ask_depth,
            "book_imbalance": summary["book_imbalance"],
            "microprice": summary["microprice"],
            "weighted_mid": weighted_mid,
            "tape_velocity": float(count),
            "aggressor_buy_ratio": (buys / count) if count else None,
            "aggressor_sell_ratio": (sells / count) if count else None,
            "replenishment": None,
            "cancellation_pressure": None,
            "levels": summary["levels"],
            "provider_at": book.provider_at,
            "received_at": book.received_at,
            "feature_at": feature_at_iso,
            "sequence_id": book.sequence_id,
        }

    def evaluate_t2(
        self,
        symbol: str,
        now: float,
        feature_at_iso: str,
        *,
        require_tape: Optional[bool] = None,
    ) -> T2Decision:
        sym = symbol.upper()
        life = self.manager.symbols.get(sym)
        want_tape = life.require_tape if require_tape is None and life is not None else bool(require_tape)

        if not self.manager._connected():
            return T2Decision(False, "PROVIDER_DISCONNECTED", "UNKNOWN", "UNKNOWN")
        if not self.manager._entitled():
            return T2Decision(False, "ENTITLEMENT_MISSING", "UNKNOWN", "UNKNOWN")
        if life is None:
            return T2Decision(False, "NOT_REQUESTED", "UNKNOWN", "UNKNOWN")

        confirmed = tuple(life.confirmed_subtypes or ())
        if SUB_ORDER_BOOK not in confirmed:
            return T2Decision(False, "ORDER_BOOK_NOT_CONFIRMED", "UNKNOWN", "UNKNOWN", confirmed)
        if want_tape and SUB_TICKER not in confirmed:
            return T2Decision(False, "TICKER_NOT_CONFIRMED", "UNKNOWN", "UNKNOWN", confirmed)
        if life.state == L2State.SEQUENCE_GAP:
            return T2Decision(False, "SEQUENCE_GAP", "UNKNOWN", "GAP", confirmed)
        if life.state == L2State.CROSSED_BOOK:
            return T2Decision(False, "CROSSED_BOOK", "UNKNOWN", "OK", confirmed)
        if life.reconnect_epoch != self.manager.reconnect_epoch:
            return T2Decision(False, "RECONNECT_EPOCH_MISMATCH", "UNKNOWN", "EPOCH_MISMATCH", confirmed)
        if life.sequence_id is None:
            # A timestamped book without sequence provenance is evidence, but not canonical T2.
            return T2Decision(False, "SEQUENCE_UNVERIFIED", "UNKNOWN", "UNVERIFIED", confirmed)
        if life.state in (L2State.WAITING_FIRST_BOOK, L2State.WAITING_FIRST_TAPE):
            return T2Decision(False, "WAITING_FIRST_DATA", "WAITING", "OK", confirmed)
        if life.state == L2State.STALE:
            feature = self.feature_snapshot(sym, now, feature_at_iso) or {}
            return T2Decision(False, "STALE_BOOK", "STALE", "OK", confirmed, feature)

        book = self.gateway.latest_book(sym)
        if book is None:
            return T2Decision(False, "NO_BOOK", "WAITING", "OK", confirmed)
        if book.crossed:
            return T2Decision(False, "CROSSED_BOOK", "UNKNOWN", "OK", confirmed)
        if book.sequence_id is None or book.sequence_id != life.sequence_id:
            return T2Decision(False, "SEQUENCE_UNVERIFIED", "UNKNOWN", "UNVERIFIED", confirmed)
        if life.state != L2State.FRESH:
            return T2Decision(False, f"NOT_FRESH_{life.state.value}", "UNKNOWN", "OK", confirmed)
        if want_tape and life.first_tape_at is None:
            return T2Decision(False, "TAPE_REQUIRED_MISSING", "WAITING", "OK", confirmed)

        feature = self.feature_snapshot(sym, now, feature_at_iso)
        if feature is None:
            return T2Decision(False, "NO_BOOK", "WAITING", "OK", confirmed)
        return T2Decision(True, "OK", "FRESH", "OK", confirmed, feature)
