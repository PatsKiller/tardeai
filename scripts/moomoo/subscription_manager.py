"""Deterministic Moomoo/OpenD L2 subscription lifecycle + quota truth.

This module owns the *decision* layer: which symbols should hold which subscriptions,
whether the simultaneous-subscription quota allows it, and the per-symbol lifecycle FSM.
It NEVER opens an OpenQuoteContext itself — it drives a `QuoteGateway` (the single owner)
through a small transport surface. Injecting a mock gateway makes every state transition
deterministic and testable without a live OpenD.

HARD invariants:
  * Quota is SIMULTANEOUS subscription quota (symbol×subtype allocations), never daily calls.
  * A state-file / arm-intent NEVER implies connected / subscribed / fresh / T2 / entitled.
  * Insufficient quota → QUOTA_DEFERRED (no silent eviction; exact required+remaining reported).
  * Moomoo min-dwell is respected before any unsubscribe.
  * Read plane only: no order/unlock path is importable or reachable here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Mapping, Optional

try:
    from .l2_lifecycle_config import L2LifecycleConfig, load_l2_lifecycle_config
except ImportError:  # pragma: no cover - direct-script import fallback
    from l2_lifecycle_config import L2LifecycleConfig, load_l2_lifecycle_config  # type: ignore


# ── canonical subtypes (mirror futu SubType names; strings so no SDK import needed) ──
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


# states that hold a live subscription (and therefore consume quota units)
_SUBSCRIBED_STATES = frozenset({
    L2State.SUBSCRIBE_REQUESTED, L2State.SUBSCRIBED, L2State.WAITING_FIRST_BOOK,
    L2State.WAITING_FIRST_TAPE, L2State.FRESH, L2State.STALE, L2State.SEQUENCE_GAP,
    L2State.CROSSED_BOOK, L2State.POST_FIRE_RETENTION, L2State.UNSUBSCRIBE_PENDING,
})

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
    last_book_at: Optional[float] = None
    last_tape_at: Optional[float] = None
    provider_at: Optional[str] = None          # provider timestamp of last book/tape
    received_at: Optional[str] = None          # ISO when we received it
    sequence_id: Optional[int] = None
    reconnect_epoch: int = 0
    book_age_ms: Optional[float] = None
    tape_age_ms: Optional[float] = None
    quota_units: int = 0
    expires_at: Optional[float] = None         # arm TTL or post-fire retention deadline
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    require_tape: bool = False
    is_fire: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


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
        """Remaining quota AFTER reserved capacity is carved out. None when unknown."""
        if self.remain is None:
            return None
        return max(0, int(self.remain) - int(self.reserved_units))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["available_for_discretionary"] = self.available_for_discretionary()
        return d


class QuotaError(Exception):
    """Raised internally to surface an exact insufficient-quota report."""

    def __init__(self, required: int, available: Optional[int]):
        self.required = required
        self.available = available
        super().__init__(f"insufficient quota: required={required} available={available}")


class SubscriptionManager:
    """Owns the L2 subscription decision layer over a single QuoteGateway.

    `gateway` must expose: ping()->bool, entitlement_ok()->bool,
    query_subscription(is_all_conn)->dict, subscribe(symbol, subtypes)->(ok, msg),
    unsubscribe(symbol, subtypes)->(ok, msg). A mock gateway satisfies the same surface,
    so the whole FSM is deterministic in tests with no live OpenD.
    """

    def __init__(self, gateway: Any, config: Optional[L2LifecycleConfig] = None):
        self.gateway = gateway
        self.cfg = config or load_l2_lifecycle_config()
        self.symbols: dict[str, SymbolLifecycle] = {}
        self.ledger = QuotaLedger(reserved_units=self.cfg.reserved_units_total)
        self.reconnect_epoch = 0

    # ── quota truth ─────────────────────────────────────────────────────────
    def refresh_quota(self, now_iso: Optional[str] = None) -> QuotaLedger:
        """Query SIMULTANEOUS subscription quota (is_all_conn=True) and update the ledger.

        Never raises — an unreachable gateway leaves the ledger's totals None (honest
        'unknown'), which the eligibility check treats as fail-closed."""
        try:
            q = self.gateway.query_subscription(is_all_conn=True) or {}
        except Exception:
            q = {}
        if q:
            total = q.get("total_quota")
            used = q.get("total_used")
            remain = q.get("remain")
            if remain is None and total is not None and used is not None:
                remain = int(total) - int(used)
            self.ledger = QuotaLedger(
                total_quota=None if total is None else int(total),
                total_used=None if used is None else int(used),
                remain=None if remain is None else int(remain),
                own_used=int(q.get("own_used", self._own_units())),
                subscriptions_by_type=dict(q.get("subscriptions_by_type") or {}),
                other_connection_usage=(None if q.get("other_connection_usage") is None
                                        else int(q.get("other_connection_usage"))),
                last_queried_at=now_iso or q.get("last_queried_at"),
                reserved_units=self.cfg.reserved_units_total,
            )
        else:
            self.ledger.own_used = self._own_units()
            self.ledger.last_queried_at = now_iso or self.ledger.last_queried_at
            self.ledger.reserved_units = self.cfg.reserved_units_total
        return self.ledger

    def _own_units(self) -> int:
        return sum(s.quota_units for s in self.symbols.values() if s.state in _SUBSCRIBED_STATES)

    def _concurrent_symbols(self) -> int:
        return sum(1 for s in self.symbols.values() if s.state in _SUBSCRIBED_STATES)

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

    # ── request / arm ───────────────────────────────────────────────────────
    def request_l2(self, symbol: str, now: float, *, reason: str = "arm",
                   priority: str = "P2", require_tape: bool = False,
                   is_fire: bool = False, now_iso: Optional[str] = None) -> SymbolLifecycle:
        """Move a symbol toward SUBSCRIBED, honoring entitlement, quota, and the symbol cap.

        Fail-closed order: provider down → PROVIDER_DISCONNECTED; no entitlement →
        ENTITLEMENT_MISSING; over the concurrent cap or reserved-quota → QUOTA_DEFERRED
        (no eviction); else SUBSCRIBE_REQUESTED → SUBSCRIBED → WAITING_FIRST_BOOK."""
        symbol = symbol.upper()
        life = self.symbols.get(symbol) or SymbolLifecycle(symbol=symbol)
        self.symbols[symbol] = life
        life.reason = reason
        life.priority = priority if priority in _PRIORITY_ORDER else "P2"
        life.require_tape = bool(require_tape)
        life.is_fire = bool(is_fire)
        life.reconnect_epoch = self.reconnect_epoch
        if life.armed_at is None:
            life.armed_at = now
        life.requested_subtypes = self.cfg.subtypes

        # already holding a live subscription → keep it, just refresh intent/expiry
        if life.state in _SUBSCRIBED_STATES:
            life.error_code = life.error_detail = None
            return life

        life.state = L2State.ARM_INTENT
        units = self.cfg.units_per_symbol()

        if not self._connected():
            life.state = L2State.PROVIDER_DISCONNECTED
            life.error_code = "PROVIDER_DISCONNECTED"
            return life
        if not self._entitled():
            life.state = L2State.ENTITLEMENT_MISSING
            life.error_code = "ENTITLEMENT_MISSING"
            return life

        # concurrent-symbol cap
        if self._concurrent_symbols() >= self.cfg.max_concurrent_l2_symbols:
            life.state = L2State.QUOTA_DEFERRED
            life.error_code = "SYMBOL_CAP"
            life.error_detail = (f"max_concurrent_l2_symbols={self.cfg.max_concurrent_l2_symbols} "
                                 f"reached")
            life.quota_units = 0
            return life

        # simultaneous-subscription quota (units), after reserved carve-out
        avail = self.ledger.available_for_discretionary()
        if avail is not None and units > avail and priority not in ("P0",):
            life.state = L2State.QUOTA_DEFERRED
            life.error_code = "QUOTA_DEFERRED"
            life.error_detail = f"required_units={units} available_units={avail}"
            life.quota_units = 0
            return life

        # subscribe through the single gateway
        life.state = L2State.SUBSCRIBE_REQUESTED
        try:
            ok, msg = self.gateway.subscribe(symbol, list(self.cfg.subtypes))
        except Exception as exc:  # never let a transport error crash the caller
            ok, msg = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            life.state = L2State.FAILED
            life.error_code = "SUBSCRIBE_FAILED"
            life.error_detail = str(msg)[:160]
            life.quota_units = 0
            return life

        life.state = L2State.SUBSCRIBED
        life.subscribed_at = now
        life.confirmed_subtypes = self.cfg.subtypes
        life.quota_units = units
        life.error_code = life.error_detail = None
        life.state = L2State.WAITING_FIRST_BOOK
        # refresh own-usage view
        self.ledger.own_used = self._own_units()
        return life

    def mark_operator_selected(self, symbol: str, now: float, now_iso: Optional[str] = None) -> SymbolLifecycle:
        return self.request_l2(symbol, now, reason="operator_selected", priority="P0", now_iso=now_iso)

    def mark_fire(self, symbol: str, now: float, *, require_tape: bool = True,
                  now_iso: Optional[str] = None) -> SymbolLifecycle:
        life = self.request_l2(symbol, now, reason="active_fire", priority="P0",
                               require_tape=require_tape, is_fire=True, now_iso=now_iso)
        life.expires_at = now + self.cfg.default_post_fire_retention_seconds
        return life

    # ── data ingest (book / tape) ───────────────────────────────────────────
    def on_book(self, symbol: str, now: float, *, provider_at: Optional[str] = None,
                received_at: Optional[str] = None, sequence_id: Optional[int] = None,
                crossed: bool = False) -> None:
        life = self.symbols.get(symbol.upper())
        if life is None or life.state not in _SUBSCRIBED_STATES:
            return
        # sequence-gap detection within the same reconnect epoch
        if (sequence_id is not None and life.sequence_id is not None
                and sequence_id < life.sequence_id):
            life.state = L2State.SEQUENCE_GAP
            life.error_code = "SEQUENCE_GAP"
            life.error_detail = f"seq {sequence_id} < {life.sequence_id}"
            return
        if sequence_id is not None:
            life.sequence_id = int(sequence_id)
        if crossed:
            life.state = L2State.CROSSED_BOOK
            life.error_code = "CROSSED_BOOK"
            return
        life.last_book_at = now
        if life.first_book_at is None:
            life.first_book_at = now
        life.provider_at = provider_at
        life.received_at = received_at
        life.error_code = life.error_detail = None
        self._recompute_fresh(life, now)

    def on_tape(self, symbol: str, now: float, *, provider_at: Optional[str] = None,
                received_at: Optional[str] = None) -> None:
        life = self.symbols.get(symbol.upper())
        if life is None or life.state not in _SUBSCRIBED_STATES:
            return
        life.last_tape_at = now
        if life.first_tape_at is None:
            life.first_tape_at = now
        self._recompute_fresh(life, now)

    def _recompute_fresh(self, life: SymbolLifecycle, now: float) -> None:
        if life.state == L2State.UNSUBSCRIBE_PENDING:
            return  # releasing — freshness must not resurrect it into FRESH/STALE
        if life.state in (L2State.SEQUENCE_GAP, L2State.CROSSED_BOOK, L2State.POST_FIRE_RETENTION):
            # POST_FIRE_RETENTION keeps its own label but freshness still tracked below
            if life.state != L2State.POST_FIRE_RETENTION:
                return
        if life.first_book_at is None:
            life.state = L2State.WAITING_FIRST_BOOK
            return
        if life.require_tape and life.first_tape_at is None:
            life.state = L2State.WAITING_FIRST_TAPE
            return
        life.book_age_ms = None if life.last_book_at is None else max(0.0, (now - life.last_book_at) * 1000.0)
        life.tape_age_ms = None if life.last_tape_at is None else max(0.0, (now - life.last_tape_at) * 1000.0)
        book_stale = life.book_age_ms is not None and life.book_age_ms > self.cfg.book_stale_after_ms
        tape_stale = (life.require_tape and life.tape_age_ms is not None
                      and life.tape_age_ms > self.cfg.tape_stale_after_ms)
        if life.state != L2State.POST_FIRE_RETENTION:
            life.state = L2State.STALE if (book_stale or tape_stale) else L2State.FRESH

    # ── freshness / expiry tick ─────────────────────────────────────────────
    def tick(self, now: float) -> None:
        """Advance freshness, post-fire retention, arm TTL, and dwell-pending releases."""
        for life in list(self.symbols.values()):
            if life.state in _SUBSCRIBED_STATES and life.first_book_at is not None:
                self._recompute_fresh(life, now)
            # post-fire retention expiry → begin release
            if life.state == L2State.POST_FIRE_RETENTION and life.expires_at and now >= life.expires_at:
                self.release(life.symbol, now, reason="post_fire_expired")
            # arm TTL expiry (non-fire) → begin release
            if (life.state in (L2State.FRESH, L2State.STALE, L2State.WAITING_FIRST_BOOK,
                               L2State.WAITING_FIRST_TAPE, L2State.SUBSCRIBED)
                    and not life.is_fire and life.expires_at and now >= life.expires_at):
                self.release(life.symbol, now, reason="arm_ttl_expired")
            # complete a dwell-pending unsubscribe once the min dwell has elapsed
            if life.state == L2State.UNSUBSCRIBE_PENDING:
                self._try_complete_unsubscribe(life, now)

    def set_arm_ttl(self, symbol: str, now: float, ttl_seconds: Optional[float] = None) -> None:
        life = self.symbols.get(symbol.upper())
        if life is None:
            return
        life.expires_at = now + (ttl_seconds if ttl_seconds is not None
                                 else self.cfg.default_arm_ttl_seconds)

    def enter_post_fire_retention(self, symbol: str, now: float,
                                  retention_seconds: Optional[float] = None) -> None:
        life = self.symbols.get(symbol.upper())
        if life is None or life.state not in _SUBSCRIBED_STATES:
            return
        life.state = L2State.POST_FIRE_RETENTION
        life.is_fire = True
        life.expires_at = now + (retention_seconds if retention_seconds is not None
                                 else self.cfg.default_post_fire_retention_seconds)

    # ── release (dwell-aware) ───────────────────────────────────────────────
    def release(self, symbol: str, now: float, *, reason: str = "release") -> SymbolLifecycle:
        """Release a subscription, respecting the Moomoo minimum dwell.

        Within the min dwell → UNSUBSCRIBE_PENDING (kept until the dwell elapses); the
        actual gateway.unsubscribe fires only when dwell is satisfied."""
        life = self.symbols.get(symbol.upper())
        if life is None:
            return SymbolLifecycle(symbol=symbol.upper(), state=L2State.NOT_REQUESTED)
        if life.state in (L2State.UNSUBSCRIBED, L2State.NOT_REQUESTED):
            return life
        life.state = L2State.UNSUBSCRIBE_PENDING
        life.reason = reason
        self._try_complete_unsubscribe(life, now)
        return life

    def _dwell_ok(self, life: SymbolLifecycle, now: float) -> bool:
        if life.subscribed_at is None:
            return True
        return (now - life.subscribed_at) >= self.cfg.min_subscription_dwell_seconds

    def _try_complete_unsubscribe(self, life: SymbolLifecycle, now: float) -> None:
        if not self._dwell_ok(life, now):
            return  # keep UNSUBSCRIBE_PENDING until dwell satisfied
        try:
            self.gateway.unsubscribe(life.symbol, list(life.confirmed_subtypes or self.cfg.subtypes))
        except Exception:
            pass
        life.state = L2State.UNSUBSCRIBED
        life.quota_units = 0
        life.confirmed_subtypes = ()
        life.expires_at = None
        self.ledger.own_used = self._own_units()

    # ── reconnect ───────────────────────────────────────────────────────────
    def on_reconnect(self, now: float) -> list[str]:
        """Bump the reconnect epoch and re-subscribe the DESIRED set without duplication.

        Desired = every symbol that held (or was pending) a live subscription. Sequence
        history is reset per epoch so a post-reconnect lower sequence is not a false gap."""
        self.reconnect_epoch += 1
        desired = [s.symbol for s in self.symbols.values()
                   if s.state in _SUBSCRIBED_STATES and s.state != L2State.UNSUBSCRIBE_PENDING]
        self.refresh_quota()
        restored: list[str] = []
        for sym in desired:
            life = self.symbols[sym]
            # reset per-symbol streaming state for the new epoch (no duplicate rows)
            life.state = L2State.SUBSCRIBE_REQUESTED
            life.first_book_at = life.first_tape_at = None
            life.last_book_at = life.last_tape_at = None
            life.sequence_id = None
            life.reconnect_epoch = self.reconnect_epoch
            try:
                ok, _ = self.gateway.subscribe(sym, list(self.cfg.subtypes))
            except Exception:
                ok = False
            if ok:
                life.state = L2State.WAITING_FIRST_BOOK
                life.subscribed_at = now
                restored.append(sym)
            else:
                life.state = L2State.FAILED
                life.error_code = "RESUBSCRIBE_FAILED"
        return restored

    def restore_desired_from_state(self, symbols: list[str]) -> None:
        """Restore DESIRED (intent) subscriptions after a process restart.

        Intent ONLY — every restored symbol starts NOT_REQUESTED→ARM_INTENT and must earn
        SUBSCRIBED/FRESH through the live path. File existence never implies connected."""
        for sym in symbols:
            sym = sym.upper()
            if sym not in self.symbols:
                self.symbols[sym] = SymbolLifecycle(symbol=sym, state=L2State.ARM_INTENT,
                                                    reason="restored_intent")

    # ── views ───────────────────────────────────────────────────────────────
    def confirmed_subscriptions(self) -> dict[str, tuple[str, ...]]:
        return {s.symbol: s.confirmed_subtypes for s in self.symbols.values()
                if s.state in _SUBSCRIBED_STATES and s.confirmed_subtypes}

    def is_confirmed_fresh(self, symbol: str, *, require_tape: Optional[bool] = None) -> bool:
        life = self.symbols.get(symbol.upper())
        if life is None or life.state != L2State.FRESH:
            return False
        want_tape = life.require_tape if require_tape is None else require_tape
        if want_tape and life.first_tape_at is None:
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
            "symbols": {s.symbol: s.to_dict() for s in self.symbols.values()},
            "confirmed_subscriptions": {k: list(v) for k, v in self.confirmed_subscriptions().items()},
        }
