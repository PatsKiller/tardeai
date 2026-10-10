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

Session window (2026-10-09, operator "fix"): the daemon captures only while the US equity session named in
STREAM_SESSIONS (env, comma list of market_session sessions, default "regular") is in progress. The window
(open/close, holidays, 13:00 early closes) comes from scripts/market_session.py — the repo's one session
calendar — and the Schwab market-hours read can only veto (is_open false). Before this, the gate was Schwab's
whole-day isOpen flag, which stays true after 16:00, so the daemon streamed until ~20:45 ET and wrote ~15.6k
rows/hour of unchanged quotes after the close. Quote rows are also deduped in process: a symbol whose
(last,bid,ask,bid_size,ask_size,volume) equals the last row written for it is not re-inserted.

Receipt: every run writes data/state/schwab_stream_receipt.json (latest; persistent-state root when present)
and appends to schwab_stream_runs.jsonl — start, heartbeat each minute, stop reason, rows written/skipped.

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


def _stream_sessions():
    """Sessions the daemon captures (config: STREAM_SESSIONS, default regular hours only)."""
    raw = os.getenv("STREAM_SESSIONS", "regular")
    out = {x.strip().lower() for x in raw.split(",") if x.strip()}
    return out or {"regular"}


def _in_session(now=None, sessions=None):
    """True while the configured session window is in progress (market_session calendar: weekends,
    NYSE holidays and early closes included). Local and cheap — checked every loop iteration."""
    import market_session
    return market_session.current_market_session(now) in (sessions or _stream_sessions())


def _schwab_is_open():
    """Schwab market-hours whole-day isOpen flag. It stays true after the 16:00 close, so it can only
    veto a day (holiday / unscheduled closure), never keep the stream running. Error → True (no veto)."""
    try:
        import schwab_transport
        h = schwab_transport.get_market_hours()
        eq = (h.get("markets") or {}).get("equity") or {}
        return bool(eq.get("is_open", True))
    except Exception:
        return True


def _market_open(now=None):
    """Capture allowed: inside the configured session window AND Schwab does not say the day is closed."""
    return _in_session(now) and _schwab_is_open()


def _receipt_dir() -> Path:
    env = os.getenv("STREAM_RECEIPT_DIR", "").strip()
    if env:
        return Path(env)
    persistent = Path.home() / "trade-ai-releases" / "persistent-state"
    if (persistent / "PERSISTENT_STATE_ROOT.json").is_file():
        return persistent / "data" / "state"
    return ROOT / "data" / "state"


def _write_receipt(rec, *, final=False, dirpath=None):
    """Latest-run receipt (atomic replace) + one jsonl line at start and stop. Never raises."""
    try:
        d = dirpath or _receipt_dir()
        d.mkdir(parents=True, exist_ok=True)
        rec = {**rec, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        tmp = d / "schwab_stream_receipt.json.tmp"
        tmp.write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")
        os.replace(tmp, d / "schwab_stream_receipt.json")
        if final or (rec.get("status") == "running" and rec.get("heartbeats", 0) == 0):
            with open(d / "schwab_stream_runs.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
    except Exception as e:
        print(f"[stream] receipt write failed ({e})")


class Capture:
    def __init__(self):
        self.quotes = {}      # symbol -> latest L1 dict
        self.books = {}       # symbol -> latest book dict
        self.q_writes = 0
        self.q_skipped = 0    # unchanged quotes not re-inserted
        self.b_writes = 0
        self._last_q = {}     # symbol -> last written quote tuple
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
            key = (q.get("last"), q.get("bid"), q.get("ask"), q.get("bid_size"), q.get("ask_size"), q.get("volume"))
            if self._last_q.get(sym) == key:
                self.q_skipped += 1
                continue
            cur.execute("""INSERT INTO schwab_stream_quotes (symbol,last,bid,ask,bid_size,ask_size,volume)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (sym, q.get("last"), q.get("bid"), q.get("ask"),
                         q.get("bid_size"), q.get("ask_size"), q.get("volume")))
            self.q_writes += 1
            self._last_q[sym] = key
        for sym, b in self.books.items():
            cur.execute("""INSERT INTO schwab_stream_book
                (symbol,venue,bid_depth,ask_depth,imbalance,best_bid,best_ask,bid_levels,ask_levels)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (sym, b["venue"], b["bid_depth"], b["ask_depth"], b["imbalance"],
                         b["best_bid"], b["best_ask"], json.dumps(b["bid_levels"]), json.dumps(b["ask_levels"])))
            self.b_writes += 1
        conn.commit()


def _stop(rec, reason, cap=None, rc=0):
    if cap is not None:
        rec.update({"messages": cap.msgs, "quote_rows": cap.q_writes, "quote_rows_skipped_unchanged": cap.q_skipped,
                    "book_rows": cap.b_writes})
    rec.update({"status": "stopped", "stop_reason": reason, "rc": rc,
                "stopped_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    _write_receipt(rec, final=True)
    return rc


async def run(max_seconds=None):
    rec = {"pid": os.getpid(), "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "sessions": sorted(_stream_sessions()), "status": "starting", "heartbeats": 0}
    if KILL_FILE.exists():
        print("[stream] STREAM_DISABLED kill switch present — exiting"); return _stop(rec, "kill_switch")
    if not _market_open():
        print("[stream] market closed — exiting"); return _stop(rec, "outside_session")
    limit = int(os.getenv("STREAM_MAX_SYMBOLS", "12"))
    scalp_limit = int(os.getenv("STREAM_MAX_SCALP_SYMBOLS", "10"))
    resub_s = float(os.getenv("STREAM_RESUBSCRIBE_S", "180"))
    syms = _union(_symbols(limit), _scalp_symbols(scalp_limit))
    if not syms:
        print("[stream] no symbols (no open positions/proposals/directives/scalp names) — exiting")
        return _stop(rec, "no_symbols")
    print(f"[stream] symbols: {syms}")

    import schwab_transport
    sc, err = schwab_transport.build_stream_client()   # schwab-py stays behind the transport boundary
    if err:
        print(f"[stream] client error: {err}"); return _stop(rec, "client_error", rc=1)

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
    last_hb = started
    rec.update({"status": "running", "symbols": syms})
    _write_receipt(rec)
    reason = "unknown"
    while True:
        try:
            await asyncio.wait_for(sc.handle_message(), timeout=10)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            # websocket drop / decode error: return 1 so supervise() reconnects while the market is open
            print(f"[stream] stream error ({e}) — returning for reconnect")
            cap.flush(conn)
            return _stop(rec, "stream_error", cap, rc=1)
        now = dt.datetime.now(dt.timezone.utc)
        if not _in_session(now):   # local session clock every iteration — stop at the close, not 10 min late
            print("[stream] session window ended — stopping"); reason = "session_end"; break
        if (now - last_flush).total_seconds() >= FLUSH_EVERY:
            cap.flush(conn); last_flush = now
        if (now - last_hb).total_seconds() >= 60:
            last_hb = now
            rec.update({"heartbeats": rec["heartbeats"] + 1, "symbols": syms, "messages": cap.msgs,
                        "quote_rows": cap.q_writes, "quote_rows_skipped_unchanged": cap.q_skipped,
                        "book_rows": cap.b_writes})
            _write_receipt(rec)
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
            print("[stream] kill switch — stopping"); reason = "kill_switch"; break
        if max_seconds and (now - started).total_seconds() > max_seconds:
            print("[stream] max runtime reached — stopping"); reason = "max_seconds"; break
        if (now - last_mh_check).total_seconds() >= 600:   # Schwab day-closed veto, every 10 min
            last_mh_check = now
            if not _market_open(now):
                print("[stream] market closed — stopping"); reason = "market_closed"; break
    cap.flush(conn)
    print(json.dumps({"messages": cap.msgs, "quote_rows": cap.q_writes, "quote_rows_skipped_unchanged": cap.q_skipped,
                      "book_rows": cap.b_writes, "symbols": syms,
                      "ran_seconds": round((dt.datetime.now(dt.timezone.utc)-started).total_seconds())}))
    try:
        await sc.logout()
    except Exception:
        pass
    return _stop(rec, reason, cap)


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
