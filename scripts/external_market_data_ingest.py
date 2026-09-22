#!/usr/bin/env python3
"""external_market_data_ingest.py — yfinance + Alpha Vantage + FRED data ingestion.

Sources:
  yfinance: real-time quotes, dividends, earnings dates (no API key)
  Alpha Vantage: fundamentals, company overview (free key)
  FRED: macro economic series (free key, optional)

Usage:
    python3 scripts/external_market_data_ingest.py --test
    python3 scripts/external_market_data_ingest.py --quotes          # yfinance quotes for all symbols
    python3 scripts/external_market_data_ingest.py --fundamentals    # Alpha Vantage fundamentals
    python3 scripts/external_market_data_ingest.py --fred            # FRED macro snapshot
    python3 scripts/external_market_data_ingest.py --all             # Everything
"""
import json, os, sys
from datetime import datetime, date
from pathlib import Path
from finviz_http import finviz_get, finviz_probe  # global Finviz throttle (2026-07-20)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# One write path per store (One Source of Truth, Phase 9). This module is the registry's
# writer_target for quote_price; the SQL itself lives in lib/writers/market_quotes_writer.py
# and is re-exported here so producers may import it from either name.
from lib.writers.market_quotes_writer import write_market_quotes  # noqa: E402,F401


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith(f"{key}="): val = line.split("=", 1)[1].strip()
    return val


# Universe = strategy-classified symbols PLUS every currently-open position. Open paper trades
# aren't always in ticker_strategy_classifications (e.g. TMHC, a swing_breakout entry), and without
# this UNION they'd never get a quote -> no current price on the Open Trades page. Generic: any open
# position is always quoted, regardless of classification.
#
# 'researched' joined 'active' on 2026-09-22. The operator asked "how is S for entry on cyber" and
# the desk answered with S's 2026-09-04 close. Measured that day: market_quotes held 4,975 distinct
# symbols refreshed within 0.2h and S's newest row was 431.1h old. The refresher was healthy; S was
# simply not in this universe. watchlist_items held two rows for S -- status='removed' (05-31) and
# status='researched' (updated 09-18) -- and NEITHER matched the predicate, because the per-row OR
# tested only in_directive_watch and 'active'. The duplicate row is a red herring: this is a UNION of
# rows, so the 'removed' row cannot suppress anything; the 'researched' row simply never qualified.
#
# ticker_prices is downstream of this table (4,752 of 4,813 rows on 2026-09-22 carry
# source='market_quotes'), so a symbol dropped here loses its daily close too -- which is the store
# the operator desk actually quoted. One exclusion, both stores.
#
# 'researched' means the house has studied the name, which is exactly the cohort the desk gets asked
# about; 659 symbols join the universe (4,874 -> 5,533, +4 Alpaca batch requests). 'removed' stays
# out: 6,899 symbols the operator deliberately dropped are not worth a provider call, and a desk
# answer about one is now marked stale rather than served as current (cio_operator_desk_loop
# .price_age_note).
UNIVERSE_SQL = """
    SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE
    UNION
    SELECT DISTINCT symbol FROM paper_trades WHERE status = 'open' AND symbol IS NOT NULL
    UNION
    -- names the operator explicitly tracks (directive-watch), active watchlist items, or names the
    -- house has researched: keep them priced even before promotion, so newly-IPO'd directives
    -- (e.g. SPCX) and researched names (e.g. S) don't go stale.
    SELECT DISTINCT symbol FROM watchlist_items
        WHERE (in_directive_watch = TRUE OR status IN ('active', 'researched'))
          AND symbol IS NOT NULL
"""


def _dict_cursor(conn):
    """A dict-row cursor, without making the psycopg2 driver a hard requirement.

    2026-09-22: `_get_symbols` is pure SQL over UNIVERSE_SQL and its test drives
    it against sqlite with `_get_conn` monkeypatched -- yet it still raised
    ModuleNotFoundError, because the cursor FACTORY reached for
    psycopg2.extras. CI installs only `pytest pyyaml`, so five tests that pass
    on any developer machine failed there and nowhere else.

    In production psycopg2 is always present and the behaviour is unchanged:
    the same RealDictCursor as before. Absent the driver, the connection's own
    cursor is used -- which is what a sqlite shim already provides.

    Applied at ALL THREE identical sites, not just the one that went red.
    """
    try:
        import psycopg2.extras  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - driver absent (CI); caller supplies its own conn
        return conn.cursor()
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _get_symbols() -> list:
    conn = _get_conn()
    cur = _dict_cursor(conn)
    cur.execute(UNIVERSE_SQL)
    symbols = [r["symbol"] for r in cur.fetchall()]
    conn.close()
    return [s for s in symbols if "-" not in s and len(s) <= 5]


# ── yfinance ─────────────────────────────────────────────────────────

def ingest_yfinance_quotes(symbols: list = None) -> dict:
    """Fetch real-time quotes via yfinance for all portfolio symbols."""
    import yfinance as yf
    if not symbols:
        symbols = _get_symbols()

    conn = _get_conn()
    cur = conn.cursor()
    fetched = 0

    for batch_start in range(0, len(symbols), 10):
        batch = symbols[batch_start:batch_start + 10]
        try:
            tickers = yf.Tickers(" ".join(batch))
            for sym in batch:
                try:
                    t = tickers.tickers.get(sym)
                    if not t:
                        continue
                    info = t.info or {}
                    price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                    if not price:
                        continue

                    rc = write_market_quotes(cur, [{
                        "symbol": sym, "price": price,
                        "prev_close": info.get("previousClose"),
                        "day_change_pct": info.get("regularMarketChangePercent"),
                        "volume": info.get("volume"),
                        "avg_volume": info.get("averageVolume"),
                        "market_cap": info.get("marketCap"),
                        "pe_ratio": info.get("trailingPE"),
                        "forward_pe": info.get("forwardPE"),
                        "dividend_yield": info.get("dividendYield"),
                        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                    }], source="yfinance")
                    fetched += rc.rows_accepted
                except Exception:
                    pass
        except Exception as e:
            print(f"  [yfinance] Batch error: {e}")

    conn.commit()
    conn.close()
    print(f"[yfinance] Fetched {fetched}/{len(symbols)} quotes")
    try:
        from lib.data_source_report import report_source
        report_source("yahoo_finance", fetched > 0, rows=fetched,
                      error=None if fetched else f"0/{len(symbols)} quotes fetched")
    except Exception:
        pass
    return {"source": "yfinance", "fetched": fetched, "total": len(symbols)}


# ── Alpaca (PRIMARY: live intraday, no rate limit, IEX free feed) ─────────────────────

def _alpaca_creds():
    return (_env("ALPACA_API_KEY") or _env("ALPACA_PAPER_API_KEY") or _env("APCA_API_KEY_ID"),
            _env("ALPACA_SECRET_KEY") or _env("ALPACA_PAPER_SECRET_KEY") or _env("APCA_API_SECRET_KEY"))


def _alpaca_prev_close(snap: dict):
    """The last completed session's close, relative to the quote being stored.

    Alpaca's ``prevDailyBar`` is the bar BEFORE ``dailyBar``. Before today's first
    bar exists (overnight, pre-market, a Monday morning) ``dailyBar`` is still the
    previous session, so ``prevDailyBar`` is two sessions back. Measured
    2026-09-14 07:15-09:00 ET: HPE stored prev_close 55.23 (Thursday) against a
    Friday close of 62.09 (Yahoo), so day_change_pct read +12.4% for a stock that
    had not traded; 7 of 9 litmus symbols were wrong the same way.
    """
    daily = snap.get("dailyBar") or {}
    prev = (snap.get("prevDailyBar") or {}).get("c")
    try:
        from zoneinfo import ZoneInfo
        bar_day = datetime.fromisoformat(str(daily.get("t")).replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York")).date()
        today = datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return prev
    if daily.get("c") and bar_day < today:
        return daily.get("c")
    return prev


def ingest_alpaca_quotes(symbols: list = None) -> dict:
    """Live intraday quotes via Alpaca snapshots (IEX free feed). Primary source — no rate limits,
    unlike yfinance (rate-limited + once-daily). Batches up to 200 symbols/request. Returns the
    fetched count plus the symbols Alpaca could NOT price, so the caller can fall back."""
    import requests
    if not symbols:
        symbols = _get_symbols()
    key, sec = _alpaca_creds()
    if not (key and sec):
        return {"source": "alpaca", "fetched": 0, "total": len(symbols), "missing": list(symbols), "error": "no creds"}
    h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    conn = _get_conn(); cur = conn.cursor()
    fetched = 0; got = set()
    for i in range(0, len(symbols), 200):
        chunk = symbols[i:i + 200]
        try:
            r = requests.get("https://data.alpaca.markets/v2/stocks/snapshots",
                             headers=h, params={"symbols": ",".join(chunk), "feed": "iex"}, timeout=25)
            if r.status_code != 200:
                print(f"  [alpaca] HTTP {r.status_code} on batch {i}")
                continue
            snaps = r.json()
            for sym, s in (snaps.items() if isinstance(snaps, dict) else []):
                if not isinstance(s, dict):
                    continue
                price = (s.get("latestTrade") or {}).get("p") or (s.get("dailyBar") or {}).get("c")
                if not price:
                    continue
                prev = _alpaca_prev_close(s)
                vol = (s.get("dailyBar") or {}).get("v")
                chg_pct = round((price - prev) / prev * 100, 4) if prev else None
                rc = write_market_quotes(cur, [{"symbol": sym, "price": price, "prev_close": prev,
                                                "day_change_pct": chg_pct, "volume": vol}], source="alpaca")
                if rc.rows_accepted:
                    fetched += 1; got.add(sym)
        except Exception as e:
            print(f"  [alpaca] batch {i} error: {e}")
    conn.commit(); conn.close()
    missing = [s for s in symbols if s not in got]
    print(f"[alpaca] Fetched {fetched}/{len(symbols)} live quotes ({len(missing)} missing → fallback)")
    return {"source": "alpaca", "fetched": fetched, "total": len(symbols), "missing": missing}


# ── Finviz (2nd-tier fallback: live quote.ashx, per-symbol incl. RVOL) ────────────────

_FINVIZ_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}


def _finviz_quote(sym: str) -> dict:
    """Parse finviz.com/quote.ashx?t=SYM snapshot table -> {price, prev, rvol, volume}. Live values."""
    import requests, re
    r = finviz_get(f"https://finviz.com/quote.ashx?t={sym}", headers=_FINVIZ_UA, timeout=15,
                   raise_on_429=False)
    if r.status_code != 200:
        return {}
    h = r.text

    def grab(label):
        m = re.search(r'snapshot-td-label">' + re.escape(label) +
                      r'</div></td><td[^>]*><div class="snapshot-td-content">(?:<b>)?\$?([\-\d.,]+)', h)
        return m.group(1).replace(",", "") if m else None
    return {"price": grab("Price"), "prev": grab("Prev Close"), "rvol": grab("Rel Volume"), "volume": grab("Volume")}


def ingest_finviz_quotes(symbols: list = None) -> dict:
    """Per-symbol live quotes from finviz quote.ashx (price/prev/rvol/volume). Used as a FALLBACK for
    the handful Alpaca can't price — finviz is one HTTP request per symbol (rate-limited if hammered),
    so it's not for the full universe, only the gap."""
    import time
    if not symbols:
        symbols = _get_symbols()
    conn = _get_conn(); cur = conn.cursor()
    fetched = 0; got = set()
    for sym in symbols:
        try:
            q = _finviz_quote(sym)
            if not q.get("price"):
                continue
            price = float(q["price"]); prev = float(q["prev"]) if q.get("prev") else None
            chg = round((price - prev) / prev * 100, 4) if prev else None
            vol = int(float(q["volume"])) if q.get("volume") else None
            rc = write_market_quotes(cur, [{"symbol": sym, "price": price, "prev_close": prev,
                                            "day_change_pct": chg, "volume": vol}], source="finviz")
            if rc.rows_accepted:
                fetched += 1; got.add(sym)
            time.sleep(0.3)  # politeness — finviz is per-symbol
        except Exception:
            pass
    conn.commit(); conn.close()
    missing = [s for s in symbols if s not in got]
    print(f"[finviz] Fetched {fetched}/{len(symbols)} quotes ({len(missing)} missing)")
    return {"source": "finviz", "fetched": fetched, "total": len(symbols), "missing": missing}


def ingest_quotes(symbols: list = None) -> dict:
    """Quote ingest with tiered fallback: Alpaca live-intraday PRIMARY (batched, no rate limit) →
    finviz quote.ashx (live, per-symbol) for what Alpaca misses → yfinance last resort. Each tier only
    runs on the symbols the prior tier couldn't price."""
    if not symbols:
        symbols = _get_symbols()
    a = ingest_alpaca_quotes(symbols)
    miss1 = a.get("missing", [])
    fv = {"fetched": 0, "missing": miss1}
    if miss1:
        try:
            fv = ingest_finviz_quotes(miss1)
        except Exception as e:
            print(f"  [fallback] finviz failed (non-fatal): {e}")
    miss2 = fv.get("missing", [])
    yf = {"fetched": 0}
    if miss2:
        try:
            yf = ingest_yfinance_quotes(miss2)
        except Exception as e:
            print(f"  [fallback] yfinance failed (non-fatal): {e}")
    total = a.get("fetched", 0) + fv.get("fetched", 0) + yf.get("fetched", 0)
    print(f"[quotes] {total}/{len(symbols)} (alpaca {a.get('fetched', 0)} + finviz {fv.get('fetched', 0)} + yf {yf.get('fetched', 0)})")

    # 2026-09-13 (Phase 3, "a health ledger that cannot lie"): this used to write
    # report_source("yahoo_finance", True) when yfinance had NOT run, so that Alpaca
    # covering the universe would not read as a yahoo_finance stall. That is a
    # success recorded for a call that never happened -- exactly the kind of entry
    # the ledger may not hold. The stall it papered over is now handled on the read
    # side: the decay view gives yahoo_finance a 168h window (yfinance domains in
    # config/data_source_authority.json) and pro_analyst_fetch.py (06:10 daily)
    # reports the real daily yfinance call. When yfinance DID run above,
    # ingest_yfinance_quotes() reported its own ok/error state.

    return {"alpaca": a.get("fetched", 0), "finviz": fv.get("fetched", 0), "yfinance": yf.get("fetched", 0),
            "fetched": total, "total": len(symbols)}


# ── Alpha Vantage ────────────────────────────────────────────────────

def _alpha_vantage_symbols(cur, limit: int) -> list:
    """Held and directive-watch names first, least recently fetched first.

    ``_get_symbols()[:limit]`` took the first five rows of an unordered UNION --
    mostly micro-caps Alpha Vantage does not cover -- so each Monday stored ONE
    symbol (CLF 09-14, POLA 08-24, RGA/LVLU 08-03) and the names the operator
    actually holds were never refreshed.
    """
    held: list = []
    try:
        doc = json.loads((PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text(encoding="utf-8"))
        held = sorted({str(h.get("symbol") or "").upper() for h in (doc.get("holdings") or [])
                       if not h.get("is_cash") and str(h.get("symbol") or "").isalpha()})
    except Exception:
        held = []
    try:
        # Priority first (the real book, then names the operator directs, then
        # paper positions, then the active watchlist); oldest fetch within a tier.
        cur.execute("""
            WITH wanted AS (
                SELECT unnest(%s::text[]) AS symbol, 0 AS pri
                UNION ALL
                SELECT symbol, 1 FROM watchlist_items WHERE in_directive_watch = TRUE AND symbol IS NOT NULL
                UNION ALL
                SELECT symbol, 2 FROM paper_trades WHERE status = 'open' AND symbol IS NOT NULL
                UNION ALL
                SELECT symbol, 3 FROM watchlist_items WHERE status = 'active' AND symbol IS NOT NULL
            ), best AS (SELECT upper(symbol) AS symbol, min(pri) AS pri FROM wanted GROUP BY 1),
            last AS (SELECT symbol, max(fetched_at) AS at FROM fundamental_data
                     WHERE source = 'alpha_vantage' GROUP BY symbol)
            SELECT b.symbol FROM best b LEFT JOIN last l ON l.symbol = b.symbol
            WHERE b.symbol !~ '[^A-Z]' AND length(b.symbol) <= 5
              AND b.symbol !~ '^[A-Z]{4}X$'  -- mutual funds (AMANX): OVERVIEW has no coverage
              AND (l.at IS NULL OR l.at < now() - interval '6 days')
            ORDER BY b.pri, l.at NULLS FIRST, b.symbol
            LIMIT %s
        """, (held, int(limit)))
        rows = [r[0] for r in cur.fetchall()]
        if rows:
            return rows
    except Exception as exc:  # noqa: BLE001
        print(f"  [av] symbol selection query failed, using the classification universe: {exc}")
        try:
            cur.connection.rollback()
        except Exception:
            pass
    return _get_symbols()[:limit]


def ingest_alpha_vantage(symbols: list = None, limit: int = 5) -> dict:
    """Fetch company fundamentals via Alpha Vantage (free tier: 25 calls/day)."""
    import urllib.request
    api_key = _env("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("[alpha-vantage] No ALPHA_VANTAGE_API_KEY — skipping")
        return {"source": "alpha_vantage", "fetched": 0, "reason": "no_key"}

    conn = _get_conn()
    cur = conn.cursor()
    if not symbols:
        symbols = _alpha_vantage_symbols(cur, limit)  # Free tier limited
    fetched = 0

    for sym in symbols[:limit]:
        try:
            url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={sym}&apikey={api_key}"
            req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            if "Symbol" not in data:
                # A rate-limit or quota notice arrives as HTTP 200 with
                # "Information"/"Note" and no "Symbol". It was skipped silently:
                # 4 of 5 symbols vanished every Monday with nothing logged.
                notice = data.get("Information") or data.get("Note") or data.get("Error Message") or "no Symbol in response"
                print(f"  [av] {sym}: not stored — {str(notice)[:120]}")
                last_exc = str(notice)[:160]
                continue

            metrics = {
                "MarketCap": data.get("MarketCapitalization"),
                "PE": data.get("PERatio"),
                "ForwardPE": data.get("ForwardPE"),
                "PEG": data.get("PEGRatio"),
                "DividendYield": data.get("DividendYield"),
                "EPS": data.get("EPS"),
                "RevenuePerShare": data.get("RevenuePerShareTTM"),
                "ProfitMargin": data.get("ProfitMargin"),
                "ROE": data.get("ReturnOnEquityTTM"),
                "DebtToEquity": data.get("DebtToEquityRatio", data.get("DebtToEquityCurrentRatio")),
                "Beta": data.get("Beta"),
                "52WeekHigh": data.get("52WeekHigh"),
                "52WeekLow": data.get("52WeekLow"),
                "50DayMA": data.get("50DayMovingAverage"),
                "200DayMA": data.get("200DayMovingAverage"),
                "AnalystTargetPrice": data.get("AnalystTargetPrice"),
            }

            for metric, value in metrics.items():
                if value and value != "None" and value != "-":
                    try:
                        cur.execute("""
                            INSERT INTO fundamental_data (symbol, source, metric_name, metric_value, period)
                            VALUES (%s, 'alpha_vantage', %s, %s, 'latest')
                            ON CONFLICT (symbol, source, metric_name, period) DO UPDATE SET metric_value=EXCLUDED.metric_value, fetched_at=NOW()
                        """, (sym, metric, float(value)))
                    except (ValueError, TypeError):
                        pass

            fetched += 1
            print(f"  [av] {sym}: {len([v for v in metrics.values() if v and v != 'None'])} metrics")
        except Exception as e:
            print(f"  [av] {sym}: {e}")
            last_exc = str(e)[:160]

    conn.commit()
    conn.close()
    # Liveness (2026-09-13): the alpha_vantage health row read 'unknown' forever
    # because this lane never reported. Scheduled: cron `0 8 * * 1` (--fundamentals).
    try:
        from lib.data_source_report import report_source
        report_source("alpha_vantage", fetched > 0, rows=fetched,
                      error=None if fetched else (locals().get("last_exc") or f"0/{len(symbols[:limit])} symbols fetched"))
    except Exception:
        pass
    return {"source": "alpha_vantage", "fetched": fetched}


def ingest_av_news_sentiment(symbols: list = None, limit: int = 10) -> dict:
    """Fetch pre-scored news sentiment via Alpha Vantage NEWS_SENTIMENT endpoint.

    Free tier: 25 calls/day total (shared with OVERVIEW).
    Each call returns up to 50 articles with per-ticker sentiment scores.
    Stores in news_articles table with sentiment_score from AV (not LLM-generated).
    """
    import urllib.request
    api_key = _env("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return {"source": "av_news_sentiment", "fetched": 0, "reason": "no_key"}

    if not symbols:
        # Top portfolio positions by market value
        h = json.loads((PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text()) if (PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json").exists() else {}
        by_mv = sorted([p for p in h.get("holdings", []) if p.get("symbol") and not p.get("is_cash") and "-" not in p.get("symbol", "") and len(p.get("symbol", "")) <= 5],
                       key=lambda x: x.get("market_value", 0), reverse=True)
        symbols = [p["symbol"] for p in by_mv[:limit]]

    conn = _get_conn()
    cur = conn.cursor()
    fetched = 0
    articles_stored = 0

    for sym in symbols[:limit]:
        try:
            url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={sym}&limit=20&apikey={api_key}"
            req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            feed = data.get("feed", [])
            if not feed:
                continue

            for article in feed[:15]:
                title = article.get("title", "")[:200]
                summary = article.get("summary", "")[:500]
                source = article.get("source", "")[:50]
                url_link = article.get("url", "")
                published = article.get("time_published", "")
                overall_sentiment = float(article.get("overall_sentiment_score", 0))
                overall_label = article.get("overall_sentiment_label", "Neutral")

                # Get ticker-specific sentiment
                ticker_sentiment = 0.0
                relevance = 0.0
                for ts in article.get("ticker_sentiment", []):
                    if ts.get("ticker") == sym:
                        ticker_sentiment = float(ts.get("ticker_sentiment_score", 0))
                        relevance = float(ts.get("relevance_score", 0))
                        break

                if relevance < 0.3:
                    continue  # Skip low-relevance articles

                # Normalize published date
                pub_date = None
                if published:
                    try:
                        pub_date = datetime.strptime(published[:8], "%Y%m%d").date()
                    except Exception:
                        pass

                try:
                    from lib.writers.news_articles_writer import write_news_articles
                    receipt = write_news_articles(cur, [{
                        "symbol": sym, "title": title, "summary": summary, "source": f"av:{source}",
                        "source_url": url_link, "published_at": pub_date,
                        "relevance_score": round(relevance * 100),
                        "sentiment": overall_label.lower(), "sentiment_score": round(ticker_sentiment, 3),
                        "strategy_tags": json.dumps([f"av_sentiment_{overall_label.lower()}"]),
                    }], source=f"av:{source}")
                    articles_stored += receipt.rows_written
                except Exception:
                    conn.rollback()

            fetched += 1
            print(f"  [av-news] {sym}: {len(feed)} articles, {articles_stored} stored")

            # Rate limit: 5 calls/min for free tier
            import time
            time.sleep(12)

        except Exception as e:
            print(f"  [av-news] {sym}: {e}")
            last_exc = str(e)[:160]

    conn.commit()
    conn.close()
    # Liveness (2026-09-13): same provider, same key ('alpha_vantage'). Not on a
    # schedule today (--news-sentiment / --all only); reports when it runs.
    try:
        from lib.data_source_report import report_source
        report_source("alpha_vantage", fetched > 0, rows=articles_stored,
                      error=None if fetched else (locals().get("last_exc") or "0 symbols fetched"))
    except Exception:
        pass
    return {"source": "av_news_sentiment", "symbols": fetched, "articles": articles_stored}


# ── FRED ─────────────────────────────────────────────────────────────

FRED_SERIES = {
    "DFF": "Federal Funds Rate",
    "T10Y2Y": "10Y-2Y Yield Spread (inversion signal)",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "Consumer Price Index (inflation)",
    "VIXCLS": "VIX Closing Value",
    "MORTGAGE30US": "30-Year Mortgage Rate",
    "SP500": "S&P 500 Index",
}


def ingest_fred() -> dict:
    """Fetch key macro economic series from FRED."""
    import urllib.request
    api_key = _env("FRED_API_KEY")
    if not api_key:
        print("[fred] No FRED_API_KEY — skipping")
        return {"source": "fred", "fetched": 0, "reason": "no_key"}

    conn = _get_conn()
    cur = conn.cursor()
    fetched = 0

    for series_id, name in FRED_SERIES.items():
        try:
            url = (f"https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={series_id}&api_key={api_key}&file_type=json"
                   f"&sort_order=desc&limit=1")
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            obs = data.get("observations", [])
            if obs:
                val = obs[0].get("value", ".")
                obs_date = obs[0].get("date", "")
                if val != "." and obs_date:
                    cur.execute("""
                        INSERT INTO fred_economic_series (series_id, series_name, value, observation_date)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (series_id, observation_date) DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                    """, (series_id, name, float(val), obs_date))
                    fetched += 1
                    print(f"  [fred] {series_id}: {val} ({obs_date})")
        except Exception as e:
            print(f"  [fred] {series_id}: {e}")
            last_exc = str(e)[:160]

    conn.commit()
    conn.close()
    # Liveness (2026-09-13): the fred health row read 'unknown' forever because
    # this lane never reported. Scheduled: cron `15 6 * * *` via
    # scripts/fred_data_ingest.py --ingest, which calls this function.
    try:
        from lib.data_source_report import report_source
        report_source("fred", fetched > 0, rows=fetched,
                      error=None if fetched else (locals().get("last_exc") or f"0/{len(FRED_SERIES)} series fetched"))
    except Exception:
        pass
    return {"source": "fred", "fetched": fetched}


# ── Macro context for agents ─────────────────────────────────────────

def get_macro_context() -> str:
    """Get macro economic context for agent prompt injection."""
    conn = _get_conn()
    cur = _dict_cursor(conn)

    cur.execute("""
        SELECT DISTINCT ON (series_id) series_id, series_name, value, observation_date
        FROM fred_economic_series
        ORDER BY series_id, observation_date DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return ""

    lines = ["MACRO ECONOMIC CONTEXT (FRED):"]
    for r in rows:
        lines.append(f"  {r['series_name']}: {float(r['value']):.2f} ({r['observation_date']})")
    return "\n".join(lines)


def get_yfinance_context(symbol: str) -> str:
    """Get latest yfinance quote context for a symbol."""
    conn = _get_conn()
    cur = _dict_cursor(conn)
    cur.execute("""
        SELECT * FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1
    """, (symbol,))
    r = cur.fetchone()

    # Also get Alpha Vantage fundamentals
    cur.execute("""
        SELECT metric_name, metric_value FROM fundamental_data
        WHERE symbol=%s AND source='alpha_vantage'
        ORDER BY fetched_at DESC LIMIT 10
    """, (symbol,))
    avs = cur.fetchall()
    conn.close()

    parts = []
    if r:
        p = float(r.get("price") or 0)
        dy = float(r.get("dividend_yield") or 0)
        pe = float(r.get("pe_ratio") or 0)
        hi = float(r.get("fifty_two_week_high") or 0)
        lo = float(r.get("fifty_two_week_low") or 0)
        parts.append(f"YFINANCE QUOTE ({symbol}): ${p:.2f} | PE:{pe:.1f} | Yield:{dy*100:.1f}% | 52wk: ${lo:.0f}-${hi:.0f}")

    if avs:
        av_str = ", ".join(f"{a['metric_name']}={float(a['metric_value']):.2f}" for a in avs[:6])
        parts.append(f"ALPHA VANTAGE ({symbol}): {av_str}")

    return "\n".join(parts)


# ── Test ─────────────────────────────────────────────────────────────

def test():
    print("=== External Market Data Test ===\n")

    # yfinance
    print("yfinance (V, SCHD, LMT):")
    result = ingest_yfinance_quotes(["V", "SCHD", "LMT"])
    print(f"  Result: {result}")

    # Alpha Vantage
    print("\nAlpha Vantage (V):")
    result = ingest_alpha_vantage(["V"], limit=1)
    print(f"  Result: {result}")

    # FRED
    print("\nFRED macro:")
    result = ingest_fred()
    print(f"  Result: {result}")

    # Context test
    print("\nyfinance context for V:")
    print(f"  {get_yfinance_context('V')}")
    print("\nMacro context:")
    print(f"  {get_macro_context()}")

    # Counts
    conn = _get_conn()
    cur = conn.cursor()
    for t in ["market_quotes", "fundamental_data", "fred_economic_series"]:
        cur.execute(f"SELECT count(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]} rows")
    conn.close()

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    elif "--quotes" in sys.argv:
        ingest_quotes()  # Alpaca live-intraday primary → yfinance fallback
    elif "--quotes-yf" in sys.argv:
        ingest_yfinance_quotes()  # legacy yfinance-only path (kept for comparison/debug)
    elif "--fundamentals" in sys.argv:
        ingest_alpha_vantage()
    elif "--news-sentiment" in sys.argv:
        ingest_av_news_sentiment()
    elif "--fred" in sys.argv:
        ingest_fred()
    elif "--all" in sys.argv:
        ingest_quotes()
        ingest_alpha_vantage()
        ingest_av_news_sentiment()
        ingest_fred()
    else:
        print("Usage: --test | --quotes | --fundamentals | --news-sentiment | --fred | --all")
