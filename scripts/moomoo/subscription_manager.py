"""Deterministic Moomoo/OpenD L2 subscription lifecycle and quota truth.

This module owns only the subscription decision state.  A future dedicated gateway
service supplies the transport and serializes calls.  It never opens an OpenQuoteContext,
never touches an order path, and fails closed whenever quota, entitlement, subscription,
or data confirmation is uncertain.

Key invariants:

* quota is simultaneous symbol-by-subtype allocation, not a daily call budget;
* P0 may consume reserved capacity but may never exceed the provider's hard remaining
  quota;
* unknown quota blocks every new subscription;
* subscribe acceptance is not data confirmation;
* ORDER_BOOK/TICKER/QUOTE become confirmed only when corresponding data is observed;
* an unsubscribe failure retains quota and stays pending instead of reporting success;
* arm intent, subscription, fresh data, and T2 admission remain distinct facts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

try:
    from .l2_lifecycle_config import L2LifecycleConfig, load_l2_lifecycle_config
except ImportError:  # pragma: no cover
    from l2_lifecycle_config import L2LifecycleConfig, load_l2_lifecycle_config  # type: ignore

SUB_QUOTE = "QUOTE"
SUB_ORDER_BOOK = "ORDER_BOOK"
SUB_TICKER = "TICKER"
SUB_K_1M = "K_1M"


class L2State(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    ARM_INTENT = "ARM_INTENT"
    QUOTA_DEFERRED = "QUOTA_DEFERRED"
    SUBSCRIBE_REQUESTED = "SUBSCRIBE_REQUESTED"
    SUBSCRIBED = "SUBSCRIBED"
    WAITING_FIRST_BOOK = "WAITING_FIRST_BOOK"
    WAITING_FIRST_TAPE = "WAITING_FIRST_TAPE"
    FRESH = "FRESH"
    STALE = "STALE"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    CROSSED_BOOK = "CROSSED_BOOK"
    ENTITLEMENT_MISSING = "ENTITLEMENT_MISSING"
    PROVIDER_DISCONNECTED = "PROVIDER_DISCONNECTED"
    FAILED = "FAILED"
    POST_FIRE_RETENTION = "POST_FIRE_RETENTION"
    UNSUBSCRIBE_PENDING = "UNSUBSCRIBE_PENDING"
    UNSUBSCRIBED = "UNSUBSCRIBED"


_SUBSCRIBED_STATES = frozenset(
    {
        L2State.SUBSCRIBE_REQUESTED,
        L2State.SUBSCRIBED,
        L2State.WAITING_FIRST_BOOK,
        L2State.WAITING_FIRST_TAPE,
        L2State.FRESH,
        L2State.STALE,
        L2State.SEQUENCE_GAP,
        L2State.CROSSED_BOOK,
        L2State.POST_FIRE_RETENTION,
        L2State.UNSUBSCRIBE_PENDING,
    }
)
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


@dataclass
class SymbolLifecycle:
    symbol: str
    state: L2State = L2State.NOT_REQUESTED
    reason: str = ""
    priority: str = "P2"
    requested_subtypes: tuple[str, ...] = ()
    confirmed_subtypes: tuple[str, ...] = ()
    armed_at: Optional[float] = None
    subscribed_at: Optional[float] = None
    first_book_at: Optional[float] = None
    first_tape_at: Optional[float] = None
    first_quote_at: Optional[float] = None
    last_book_at: Optional[float] = None
    last_tape_at: Optional[float] = None
    last_quote_at: Optional[float] = None
    provider_at: Optional[str] = None
    received_at: Optional[str] = None
    sequence_id: Optional[int] = None
    reconnect_epoch: int = 0
    book_age_ms: Optional[float] = None
    tape_age_ms: Optional[float] = None
    quota_units: int = 0
    expires_at: Optional[float] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    require_tape: bool = False
    is_fire: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass
class QuotaLedger:
    total_quota: Optional[int] = None
    total_used: Optional[int] = None
    remain: Optional[int] = None
    own_used: int = 0
    subscriptions_by_type: Mapping[str, int] = field(default_factory=dict)
    other_connection_usage: Optional[int] = None
    last_queried_at: Optional[str] = None
    reserved_units: int = 0

    def available_for_discretionary(self) -> Optional[int]:
        if self.remain is None:
            return None
        return max(0, int(self.remain) - int(self.reserved_units))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["available_for_discretionary"] = self.available_for_discretionary()
        return data


class QuotaError(Exception):
    def __init__(self, required: int, available: Optional[int]):
        self.required = required
        self.available = available
        super().__init__(f"insufficient quota: required={required} available={available}")


class SubscriptionManager:
    """Fail-closed lifecycle manager over one injected read-only gateway."""

    def __init__(self, gateway: Any, config: Optional[L2LifecycleConfig] = None):
        self.gateway = gateway
        self.cfg = config or load_l2_lifecycle_config()
        self.symbols: dict[str, SymbolLifecycle] = {}
        self.ledger = QuotaLedger(reserved_units=self.cfg.reserved_units_total)
        self.reconnect_epoch = 0

    # ── quota truth ──────────────────────────────────────────────────────
    def refresh_quota(self, now_iso: Optional[str] = None) -> QuotaLedger:
        """Refresh provider truth; a failed query clears stale capacity."""
        try:
            quota = self.gateway.query_subscription(is_all_conn=True) or {}
        except Exception:
            quota = {}
        if not quota:
            self.ledger = QuotaLedger(
                total_quota=None,
                total_used=None,
                remain=None,
                own_used=self._own_units(),
                subscriptions_by_type={},
                other_connection_usage=None,
                last_queried_at=now_iso,
                reserved_units=self.cfg.reserved_units_total,
            )
            return self.ledger

        total = quota.get("total_quota")
        used = quota.get("total_used")
        remain = quota.get("remain")
        if remain is None and total is not None and used is not None:
            remain = int(total) - int(used)
        self.ledger = QuotaLedger(
            total_quota=None if total is None else int(total),
            total_used=None if used is None else int(used),
            remain=None if remain is None else max(0, int(remain)),
            own_used=int(quota.get("own_used", self._own_units())),
            subscriptions_by_type=dict(quota.get("subscriptions_by_type") or {}),
            other_connection_usage=(
                None
                if quota.get("other_connection_usage") is None
                else int(quota.get("other_connection_usage"))
            ),
            last_queried_at=now_iso or quota.get("last_queried_at"),
            reserved_units=self.cfg.reserved_units_total,
        )
        return self.ledger

    def _own_units(self) -> int:
        return sum(
            lifecycle.quota_units
            for lifecycle in self.symbols.values()
            if lifecycle.state in _SUBSCRIBED_STATES
        )

    def _concurrent_symbols(self) -> int:
        return sum(1 for lifecycle in self.symbols.values() if lifecycle.state in _SUBSCRIBED_STATES)

    def _entitled(self) -> bool:
        try:
            return bool(self.gateway.entitlement_ok())
        except Exception:
            return False

    def _connected(self) -> bool:
        try:
            return bool(self.gateway.ping())
        except Exception:
            return False

    def _reserve_local_quota(self, units: int, subtypes: tuple[str, ...]) -> None:
        if self.ledger.total_used is not None:
            self.ledger.total_used += units
        if self.ledger.remain is not None:
            self.ledger.remain = max(0, self.ledger.remain - units)
        by_type = dict(self.ledger.subscriptions_by_type)
        for subtype in subtypes:
            by_type[subtype] = int(by_type.get(subtype, 0)) + 1
        self.ledger.subscriptions_by_type = by_type
        self.ledger.own_used = self._own_units()

    def _release_local_quota(self, units: int, subtypes: tuple[str, ...]) -> None:
        if self.ledger.total_used is not None:
            self.ledger.total_used = max(0, self.ledger.total_used - units)
        if self.ledger.remain is not None:
            hard_cap = self.ledger.total_quota
            updated = self.ledger.remain + units
            self.ledger.remain = min(hard_cap, updated) if hard_cap is not None else updated
        by_type = dict(self.ledger.subscriptions_by_type)
        for subtype in subtypes:
            by_type[subtype] = max(0, int(by_type.get(subtype, 0)) - 1)
            if by_type[subtype] == 0:
                by_type.pop(subtype, None)
        self.ledger.subscriptions_by_type = by_type
        self.ledger.own_used = self._own_units()

    # ── request / arm ───────────────────────────────────────────────────
    def request_l2(
        self,
        symbol: str,
        now: float,
        *,
        reason: str = "arm",
        priority: str = "P2",
        require_tape: bool = False,
        is_fire: bool = False,
        now_iso: Optional[str] = None,
    ) -> SymbolLifecycle:
        symbol = symbol.upper()
        lifecycle = self.symbols.get(symbol) or SymbolLifecycle(symbol=symbol)
        self.symbols[symbol] = lifecycle
        lifecycle.reason = reason
        lifecycle.priority = priority if priority in _PRIORITY_ORDER else "P2"
        lifecycle.require_tape = bool(require_tape)
        lifecycle.is_fire = bool(is_fire)
        lifecycle.reconnect_epoch = self.reconnect_epoch
        lifecycle.requested_subtypes = tuple(self.cfg.subtypes)
        if lifecycle.armed_at is None:
            lifecycle.armed_at = now

        if lifecycle.state in _SUBSCRIBED_STATES:
            lifecycle.error_code = lifecycle.error_detail = None
            return lifecycle

        lifecycle.state = L2State.ARM_INTENT
        lifecycle.confirmed_subtypes = ()
        units = self.cfg.units_per_symbol()

        if not self._connected():
            lifecycle.state = L2State.PROVIDER_DISCONNECTED
            lifecycle.error_code = "PROVIDER_DISCONNECTED"
            return lifecycle
        if not self._entitled():
            lifecycle.state = L2State.ENTITLEMENT_MISSING
            lifecycle.error_code = "ENTITLEMENT_MISSING"
            return lifecycle
        if self._concurrent_symbols() >= self.cfg.max_concurrent_l2_symbols:
            lifecycle.state = L2State.QUOTA_DEFERRED
            lifecycle.error_code = "SYMBOL_CAP"
            lifecycle.error_detail = (
                f"max_concurrent_l2_symbols={self.cfg.max_concurrent_l2_symbols} reached"
            )
            lifecycle.quota_units = 0
            return lifecycle

        hard_remaining = self.ledger.remain
        if hard_remaining is None:
            lifecycle.state = L2State.QUOTA_DEFERRED
            lifecycle.error_code = "QUOTA_UNKNOWN"
            lifecycle.error_detail = f"required_units={units} available_units=unknown"
            lifecycle.quota_units = 0
            return lifecycle
        if units > hard_remaining:
            lifecycle.state = L2State.QUOTA_DEFERRED
            lifecycle.error_code = "QUOTA_DEFERRED"
            lifecycle.error_detail = f"required_units={units} available_units={hard_remaining}"
            lifecycle.quota_units = 0
            return lifecycle
        if lifecycle.priority != "P0":
            discretionary = self.ledger.available_for_discretionary()
            if discretionary is None or units > discretionary:
                lifecycle.state = L2State.QUOTA_DEFERRED
                lifecycle.error_code = "QUOTA_DEFERRED"
                lifecycle.error_detail = f"required_units={units} available_units={discretionary}"
                lifecycle.quota_units = 0
                return lifecycle

        lifecycle.state = L2State.SUBSCRIBE_REQUESTED
        try:
            ok, message = self.gateway.subscribe(symbol, list(lifecycle.requested_subtypes))
        except Exception as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            lifecycle.state = L2State.FAILED
            lifecycle.error_code = "SUBSCRIBE_FAILED"
            lifecycle.error_detail = str(message)[:160]
            lifecycle.quota_units = 0
            return lifecycle

        lifecycle.state = L2State.WAITING_FIRST_BOOK
        lifecycle.subscribed_at = now
        lifecycle.quota_units = units
        lifecycle.confirmed_subtypes = ()
        lifecycle.error_code = lifecycle.error_detail = None
        self._reserve_local_quota(units, lifecycle.requested_subtypes)
        return lifecycle

    def mark_operator_selected(
        self, symbol: str, now: float, now_iso: Optional[str] = None
    ) -> SymbolLifecycle:
        return self.request_l2(
            symbol,
            now,
            reason="operator_selected",
            priority="P0",
            now_iso=now_iso,
        )

    def mark_fire(
        self,
        symbol: str,
        now: float,
        *,
        require_tape: bool = True,
        now_iso: Optional[str] = None,
    ) -> SymbolLifecycle:
        lifecycle = self.request_l2(
            symbol,
            now,
            reason="active_fire",
            priority="P0",
            require_tape=require_tape,
            is_fire=True,
            now_iso=now_iso,
        )
        lifecycle.expires_at = now + self.cfg.default_post_fire_retention_seconds
        return lifecycle

    # ── data confirmation ───────────────────────────────────────────────
    @staticmethod
    def _confirm(lifecycle: SymbolLifecycle, subtype: str) -> None:
        lifecycle.confirmed_subtypes = tuple(
            sorted(set(lifecycle.confirmed_subtypes).union({subtype}))
        )

    def on_book(
        self,
        symbol: str,
        now: float,
        *,
        provider_at: Optional[str] = None,
        received_at: Optional[str] = None,
        sequence_id: Optional[int] = None,
        crossed: bool = False,
    ) -> None:
        lifecycle = self.symbols.get(symbol.upper())
        if lifecycle is None or lifecycle.state not in _SUBSCRIBED_STATES:
            return
        if (
            sequence_id is not None
            and lifecycle.sequence_id is not None
            and sequence_id < lifecycle.sequence_id
        ):
            lifecycle.state = L2State.SEQUENCE_GAP
            lifecycle.error_code = "SEQUENCE_GAP"
            lifecycle.error_detail = f"seq {sequence_id} < {lifecycle.sequence_id}"
            return
        if sequence_id is not None:
            lifecycle.sequence_id = int(sequence_id)
        if crossed:
            lifecycle.state = L2State.CROSSED_BOOK
            lifecycle.error_code = "CROSSED_BOOK"
            return
        self._confirm(lifecycle, SUB_ORDER_BOOK)
        lifecycle.last_book_at = now
        if lifecycle.first_book_at is None:
            lifecycle.first_book_at = now
        lifecycle.provider_at = provider_at
        lifecycle.received_at = received_at
        lifecycle.error_code = lifecycle.error_detail = None
        self._recompute_fresh(lifecycle, now)

    def on_tape(
        self,
        symbol: str,
        now: float,
        *,
        provider_at: Optional[str] = None,
        received_at: Optional[str] = None,
    ) -> None:
        lifecycle = self.symbols.get(symbol.upper())
        if lifecycle is None or lifecycle.state not in _SUBSCRIBED_STATES:
            return
        self._confirm(lifecycle, SUB_TICKER)
        lifecycle.last_tape_at = now
        if lifecycle.first_tape_at is None:
            lifecycle.first_tape_at = now
        if provider_at:
            lifecycle.provider_at = provider_at
        if received_at:
            lifecycle.received_at = received_at
        self._recompute_fresh(lifecycle, now)

    def on_quote(
        self,
        symbol: str,
        now: float,
        *,
        provider_at: Optional[str] = None,
        received_at: Optional[str] = None,
    ) -> None:
        lifecycle = self.symbols.get(symbol.upper())
        if lifecycle is None or lifecycle.state not in _SUBSCRIBED_STATES:
            return
        self._confirm(lifecycle, SUB_QUOTE)
        lifecycle.last_quote_at = now
        if lifecycle.first_quote_at is None:
            lifecycle.first_quote_at = now
        if provider_at:
            lifecycle.provider_at = provider_at
        if received_at:
            lifecycle.received_at = received_at

    def _recompute_fresh(self, lifecycle: SymbolLifecycle, now: float) -> None:
        if lifecycle.state == L2State.UNSUBSCRIBE_PENDING:
            return
        if lifecycle.state in (L2State.SEQUENCE_GAP, L2State.CROSSED_BOOK):
            return
        if lifecycle.first_book_at is None:
            lifecycle.state = L2State.WAITING_FIRST_BOOK
            return
        if lifecycle.require_tape and lifecycle.first_tape_at is None:
            lifecycle.state = L2State.WAITING_FIRST_TAPE
            return
        lifecycle.book_age_ms = (
            None
            if lifecycle.last_book_at is None
            else max(0.0, (now - lifecycle.last_book_at) * 1000.0)
        )
        lifecycle.tape_age_ms = (
            None
            if lifecycle.last_tape_at is None
            else max(0.0, (now - lifecycle.last_tape_at) * 1000.0)
        )
        book_stale = (
            lifecycle.book_age_ms is not None
            and lifecycle.book_age_ms > self.cfg.book_stale_after_ms
        )
        tape_stale = (
            lifecycle.require_tape
            and lifecycle.tape_age_ms is not None
            and lifecycle.tape_age_ms > self.cfg.tape_stale_after_ms
        )
        if lifecycle.state != L2State.POST_FIRE_RETENTION:
            lifecycle.state = L2State.STALE if (book_stale or tape_stale) else L2State.FRESH

    # ── freshness / expiry ──────────────────────────────────────────────
    def tick(self, now: float) -> None:
        for lifecycle in list(self.symbols.values()):
            if lifecycle.state in _SUBSCRIBED_STATES and lifecycle.first_book_at is not None:
                self._recompute_fresh(lifecycle, now)
            if (
                lifecycle.state == L2State.POST_FIRE_RETENTION
                and lifecycle.expires_at
                and now >= lifecycle.expires_at
            ):
                self.release(lifecycle.symbol, now, reason="post_fire_expired")
            if (
                lifecycle.state
                in (
                    L2State.FRESH,
                    L2State.STALE,
                    L2State.WAITING_FIRST_BOOK,
                    L2State.WAITING_FIRST_TAPE,
                    L2State.SUBSCRIBED,
                )
                and not lifecycle.is_fire
                and lifecycle.expires_at
                and now >= lifecycle.expires_at
            ):
                self.release(lifecycle.symbol, now, reason="arm_ttl_expired")
            if lifecycle.state == L2State.UNSUBSCRIBE_PENDING:
                self._try_complete_unsubscribe(lifecycle, now)

    def set_arm_ttl(
        self, symbol: str, now: float, ttl_seconds: Optional[float] = None
    ) -> None:
        lifecycle = self.symbols.get(symbol.upper())
        if lifecycle is None:
            return
        lifecycle.expires_at = now + (
            ttl_seconds if ttl_seconds is not None else self.cfg.default_arm_ttl_seconds
        )

    def enter_post_fire_retention(
        self, symbol: str, now: float, retention_seconds: Optional[float] = None
    ) -> None:
        lifecycle = self.symbols.get(symbol.upper())
        if lifecycle is None or lifecycle.state not in _SUBSCRIBED_STATES:
            return
        lifecycle.state = L2State.POST_FIRE_RETENTION
        lifecycle.is_fire = True
        lifecycle.expires_at = now + (
            retention_seconds
            if retention_seconds is not None
            else self.cfg.default_post_fire_retention_seconds
        )

    # ── release ─────────────────────────────────────────────────────────
    def release(
        self, symbol: str, now: float, *, reason: str = "release"
    ) -> SymbolLifecycle:
        lifecycle = self.symbols.get(symbol.upper())
        if lifecycle is None:
            return SymbolLifecycle(symbol=symbol.upper(), state=L2State.NOT_REQUESTED)
        if lifecycle.state in (L2State.UNSUBSCRIBED, L2State.NOT_REQUESTED):
            return lifecycle
        lifecycle.state = L2State.UNSUBSCRIBE_PENDING
        lifecycle.reason = reason
        self._try_complete_unsubscribe(lifecycle, now)
        return lifecycle

    def _dwell_ok(self, lifecycle: SymbolLifecycle, now: float) -> bool:
        if lifecycle.subscribed_at is None:
            return True
        return (now - lifecycle.subscribed_at) >= self.cfg.min_subscription_dwell_seconds

    def _try_complete_unsubscribe(self, lifecycle: SymbolLifecycle, now: float) -> None:
        if not self._dwell_ok(lifecycle, now):
            return
        subtypes = lifecycle.requested_subtypes or tuple(self.cfg.subtypes)
        try:
            ok, message = self.gateway.unsubscribe(lifecycle.symbol, list(subtypes))
        except Exception as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            lifecycle.state = L2State.UNSUBSCRIBE_PENDING
            lifecycle.error_code = "UNSUBSCRIBE_FAILED"
            lifecycle.error_detail = str(message)[:160]
            return
        units = lifecycle.quota_units
        lifecycle.state = L2State.UNSUBSCRIBED
        lifecycle.quota_units = 0
        lifecycle.confirmed_subtypes = ()
        lifecycle.expires_at = None
        lifecycle.error_code = lifecycle.error_detail = None
        self._release_local_quota(units, subtypes)

    # ── reconnect ───────────────────────────────────────────────────────
    def on_reconnect(self, now: float) -> list[str]:
        self.reconnect_epoch += 1
        desired = [
            lifecycle.symbol
            for lifecycle in self.symbols.values()
            if lifecycle.state in _SUBSCRIBED_STATES
            and lifecycle.state != L2State.UNSUBSCRIBE_PENDING
        ]
        self.refresh_quota()
        restored: list[str] = []
        for symbol in desired:
            lifecycle = self.symbols[symbol]
            lifecycle.state = L2State.SUBSCRIBE_REQUESTED
            lifecycle.first_book_at = lifecycle.first_tape_at = lifecycle.first_quote_at = None
            lifecycle.last_book_at = lifecycle.last_tape_at = lifecycle.last_quote_at = None
            lifecycle.sequence_id = None
            lifecycle.confirmed_subtypes = ()
            lifecycle.reconnect_epoch = self.reconnect_epoch
            try:
                ok, message = self.gateway.subscribe(symbol, list(lifecycle.requested_subtypes))
            except Exception as exc:
                ok, message = False, f"{type(exc).__name__}: {exc}"
            if ok:
                lifecycle.state = L2State.WAITING_FIRST_BOOK
                lifecycle.subscribed_at = now
                lifecycle.error_code = lifecycle.error_detail = None
                restored.append(symbol)
            else:
                lifecycle.state = L2State.FAILED
                lifecycle.error_code = "RESUBSCRIBE_FAILED"
                lifecycle.error_detail = str(message)[:160]
        return restored

    def restore_desired_from_state(self, symbols: list[str]) -> None:
        for symbol in symbols:
            normalized = symbol.upper()
            if normalized not in self.symbols:
                self.symbols[normalized] = SymbolLifecycle(
                    symbol=normalized,
                    state=L2State.ARM_INTENT,
                    reason="restored_intent",
                )

    # ── views ───────────────────────────────────────────────────────────
    def confirmed_subscriptions(self) -> dict[str, tuple[str, ...]]:
        return {
            lifecycle.symbol: lifecycle.confirmed_subtypes
            for lifecycle in self.symbols.values()
            if lifecycle.state in _SUBSCRIBED_STATES and lifecycle.confirmed_subtypes
        }

    def is_confirmed_fresh(
        self, symbol: str, *, require_tape: Optional[bool] = None
    ) -> bool:
        lifecycle = self.symbols.get(symbol.upper())
        if lifecycle is None or lifecycle.state != L2State.FRESH:
            return False
        if SUB_ORDER_BOOK not in lifecycle.confirmed_subtypes:
            return False
        if lifecycle.sequence_id is None or lifecycle.reconnect_epoch != self.reconnect_epoch:
            return False
        want_tape = lifecycle.require_tape if require_tape is None else require_tape
        if want_tape and SUB_TICKER not in lifecycle.confirmed_subtypes:
            return False
        return True

    def snapshot(self, now_iso: Optional[str] = None) -> dict[str, Any]:
        return {
            "provider_connected": self._connected(),
            "entitlement_ok": self._entitled(),
            "reconnect_epoch": self.reconnect_epoch,
            "quota": self.ledger.to_dict(),
            "concurrent_symbols": self._concurrent_symbols(),
            "max_concurrent_l2_symbols": self.cfg.max_concurrent_l2_symbols,
            "min_dwell_seconds": self.cfg.min_subscription_dwell_seconds,
            "symbols": {
                lifecycle.symbol: lifecycle.to_dict() for lifecycle in self.symbols.values()
            },
            "confirmed_subscriptions": {
                key: list(value) for key, value in self.confirmed_subscriptions().items()
            },
            "generated_at": now_iso,
        }
