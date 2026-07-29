"""Real futu-backed transport for the single-owner QuoteGateway.

Composes ONE ``client.FutuTransport`` (the single OpenQuoteContext construction site) and
exposes the gateway transport surface. Fail-closed: any SDK/host problem reports down /
unentitled and returns empty books, so the gateway degrades to honest "not connected"
rather than fabricating market data. Read plane only — no order/unlock path.

NOT exercised in CI (no live OpenD). The consumer path is not claimed live until an
integration probe against a logged-in OpenD proves book+tape+quota round-trip.
"""
from __future__ import annotations

from typing import Optional

try:
    from .client import FutuTransport
    from .config import load_stage0_config
except ImportError:  # pragma: no cover
    from client import FutuTransport  # type: ignore
    from config import load_stage0_config  # type: ignore


class RealGatewayTransport:
    def __init__(self, futu: Optional[FutuTransport] = None):
        if futu is not None:
            self._t = futu
            return
        try:
            cfg = load_stage0_config()
            self._t = FutuTransport(cfg.host, cfg.port,
                                    timeout=cfg.connect_timeout_seconds or 4.0)
        except Exception:
            self._t = None

    def ping(self) -> bool:
        try:
            return bool(self._t and self._t.ping())
        except Exception:
            return False

    def entitlement_ok(self) -> bool:
        try:
            return bool(self._t and self._t.entitlement_ok())
        except Exception:
            return False

    def query_subscription(self, is_all_conn: bool = True) -> dict:
        try:
            return dict(self._t.query_subscription(is_all_conn=is_all_conn)) if self._t else {}
        except Exception:
            return {}

    def subscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        if not self._t:
            return False, "transport unavailable"
        try:
            return self._t.subscribe(symbol, list(subtypes))
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def unsubscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        if not self._t:
            return False, "transport unavailable"
        try:
            return self._t.unsubscribe(symbol, list(subtypes))
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def get_order_book(self, symbol: str, levels: int = 10) -> dict:
        if not self._t:
            return {"bids": [], "asks": [], "ts": None}
        try:
            return self._t.get_order_book(symbol, levels=levels)
        except Exception:
            return {"bids": [], "asks": [], "ts": None}
