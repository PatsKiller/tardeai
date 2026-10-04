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

    def close(self) -> None:
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
