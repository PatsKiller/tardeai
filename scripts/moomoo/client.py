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


def to_futu_symbol(symbol: str, market: str = "US") -> str:
    """'AAPL' -> 'US.AAPL'. Already-qualified symbols pass through."""
    s = str(symbol or "").strip().upper()
    return s if "." in s else f"{market}.{s}"


# The futu SDK's real logger names. Discovered by introspection, not documented:
# FTConsoleLog owns a StreamHandler bound to stdout at INFO.
_FUTU_LOGGERS = ("FTConsoleLog", "FTFileLog", "futu", "futu.common", "FTLog")


def quiet_futu_logging():
    """Raise the futu loggers to CRITICAL and return a redirect_stdout guard.

    Both halves are needed: the level change stops FTConsoleLog (whose handler holds
    the real stdout from import time, so redirection alone misses it) and the
    redirect catches anything the SDK prints directly.
    """
    import contextlib
    import io
    import logging
    for name in _FUTU_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(logging.CRITICAL)
        lg.propagate = False
        for h in list(lg.handlers):
            h.setLevel(logging.CRITICAL)
    return contextlib.redirect_stdout(io.StringIO())


class FutuTransport:
    """Real OpenD transport over the futu SDK. Read plane only — quotes and depth.

    ping() deliberately issues a REAL query rather than a TCP connect: OpenD binds
    127.0.0.1:11111 before it authenticates, so a reachable port says nothing about
    login. On 2026-07-23 it listened and exited seconds later on a bad password.

    The SDK logs verbosely to stdout on connect; that is silenced here so callers
    (cron jobs emitting JSON) keep clean output.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 11111, *, timeout: float = 4.0):
        self.host, self.port, self.timeout = host, int(port), float(timeout)
        self._ctx = None
        self._subscribed: set[str] = set()

    # ── context lifecycle ────────────────────────────────────────────────────
    @staticmethod
    def _quiet():
        """Silence the futu SDK's own loggers and swallow its stdout.

        The SDK installs 'FTConsoleLog' (StreamHandler → stdout, INFO) and
        'FTFileLog' (TimedRotatingFileHandler) at import. Left alone, FTConsoleLog
        interleaves with JSON output from cron jobs, and FTFileLog wrote a 25 MB
        day-file the last time this ran. redirect_stdout alone does NOT fix the
        console one — its handler binds the real stdout at import time — so the
        logger levels must be raised as well.
        """
        return quiet_futu_logging()

    def _context(self):
        if self._ctx is not None:
            return self._ctx
        if not tcp_reachable(self.host, self.port, self.timeout):
            raise MoomooUnavailable(f"OpenD not reachable at {self.host}:{self.port}")
        try:
            with self._quiet():
                from futu import OpenQuoteContext, SysConfig
                # The SDK's networking threads are NON-daemon by default, so an open
                # context keeps the interpreter alive forever — a cron scan that
                # builds a provider would never exit and jobs would pile up. Make
                # them daemon so process exit is always possible, and register an
                # atexit close so subscriptions are released on the way out.
                SysConfig.set_all_thread_daemon(True)
                self._ctx = OpenQuoteContext(host=self.host, port=self.port)
            import atexit
            atexit.register(self.close)
        except ImportError as e:
            raise MoomooUnavailable(f"futu SDK not installed: {e}") from e
        except Exception as e:
            raise MoomooUnavailable(f"OpenD connect failed: {e}") from e
        return self._ctx

    def close(self) -> None:
        if self._ctx is not None:
            try:
                with self._quiet():
                    for s in list(self._subscribed):
                        self.unsubscribe_book(s)
                    self._ctx.close()
            except Exception:
                pass
            self._ctx = None
            self._subscribed.clear()

    # ── read plane ───────────────────────────────────────────────────────────
    def ping(self) -> bool:
        """True only when a real query round-trips — i.e. OpenD is LOGGED IN."""
        try:
            from futu import RET_OK
            with self._quiet():
                ret, _ = self._context().get_market_snapshot([to_futu_symbol("AAPL")])
            return ret == RET_OK
        except Exception:
            return False

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        from futu import RET_OK
        sym = to_futu_symbol(symbol)
        with self._quiet():
            ret, data = self._context().get_market_snapshot([sym])
        if ret != RET_OK or data is None or len(data) == 0:
            raise MoomooUnavailable(f"snapshot failed for {sym}: {str(data)[:120]}")
        row = data.iloc[0]

        def _f(key):
            try:
                v = float(row.get(key))
                return v if v == v else None       # NaN -> None
            except (TypeError, ValueError):
                return None

        return QuoteSnapshot(
            symbol=str(symbol).upper(),
            bid=_f("bid_price"), ask=_f("ask_price"), last=_f("last_price"),
            ts_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            source="moomoo_opend",
        )

    # ── L2 depth (armed symbols only — the caller owns the budget) ───────────
    def subscribe_book(self, symbol: str) -> bool:
        from futu import RET_OK, SubType
        sym = to_futu_symbol(symbol)
        if sym in self._subscribed:
            return True
        with self._quiet():
            ret, msg = self._context().subscribe([sym], [SubType.ORDER_BOOK])
        if ret != RET_OK:
            raise MoomooUnavailable(f"ORDER_BOOK subscribe refused for {sym}: {str(msg)[:120]}")
        self._subscribed.add(sym)
        return True

    def unsubscribe_book(self, symbol: str) -> None:
        from futu import SubType
        sym = to_futu_symbol(symbol)
        if sym not in self._subscribed:
            return
        try:
            with self._quiet():
                self._context().unsubscribe([sym], [SubType.ORDER_BOOK])
        except Exception:
            pass
        self._subscribed.discard(sym)

    def get_order_book(self, symbol: str, levels: int = 5) -> dict:
        """{bids:[(price,size)…], asks:[…], ts} — subscribes on first use.

        futu returns rows as (price, volume, order_count, extra); the provider only
        consumes (price, size), so flatten to pairs here.
        """
        from futu import RET_OK
        sym = to_futu_symbol(symbol)
        self.subscribe_book(symbol)
        with self._quiet():
            ret, book = self._context().get_order_book(sym, num=int(levels))
        if ret != RET_OK or not isinstance(book, dict):
            raise MoomooUnavailable(f"order book failed for {sym}: {str(book)[:120]}")

        def _pairs(rows):
            out = []
            for r in (rows or [])[:levels]:
                try:
                    out.append((float(r[0]), float(r[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            return out

        return {
            "bids": _pairs(book.get("Bid")),
            "asks": _pairs(book.get("Ask")),
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

    # ── gateway surface (single-context subtype subscribe + quota truth) ─────
    # Used by the single-owner QuoteGateway. Reuses the ONE OpenQuoteContext above so
    # no second production context is ever created. Not exercised in CI (no live OpenD).
    def entitlement_ok(self) -> bool:
        """OpenD logged in and serving (proxy for data-plane entitlement)."""
        return self.ping()

    @staticmethod
    def _subtype_objs(subtypes):
        """Map canonical subtype NAMES to futu SubType members (unknown names skipped)."""
        from futu import SubType
        out = []
        for name in subtypes or ():
            member = getattr(SubType, str(name).upper(), None)
            if member is not None:
                out.append(member)
        return out

    def subscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        from futu import RET_OK
        sym = to_futu_symbol(symbol)
        objs = self._subtype_objs(subtypes)
        if not objs:
            return False, f"no known subtypes in {subtypes!r}"
        with self._quiet():
            ret, msg = self._context().subscribe([sym], objs)
        if ret != RET_OK:
            return False, str(msg)[:160]
        self._subscribed.add(sym)
        return True, "ok"

    def unsubscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        sym = to_futu_symbol(symbol)
        objs = self._subtype_objs(subtypes)
        try:
            with self._quiet():
                self._context().unsubscribe([sym], objs)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        self._subscribed.discard(sym)
        return True, "ok"

    def query_subscription(self, is_all_conn: bool = True) -> dict:
        """SIMULTANEOUS subscription quota via ctx.query_subscription(is_all_conn=…).

        Returns {total_quota,total_used,remain,own_used,other_connection_usage,
        subscriptions_by_type}. Never raises — {} on any failure (honest 'unknown')."""
        from futu import RET_OK
        try:
            with self._quiet():
                ret, data = self._context().query_subscription(is_all_conn=is_all_conn)
        except Exception:
            return {}
        if ret != RET_OK or not isinstance(data, dict):
            return {}
        total = data.get("total_used")
        remain = data.get("remain")
        own = data.get("own_used")
        by_type = {}
        subs = data.get("sub_list") or {}
        if isinstance(subs, dict):
            for st, syms in subs.items():
                try:
                    by_type[str(st)] = len(syms)
                except TypeError:
                    continue
        total_quota = None
        try:
            if remain is not None and total is not None:
                total_quota = int(remain) + int(total)
        except (TypeError, ValueError):
            total_quota = None
        return {
            "total_quota": total_quota,
            "total_used": None if total is None else int(total),
            "remain": None if remain is None else int(remain),
            "own_used": None if own is None else int(own),
            "other_connection_usage": (None if (total is None or own is None)
                                       else max(0, int(total) - int(own))),
            "subscriptions_by_type": by_type,
        }


class MoomooTradeReader:
    """READ-ONLY account facts from the moomoo trade context. No order path, no unlock.

    Stage 0 keeps quotes and orders apart, and it must stay that way — but balances and
    positions are only reachable through OpenSecTradeContext. This class opens that
    context for `accinfo_query` / `position_list_query` ONLY. It never calls
    `unlock_trade`, never places/modifies/cancels, and mirrors MoomooClient's hard
    refusal so an order path cannot be reached through it either. Reads require no
    unlock; only order placement does.

    The REAL US account lives under SecurityFirm.FUTUINC. FUTUSECURITIES returns only
    the SIMULATE account, which reads exactly like "no live account exists" — that
    mistake is why moomoo looked unwired on 2026-07-28.
    """

    FORBIDDEN_METHODS = frozenset({
        "place_order", "modify_order", "cancel_order", "unlock_trade", "lock_trade",
        "submit_order", "execute_trade",
    })

    def __init__(self, host: str = "127.0.0.1", port: int = 11111, *, firm: str = "FUTUINC"):
        self.host, self.port, self.firm = host, int(port), firm

    def _ctx(self):
        from futu import OpenSecTradeContext, TrdMarket, SecurityFirm
        firm = getattr(SecurityFirm, self.firm, None)
        if firm is None:
            raise MoomooUnavailable(f"unknown security firm {self.firm!r}")
        return OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=self.host,
                                   port=self.port, security_firm=firm)

    def accounts(self) -> list[dict]:
        """Every account this firm exposes, with trd_env so REAL vs SIMULATE is explicit."""
        from futu import RET_OK
        with quiet_futu_logging():
            ctx = self._ctx()
            try:
                ret, df = ctx.get_acc_list()
            finally:
                ctx.close()
        if ret != RET_OK:
            raise MoomooUnavailable(f"get_acc_list failed: {str(df)[:120]}")
        return [{"acc_id": r.get("acc_id"), "trd_env": str(r.get("trd_env")),
                 "acc_type": str(r.get("acc_type")), "acc_status": str(r.get("acc_status"))}
                for _, r in df.iterrows()]

    def snapshot(self, acc_id: int) -> dict:
        """{cash, total_assets, market_val, positions:[…]} for one REAL account."""
        from futu import RET_OK, TrdEnv
        with quiet_futu_logging():
            ctx = self._ctx()
            try:
                r1, info = ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=int(acc_id), currency="USD")
                r2, pos = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=int(acc_id))
            finally:
                ctx.close()
        if r1 != RET_OK:
            raise MoomooUnavailable(f"accinfo_query failed: {str(info)[:120]}")

        def _f(v):
            try:
                f = float(v)
                return f if f == f else None
            except (TypeError, ValueError):
                return None

        row = info.iloc[0]
        positions = []
        if r2 == RET_OK and pos is not None and len(pos):
            for _, p in pos.iterrows():
                positions.append({
                    "code": str(p.get("code") or ""),
                    "qty": _f(p.get("qty")),
                    "market_val": _f(p.get("market_val")),
                    "cost_price": _f(p.get("cost_price")),
                    "nominal_price": _f(p.get("nominal_price")),
                })
        return {
            "acc_id": int(acc_id),
            "cash": _f(row.get("cash")),
            "total_assets": _f(row.get("total_assets")),
            "market_val": _f(row.get("market_val")),
            "currency": str(row.get("currency") or "USD"),
            "positions": positions,
        }

    def __getattr__(self, name):
        if name in self.FORBIDDEN_METHODS:
            raise MoomooAuthorityError(f"{name} is OUT of the read plane (order path forbidden)")
        raise AttributeError(name)


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
