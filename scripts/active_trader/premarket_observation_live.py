"""Stage 5 harness — LIVE data-only capture (authorized sessions only).

Reuses the proven smoke wiring (secret_render -> OpenD -> OpenQuoteContext, NOT a trade
context) plus SDK push handlers to capture QUOTE / K_1M(ext) / ORDER_BOOK(detailed) /
TICKER(ext) into a checksummed WAL, then compacts to zstd Parquet, replays, and evaluates
the three observation verdicts. DATA ONLY: no trade context/account/order/unlock, no real
2FA, no quote-right grab (auto_hold_quote_right=0). Imported only on the live path.

This module is NOT part of the deterministic test surface (it imports the moomoo SDK). It is
exercised by a short operator-run validation and by the scheduled Session capture.
"""
from __future__ import annotations

import datetime as _dt
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from active_trader.moomoo import replay as _replay
from active_trader import premarket_observation as po

_TZ = ZoneInfo("America/New_York")


def _now_et() -> _dt.datetime:
    return _dt.datetime.now(_TZ)


def _et_seconds(dt: _dt.datetime) -> float:
    d = dt.astimezone(_TZ)
    return d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6


class _Sink:
    """Thread-safe collector: SDK recv threads push here; the main thread reads."""

    def __init__(self, session_id: str, wal_path: Path, symbols: dict):
        self._lock = threading.Lock()
        self.events: list[po.ObservationEvent] = []
        self._wal = _replay.WALWriter(wal_path)
        self.session_id = session_id
        self.roles = symbols                     # {symbol: "BASELINE"|"REPRESENTATIVE"}
        self._seen_first: set = set()
        self.counts: dict = {}

    def push(self, stream: str, symbol: str, fields: dict) -> None:
        now = _now_et()
        key = (stream, symbol)
        first = key not in self._seen_first
        with self._lock:
            if first:
                self._seen_first.add(key)
            self.counts[stream] = self.counts.get(stream, 0) + 1
            ev = po.ObservationEvent(
                observation_session_id=self.session_id, symbol=symbol,
                symbol_role=self.roles.get(symbol, "BASELINE"), stream=stream,
                receive_ts=now, provider_timestamp=fields.get("provider_ts"),
                server_bid_timestamp=fields.get("svr_bid_ts"),
                server_ask_timestamp=fields.get("svr_ask_ts"),
                ingest_timestamp=now.isoformat(),
                cached_first_push=first,
                freshness_state=(po.Freshness.CACHED_FIRST_PUSH.value if first else po.Freshness.FRESH.value),
                market_state=fields.get("market_state"),
                bid=fields.get("bid"), ask=fields.get("ask"),
                bid_size=fields.get("bid_size"), ask_size=fields.get("ask_size"),
                bids=fields.get("bids"), asks=fields.get("asks"),
                last=fields.get("last"), trade_size=fields.get("trade_size"))
            self.events.append(ev)
            self._wal.append({
                "stream": stream, "symbol": symbol, "role": ev.symbol_role,
                "receive_ts": now.isoformat(), "t": _et_seconds(now),
                "provider_timestamp": ev.provider_timestamp,
                "server_bid_timestamp": ev.server_bid_timestamp,
                "server_ask_timestamp": ev.server_ask_timestamp,
                "cached_first_push": first, "freshness_state": ev.freshness_state,
                "market_state": ev.market_state, "bid": ev.bid, "ask": ev.ask,
                "bid_size": ev.bid_size, "ask_size": ev.ask_size,
                "bids": ev.bids, "asks": ev.asks, "last": ev.last, "trade_size": ev.trade_size,
                "gateway_receive_timestamp": now.isoformat()})

    def close(self):
        with self._lock:
            self._wal.close()


# ---- SDK push handlers (parse defensively; shapes verified live) ------------

def _make_handlers(sink: _Sink):  # pragma: no cover (live only)
    from moomoo import (RET_OK, OrderBookHandlerBase, StockQuoteHandlerBase,
                        TickerHandlerBase, CurKlineHandlerBase)

    def _rows(data):
        if data is None:
            return []
        if hasattr(data, "to_dict"):
            return data.to_dict("records")
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        return []

    class Book(OrderBookHandlerBase):
        def on_recv_rsp(self, rsp):
            ret, data = super().on_recv_rsp(rsp)
            if ret == RET_OK and isinstance(data, dict):
                code = data.get("code")
                bids = [(b[0], b[1]) for b in (data.get("Bid") or [])]
                asks = [(a[0], a[1]) for a in (data.get("Ask") or [])]
                sink.push("ORDER_BOOK", code, {
                    "bid": bids[0][0] if bids else None, "ask": asks[0][0] if asks else None,
                    "bid_size": bids[0][1] if bids else None, "ask_size": asks[0][1] if asks else None,
                    "bids": bids, "asks": asks,
                    "svr_bid_ts": data.get("svr_recv_time_bid"),
                    "svr_ask_ts": data.get("svr_recv_time_ask")})
            return ret, data

    class Quote(StockQuoteHandlerBase):
        def on_recv_rsp(self, rsp):
            ret, data = super().on_recv_rsp(rsp)
            if ret == RET_OK:
                for r in _rows(data):
                    g = lambda *ks: next((r[k] for k in ks if k in r and r[k] is not None), None)
                    sink.push("QUOTE", r.get("code"), {
                        "bid": g("bid_price", "bidPrice", "bid"),
                        "ask": g("ask_price", "askPrice", "ask"),
                        "bid_size": g("bid_vol", "bidVol", "bid_size"),
                        "ask_size": g("ask_vol", "askVol", "ask_size"),
                        "last": g("last_price", "cur_price", "price"),
                        "provider_ts": g("data_time", "update_time", "data_date"),
                        "market_state": g("sec_status", "data_status")})
            return ret, data

    class Ticker(TickerHandlerBase):
        def on_recv_rsp(self, rsp):
            ret, data = super().on_recv_rsp(rsp)
            if ret == RET_OK:
                for r in _rows(data):
                    sink.push("TICKER", r.get("code"), {
                        "last": r.get("price"), "trade_size": r.get("volume"),
                        "provider_ts": r.get("time")})
            return ret, data

    class Kline(CurKlineHandlerBase):
        def on_recv_rsp(self, rsp):
            ret, data = super().on_recv_rsp(rsp)
            if ret == RET_OK:
                for r in _rows(data):
                    sink.push("K_1M", r.get("code"), {
                        "last": r.get("close"), "trade_size": r.get("volume"),
                        "provider_ts": r.get("time_key")})
            return ret, data

    return Book(), Quote(), Ticker(), Kline()


@dataclass
class CaptureResult:
    result: str
    session_id: str
    symbols: dict
    counts: dict
    event_count: int
    wal_path: str
    parquet_verified: bool = False
    parquet_row_count: int = 0
    safety: dict = field(default_factory=lambda: {
        "trade_context": False, "trade_call": False, "account_query": False, "auto_grab": False})


def capture(*, session_id: str, symbols: dict, end_et: _dt.datetime, out_dir: Path,
            poll_seconds: float = 1.0, max_seconds: float | None = None) -> CaptureResult:  # pragma: no cover (live)
    """Data-only continuous capture until end_et (ET). Always tears down."""
    from active_trader.moomoo import secret_render
    from moomoo import OpenQuoteContext, RET_OK, SubType, Session

    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    wal = out_dir / f"{session_id}.wal"
    sink = _Sink(session_id, wal, symbols)
    proc = ctx = None
    started = time.monotonic()
    try:
        secrets = secret_render.load_data_secrets()
        cfg = secret_render.render_opend_config(secrets)
        proc = secret_render.start_opend(cfg)
        # wait for loopback
        import socket
        for _ in range(50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", secret_render.API_PORT)) == 0:
                    break
            time.sleep(0.5)
        ctx = OpenQuoteContext(host="127.0.0.1", port=secret_render.API_PORT)
        gret, _ = ctx.get_global_state()
        book, quote, ticker, kline = _make_handlers(sink)
        ctx.set_handler(book); ctx.set_handler(quote); ctx.set_handler(ticker); ctx.set_handler(kline)
        codes = list(symbols.keys())
        session_all = Session.ALL
        # QUOTE (normal), K_1M (ext), ORDER_BOOK (detailed), TICKER (ext)
        ctx.subscribe(codes, [SubType.QUOTE], is_first_push=True, subscribe_push=True)
        try:
            ctx.subscribe(codes, [SubType.K_1M], is_first_push=True, subscribe_push=True,
                          extended_time=True, session=session_all)
            ctx.subscribe(codes, [SubType.TICKER], is_first_push=True, subscribe_push=True,
                          extended_time=True, session=session_all)
        except TypeError:
            ctx.subscribe(codes, [SubType.K_1M, SubType.TICKER], is_first_push=True, subscribe_push=True)
        ctx.subscribe(codes, [SubType.ORDER_BOOK], is_first_push=True, subscribe_push=True,
                      is_detailed_orderbook=True)
        # capture loop
        while _now_et() < end_et:
            if max_seconds and (time.monotonic() - started) >= max_seconds:
                break
            time.sleep(poll_seconds)
        # unsubscribe
        for st in (SubType.QUOTE, SubType.K_1M, SubType.ORDER_BOOK, SubType.TICKER):
            try:
                ctx.unsubscribe(codes, [st])
            except Exception:
                pass
        sink.close()
        # compact + verify
        pv, prc = False, 0
        try:
            res = _replay.compact_to_parquet(wal, out_dir / f"{session_id}.parquet")
            pv, prc = res.verified, res.row_count
        except Exception:
            pass
        return CaptureResult("CAPTURE_OK", session_id, symbols, dict(sink.counts),
                             len(sink.events), str(wal), pv, prc)
    finally:
        try:
            sink.close()
        except Exception:
            pass
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass
        if proc is not None:
            # OpenD is started with start_new_session=True (own process group) and ignores
            # SIGTERM, so terminate() alone leaves it running. Kill the whole group by pgid.
            import os, signal
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass
            try:
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            secret_render.cleanup()
        except Exception:
            pass


def events_from_wal(wal_path: Path) -> list:
    """Rebuild ObservationEvents from the WAL (for post-capture evaluate + replay-equality)."""
    from active_trader.moomoo import replay as rp
    out = []
    for r in rp.wal_read(Path(wal_path)):
        rts = _dt.datetime.fromisoformat(r["receive_ts"])
        out.append(po.ObservationEvent(
            observation_session_id=r.get("role") and "live" or "live", symbol=r["symbol"],
            symbol_role=r.get("role", "BASELINE"), stream=r["stream"], receive_ts=rts,
            provider_timestamp=r.get("provider_timestamp"),
            server_bid_timestamp=r.get("server_bid_timestamp"),
            server_ask_timestamp=r.get("server_ask_timestamp"),
            cached_first_push=bool(r.get("cached_first_push")),
            freshness_state=r.get("freshness_state", po.Freshness.FRESH.value),
            market_state=r.get("market_state"),
            bid=r.get("bid"), ask=r.get("ask"), bid_size=r.get("bid_size"), ask_size=r.get("ask_size"),
            bids=[tuple(x) for x in r["bids"]] if r.get("bids") else None,
            asks=[tuple(x) for x in r["asks"]] if r.get("asks") else None,
            last=r.get("last"), trade_size=r.get("trade_size")))
    return out
