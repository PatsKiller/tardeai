"""L2 feature snapshots + the deterministic T2 admission gate.

Turns the gateway's bounded book/tape buffers into a compact, non-secret feature snapshot,
and decides whether a symbol currently qualifies as real Tier-2 (T2). T2 is NEVER inferred
from "armed" or "requested": it requires EVERY one of —
  * OpenD healthy (provider connected)
  * L2 entitlement available
  * subscription confirmed (ORDER_BOOK, and TICKER when tape is required)
  * a FRESH book
  * a FRESH tape when the setup requires tape
  * healthy sequence + matching reconnect epoch (no gap)
  * a non-crossed, coherent book

Any failure → NOT T2, with a typed reason. Pure over injected gateway+manager state, so it
is fully deterministic in tests. No I/O, no DB writes, no order path.
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
    from .quote_gateway import QuoteGateway, BookSnapshot
except ImportError:  # pragma: no cover
    from subscription_manager import L2State, SubscriptionManager, SUB_ORDER_BOOK, SUB_TICKER  # type: ignore
    from quote_gateway import QuoteGateway, BookSnapshot  # type: ignore


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
            "is_t2": self.is_t2, "reason": self.reason,
            "freshness_state": self.freshness_state, "sequence_state": self.sequence_state,
            "confirmed_subtypes": list(self.confirmed_subtypes), "feature": self.feature,
        }


class L2FeatureService:
    def __init__(self, gateway: QuoteGateway, manager: SubscriptionManager, *, levels: int = 5):
        self.gateway = gateway
        self.manager = manager
        self.levels = int(levels)

    # ── feature snapshot (compact, non-secret) ───────────────────────────────
    def feature_snapshot(self, symbol: str, now: float, feature_at_iso: str) -> Optional[dict[str, Any]]:
        sym = symbol.upper()
        book = self.gateway.latest_book(sym)
        if book is None or not book.bids or not book.asks:
            return None
        bids, asks = book.bids, book.asks
        summ = t2m.book_summary(bids, asks, self.levels)
        bb, ba = summ["best_bid"], summ["best_ask"]
        spread_cents = None if (bb is None or ba is None) else round((ba - bb) * 100.0, 4)
        top_bid_depth = float(sum(float(s) for _p, s in bids[:self.levels]))
        top_ask_depth = float(sum(float(s) for _p, s in asks[:self.levels]))
        # weighted mid (depth-weighted across top N) — distinct from Stoikov microprice
        weighted_mid = None
        if bb is not None and ba is not None and (top_bid_depth + top_ask_depth) > 0:
            weighted_mid = (bb * top_ask_depth + ba * top_bid_depth) / (top_bid_depth + top_ask_depth)

        prints = self.gateway.tape(sym)
        buys = sum(1 for p in prints if p.side == "BUY")
        sells = sum(1 for p in prints if p.side == "SELL")
        n = len(prints)
        tape_velocity = float(n)  # prints in the bounded window (per-window count)
        aggressor_buy_ratio = (buys / n) if n else None
        aggressor_sell_ratio = (sells / n) if n else None

        return {
            "best_bid": bb, "best_ask": ba,
            "spread_cents": spread_cents, "spread_bps": summ["quoted_spread_bps"],
            "top_n_bid_depth": top_bid_depth, "top_n_ask_depth": top_ask_depth,
            "book_imbalance": summ["book_imbalance"], "microprice": summ["microprice"],
            "weighted_mid": weighted_mid,
            "tape_velocity": tape_velocity,
            "aggressor_buy_ratio": aggressor_buy_ratio, "aggressor_sell_ratio": aggressor_sell_ratio,
            "replenishment": None,          # requires multi-snapshot delta history (not in window yet)
            "cancellation_pressure": None,  # ditto — reported honestly as absent, never fabricated
            "levels": summ["levels"],
            "provider_at": book.provider_at, "received_at": book.received_at,
            "feature_at": feature_at_iso, "sequence_id": book.sequence_id,
        }

    # ── T2 admission gate ────────────────────────────────────────────────────
    def evaluate_t2(self, symbol: str, now: float, feature_at_iso: str, *,
                    require_tape: Optional[bool] = None) -> T2Decision:
        sym = symbol.upper()
        life = self.manager.symbols.get(sym)
        want_tape = (life.require_tape if (require_tape is None and life is not None)
                     else bool(require_tape))

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

        # deterministic lifecycle state is the source of truth for freshness/waiting
        if life.state in (L2State.WAITING_FIRST_BOOK, L2State.WAITING_FIRST_TAPE):
            return T2Decision(False, "WAITING_FIRST_DATA", "WAITING", "OK", confirmed)
        if life.state == L2State.STALE:
            feat = self.feature_snapshot(sym, now, feature_at_iso) or {}
            return T2Decision(False, "STALE_BOOK", "STALE", "OK", confirmed, feat)

        book = self.gateway.latest_book(sym)
        if book is None:
            return T2Decision(False, "NO_BOOK", "WAITING", "OK", confirmed)
        if book.crossed:
            return T2Decision(False, "CROSSED_BOOK", "UNKNOWN", "OK", confirmed)

        if life.state != L2State.FRESH:
            return T2Decision(False, f"NOT_FRESH_{life.state.value}", "UNKNOWN", "OK", confirmed)
        if want_tape and life.first_tape_at is None:
            return T2Decision(False, "TAPE_REQUIRED_MISSING", "WAITING", "OK", confirmed)

        feat = self.feature_snapshot(sym, now, feature_at_iso)
        if feat is None:
            return T2Decision(False, "NO_BOOK", "WAITING", "OK", confirmed)
        return T2Decision(True, "OK", "FRESH", "OK", confirmed, feat)
