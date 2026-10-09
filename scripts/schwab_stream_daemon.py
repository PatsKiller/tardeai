#!/usr/bin/env python3
"""schwab_stream_daemon.py — READ-ONLY Schwab streaming capture (Level-1 quotes + Level-2 book).

Rule-9 ISOLATION (operator governance): this daemon is a standalone process with its own tables
(schwab_stream_quotes / schwab_stream_book). It imports NOTHING from, and is imported BY nothing in, the
screener / GO-WAIT / ATM / proposal-generation path. Proposals may later READ the derived book-pressure
metrics via the read-only API as additive evidence — never as an execution trigger.

Safety: market-data subscriptions ONLY (LEVELONE_EQUITIES + NASDAQ_BOOK). No account/order streams. The
Schwab write fence (validate_schwab_no_writes 12/12) is untouched — streaming uses the same read-only client.

Symbols (no hardcoding): union of open paper positions + active PENDING proposals + active directive symbols,
capped via STREAM_MAX_SYMBOLS (env, default 12), PLUS the momentum-scalp names the Active Trader
microstructure recorder is watching (its live_symbols.json file, capped via STREAM_MAX_SCALP_SYMBOLS, default
10). The scalp list is re-read every STREAM_RESUBSCRIBE_S (default 180) and new names are added to the
L1 + NASDAQ book subscriptions (2026-10-05: scalp names were never subscribed, so the Schwab comparison book
was missing on every alert). Reading a JSON file keeps Rule-9 isolation: nothing is imported from the engine.
Kill switch: data/state/STREAM_DISABLED file.

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


def _scalp_symbols_path() -> Path:
    env = os.getenv("ACTIVE_TRADER_ALERTS_DIR", "").strip()
    if env:
        return Path(env) / "micro" / "live_symbols.json"
    persistent = Path.home() / "trade-ai-releases" / "persistent-state"
    if (persistent / "PERSISTENT_STATE_ROOT.json").is_file():
        return persistent / "data" / "active_trader" / "micro" / "live_symbols.json"
    return ROOT / "data" / "active_trader" / "micro" / "live_symbols.json"


def _scalp_symbols(limit, *, now=None, path=None, max_age_s=None):
    """The recorder's live scalp list; a stale or missing file contributes nothing."""
    p = path or _scalp_symbols_path()
    max_age_s = float(os.getenv("STREAM_SCALP_SYMBOLS_MAX_AGE_S", "900")) if max_age_s is None else max_age_s
    now = dt.datetime.now(dt.timezone.utc).timestamp() if now is None else now
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if now - float(d.get("ts_epoch") or 0) > max_age_s:
        return []
    return [s for s in (d.get("symbols") or []) if isinstance(s, str) and s.isalpha()][: limit]


def _union(base, scalp):
    out = list(base)
    for s in scalp:
        if s not in out:
            out.append(s)
    return out


async def _add_subscriptions(sc, new_syms):
    """Add symbols to the running L1 + NASDAQ book subscriptions (schwab-py *_add keeps the
    existing set; *_subs would replace it, so it is never used here)."""
    await sc.level_one_equity_add(new_syms)
    await sc.nasdaq_book_add(new_syms)


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
    scalp_limit = int(os.getenv("STREAM_MAX_SCALP_SYMBOLS", "10"))
    resub_s = float(os.getenv("STREAM_RESUBSCRIBE_S", "180"))
    syms = _union(_symbols(limit), _scalp_symbols(scalp_limit))
    if not syms:
        print("[stream] no symbols (no open positions/proposals/directives/scalp names) — exiting"); return 0
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
    last_mh_check = started
    last_resub = started
    while True:
        try:
            await asyncio.wait_for(sc.handle_message(), timeout=10)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            # websocket drop / decode error: return 1 so supervise() reconnects while the market is open
            print(f"[stream] stream error ({e}) — returning for reconnect")
            cap.flush(conn)
            return 1
        now = dt.datetime.now(dt.timezone.utc)
        if (now - last_flush).total_seconds() >= FLUSH_EVERY:
            cap.flush(conn); last_flush = now
        if (now - last_resub).total_seconds() >= resub_s:
            last_resub = now
            new = [x for x in _scalp_symbols(scalp_limit) if x not in syms]
            if new:
                try:
                    await _add_subscriptions(sc, new)
                    syms = syms + new
                    print(f"[stream] added scalp symbols: {new}")
                except Exception as e:
                    print(f"[stream] add subscription failed ({e}) — keeping {len(syms)} symbols")
        if KILL_FILE.exists():
            print("[stream] kill switch — stopping"); break
        if max_seconds and (now - started).total_seconds() > max_seconds:
            print("[stream] max runtime reached — stopping"); break
        if (now - last_mh_check).total_seconds() >= 600:   # reliable every-10-min close check
            last_mh_check = now
            if not _market_open():
                print("[stream] market closed — stopping"); break
    cap.flush(conn)
    print(json.dumps({"messages": cap.msgs, "quote_rows": cap.q_writes, "book_rows": cap.b_writes,
                      "symbols": syms, "ran_seconds": round((dt.datetime.now(dt.timezone.utc)-started).total_seconds())}))
    try:
        await sc.logout()
    except Exception:
        pass
    return 0


def supervise(run_once, market_open, sleep, max_restarts: int, backoff_s: float, backoff_cap_s: float = 300.0) -> int:
    """Reconnect after a stream drop while the market is open.

    2026-10-09: the cron line starts this daemon once at 09:31 and nothing restarts it (the "systemd
    Restart=on-failure" the drop message relied on was never installed), so one websocket drop ended capture
    for the day — 10-06 had no stream rows after 09:xx. run_once returns 1 on a drop / client error.
    """
    rc, restarts, wait = run_once(), 0, backoff_s
    while rc == 1 and restarts < max_restarts and market_open():
        restarts += 1
        print(f"[stream] reconnect {restarts}/{max_restarts} in {wait:.0f}s")
        sleep(wait)
        if not market_open():
            break
        rc = run_once()
        wait = min(wait * 2, backoff_cap_s)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seconds", type=int, default=None)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)   # the cron log otherwise shows nothing until exit
    except Exception:
        pass
    import time

    raise SystemExit(supervise(lambda: asyncio.run(run(a.max_seconds)), _market_open, time.sleep,
                               int(os.getenv("STREAM_MAX_RESTARTS", "20")),
                               float(os.getenv("STREAM_RESTART_BACKOFF_S", "30"))))


if __name__ == "__main__":
    main()
