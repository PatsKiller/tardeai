"""Thin Moomoo OpenD adapter interface — Stage 0 read-plane only.

Fail-closed when OpenD is down or trading/order methods are requested.
No SDK import required for the stub adapter (CI-safe).
"""
from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from .config import Stage0Config


class MoomooUnavailable(RuntimeError):
    """OpenD data plane is not available — fail closed."""


class MoomooAuthorityError(RuntimeError):
    """Order / unlock / trading path refused in Stage 0."""


@dataclass(frozen=True)
class QuoteSnapshot:
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    ts_utc: str
    source: str = "stub"


class OpenDTransport(Protocol):
    def ping(self) -> bool: ...
    def get_quote(self, symbol: str) -> QuoteSnapshot: ...


class StubTransport:
    """In-process stub: healthy only when ``force_up`` is True."""

    def __init__(self, *, force_up: bool = False) -> None:
        self.force_up = force_up

    def ping(self) -> bool:
        return bool(self.force_up)

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        if not self.force_up:
            raise MoomooUnavailable("stub OpenD is down")
        return QuoteSnapshot(
            symbol=symbol,
            bid=None,
            ask=None,
            last=None,
            ts_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            source="stub",
        )


def tcp_reachable(host: str, port: int, timeout: float) -> bool:
    """Best-effort TCP connect probe. Never logs credentials."""
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout)):
            return True
    except OSError:
        return False


class MoomooClient:
    """Stage 0 client: quotes/history interface with hard order-path refusal."""

    FORBIDDEN_METHODS = frozenset({
        "place_order",
        "modify_order",
        "cancel_order",
        "unlock_trade",
        "lock_trade",
        "submit_order",
        "execute_trade",
    })

    def __init__(
        self,
        config: Stage0Config,
        *,
        transport: OpenDTransport | None = None,
        opend_up: bool | None = None,
    ) -> None:
        if config.order_routing or config.trade_unlock:
            raise MoomooAuthorityError("Stage 0 client refuses order_routing/trade_unlock config")
        self.config = config
        self._transport = transport or StubTransport(force_up=False)
        # Explicit health override for tests; None = ask transport
        self._opend_up_override = opend_up

    @property
    def opend_up(self) -> bool:
        if self._opend_up_override is not None:
            return bool(self._opend_up_override)
        try:
            return bool(self._transport.ping())
        except Exception:
            return False

    def mark_opend(self, up: bool) -> None:
        self._opend_up_override = bool(up)
        if isinstance(self._transport, StubTransport):
            self._transport.force_up = bool(up)

    def ensure_up(self) -> None:
        if not self.opend_up:
            raise MoomooUnavailable(
                f"OpenD data plane unavailable at {self.config.host}:{self.config.port} "
                "(Stage 0 fail-closed; no order path)"
            )

    def health(self) -> dict[str, Any]:
        return {
            "stage": 0,
            "mode": self.config.mode,
            "opend_up": self.opend_up,
            "host": self.config.host,
            "port": self.config.port,
            "adapter": self.config.adapter,
            "fail_closed": self.config.fail_closed,
            "order_routing": False,
            "trade_unlock": False,
            "read_only": True,
        }

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        if self.config.fail_closed:
            self.ensure_up()
        return self._transport.get_quote(symbol)

    def get_history(self, symbol: str, *, bars: int = 1) -> Sequence[Mapping[str, Any]]:
        if self.config.fail_closed:
            self.ensure_up()
        # Stage 0: empty history scaffold when stub is up
        _ = bars
        return ()

    def place_order(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        raise MoomooAuthorityError("place_order is OUT of Stage 0 (order path forbidden)")

    def unlock_trade(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        raise MoomooAuthorityError("unlock_trade is OUT of Stage 0 (trade unlock forbidden)")

    def __getattr__(self, name: str) -> Any:
        if name in self.FORBIDDEN_METHODS:
            raise MoomooAuthorityError(f"{name} is OUT of Stage 0 (order path forbidden)")
        raise AttributeError(name)
