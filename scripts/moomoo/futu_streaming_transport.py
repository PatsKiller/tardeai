"""Single-context Futu streaming transport for the dedicated gateway service.

Only this transport, when constructed by ``gateway_service.py``, may own the production
OpenQuoteContext. It installs quote/order-book/ticker handlers on that same context and
provides pull fallbacks for recovery. No trade context or order method is imported.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    from .client import FutuTransport, MoomooUnavailable, to_futu_symbol
    from .config import load_stage0_config
except ImportError:  # pragma: no cover
    from client import FutuTransport, MoomooUnavailable, to_futu_symbol  # type: ignore
    from config import load_stage0_config  # type: ignore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FutuStreamingTransport:
    """One explicitly owned FutuTransport plus push callbacks and provider reconciliation."""

    def __init__(self, futu: Optional[FutuTransport] = None):
        if futu is None:
            config = load_stage0_config()
            futu = FutuTransport(
                config.host,
                config.port,
                timeout=config.connect_timeout_seconds or 4.0,
            )
        self._t = futu
        self._lock = threading.RLock()
        self._handlers_installed = False
        self._on_quote: Optional[Callable[[Any, str], None]] = None
        self._on_book: Optional[Callable[[Any, str], None]] = None
        self._on_tape: Optional[Callable[[Any, str], None]] = None

    def bind_callbacks(
        self,
        *,
        on_quote: Callable[[Any, str], None],
        on_book: Callable[[Any, str], None],
        on_tape: Callable[[Any, str], None],
    ) -> None:
        with self._lock:
            self._on_quote = on_quote
            self._on_book = on_book
            self._on_tape = on_tape
            try:
                self._install_handlers()
            except Exception:
                # OpenD may be down at service start. Pull recovery and a later health
                # transition retry handler installation on the same eventual context.
                self._handlers_installed = False

    def _safe_emit(self, callback, data) -> None:
        if callback is None:
            return
        try:
            callback(data, _utc_now())
        except Exception:
            # SDK networking threads must never die because a consumer rejected one payload.
            return

    def _install_handlers(self) -> None:
        if self._handlers_installed:
            return
        context = self._t._context()  # one construction site, one owner process
        try:
            from futu import (
                RET_OK,
                OrderBookHandlerBase,
                StockQuoteHandlerBase,
                TickerHandlerBase,
            )
        except ImportError as exc:  # pragma: no cover - host dependency
            raise MoomooUnavailable(f"futu SDK not installed: {exc}") from exc
        owner = self

        class _QuoteHandler(StockQuoteHandlerBase):
            def on_recv_rsp(self, rsp_pb):  # noqa: N802 - SDK contract
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret == RET_OK:
                    owner._safe_emit(owner._on_quote, data)
                return ret, data

        class _BookHandler(OrderBookHandlerBase):
            def on_recv_rsp(self, rsp_pb):  # noqa: N802
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret == RET_OK:
                    owner._safe_emit(owner._on_book, data)
                return ret, data

        class _TickerHandler(TickerHandlerBase):
            def on_recv_rsp(self, rsp_pb):  # noqa: N802
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret == RET_OK:
                    owner._safe_emit(owner._on_tape, data)
                return ret, data

        for handler in (_QuoteHandler(), _BookHandler(), _TickerHandler()):
            result = context.set_handler(handler)
            code = result[0] if isinstance(result, tuple) and result else result
            if code not in (None, 0, RET_OK):
                raise MoomooUnavailable(f"OpenD rejected callback handler: {result}")
        self._handlers_installed = True

    def ping(self) -> bool:
        connected = bool(self._t.ping())
        if connected and not self._handlers_installed:
            try:
                self._install_handlers()
            except Exception:
                # Pull fallbacks remain available; callback installation is retried.
                self._handlers_installed = False
        return connected

    def entitlement_ok(self) -> bool:
        return bool(self._t.entitlement_ok())

    @staticmethod
    def _subtype_objects(subtypes: list[str]):
        from futu import SubType

        result = []
        for name in subtypes:
            value = getattr(SubType, str(name).upper(), None)
            if value is not None:
                result.append(value)
        return result

    def subscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        try:
            from futu import RET_OK, Session

            context = self._t._context()
            objects = self._subtype_objects(subtypes)
            if len(objects) != len(set(subtypes)):
                return False, f"unknown subtype requested: {subtypes!r}"
            kwargs = {"is_first_push": True, "subscribe_push": True}
            session_all = getattr(Session, "ALL", None)
            if session_all is not None:
                kwargs["session"] = session_all
            try:
                ret, message = context.subscribe([to_futu_symbol(symbol)], objects, **kwargs)
            except TypeError:
                kwargs.pop("session", None)
                ret, message = context.subscribe([to_futu_symbol(symbol)], objects, **kwargs)
            if ret != RET_OK:
                return False, str(message)[:240]
            self._t._subscribed.add(to_futu_symbol(symbol))
            return True, "ok"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def unsubscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        try:
            from futu import RET_OK

            objects = self._subtype_objects(subtypes)
            ret, message = self._t._context().unsubscribe([to_futu_symbol(symbol)], objects)
            if ret != RET_OK:
                return False, str(message)[:240]
            self._t._subscribed.discard(to_futu_symbol(symbol))
            return True, "ok"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _normalize_provider_symbol(value: Any) -> str:
        text = str(value or "").upper()
        return text[3:] if text.startswith("US.") else text

    def query_subscription(self, is_all_conn: bool = True) -> dict:
        try:
            from futu import RET_OK

            ret, data = self._t._context().query_subscription(is_all_conn=is_all_conn)
            if ret != RET_OK or not isinstance(data, dict):
                return {}
        except Exception:
            return {}
        total_used = data.get("total_used")
        own_used = data.get("own_used")
        remain = data.get("remain")
        by_type: dict[str, int] = {}
        by_symbol: dict[str, set[str]] = {}
        raw_subscriptions = data.get("sub_list") or {}
        if isinstance(raw_subscriptions, dict):
            for raw_type, raw_symbols in raw_subscriptions.items():
                subtype = str(raw_type).split(".")[-1].upper()
                symbols = list(raw_symbols or [])
                by_type[subtype] = len(symbols)
                for raw_symbol in symbols:
                    symbol = self._normalize_provider_symbol(raw_symbol)
                    if symbol:
                        by_symbol.setdefault(symbol, set()).add(subtype)
        total_quota = None
        try:
            if total_used is not None and remain is not None:
                total_quota = int(total_used) + int(remain)
        except (TypeError, ValueError):
            pass
        return {
            "total_quota": total_quota,
            "total_used": None if total_used is None else int(total_used),
            "own_used": None if own_used is None else int(own_used),
            "remain": None if remain is None else int(remain),
            "other_connection_usage": (
                None
                if total_used is None or own_used is None
                else max(0, int(total_used) - int(own_used))
            ),
            "subscriptions_by_type": by_type,
            "subscriptions_by_symbol": {
                symbol: sorted(subtypes) for symbol, subtypes in sorted(by_symbol.items())
            },
            "provider_raw_keys": sorted(str(key) for key in data),
        }

    def get_order_book(self, symbol: str, levels: int = 10) -> dict:
        raw = dict(self._t.get_order_book(symbol, levels=levels) or {})
        # The pull API does not document a provider book timestamp. Preserve the
        # local observation separately; do not relabel it as provider time.
        raw["poll_observed_at"] = raw.pop("ts", None)
        return raw

    def get_quote(self, symbol: str) -> dict:
        try:
            from futu import RET_OK

            with self._t._quiet():
                ret, data = self._t._context().get_market_snapshot([to_futu_symbol(symbol)])
            if ret != RET_OK or data is None or len(data) == 0:
                return {"code": to_futu_symbol(symbol)}
            row = data.iloc[0]
            return {
                "code": to_futu_symbol(symbol),
                "bid_price": row.get("bid_price"),
                "ask_price": row.get("ask_price"),
                "last_price": row.get("last_price"),
                "data_date": row.get("data_date"),
                "data_time": row.get("data_time"),
            }
        except Exception:
            return {"code": to_futu_symbol(symbol)}

    def get_ticker(self, symbol: str, count: int = 1000) -> Any:
        try:
            from futu import RET_OK

            ret, data = self._t._context().get_rt_ticker(to_futu_symbol(symbol), num=int(count))
            return data if ret == RET_OK else None
        except Exception:
            return None

    def close(self) -> None:
        self._t.close()
