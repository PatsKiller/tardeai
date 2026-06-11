#!/usr/bin/env python3
"""schwab_stream_daemon.py — READ-ONLY Schwab streaming capture (Level-1 quotes + Level-2 book).

Rule-9 ISOLATION (operator governance): this daemon is a standalone process with its own tables
(schwab_stream_quotes / schwab_stream_book). It imports NOTHING from, and is imported BY nothing in, the
screener / GO-WAIT / ATM / proposal-generation path. Proposals may later READ the derived book-pressure
metrics via the read-only API as additive evidence — never as an execution trigger.

Safety: market-data subscriptions ONLY (LEVELONE_EQUITIES + NASDAQ_BOOK). No account/order streams. The
Schwab write fence (validate_schwab_no_writes 12/12) is untouched — streaming uses the same read-only client.

Symbols (no hardcoding): union of open paper positions + active PENDING proposals + active directive symbols,
capped via STREAM_MAX_SYMBOLS (env, default 12). Kill switch: data/state/STREAM_DISABLED file.

  .venv/bin/python scripts/schwab_stream_daemon.py --max-seconds 90      # spike/test run
  .venv/bin/python scripts/schwab_stream_daemon.py                       # run until market close / kill switch
"""
import argparse
import asyncio
import json
import os
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

KILL_FILE = ROOT / "data" / "state" / "STREAM_DISABLED"
FLUSH_EVERY = 5.0          # seconds between DB flushes
BOOK_TOP_N = 5             # book levels persisted per side


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _symbols(limit):
    """Union: open paper positions + PENDING proposals + active ticker directives. Config/DB-driven."""
    syms = []
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("SELECT DISTINCT symbol FROM paper_trades WHERE status IN ('open','pending')")
        syms += [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT symbol FROM paper_trade_proposals WHERE status='PENDING' AND created_at > NOW()-INTERVAL '48 hours'")
        syms += [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT UPPER(spec->>'symbol') FROM watch_directives WHERE status='active' AND spec ? 'symbol'")
        syms += [r[0] for r in cur.fetchall() if r[0]]
    except Exception as e:
        print(f"[stream] symbol query degraded: {e}")
    out = sorted({s for s in syms if s and s.isalpha()})[: limit]
    return out


def _market_open():
    """Authoritative market-hours via the newly wired read (falls back open=True on error to let the
    connection itself decide)."""
    try:
        import schwab_transport
        h = schwab_transport.get_market_hours()
        eq = (h.get("markets") or {}).get("equity") or {}
        return bool(eq.get("is_open", True))
    except Exception:
        return True


class Capture:
    def __init__(self):
        self.quotes = {}      # symbol -> latest L1 dict
        self.books = {}       # symbol -> latest book dict
        self.q_writes = 0
        self.b_writes = 0
        self.msgs = 0

    def on_l1(self, msg):
        self.msgs += 1
        for c in msg.get("content", []):
            sym = c.get("key")
            if not sym:
                continue
            q = self.quotes.setdefault(sym, {})
            # schwab-py LEVELONE_EQUITIES numeric field names
            for k_src, k_dst in (("LAST_PRICE", "last"), ("BID_PRICE", "bid"), ("ASK_PRICE", "ask"),
                                 ("BID_SIZE", "bid_size"), ("ASK_SIZE", "ask_size"), ("TOTAL_VOLUME", "volume")):
                if c.get(k_src) is not None:
                    q[k_dst] = c[k_src]

    def on_book(self, msg, venue):
        self.msgs += 1
        for c in msg.get("content", []):
            sym = c.get("key")
            if not sym:
                continue
            bids = [{"price": l.get("BID_PRICE") or l.get("price"), "size": l.get("TOTAL_VOLUME") or l.get("size"),
                     "mm_count": l.get("NUM_BIDS") or l.get("num")} for l in (c.get("BIDS") or [])[:BOOK_TOP_N]]
            asks = [{"price": l.get("ASK_PRICE") or l.get("price"), "size": l.get("TOTAL_VOLUME") or l.get("size"),
                     "mm_count": l.get("NUM_ASKS") or l.get("num")} for l in (c.get("ASKS") or [])[:BOOK_TOP_N]]
            bd = sum(float(b["size"] or 0) for b in bids)
            ad = sum(float(a["size"] or 0) for a in asks)
            imb = round((bd - ad) / (bd + ad), 4) if (bd + ad) > 0 else None
            self.books[sym] = {"venue": venue, "bid_depth": bd, "ask_depth": ad, "imbalance": imb,
                               "best_bid": (bids[0]["price"] if bids else None),
                               "best_ask": (asks[0]["price"] if asks else None),
                               "bid_levels": bids, "ask_levels": asks}

    def flush(self, conn):
        cur = conn.cursor()
        for sym, q in self.quotes.items():
            if not q:
                continue
            cur.execute("""INSERT INTO schwab_stream_quotes (symbol,last,bid,ask,bid_size,ask_size,volume)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (sym, q.get("last"), q.get("bid"), q.get("ask"),
                         q.get("bid_size"), q.get("ask_size"), q.get("volume")))
            self.q_writes += 1
        for sym, b in self.books.items():
            cur.execute("""INSERT INTO schwab_stream_book
                (symbol,venue,bid_depth,ask_depth,imbalance,best_bid,best_ask,bid_levels,ask_levels)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (sym, b["venue"], b["bid_depth"], b["ask_depth"], b["imbalance"],
                         b["best_bid"], b["best_ask"], json.dumps(b["bid_levels"]), json.dumps(b["ask_levels"])))
            self.b_writes += 1
        conn.commit()


async def run(max_seconds=None):
    if KILL_FILE.exists():
        print("[stream] STREAM_DISABLED kill switch present — exiting"); return 0
    if not _market_open():
        print("[stream] market closed — exiting"); return 0
    limit = int(os.getenv("STREAM_MAX_SYMBOLS", "12"))
    syms = _symbols(limit)
    if not syms:
        print("[stream] no symbols (no open positions/proposals/directives) — exiting"); return 0
    print(f"[stream] symbols: {syms}")

    import schwab_transport
    sc, err = schwab_transport.build_stream_client()   # schwab-py stays behind the transport boundary
    if err:
        print(f"[stream] client error: {err}"); return 1

    cap = Capture()
    await sc.login()
    sc.add_level_one_equity_handler(cap.on_l1)
    sc.add_nasdaq_book_handler(lambda m: cap.on_book(m, "NASDAQ_BOOK"))
    await sc.level_one_equity_subs(syms)
    await sc.nasdaq_book_subs(syms)
    print("[stream] subscribed (L1 + NASDAQ book) — read-only market data")

    conn = _conn()
    started = dt.datetime.now(dt.timezone.utc)
    last_flush = started
    while True:
        try:
            await asyncio.wait_for(sc.handle_message(), timeout=10)
        except asyncio.TimeoutError:
            pass
        now = dt.datetime.now(dt.timezone.utc)
        if (now - last_flush).total_seconds() >= FLUSH_EVERY:
            cap.flush(conn); last_flush = now
        if KILL_FILE.exists():
            print("[stream] kill switch — stopping"); break
        if max_seconds and (now - started).total_seconds() > max_seconds:
            print("[stream] max runtime reached — stopping"); break
        if (now - started).total_seconds() % 600 < 1 and not _market_open():
            print("[stream] market closed — stopping"); break
    cap.flush(conn)
    print(json.dumps({"messages": cap.msgs, "quote_rows": cap.q_writes, "book_rows": cap.b_writes,
                      "symbols": syms, "ran_seconds": round((dt.datetime.now(dt.timezone.utc)-started).total_seconds())}))
    try:
        await sc.logout()
    except Exception:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seconds", type=int, default=None)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(run(a.max_seconds)))


if __name__ == "__main__":
    main()
