"""Read-only data adapters for Phase 1 momentum alerts (operator-approved 2026-10-04).

moomoo (primary): order book, tape and snapshot time through OpenD's QUOTE context only
(scripts/moomoo/client.FutuTransport). No trade context is opened here; FutuTransport has no
order method and MoomooClient refuses place/modify/cancel/unlock.

Schwab (comparison only): the latest captured NASDAQ_BOOK row from schwab_stream_book, read
with SELECT. It is journaled beside the moomoo evidence and never decides an alert.

Every timestamp is the data's own time (exchange or capture), converted to epoch seconds, so
momentum_alerts can fail closed on staleness.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

EXCHANGE_TZ = ZoneInfo("America/New_York")


def exchange_time_to_epoch(raw: Any) -> Optional[float]:
    """'2026-10-02 16:00:00.614' (US exchange-local) → epoch seconds. Empty/invalid → None."""
    s = str(raw or "").strip()
    if not s or s.lower() in ("nan", "none", "n/a"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=EXCHANGE_TZ).timestamp()
        except ValueError:
            continue
    return None


class MoomooSource:
    """Lazily opens one FutuTransport (quote context) and reuses it for the whole pass."""

    def __init__(self, transport=None, *, levels: int = 10, prints: int = 50):
        self._t = transport
        self.levels, self.prints = int(levels), int(prints)

    def _transport(self):
        if self._t is None:
            try:
                from moomoo.client import FutuTransport
                from moomoo.config import load_stage0_config
            except ModuleNotFoundError:
                from scripts.moomoo.client import FutuTransport
                from scripts.moomoo.config import load_stage0_config
            cfg = load_stage0_config()
            self._t = FutuTransport(cfg.host, cfg.port, timeout=cfg.connect_timeout_seconds or 4.0)
        return self._t

    def book(self, symbol: str, *, now: Optional[float] = None) -> Optional[dict]:
        import time as _time
        fetched = _time.time() if now is None else now
        b = self._transport().get_order_book(symbol, levels=self.levels)
        times = [exchange_time_to_epoch(b.get("svr_recv_time_bid")),
                 exchange_time_to_epoch(b.get("svr_recv_time_ask"))]
        times = [t for t in times if t is not None]
        # OpenD keeps a subscribed book current by push, but returned an empty server receive
        # time on 2026-10-04 (weekend). Prefer the server time; otherwise fall back to the fetch
        # time and SAY so (ts_source=fetch). TRIGGERED still needs a fresh exchange-stamped tape.
        if times:
            return {"bids": b.get("bids") or [], "asks": b.get("asks") or [],
                    "ts_epoch": min(times), "ts_source": "opend_server"}
        return {"bids": b.get("bids") or [], "asks": b.get("asks") or [],
                "ts_epoch": fetched, "ts_source": "fetch"}

    def tape(self, symbol: str) -> list[dict]:
        rows = self._transport().get_ticker(symbol, num=self.prints)
        return [{"ts_epoch": exchange_time_to_epoch(r.get("time")), "price": r.get("price"),
                 "volume": r.get("volume"), "direction": r.get("direction")} for r in rows]

    def quote(self, symbol: str) -> tuple[Optional[float], Optional[float]]:
        q = self._transport().get_snapshot_time(symbol)
        try:
            last = float(q.get("last"))
        except (TypeError, ValueError):
            last = None
        return last, exchange_time_to_epoch(q.get("update_time"))

    def bars_1m(self, symbol: str, num: int = 500) -> list[dict]:
        """Today's 1-min K-lines incl. extended hours and the FORMING bar, normalized to bar START.
        moomoo labels a 1-min bar by its END (verified 2026-10-05 16:25:27 ET: newest time_key was
        16:26:00), so start = time_key − 60 s. Quote context only. Producer: the microstructure
        recorder; consumers read its store, never this method (operator rule 2026-10-05)."""
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _Z
        from futu import KLType, SubType
        ctx = self._transport()._context()
        code = f"US.{symbol.upper()}"
        subs = getattr(self, "_kl", None)
        if subs is None:
            subs = self._kl = set()
        if code not in subs:
            ret, msg = ctx.subscribe([code], [SubType.K_1M], subscribe_push=False, extended_time=True)
            if ret != 0:
                raise RuntimeError(f"K_1M subscribe refused for {symbol}: {str(msg)[:120]}")
            subs.add(code)
        ret, df = ctx.get_cur_kline(code, num=num, ktype=KLType.K_1M)
        if ret != 0:
            raise RuntimeError(f"get_cur_kline failed for {symbol}: {str(df)[:120]}")
        et = _Z("America/New_York")
        out = []
        for r in df[["time_key", "open", "high", "low", "close", "volume"]].to_dict("records"):
            end = _dt.strptime(str(r["time_key"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=et).timestamp()
            out.append({"s": end - 60.0, "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                        "c": float(r["close"]), "v": float(r["volume"] or 0)})
        return out

    def close(self) -> None:
        if getattr(self, "_kl", None):
            try:
                from futu import SubType
                self._t._context().unsubscribe(list(self._kl), [SubType.K_1M])
            except Exception:  # noqa: BLE001 — OpenD drops subscriptions with the connection anyway
                pass
        if self._t is not None:
            try:
                self._t.close()
            except Exception:  # noqa: BLE001
                pass


def schwab_book_fetcher(conn) -> Callable[[str], Optional[dict]]:
    """Latest schwab_stream_book row for a symbol (SELECT only)."""
    def _fetch(symbol: str) -> Optional[dict]:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT bid_levels, ask_levels, extract(epoch from captured_at)
                   FROM schwab_stream_book WHERE symbol=%s ORDER BY captured_at DESC LIMIT 1""",
                [symbol.upper()])
            row = cur.fetchone()
        if not row:
            return None
        def _pairs(levels):
            return [(lv.get("price"), lv.get("size")) for lv in (levels or []) if isinstance(lv, dict)]
        return {"bids": _pairs(row[0]), "asks": _pairs(row[1]),
                "ts_epoch": float(row[2]) if row[2] is not None else None}
    return _fetch


def float_lookup(conn) -> Callable[[str], Optional[float]]:
    """Most recent float (millions) from scalp_scan_results (SELECT only)."""
    def _f(symbol: str) -> Optional[float]:
        with conn.cursor() as cur:
            cur.execute("""SELECT float_mm FROM scalp_scan_results WHERE symbol=%s AND float_mm IS NOT NULL
                           ORDER BY scanned_at DESC LIMIT 1""", [symbol.upper()])
            row = cur.fetchone()
        try:
            return float(row[0]) if row else None
        except (TypeError, ValueError):
            return None
    return _f
