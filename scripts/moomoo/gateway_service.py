#!/usr/bin/env python3
"""Dedicated single-owner Moomoo/OpenD L2 gateway service.

This is a read-only market-data daemon. It is the only component allowed to construct the
production quote transport. It owns subscription reconciliation and publishes atomic IPC
snapshots consumed by ActiveTrader and the scalp engine. The shipped config is disabled;
installing or starting the systemd unit remains an explicit operator action after review.

No order, trade unlock, trade context, 2FA, credential-read, database-write, or LLM path.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

try:
    from .futu_normalizer import (
        NormalizedBook,
        NormalizedQuote,
        NormalizedTape,
        normalize_order_book_payload,
        normalize_quote_payload,
        normalize_ticker_payload,
    )
    from .gateway_ipc import (
        GatewayStateStore,
        OwnerLock,
        SnapshotPublisher,
        default_lock_path,
        default_runtime_dir,
        default_snapshot_path,
        default_state_path,
        expand_path,
        merge_intents,
        utc_now_iso,
    )
    from .gateway_journal import GatewayJournal
    from .l2_feature_service import L2FeatureService
    from .l2_lifecycle_config import load_l2_lifecycle_config
    from .quote_gateway import QuoteGateway
    from .real_gateway_transport import RealGatewayTransport
    from .subscription_manager import L2State, SubscriptionManager, SymbolLifecycle
except ImportError:  # pragma: no cover - direct script
    from futu_normalizer import (  # type: ignore
        NormalizedBook,
        NormalizedQuote,
        NormalizedTape,
        normalize_order_book_payload,
        normalize_quote_payload,
        normalize_ticker_payload,
    )
    from gateway_ipc import (  # type: ignore
        GatewayStateStore,
        OwnerLock,
        SnapshotPublisher,
        default_lock_path,
        default_runtime_dir,
        default_snapshot_path,
        default_state_path,
        expand_path,
        merge_intents,
        utc_now_iso,
    )
    from gateway_journal import GatewayJournal  # type: ignore
    from l2_feature_service import L2FeatureService  # type: ignore
    from l2_lifecycle_config import load_l2_lifecycle_config  # type: ignore
    from quote_gateway import QuoteGateway  # type: ignore
    from real_gateway_transport import RealGatewayTransport  # type: ignore
    from subscription_manager import L2State, SubscriptionManager, SymbolLifecycle  # type: ignore

SERVICE_CONTRACT = "moomoo-l2-gateway-service-v1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_commit() -> str:
    value = os.environ.get("TRADEAI_SOURCE_COMMIT", "").strip()
    if value:
        return value
    try:
        import subprocess

        completed = subprocess.run(
            ["git", "-C", str(_repo_root()), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if completed.returncode == 0:
            return completed.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


@dataclass(frozen=True)
class GatewayServiceConfig:
    enabled: bool
    snapshot_path: Path
    state_path: Path
    lock_path: Path
    journal_dir: Path
    intent_paths: tuple[Path, ...]
    loop_interval_ms: int = 500
    health_interval_seconds: float = 5.0
    quota_refresh_seconds: float = 15.0
    intent_refresh_seconds: float = 1.0
    book_poll_seconds: float = 1.0
    quote_poll_seconds: float = 1.5
    ticker_poll_seconds: float = 2.0
    heartbeat_seconds: float = 1.0
    snapshot_stale_after_seconds: float = 5.0
    journal_retention_days: int = 14
    journal_flush_seconds: float = 1.0
    state_save_seconds: float = 5.0
    book_levels: int = 10
    ticker_pull_count: int = 200


def load_service_config(path: str | Path | None = None) -> GatewayServiceConfig:
    explicit = path or os.environ.get("MOOMOO_L2_GATEWAY_CONFIG", "")
    config_path = expand_path(explicit) if explicit else _repo_root() / "config" / "moomoo_l2_gateway.example.yaml"
    data: dict[str, Any] = {}
    try:
        import yaml  # type: ignore

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        data = raw if isinstance(raw, dict) else {}
    except Exception:
        data = {}
    runtime = data.get("runtime") if isinstance(data.get("runtime"), Mapping) else {}
    polling = data.get("polling") if isinstance(data.get("polling"), Mapping) else {}
    journal = data.get("journal") if isinstance(data.get("journal"), Mapping) else {}
    intent = data.get("intent") if isinstance(data.get("intent"), Mapping) else {}
    default_arm = _repo_root() / "data" / "scalp" / "moomoo_armed_state.json"
    raw_intent = intent.get("paths") if isinstance(intent.get("paths"), list) else [default_arm]
    return GatewayServiceConfig(
        enabled=bool(data.get("enabled", False)),
        snapshot_path=expand_path(runtime.get("snapshot_path") or default_snapshot_path()),
        state_path=expand_path(runtime.get("state_path") or default_state_path()),
        lock_path=expand_path(runtime.get("lock_path") or default_lock_path()),
        journal_dir=expand_path(journal.get("directory") or default_runtime_dir() / "moomoo_l2_journal"),
        intent_paths=tuple(expand_path(value) for value in raw_intent),
        loop_interval_ms=max(100, int(polling.get("loop_interval_ms", 500))),
        health_interval_seconds=max(1.0, float(polling.get("health_interval_seconds", 5))),
        quota_refresh_seconds=max(1.0, float(polling.get("quota_refresh_seconds", 15))),
        intent_refresh_seconds=max(0.25, float(polling.get("intent_refresh_seconds", 1))),
        book_poll_seconds=max(0.25, float(polling.get("book_poll_seconds", 1))),
        quote_poll_seconds=max(0.25, float(polling.get("quote_poll_seconds", 1.5))),
        ticker_poll_seconds=max(0.25, float(polling.get("ticker_poll_seconds", 2))),
        heartbeat_seconds=max(0.25, float(polling.get("heartbeat_seconds", 1))),
        snapshot_stale_after_seconds=max(1.0, float(runtime.get("snapshot_stale_after_seconds", 5))),
        journal_retention_days=max(1, int(journal.get("retention_days", 14))),
        journal_flush_seconds=max(0.1, float(journal.get("flush_seconds", 1))),
        state_save_seconds=max(1.0, float(runtime.get("state_save_seconds", 5))),
        book_levels=max(1, min(50, int(polling.get("book_levels", 10)))),
        ticker_pull_count=max(1, min(1000, int(polling.get("ticker_pull_count", 200)))),
    )


class GatewayDisabled(RuntimeError):
    pass


class MoomooL2GatewayService:
    """Stateful owner with dependency injection for deterministic tests."""

    def __init__(
        self,
        config: GatewayServiceConfig,
        *,
        transport=None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.monotonic = monotonic
        self.wall_time = wall_time
        self.sleep = sleep
        self.transport = transport or RealGatewayTransport()
        self.gateway = QuoteGateway(self.transport)
        self.lifecycle_config = load_l2_lifecycle_config()
        self.manager = SubscriptionManager(self.gateway, self.lifecycle_config)
        self.features = L2FeatureService(self.gateway, self.manager, levels=config.book_levels)
        self.publisher = SnapshotPublisher(config.snapshot_path)
        self.state_store = GatewayStateStore(config.state_path)
        self.journal = GatewayJournal(config.journal_dir, retention_days=config.journal_retention_days)
        self.owner_lock = OwnerLock(config.lock_path)
        self.started_at = utc_now_iso()
        self.source_commit = _source_commit()
        self.running = False
        self._connected = False
        self._entitled = False
        self._desired: dict[str, dict[str, Any]] = {}
        self._provider_subscriptions: dict[str, list[str]] = {}
        self._book_meta: dict[str, dict[str, Any]] = {}
        self._tape_meta: dict[str, dict[str, Any]] = {}
        self._quote_meta: dict[str, dict[str, Any]] = {}
        self._ticker_sequence: dict[str, int] = {}
        self._book_sequence: dict[str, int] = {}
        self._coverage_active: set[str] = set()
        self._last_lifecycle: dict[str, str] = {}
        self._last_health = self._last_quota = self._last_intent = 0.0
        self._last_book_poll: dict[str, float] = {}
        self._last_quote_poll: dict[str, float] = {}
        self._last_ticker_poll: dict[str, float] = {}
        self._last_publish = 0.0
        self._last_state_save = 0.0
        self._last_journal_flush = 0.0
        self._journal_queue: list[dict[str, Any]] = []
        self._last_error: Optional[dict[str, str]] = None

    @staticmethod
    def _authority() -> dict[str, bool]:
        return {
            "mutation": False,
            "order": False,
            "session_authorize": False,
            "canary": False,
            "financial_action": False,
            "trade_unlock": False,
        }

    def start(self) -> None:
        if not self.config.enabled:
            raise GatewayDisabled("gateway config enabled=false; explicit operator enablement required")
        self.owner_lock.acquire(
            {
                "service_contract": SERVICE_CONTRACT,
                "source_commit": self.source_commit,
                "snapshot_path": str(self.config.snapshot_path),
            }
        )
        self.running = True
        self._journal_event(
            "OWNER_START",
            payload={"pid": os.getpid(), "source_commit": self.source_commit, "started_at": self.started_at},
        )
        self.transport.bind_callbacks(
            on_quote=self._on_quote_payload,
            on_book=self._on_book_payload,
            on_tape=self._on_ticker_payload,
        )
        self._load_previous_state()
        self.run_once(force=True)

    def stop(self) -> None:
        if not self.running and not self.owner_lock.held:
            return
        try:
            for symbol in sorted(self._coverage_active):
                self._journal_event("COVERAGE_GAP", symbol=symbol, payload={"reason": "OWNER_STOP"})
            self._save_state(force=True)
            self._publish_snapshot(force=True, service_state="STOPPING")
            self._journal_event("OWNER_STOP", payload={"pid": os.getpid(), "source_commit": self.source_commit})
            self._flush_journal(force=True)
            try:
                self.transport.close()
            except Exception:
                pass
        finally:
            self.running = False
            self.owner_lock.release()

    def _load_previous_state(self) -> None:
        state = self.state_store.load()
        previous_epoch = state.get("reconnect_epoch")
        try:
            self.manager.reconnect_epoch = max(0, int(previous_epoch or 0))
        except (TypeError, ValueError):
            self.manager.reconnect_epoch = 0
        previous_book_sequence = state.get("book_sequence") or {}
        previous_ticker_sequence = state.get("ticker_sequence") or {}
        self._book_sequence = {str(k): int(v) for k, v in previous_book_sequence.items() if str(v).isdigit()}
        self._ticker_sequence = {str(k): int(v) for k, v in previous_ticker_sequence.items() if str(v).isdigit()}

    def _save_state(self, *, force: bool = False) -> None:
        now_mono = self.monotonic()
        if not force and now_mono - self._last_state_save < self.config.state_save_seconds:
            return
        self.state_store.save(
            {
                "source_commit": self.source_commit,
                "reconnect_epoch": self.manager.reconnect_epoch,
                "desired": self._desired,
                "provider_subscriptions": self._provider_subscriptions,
                "symbols": {k: v.to_dict() for k, v in self.manager.symbols.items()},
                "book_sequence": self._book_sequence,
                "ticker_sequence": self._ticker_sequence,
                "connected": self._connected,
                "entitled": self._entitled,
            }
        )
        self._last_state_save = now_mono

    def _set_error(self, where: str, exc: Exception | str) -> None:
        self._last_error = {
            "where": where,
            "type": type(exc).__name__ if isinstance(exc, Exception) else "RuntimeError",
            "detail": str(exc)[:240],
            "at": utc_now_iso(),
        }

    def _journal_event(
        self,
        event_type: str,
        *,
        symbol: Optional[str] = None,
        event_at: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        event = self.journal.make_event(
            event_type, symbol=symbol, event_at=event_at, payload=payload
        )
        self._journal_queue.append(event)
        return event

    def _flush_journal(self, *, force: bool = False) -> None:
        now_mono = self.monotonic()
        if not self._journal_queue:
            return
        if not force and now_mono - self._last_journal_flush < self.config.journal_flush_seconds:
            return
        batch, self._journal_queue = self._journal_queue, []
        self.journal.append_events(batch)
        self._last_journal_flush = now_mono

    def _next_book_sequence(self, symbol: str) -> int:
        value = int(self._book_sequence.get(symbol, 0)) + 1
        self._book_sequence[symbol] = value
        return value

    def _on_quote_payload(self, data: Any, received_at: str) -> None:
        for normalized in normalize_quote_payload(data, received_at):
            self._ingest_quote(normalized)

    def _on_book_payload(self, data: Any, received_at: str) -> None:
        rows = data.to_dict("records") if hasattr(data, "to_dict") else ([data] if isinstance(data, Mapping) else [])
        symbol_raw = (rows[0].get("code") or rows[0].get("symbol")) if rows else None
        symbol = str(symbol_raw or "").upper().replace("US.", "")
        sequence = self._next_book_sequence(symbol) if symbol else None
        normalized = normalize_order_book_payload(
            data,
            received_at,
            sequence_id=sequence,
            sequence_source="gateway_monotonic_per_reconnect_epoch",
            levels=self.config.book_levels,
        )
        if normalized is not None:
            self._ingest_book(normalized)

    def _on_ticker_payload(self, data: Any, received_at: str) -> None:
        for normalized in normalize_ticker_payload(data, received_at):
            self._ingest_tape(normalized)

    def _ensure_coverage(self, symbol: str, source: str, event_at: str) -> None:
        if symbol in self._coverage_active:
            return
        self._coverage_active.add(symbol)
        self._journal_event(
            "COVERAGE_START",
            symbol=symbol,
            event_at=event_at,
            payload={"source": source, "reconnect_epoch": self.manager.reconnect_epoch},
        )

    def _journal_mark(
        self,
        symbol: str,
        *,
        bid: Optional[float],
        ask: Optional[float],
        last: Optional[float],
        source: str,
        provider_at: Optional[str],
        received_at: str,
        sequence_id: Optional[int] = None,
        sequence_source: Optional[str] = None,
    ) -> None:
        if bid is None and ask is None and last is None:
            return
        self._ensure_coverage(symbol, source, received_at)
        self._journal_event(
            "MARK",
            symbol=symbol,
            event_at=received_at,
            payload={
                "bid": bid,
                "ask": ask,
                "last": last,
                "source": source,
                "provider_at": provider_at,
                "received_at": received_at,
                "sequence_id": sequence_id,
                "sequence_source": sequence_source,
                "reconnect_epoch": self.manager.reconnect_epoch,
            },
        )

    def _ingest_quote(self, normalized: NormalizedQuote) -> None:
        symbol, tick = normalized.symbol, normalized.tick
        if tick.bid is None and tick.ask is None and tick.last is None:
            return
        self.gateway.on_quote_push(symbol, tick)
        self.manager.on_quote(symbol, self.monotonic(), provider_at=tick.provider_at, received_at=tick.received_at)
        self._quote_meta[symbol] = {
            "provider_at": tick.provider_at,
            "received_at": tick.received_at,
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
        }
        self._journal_mark(
            symbol,
            bid=tick.bid,
            ask=tick.ask,
            last=tick.last,
            source="moomoo_quote",
            provider_at=tick.provider_at,
            received_at=tick.received_at,
        )

    def _ingest_book(self, normalized: NormalizedBook) -> None:
        symbol, snapshot = normalized.symbol, normalized.snapshot
        if not snapshot.bids or not snapshot.asks:
            return
        self.gateway.on_book_push(snapshot)
        self.manager.on_book(
            symbol,
            self.monotonic(),
            provider_at=snapshot.provider_at,
            received_at=snapshot.received_at,
            sequence_id=snapshot.sequence_id,
            crossed=snapshot.crossed,
        )
        best_bid = float(snapshot.bids[0][0]) if snapshot.bids else None
        best_ask = float(snapshot.asks[0][0]) if snapshot.asks else None
        self._book_meta[symbol] = {
            "bid_provider_at": normalized.bid_provider_at,
            "ask_provider_at": normalized.ask_provider_at,
            "provider_at": snapshot.provider_at,
            "received_at": normalized.received_at,
            "sequence_id": snapshot.sequence_id,
            "sequence_source": normalized.sequence_source,
            "crossed": snapshot.crossed,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "levels": {"bid": len(snapshot.bids), "ask": len(snapshot.asks)},
        }
        self._journal_event(
            "BOOK",
            symbol=symbol,
            event_at=normalized.received_at,
            payload={**self._book_meta[symbol], "bids": snapshot.bids, "asks": snapshot.asks},
        )
        self._journal_mark(
            symbol,
            bid=best_bid,
            ask=best_ask,
            last=(best_bid + best_ask) / 2.0 if best_bid is not None and best_ask is not None else None,
            source="moomoo_order_book",
            provider_at=snapshot.provider_at,
            received_at=normalized.received_at,
            sequence_id=snapshot.sequence_id,
            sequence_source=normalized.sequence_source,
        )

    def _ingest_tape(self, normalized: NormalizedTape) -> None:
        symbol = normalized.symbol
        previous = self._ticker_sequence.get(symbol)
        if normalized.provider_sequence is not None and previous is not None and normalized.provider_sequence < previous:
            lifecycle = self.manager.symbols.get(symbol)
            if lifecycle is not None:
                lifecycle.state = L2State.SEQUENCE_GAP
                lifecycle.error_code = "TICKER_SEQUENCE_GAP"
                lifecycle.error_detail = f"ticker seq {normalized.provider_sequence} < {previous}"
            self._journal_event(
                "COVERAGE_GAP",
                symbol=symbol,
                event_at=normalized.received_at,
                payload={"reason": "TICKER_SEQUENCE_REGRESSION", "previous": previous, "current": normalized.provider_sequence},
            )
            self._coverage_active.discard(symbol)
            return
        accepted = []
        for sequence, print_ in zip(normalized.sequences, normalized.prints):
            if sequence is None or previous is None or sequence > previous:
                accepted.append(print_)
        if previous is not None and normalized.provider_sequence is not None and normalized.provider_sequence == previous and not accepted:
            return
        if normalized.provider_sequence is not None:
            self._ticker_sequence[symbol] = normalized.provider_sequence
        if not accepted:
            return
        self.gateway.on_tape_push(symbol, accepted)
        self.manager.on_tape(
            symbol,
            self.monotonic(),
            provider_at=normalized.provider_at,
            received_at=normalized.received_at,
        )
        last_print = accepted[-1] if accepted else None
        self._tape_meta[symbol] = {
            "provider_at": normalized.provider_at,
            "received_at": normalized.received_at,
            "provider_sequence": normalized.provider_sequence,
            "print_count": len(accepted),
            "last": last_print.price if last_print else None,
            "last_size": last_print.size if last_print else None,
            "last_side": last_print.side if last_print else None,
        }
        self._journal_event(
            "TAPE",
            symbol=symbol,
            event_at=normalized.received_at,
            payload={
                **self._tape_meta[symbol],
                "prints": [asdict(print_) for print_ in accepted],
            },
        )
        if last_print is not None:
            self._journal_mark(
                symbol,
                bid=None,
                ask=None,
                last=last_print.price,
                source="moomoo_ticker",
                provider_at=last_print.provider_at,
                received_at=last_print.received_at,
                sequence_id=normalized.provider_sequence,
                sequence_source="provider_ticker_sequence",
            )

    def _refresh_health(self, now_mono: float, *, force: bool = False) -> None:
        if not force and now_mono - self._last_health < self.config.health_interval_seconds:
            return
        self._last_health = now_mono
        previous = self._connected
        try:
            self._connected = bool(self.transport.ping())
            self._entitled = bool(self._connected and self.transport.entitlement_ok())
        except Exception as exc:
            self._connected = self._entitled = False
            self._set_error("health", exc)
        if previous and not self._connected:
            for symbol in sorted(self._coverage_active):
                self._journal_event(
                    "COVERAGE_GAP",
                    symbol=symbol,
                    payload={"reason": "PROVIDER_DISCONNECTED", "reconnect_epoch": self.manager.reconnect_epoch},
                )
            self._coverage_active.clear()
            for lifecycle in self.manager.symbols.values():
                if lifecycle.state not in (L2State.UNSUBSCRIBED, L2State.NOT_REQUESTED):
                    lifecycle.state = L2State.PROVIDER_DISCONNECTED
                    lifecycle.error_code = "PROVIDER_DISCONNECTED"
        elif not previous and self._connected:
            self.manager.reconnect_epoch += 1
            self._book_sequence = {}
            self._ticker_sequence = {}
            for lifecycle in self.manager.symbols.values():
                lifecycle.reconnect_epoch = self.manager.reconnect_epoch
                lifecycle.confirmed_subtypes = ()
                lifecycle.first_book_at = lifecycle.first_tape_at = lifecycle.first_quote_at = None
                lifecycle.last_book_at = lifecycle.last_tape_at = lifecycle.last_quote_at = None
                lifecycle.sequence_id = None
            self._journal_event(
                "RECONNECT",
                payload={"reconnect_epoch": self.manager.reconnect_epoch, "source_commit": self.source_commit},
            )
            self._last_quota = 0.0

    def _refresh_intent(self, now_mono: float, *, force: bool = False) -> None:
        if not force and now_mono - self._last_intent < self.config.intent_refresh_seconds:
            return
        self._last_intent = now_mono
        self._desired = merge_intents(self.config.intent_paths, now_epoch=self.wall_time())

    def _adopt_provider_symbol(self, symbol: str, subtypes: list[str], now_mono: float) -> SymbolLifecycle:
        lifecycle = self.manager.symbols.get(symbol)
        if lifecycle is None:
            lifecycle = SymbolLifecycle(symbol=symbol)
            self.manager.symbols[symbol] = lifecycle
        lifecycle.requested_subtypes = tuple(subtypes or self.lifecycle_config.subtypes)
        lifecycle.quota_units = max(1, len(subtypes))
        lifecycle.subscribed_at = lifecycle.subscribed_at if lifecycle.subscribed_at is not None else now_mono
        lifecycle.reconnect_epoch = self.manager.reconnect_epoch
        if lifecycle.state in (
            L2State.NOT_REQUESTED,
            L2State.ARM_INTENT,
            L2State.PROVIDER_DISCONNECTED,
            L2State.FAILED,
            L2State.UNSUBSCRIBED,
        ):
            lifecycle.state = L2State.WAITING_FIRST_BOOK
        lifecycle.error_code = lifecycle.error_detail = None
        return lifecycle

    def _refresh_provider_truth(self, now_mono: float, *, force: bool = False) -> None:
        if not force and now_mono - self._last_quota < self.config.quota_refresh_seconds:
            return
        self._last_quota = now_mono
        self.manager.refresh_quota(utc_now_iso())
        try:
            provider = self.transport.query_subscription(is_all_conn=True) or {}
        except Exception as exc:
            provider = {}
            self._set_error("query_subscription", exc)
        raw_by_symbol = provider.get("subscriptions_by_symbol") if isinstance(provider, Mapping) else None
        self._provider_subscriptions = {
            str(symbol).upper(): sorted(str(subtype).upper() for subtype in subtypes)
            for symbol, subtypes in (raw_by_symbol or {}).items()
        }
        for symbol, subtypes in self._provider_subscriptions.items():
            self._adopt_provider_symbol(symbol, subtypes, now_mono)

    def _request_missing_provider_subtypes(
        self, symbol: str, detail: Mapping[str, Any]
    ) -> bool:
        observed = set(self._provider_subscriptions.get(symbol) or [])
        required = set(self.lifecycle_config.subtypes)
        missing = tuple(sorted(required - observed))
        if not missing:
            return False
        hard_remaining = self.manager.ledger.remain
        if hard_remaining is None or len(missing) > hard_remaining:
            return False
        priority = str(detail.get("priority") or "P2").upper()
        if priority != "P0":
            discretionary = self.manager.ledger.available_for_discretionary()
            if discretionary is None or len(missing) > discretionary:
                return False
        try:
            ok, message = self.gateway.subscribe(symbol, list(missing))
        except Exception as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        self._journal_event(
            "SUBTYPE_RECONCILE_REQUEST",
            symbol=symbol,
            payload={
                "missing_subtypes": list(missing),
                "accepted": bool(ok),
                "detail": str(message)[:160],
            },
        )
        if ok:
            reserve = getattr(self.manager, "_reserve_local_quota", None)
            if callable(reserve):
                reserve(len(missing), missing)
            return True
        return False

    def _drive_desired(self, now_mono: float) -> None:
        if not (self._connected and self._entitled):
            return
        for symbol, detail in self._desired.items():
            lifecycle = self.manager.symbols.get(symbol)
            provider_has = symbol in self._provider_subscriptions
            if provider_has:
                lifecycle = self._adopt_provider_symbol(symbol, self._provider_subscriptions[symbol], now_mono)
                self._request_missing_provider_subtypes(symbol, detail)
            elif lifecycle is None or lifecycle.state not in {
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
            }:
                lifecycle = self.manager.request_l2(
                    symbol,
                    now_mono,
                    reason=str(detail.get("reason") or "gateway_intent"),
                    priority=str(detail.get("priority") or "P2"),
                    require_tape=bool(detail.get("require_tape")),
                    is_fire=bool(detail.get("is_fire")),
                    now_iso=utc_now_iso(),
                )
            expires_at = detail.get("expires_at")
            if lifecycle is not None and expires_at is not None:
                try:
                    remaining = max(0.0, float(expires_at) - self.wall_time())
                    lifecycle.expires_at = now_mono + remaining
                except (TypeError, ValueError):
                    pass
        for symbol in sorted(set(self.manager.symbols) - set(self._desired)):
            lifecycle = self.manager.symbols[symbol]
            if lifecycle.state not in (L2State.NOT_REQUESTED, L2State.UNSUBSCRIBED, L2State.UNSUBSCRIBE_PENDING):
                self.manager.release(symbol, now_mono, reason="not_in_desired_intent")

    def _poll_symbol(self, symbol: str, now_mono: float) -> None:
        if now_mono - self._last_quote_poll.get(symbol, 0.0) >= self.config.quote_poll_seconds:
            self._last_quote_poll[symbol] = now_mono
            try:
                self._on_quote_payload(self.transport.get_quote(symbol), utc_now_iso())
            except Exception as exc:
                self._set_error(f"quote:{symbol}", exc)
        if now_mono - self._last_book_poll.get(symbol, 0.0) >= self.config.book_poll_seconds:
            self._last_book_poll[symbol] = now_mono
            try:
                raw = dict(self.transport.get_order_book(symbol, levels=self.config.book_levels) or {})
                raw.setdefault("code", f"US.{symbol}")
                sequence = self._next_book_sequence(symbol)
                normalized = normalize_order_book_payload(
                    raw,
                    utc_now_iso(),
                    sequence_id=sequence,
                    sequence_source="gateway_monotonic_per_reconnect_epoch",
                    levels=self.config.book_levels,
                )
                if normalized is not None:
                    self._ingest_book(normalized)
            except Exception as exc:
                self._set_error(f"book:{symbol}", exc)
        if now_mono - self._last_ticker_poll.get(symbol, 0.0) >= self.config.ticker_poll_seconds:
            self._last_ticker_poll[symbol] = now_mono
            try:
                data = self.transport.get_ticker(symbol, count=self.config.ticker_pull_count)
                if data is not None:
                    self._on_ticker_payload(data, utc_now_iso())
            except Exception as exc:
                self._set_error(f"ticker:{symbol}", exc)

    def _poll_data(self, now_mono: float) -> None:
        if not (self._connected and self._entitled):
            return
        for symbol, lifecycle in sorted(self.manager.symbols.items()):
            if lifecycle.state in {
                L2State.SUBSCRIBE_REQUESTED,
                L2State.SUBSCRIBED,
                L2State.WAITING_FIRST_BOOK,
                L2State.WAITING_FIRST_TAPE,
                L2State.FRESH,
                L2State.STALE,
                L2State.SEQUENCE_GAP,
                L2State.CROSSED_BOOK,
                L2State.POST_FIRE_RETENTION,
            }:
                self._poll_symbol(symbol, now_mono)

    def _observe_lifecycle_gaps(self) -> None:
        for symbol, lifecycle in self.manager.symbols.items():
            state = lifecycle.state.value
            old = self._last_lifecycle.get(symbol)
            self._last_lifecycle[symbol] = state
            if state in {L2State.STALE.value, L2State.SEQUENCE_GAP.value, L2State.CROSSED_BOOK.value}:
                if symbol in self._coverage_active and old != state:
                    self._journal_event(
                        "COVERAGE_GAP",
                        symbol=symbol,
                        payload={"reason": state, "reconnect_epoch": self.manager.reconnect_epoch},
                    )
                    self._coverage_active.discard(symbol)

    @staticmethod
    def _age_ms(received_at: Optional[str], now: datetime) -> Optional[float]:
        if not received_at:
            return None
        try:
            parsed = datetime.fromisoformat(str(received_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() * 1000.0)
        except (TypeError, ValueError):
            return None

    def _current_mark(self, symbol: str, now: datetime) -> dict[str, Any]:
        threshold = float(self.lifecycle_config.live_mark_stale_after_ms)
        quote = self._quote_meta.get(symbol) or {}
        quote_age = self._age_ms(quote.get("received_at"), now)
        if quote and quote_age is not None and quote_age <= threshold and any(
            quote.get(key) is not None for key in ("bid", "ask", "last")
        ):
            return {
                "symbol": symbol,
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                "last": quote.get("last"),
                "source": "moomoo_quote",
                "provider_at": quote.get("provider_at"),
                "received_at": quote.get("received_at"),
                "age_ms": quote_age,
                "stale": False,
                "available": True,
            }
        tape = self._tape_meta.get(symbol) or {}
        tape_age = self._age_ms(tape.get("received_at"), now)
        if tape.get("last") is not None and tape_age is not None and tape_age <= threshold:
            return {
                "symbol": symbol,
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                "last": tape.get("last"),
                "source": "moomoo_ticker",
                "provider_at": tape.get("provider_at"),
                "received_at": tape.get("received_at"),
                "age_ms": tape_age,
                "stale": False,
                "available": True,
                "provider_sequence": tape.get("provider_sequence"),
            }
        book = self._book_meta.get(symbol) or {}
        book_age = self._age_ms(book.get("received_at"), now)
        bid, ask = book.get("best_bid"), book.get("best_ask")
        if bid is not None and ask is not None and book_age is not None and book_age <= threshold:
            return {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "last": (float(bid) + float(ask)) / 2.0,
                "source": "moomoo_order_book",
                "provider_at": book.get("provider_at"),
                "received_at": book.get("received_at"),
                "age_ms": book_age,
                "stale": False,
                "available": True,
                "sequence_id": book.get("sequence_id"),
                "sequence_source": book.get("sequence_source"),
            }
        candidates = [value for value in (quote_age, tape_age, book_age) if value is not None]
        return {
            "symbol": symbol,
            "bid": quote.get("bid") or bid,
            "ask": quote.get("ask") or ask,
            "last": quote.get("last") or tape.get("last"),
            "source": None,
            "provider_at": None,
            "received_at": None,
            "age_ms": min(candidates) if candidates else None,
            "stale": True,
            "available": False,
        }

    def _snapshot_payload(self, service_state: str = "RUNNING") -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        manager_snapshot = self.manager.snapshot(now_iso)
        symbols: dict[str, Any] = {}
        for symbol, raw in manager_snapshot.get("symbols", {}).items():
            lifecycle = dict(raw)
            try:
                decision = self.features.evaluate_t2(symbol, self.monotonic(), now_iso).to_dict()
            except Exception as exc:
                decision = {"is_t2": False, "reason": f"EVAL_ERROR_{type(exc).__name__}"}
            symbols[symbol] = {
                **lifecycle,
                "provider_subtypes": self._provider_subscriptions.get(symbol, []),
                "book": self._book_meta.get(symbol),
                "tape": self._tape_meta.get(symbol),
                "quote": self._quote_meta.get(symbol),
                "t2": decision,
            }
        all_symbols = sorted(set(symbols) | set(self._desired) | set(self._provider_subscriptions))
        marks = {symbol: self._current_mark(symbol, now) for symbol in all_symbols}
        return {
            "service_contract": SERVICE_CONTRACT,
            "service_state": service_state,
            "source_commit": self.source_commit,
            "started_at": self.started_at,
            "heartbeat_at": now_iso,
            "owner": {
                "pid": os.getpid(),
                "exclusive_lock_held": self.owner_lock.held,
                "lock_path": str(self.config.lock_path),
                "context_owner": "gateway_service",
            },
            "provider": {
                "connected": self._connected,
                "entitled_realtime": self._entitled,
                "reconnect_epoch": self.manager.reconnect_epoch,
                "subscriptions_by_symbol": self._provider_subscriptions,
            },
            "quota": manager_snapshot.get("quota"),
            "concurrent_symbols": manager_snapshot.get("concurrent_symbols"),
            "max_concurrent_l2_symbols": manager_snapshot.get("max_concurrent_l2_symbols"),
            "min_dwell_seconds": manager_snapshot.get("min_dwell_seconds"),
            "desired_intent": self._desired,
            "symbols": symbols,
            "current_marks": marks,
            "journal": {
                "contract": "moomoo-l2-gateway-event-v1",
                "directory": str(self.config.journal_dir),
                "retention_days": self.config.journal_retention_days,
                "durable_replay_available": True,
            },
            "last_error": self._last_error,
            "snapshot_stale_after_seconds": self.config.snapshot_stale_after_seconds,
            "read_only": True,
            "write": False,
            "order_path": False,
            "authority": self._authority(),
        }

    def _publish_snapshot(self, *, force: bool = False, service_state: str = "RUNNING") -> None:
        now_mono = self.monotonic()
        if not force and now_mono - self._last_publish < self.config.heartbeat_seconds:
            return
        self._last_publish = now_mono
        self.publisher.publish(self._snapshot_payload(service_state))

    def run_once(self, *, force: bool = False) -> dict[str, Any]:
        now_mono = self.monotonic()
        self._refresh_health(now_mono, force=force)
        self._refresh_intent(now_mono, force=force)
        self._refresh_provider_truth(now_mono, force=force)
        self._drive_desired(now_mono)
        if force:
            self._refresh_provider_truth(now_mono, force=True)
        self._poll_data(now_mono)
        self.manager.tick(now_mono)
        if force:
            self._refresh_provider_truth(now_mono, force=True)
        self._observe_lifecycle_gaps()
        self._save_state(force=force)
        self._publish_snapshot(force=force)
        self._flush_journal(force=force)
        return self._snapshot_payload()

    def serve_forever(self) -> None:
        self.start()
        try:
            while self.running:
                self.run_once()
                self.sleep(self.config.loop_interval_ms / 1000.0)
        finally:
            self.stop()


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dedicated read-only Moomoo L2 gateway")
    parser.add_argument("--config", help="gateway YAML; shipped example is disabled")
    parser.add_argument("--once", action="store_true", help="one reconciliation cycle, then clean shutdown")
    parser.add_argument("--print-config", action="store_true", help="print resolved non-secret config and exit")
    args = parser.parse_args(argv)
    config = load_service_config(args.config)
    if args.print_config:
        print(json.dumps({**asdict(config), **{
            "snapshot_path": str(config.snapshot_path),
            "state_path": str(config.state_path),
            "lock_path": str(config.lock_path),
            "journal_dir": str(config.journal_dir),
            "intent_paths": [str(path) for path in config.intent_paths],
        }}, indent=2, default=str))
        return 0
    service = MoomooL2GatewayService(config)

    def _stop(_signum, _frame):
        service.running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        if args.once:
            service.start()
            service.stop()
        else:
            service.serve_forever()
    except GatewayDisabled as exc:
        print(json.dumps({"ok": False, "error": "GATEWAY_DISABLED", "detail": str(exc)}))
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
