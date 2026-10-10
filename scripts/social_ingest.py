#!/usr/bin/env python3
"""social_ingest.py — Ingest social sentiment from StockTwits (free, no auth).

Usage:
    python3 scripts/social_ingest.py --source stocktwits --symbols "SCHD,V,TDG,LHX,LMT,NOC,RTX"
    python3 scripts/social_ingest.py --source stocktwits --holdings   # uses holdings.json symbols
    python3 scripts/social_ingest.py --source reddit                  # r/dividends, r/investing
    python3 scripts/social_ingest.py --source all --dry-run           # report the plan only

Lanes (lane id derived from argv): ``--source all`` -> ``social-ingest-all`` (cron L243);
``--source stocktwits --discover`` -> ``social-ingest-stocktwits`` (cron L244). Any other argv form
(manual --symbols / --holdings / reddit runs) is not a lane run and writes no receipt.

``--dry-run`` returns before pipeline_registry.run_start (no pipeline_runs row), before any StockTwits /
Reddit request and before any DB connection; it does not resolve the Reddit credentials. It prints the
symbol sets and subreddits a real run would query (from holdings.json and the static discovery lists;
the StockTwits trending list is network-only and is reported as "would fetch"). No receipt.

A real lane run writes ``<state_root>/data/runtime/<lane_id>_last.json`` (LaneRunReceipt@v1; ``ok_at``
only on success) with a per-source summary. Exit codes: 0 = ran (posts already stored, Reddit not
configured while StockTwits fetched, or zero new posts are findings); 1 = the run failed: crash / DB
unavailable (failed receipt, exception re-raised), or nothing could be fetched from any source while
requests were attempted and errored (incl. HTTP 429); 2 = usage error (unknown --source).

SCALP HOT TIER (``--source stocktwits --scalp-list`` -> lane ``social-ingest-scalp-hot``; operator decision (4),
2026-10-10): every 10 min on market days 06:00-11:00 ET, StockTwits for the names on the scalp list
(``lib.data_broker.scalp_list``, cap 25) into ``social_posts`` through the same ``ingest_stocktwits`` (this module
stays the single writer). Inert unless ``SCALP_HOT_TIER=1`` and no kill file (SKIPPED_FLAG_OFF, exit 0). An empty
list is a successful poll (receipt ok, 0 symbols). ``--dry-run`` reads the list only and prints the symbols.
"""
import json, sys, time, hashlib
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _get_holdings_symbols():
    """Get portfolio symbols from holdings.json."""
    f = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text())
    return [h["symbol"] for h in data.get("holdings", [])
            if h.get("symbol") and not h.get("is_cash") and not h.get("is_fund")]


def ingest_stocktwits(symbols: list) -> dict:
    """Fetch recent messages from StockTwits public API for given symbols."""
    import requests

    conn = _get_conn()
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    errors = []

    for sym in symbols:
        try:
            url = f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
            r = requests.get(url, timeout=15, headers={"User-Agent": "TradeAI/1.0"})

            if r.status_code == 429:
                print(f"  [stocktwits] Rate limited — stopping. Got {total_inserted} posts so far.")
                errors.append(f"{sym}: HTTP 429 (rate limited; remaining symbols not fetched)")
                break

            if r.status_code != 200:
                errors.append(f"{sym}: HTTP {r.status_code}")
                continue

            data = r.json()
            messages = data.get("messages", [])

            for msg in messages[:10]:
                post_id = str(msg.get("id", ""))
                if not post_id:
                    continue

                # Check dedup
                cur.execute("SELECT 1 FROM social_posts WHERE platform='stocktwits' AND post_id=%s", (post_id,))
                if cur.fetchone():
                    total_skipped += 1
                    continue

                # Parse sentiment
                sentiment_data = msg.get("entities", {}).get("sentiment", {})
                raw_sentiment = sentiment_data.get("basic", "neutral") if sentiment_data else "neutral"
                sentiment = raw_sentiment.lower() if raw_sentiment else "neutral"
                sentiment_score = 0.7 if sentiment == "bullish" else (-0.7 if sentiment == "bearish" else 0.0)

                # Quality score: based on likes + basic engagement
                likes = msg.get("likes", {}).get("total", 0) if isinstance(msg.get("likes"), dict) else 0
                quality = min(50 + likes * 5, 95)

                # Post date
                created = msg.get("created_at", "")
                try:
                    post_date = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    post_date = datetime.now(timezone.utc)

                user = msg.get("user", {})
                username = user.get("username", "")
                followers = user.get("followers", 0)

                cur.execute("""
                    INSERT INTO social_posts
                        (platform, post_id, username, display_name, text, post_date, url,
                         followers, likes, symbols_mentioned, quality_score, relevance_score,
                         sentiment, sentiment_score, added_by, strategy_tags, agent_tags)
                    VALUES ('stocktwits', %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, 0.5,
                            %s, %s, 'social_ingest', '[]'::jsonb, '[]'::jsonb)
                """, (
                    post_id, username, user.get("name", username),
                    msg.get("body", "")[:2000], post_date,
                    f"https://stocktwits.com/{username}/message/{post_id}",
                    followers, likes, json.dumps([sym]),
                    quality, sentiment, sentiment_score
                ))
                total_inserted += 1

            conn.commit()
            time.sleep(1)  # Rate limit: be polite

        except Exception as e:
            errors.append(f"{sym}: {e}")
            continue

    cur.close()
    conn.close()

    result = {"inserted": total_inserted, "skipped": total_skipped, "errors": errors}
    print(f"[stocktwits] Inserted: {total_inserted}, Skipped (dupes): {total_skipped}, Errors: {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}")
    return result


REDDIT_OAUTH_BASE = "https://oauth.reddit.com"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_UA = "linux:tradeai-social-ingest:1.0 (personal research; read-only)"
# Momentum/small-cap subreddits feed the social scalp scanner (operator 2026-10-05).
REDDIT_MOMENTUM_SUBS = ["pennystocks", "smallstreetbets", "Daytrading", "wallstreetbets", "stocks",
                        "RobinHoodPennyStocks", "StockMarket"]
_REDDIT_STRATEGY = {"pennystocks": "momentum_scalp", "smallstreetbets": "momentum_scalp",
                    "Daytrading": "momentum_scalp", "wallstreetbets": "momentum_scalp",
                    "RobinHoodPennyStocks": "momentum_scalp", "StockMarket": "growth_momentum"}


def _reddit_secret(name: str) -> str:
    try:
        sec = Path(__file__).resolve().parent / "secrets"
        if str(sec) not in sys.path:
            sys.path.insert(0, str(sec))
        from resolve_secret import resolve_secret
        return (resolve_secret(name, "") or "").strip()
    except Exception:
        import os
        return (os.environ.get(name) or "").strip()


def reddit_session() -> dict:
    """Official Reddit Data API, app-only OAuth (client_credentials).

    Reddit has refused unauthenticated `www.reddit.com/.../.json` reads with HTTP 403 for this
    host (measured 2026-10-05; social_posts had 0 reddit rows ever). Returns
    {"ok": True, "base": oauth base, "headers": {...}} or {"ok": False, "reason": ...}.
    Never prints or returns the credentials or the token.
    """
    import requests
    cid, secret = _reddit_secret("REDDIT_CLIENT_ID"), _reddit_secret("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        return {"ok": False, "reason": "REDDIT_NOT_CONFIGURED: create a 'script' app at reddit.com/prefs/apps "
                                       "and store REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET with "
                                       "scripts/secrets/rotate.py (unauthenticated Reddit returns HTTP 403)"}
    try:
        r = requests.post(REDDIT_TOKEN_URL, auth=(cid, secret), data={"grant_type": "client_credentials"},
                          headers={"User-Agent": REDDIT_UA}, timeout=15)
        if r.status_code != 200:
            return {"ok": False, "reason": f"REDDIT_TOKEN_HTTP_{r.status_code}"}
        token = (r.json() or {}).get("access_token")
        if not token:
            return {"ok": False, "reason": "REDDIT_TOKEN_MISSING"}
        return {"ok": True, "base": REDDIT_OAUTH_BASE,
                "headers": {"Authorization": f"bearer {token}", "User-Agent": REDDIT_UA}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"REDDIT_TOKEN_ERROR: {type(exc).__name__}"}


def _report_reddit(ok: bool, rows: int, error: str | None) -> None:
    """Make Reddit failures loud: print them and record the source's health row."""
    if error:
        print(f"[reddit] FAILED: {error}")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lib.data_source_report import report_source
        report_source("reddit", ok, rows=rows, error=error)
    except Exception:
        pass


def ingest_reddit(subreddits: list = None) -> dict:
    """Fetch recent posts from Reddit via the official Data API (app-only OAuth; see reddit_session)."""
    import requests

    if subreddits is None:
        subreddits = list(REDDIT_DEFAULT_SUBS)

    session = reddit_session()
    if not session.get("ok"):
        _report_reddit(False, 0, session.get("reason"))
        return {"inserted": 0, "skipped": 0, "errors": [session.get("reason")], "configured": False}

    conn = _get_conn()
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    errors = []

    for sub in subreddits:
        try:
            url = f"{session['base']}/r/{sub}/new?limit=25&raw_json=1"
            r = requests.get(url, timeout=15, headers=session["headers"])

            if r.status_code == 429:
                print(f"  [reddit] Rate limited on r/{sub} — stopping.")
                break
            if r.status_code != 200:
                errors.append(f"r/{sub}: HTTP {r.status_code}")
                continue

            data = r.json()
            posts = data.get("data", {}).get("children", [])

            for post in posts:
                pd = post.get("data", {})
                post_id = pd.get("id", "")
                if not post_id:
                    continue

                cur.execute("SELECT 1 FROM social_posts WHERE platform='reddit' AND post_id=%s", (post_id,))
                if cur.fetchone():
                    total_skipped += 1
                    continue

                title = pd.get("title", "")
                body = pd.get("selftext", "")[:1500]
                text = f"{title}\n{body}".strip()

                post_date = datetime.fromtimestamp(pd.get("created_utc", 0), tz=timezone.utc)
                score = pd.get("score", 0)
                num_comments = pd.get("num_comments", 0)
                quality = min(40 + score + num_comments * 2, 95)

                cur.execute("""
                    INSERT INTO social_posts
                        (platform, post_id, username, display_name, text, post_date, url,
                         followers, likes, replies, symbols_mentioned, quality_score, relevance_score,
                         sentiment, sentiment_score, added_by, strategy_tags, agent_tags)
                    VALUES ('reddit', %s, %s, %s, %s, %s, %s,
                            0, %s, %s, '[]'::jsonb, %s, 0.4,
                            'neutral', 0, 'social_ingest', %s, '[]'::jsonb)
                """, (
                    post_id, pd.get("author", ""), pd.get("author", ""),
                    text, post_date,
                    f"https://reddit.com{pd.get('permalink', '')}",
                    score, num_comments, quality,
                    json.dumps([f"retirement_{sub}" if sub in ("retirement", "financialindependence") else f"dividend_{sub}"])
                ))
                total_inserted += 1

            conn.commit()
            time.sleep(2)  # Reddit asks for 1 req/sec

        except Exception as e:
            errors.append(f"r/{sub}: {e}")
            continue

    cur.close()
    conn.close()

    result = {"inserted": total_inserted, "skipped": total_skipped, "errors": errors}
    print(f"[reddit] Inserted: {total_inserted}, Skipped (dupes): {total_skipped}, Errors: {len(errors)}")
    return result


def _extract_tickers(text: str) -> list:
    """Extract $TICKER mentions and bare uppercase tickers from text."""
    import re
    # $TICKER format
    dollar_tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
    # Bare tickers in context (3-5 uppercase letters not common words)
    COMMON_WORDS = {'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER',
                    'WAS', 'ONE', 'OUR', 'OUT', 'HAS', 'HIS', 'HOW', 'ITS', 'MAY', 'NEW',
                    'NOW', 'OLD', 'SEE', 'WAY', 'WHO', 'DID', 'GET', 'HAS', 'HIM', 'LET',
                    'SAY', 'SHE', 'TOO', 'USE', 'DAD', 'MOM', 'SON', 'AGO', 'ANY', 'BAD',
                    'BIG', 'END', 'FAR', 'FEW', 'GOT', 'HAD', 'HIGH', 'JUST', 'KEEP',
                    'THIS', 'THAT', 'WILL', 'WITH', 'FROM', 'HAVE', 'BEEN', 'COULD',
                    'WOULD', 'SHOULD', 'EACH', 'MAKE', 'LIKE', 'LONG', 'LOOK', 'MANY',
                    'MOST', 'MUCH', 'NEED', 'NEXT', 'ONLY', 'OVER', 'SAME', 'SOME',
                    'THAN', 'THEM', 'THEN', 'THEY', 'WANT', 'WELL', 'WHAT', 'WHEN',
                    'ALSO', 'BACK', 'BEEN', 'CALL', 'COME', 'DOWN', 'EVEN', 'FIND',
                    'FIRE', 'FIRST', 'GIVE', 'GOOD', 'HELP', 'HERE', 'KNOW', 'LAST',
                    'LEFT', 'LIFE', 'LIVE', 'MADE', 'MORE', 'MOVE', 'MUCH', 'MUST',
                    'NAME', 'PART', 'PLAN', 'PLAY', 'POST', 'REAL', 'SELL', 'SURE',
                    'TAKE', 'TELL', 'TURN', 'VERY', 'WORK', 'YEAR', 'YOLO', 'HOLD',
                    'EDIT', 'TLDR', 'HODL', 'FOMO', 'ROTH', 'SSDI'}
    bare = re.findall(r'\b([A-Z]{2,5})\b', text)
    bare_tickers = [t for t in bare if t not in COMMON_WORDS and len(t) >= 2]
    return list(set(dollar_tickers + bare_tickers))


# Strategy-based discovery lists for StockTwits trending
STRATEGY_DISCOVERY = {
    "dividend_growth": ["SCHD", "VYM", "DGRO", "VIG", "HDV", "DIVO", "JEPI", "JEPQ", "O", "MAIN"],
    "defense_aerospace": ["LMT", "NOC", "RTX", "LHX", "GD", "BA", "HII", "TDG", "LDOS", "BAH"],
    "growth_tech": ["NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "TSM", "AVGO", "AMD", "CRM"],
    "retirement_income": ["SCHD", "VZ", "T", "MO", "PM", "KO", "PEP", "JNJ", "PG", "MMM"],
    "sector_rotation": ["XLF", "XLE", "XLK", "XLV", "XLI", "XLU", "XLP", "XLB", "XLRE", "XLC"],
}


def ingest_stocktwits_discovery() -> dict:
    """Fetch trending symbols across strategies — discover what's hot, not just portfolio."""
    import requests

    conn = _get_conn()
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    errors = []

    # 1. StockTwits trending endpoint
    try:
        r = requests.get("https://api.stocktwits.com/api/2/trending/symbols.json",
                         timeout=15, headers={"User-Agent": "TradeAI/1.0"})
        if r.status_code == 200:
            trending = r.json().get("symbols", [])
            trending_tickers = [s.get("symbol", "") for s in trending[:20]]
            print(f"  [discovery] StockTwits trending: {', '.join(trending_tickers[:10])}")
            result = ingest_stocktwits(trending_tickers[:10])
            total_inserted += result.get("inserted", 0)
            total_skipped += result.get("skipped", 0)
            errors.extend(result.get("errors") or [])
        else:
            errors.append(f"trending: HTTP {r.status_code}")
    except Exception as e:
        errors.append(f"trending: {e}")

    # 2. Strategy-based discovery — pick 3 non-portfolio symbols per strategy
    holdings_syms = set(_get_holdings_symbols())
    for strategy, symbols in STRATEGY_DISCOVERY.items():
        discovery_syms = [s for s in symbols if s not in holdings_syms][:3]
        if discovery_syms:
            try:
                result = ingest_stocktwits(discovery_syms)
                total_inserted += result.get("inserted", 0)
                total_skipped += result.get("skipped", 0)
                errors.extend(result.get("errors") or [])
                time.sleep(1)
            except Exception as e:
                errors.append(f"{strategy}: {e}")

    conn.close()
    print(f"[discovery] Total inserted: {total_inserted}, Errors: {len(errors)}")
    return {"inserted": total_inserted, "skipped": total_skipped, "errors": errors}


def ingest_reddit_with_discovery(subreddits: list = None) -> dict:
    """Reddit ingest that also extracts ticker mentions for discovery routing."""
    import requests

    if subreddits is None:
        subreddits = list(REDDIT_DISCOVERY_SUBS)

    session = reddit_session()
    if not session.get("ok"):
        _report_reddit(False, 0, session.get("reason"))
        return {"inserted": 0, "skipped": 0, "errors": [session.get("reason")], "discovered_tickers": {},
                "configured": False}

    conn = _get_conn()
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    discovered_tickers = {}
    errors = []

    # Map subreddits to strategies
    SUB_STRATEGY = {
        "dividends": "dividend_income",
        "investing": "general",
        "retirement": "retirement_ssdi_roth_tax",
        "financialindependence": "retirement_ssdi_roth_tax",
        "stocks": "growth_momentum",
        "ValueInvesting": "value_dividend",
        **_REDDIT_STRATEGY,
    }

    for sub in subreddits:
        try:
            url = f"{session['base']}/r/{sub}/hot?limit=25&raw_json=1"
            r = requests.get(url, timeout=15, headers=session["headers"])

            if r.status_code == 429:
                print(f"  [reddit] Rate limited on r/{sub} — stopping.")
                break
            if r.status_code != 200:
                errors.append(f"r/{sub}: HTTP {r.status_code}")
                continue

            data = r.json()
            posts = data.get("data", {}).get("children", [])

            for post in posts:
                pd = post.get("data", {})
                post_id = pd.get("id", "")
                if not post_id:
                    continue

                cur.execute("SELECT 1 FROM social_posts WHERE platform='reddit' AND post_id=%s", (post_id,))
                if cur.fetchone():
                    total_skipped += 1
                    continue

                title = pd.get("title", "")
                body = pd.get("selftext", "")[:1500]
                text = f"{title}\n{body}".strip()

                # Extract tickers for discovery
                tickers = _extract_tickers(text)
                strategy = SUB_STRATEGY.get(sub, "general")
                for t in tickers:
                    if t not in discovered_tickers:
                        discovered_tickers[t] = {"count": 0, "strategies": set()}
                    discovered_tickers[t]["count"] += 1
                    discovered_tickers[t]["strategies"].add(strategy)

                post_date = datetime.fromtimestamp(pd.get("created_utc", 0), tz=timezone.utc)
                score = pd.get("score", 0)
                num_comments = pd.get("num_comments", 0)
                quality = min(40 + score + num_comments * 2, 95)

                # Sentiment from score + upvote ratio
                upvote_ratio = pd.get("upvote_ratio", 0.5)
                sentiment = "bullish" if upvote_ratio > 0.75 and score > 10 else ("bearish" if upvote_ratio < 0.4 else "neutral")
                sentiment_score = (upvote_ratio - 0.5) * 2  # -1 to 1 scale

                cur.execute("""
                    INSERT INTO social_posts
                        (platform, post_id, username, display_name, text, post_date, url,
                         followers, likes, replies, symbols_mentioned, quality_score, relevance_score,
                         sentiment, sentiment_score, added_by, strategy_tags, agent_tags)
                    VALUES ('reddit', %s, %s, %s, %s, %s, %s,
                            0, %s, %s, %s, %s, 0.5,
                            %s, %s, 'social_ingest', %s, '[]'::jsonb)
                """, (
                    post_id, pd.get("author", ""), pd.get("author", ""),
                    text, post_date,
                    f"https://reddit.com{pd.get('permalink', '')}",
                    score, num_comments, json.dumps(tickers[:10]),
                    quality, sentiment, round(sentiment_score, 3),
                    json.dumps([strategy])
                ))
                total_inserted += 1

            conn.commit()
            time.sleep(2)

        except Exception as e:
            errors.append(f"r/{sub}: {e}")
            continue

    cur.close()
    conn.close()

    # Report discovered tickers
    if discovered_tickers:
        top_mentions = sorted(discovered_tickers.items(), key=lambda x: x[1]["count"], reverse=True)[:15]
        print("[reddit-discovery] Top mentioned tickers:")
        for ticker, info in top_mentions:
            strategies = ", ".join(info["strategies"])
            print(f"  ${ticker}: {info['count']}x ({strategies})")

    result = {"inserted": total_inserted, "skipped": total_skipped, "errors": errors,
              "discovered_tickers": {k: {"count": v["count"], "strategies": list(v["strategies"])}
                                    for k, v in list(discovered_tickers.items())[:30]}}
    print(f"[reddit] Inserted: {total_inserted}, Skipped: {total_skipped}, Tickers found: {len(discovered_tickers)}")
    for e in errors[:10]:
        print(f"  [reddit] error: {e}")
    fetched = total_inserted + total_skipped
    _report_reddit(fetched > 0, total_inserted,
                   None if fetched > 0 else ("; ".join(errors[:3]) or "0 posts fetched"))
    return result


def rows_from_results(results) -> int | None:
    """Sum the `inserted` counts an ingest run actually reported.

    Returns None when NOTHING reported a count, which pipeline_registry writes
    as JSON null meaning NOT MEASURED. Zero is reserved for "ran and genuinely
    inserted nothing". Those two states must stay distinguishable: collapsing
    them is what made pipeline_zero_rows fire on this healthy pipeline for
    months while it was writing hundreds of rows a day.
    """
    counts = [
        int(r.get("inserted") or 0)
        for r in results
        if isinstance(r, dict) and "inserted" in r
    ]
    return sum(counts) if counts else None


DEFAULT_STOCKTWITS_SYMBOLS = ["SCHD", "V", "TDG", "LHX", "LMT", "NOC", "RTX"]
REDDIT_DEFAULT_SUBS = ["dividends", "investing", "retirement", "financialindependence"]
REDDIT_DISCOVERY_SUBS = ["dividends", "investing", "retirement", "financialindependence",
                         "stocks", "ValueInvesting"] + [x for x in REDDIT_MOMENTUM_SUBS if x != "stocks"]


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.social_ingest
        from scripts.lib import lane_last_receipt as lr
    return lr


def lane_id_for(source: str, discover: bool) -> str | None:
    """The lane id an argv form belongs to (cron L243 / L244); None = a manual run, no receipt."""
    if source == "all":
        return "social-ingest-all"
    if source == "stocktwits" and discover:
        return "social-ingest-stocktwits"
    return None


def _discovery_plan() -> dict:
    holdings_syms = set(_get_holdings_symbols())
    return {"trending": "would fetch api.stocktwits.com trending (top 10)",
            "strategy_symbols": {k: [s for s in v if s not in holdings_syms][:3]
                                 for k, v in STRATEGY_DISCOVERY.items()}}


def plan(source: str, discover: bool, symbols: list) -> dict:
    """What a real run would query. Reads holdings.json only: no network, no DB, no credentials."""
    if source == "stocktwits":
        if discover:
            return {"stocktwits_discovery": _discovery_plan()}
        syms = symbols or _get_holdings_symbols()[:15] or list(DEFAULT_STOCKTWITS_SYMBOLS)
        return {"stocktwits_symbols": syms}
    if source == "reddit":
        return {"reddit_subreddits": REDDIT_DISCOVERY_SUBS if discover else REDDIT_DEFAULT_SUBS}
    if source == "all":
        return {"stocktwits_symbols": _get_holdings_symbols()[:15],
                "stocktwits_discovery": _discovery_plan(),
                "reddit_subreddits": REDDIT_DISCOVERY_SUBS}
    raise ValueError(source)


def run_failed(results) -> bool:
    """Honest exit: True when requests were attempted, all errored, and nothing was fetched."""
    fetched = sum(int((r or {}).get("inserted") or 0) + int((r or {}).get("skipped") or 0)
                  for r in results if isinstance(r, dict))
    errored = any((r or {}).get("errors") for r in results if isinstance(r, dict))
    return fetched == 0 and errored


def _per_source(source: str, discover: bool, results) -> dict:
    if source == "all":
        names = ["stocktwits_holdings", "stocktwits_discovery", "reddit_discovery"]
    elif source == "stocktwits":
        names = ["stocktwits_discovery" if discover else "stocktwits"]
    else:
        names = ["reddit_discovery" if discover else "reddit"]
    out = {}
    for name, r in zip(names, results):
        r = r if isinstance(r, dict) else {}
        out[name] = {"inserted": int(r.get("inserted") or 0), "skipped": int(r.get("skipped") or 0),
                     "errors": len(r.get("errors") or [])}
        if "configured" in r:
            out[name]["configured"] = bool(r["configured"])
    return out


SCALP_HOT_LANE_ID = "social-ingest-scalp-hot"


def _scalp_hot_main(argv: list, now=None) -> int:
    """Lane social-ingest-scalp-hot. Returns before any request/DB connection when off, off-window or dry run."""
    try:
        from lib import scalp_hot_tier as hot
        from lib.data_broker import scalp_list as sl
    except ImportError:  # imported as scripts.social_ingest
        from scripts.lib import scalp_hot_tier as hot  # type: ignore
        from scripts.lib.data_broker import scalp_list as sl  # type: ignore
    flag = hot.flag_state()
    if not flag["enabled"]:
        print(json.dumps({"lane": SCALP_HOT_LANE_ID, "status": "SKIPPED_FLAG_OFF", "hot_tier": flag}))
        return 0
    if not hot.in_window("social", now):
        print(json.dumps({"lane": SCALP_HOT_LANE_ID, "status": "SKIPPED_OFF_WINDOW", "phase": hot.phase(now)}))
        return 0
    lst = sl.get_scalp_list(now=now)
    symbols = list(lst.get("symbols") or [])[: hot.SOCIAL_SYMBOL_CAP]
    summary = {"symbols": symbols, "list_source": lst.get("list_source"), "list_as_of": lst.get("as_of"),
               "list_stale": lst.get("stale"), "stocktwits_symbol_requests": len(symbols)}
    if "--dry-run" in argv:
        _receipt_lib().dry_run_report(
            SCALP_HOT_LANE_ID, summary,
            would_write=["social_posts INSERT (<= 10 per StockTwits symbol; dupes skipped)"])
        return 0
    started = _receipt_lib().now_iso()
    try:
        result = ingest_stocktwits(symbols) if symbols else {"inserted": 0, "skipped": 0, "errors": []}
    except Exception as exc:
        _receipt_lib().write_lane_receipt(SCALP_HOT_LANE_ID, ok=False, exit_code=1, started_at=started,
                                          script="social_ingest.py --scalp-list", summary=summary,
                                          error=f"{type(exc).__name__}: {exc}")
        raise
    failed = bool(symbols) and run_failed([result])
    summary.update(inserted=int(result.get("inserted") or 0), skipped=int(result.get("skipped") or 0),
                   errors=len(result.get("errors") or []))
    _receipt_lib().write_lane_receipt(SCALP_HOT_LANE_ID, ok=not failed, exit_code=int(failed), started_at=started,
                                      script="social_ingest.py --scalp-list", summary=summary)
    return 1 if failed else 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    source = "stocktwits"
    symbols = []

    if "--source" in argv:
        idx = argv.index("--source")
        if idx + 1 < len(argv):
            source = argv[idx + 1]

    if "--symbols" in argv:
        idx = argv.index("--symbols")
        if idx + 1 < len(argv):
            symbols = [s.strip() for s in argv[idx + 1].split(",") if s.strip()]

    if "--holdings" in argv:
        symbols = _get_holdings_symbols()

    discover = "--discover" in argv
    if "--scalp-list" in argv:
        if source != "stocktwits" or discover or symbols:
            print("--scalp-list takes --source stocktwits and no --discover/--symbols/--holdings")
            return 2
        return _scalp_hot_main(argv)
    if source not in ("stocktwits", "reddit", "all"):
        print(f"Unknown source: {source}. Use --source stocktwits|reddit|all [--discover] [--holdings] [--dry-run]")
        return 2
    lane_id = lane_id_for(source, discover)

    if "--dry-run" in argv:
        # Structural (AGENTS.md §6): returns before run_start, before any request, connection or secret.
        p = plan(source, discover, symbols)
        print(json.dumps(p, indent=2))
        n_st = len(p.get("stocktwits_symbols") or []) + sum(
            len(v) for v in ((p.get("stocktwits_discovery") or {}).get("strategy_symbols") or {}).values())
        _receipt_lib().dry_run_report(
            lane_id or f"social-ingest-manual-{source}",
            {"source": source, "discover": discover, "lane_run": lane_id is not None,
             "stocktwits_symbol_requests": n_st,
             "stocktwits_trending": "stocktwits_discovery" in p,
             "reddit_subreddits": len(p.get("reddit_subreddits") or [])},
            would_write=["social_posts INSERT (<= 10 per StockTwits symbol, <= 25 per subreddit; dupes skipped)",
                         "data_source health row 'reddit' (report_source)", "pipeline_runs row (run_start)"])
        return 0

    started = _receipt_lib().now_iso()
    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start('social_ingest')
    except Exception:
        pass

    # Rows are COUNTED, not assumed.
    #
    # This block used to end in `run_complete(_run_id, rows_processed=0)` with a
    # hardcoded literal, while every ingest function below already returned an
    # "inserted" count that was simply thrown away. The pipeline therefore
    # reported rows_produced=0 on every successful run no matter what it wrote,
    # and pipeline_zero_rows alerted on it as a dead producer — measured
    # 2026-09-11, social_posts had gained 761 real rows in the preceding 36h.
    #
    # The 2026-09-06 sweep that fixed sixteen other scripts missed this one
    # because those relied on the DEFAULT rows_processed=0; this passed 0
    # explicitly, so it looked deliberate.
    #
    # None still means NOT MEASURED (see pipeline_registry.run_complete). It is
    # used only where nothing ran at all, so "no input" stays distinguishable
    # from "produced nothing".
    _results: list = []

    def _count(result) -> None:
        _results.append(result)

    try:
        if source == "stocktwits":
            if discover:
                print("[stocktwits] Running discovery mode (trending + strategy exploration)...")
                _count(ingest_stocktwits_discovery())
            else:
                if not symbols:
                    symbols = _get_holdings_symbols()[:15]
                if not symbols:
                    symbols = list(DEFAULT_STOCKTWITS_SYMBOLS)
                print(f"[stocktwits] Ingesting for {len(symbols)} symbols: {', '.join(symbols[:10])}...")
                _count(ingest_stocktwits(symbols))

        elif source == "reddit":
            if discover:
                print("[reddit] Running discovery mode (hot + ticker extraction)...")
                _count(ingest_reddit_with_discovery())
            else:
                print("[reddit] Ingesting new posts from retirement/dividend subs...")
                _count(ingest_reddit())

        elif source == "all":
            print("=== FULL SOCIAL INGEST ===")
            print("\n[1/3] StockTwits: portfolio holdings...")
            _count(ingest_stocktwits(_get_holdings_symbols()[:15]))
            print("\n[2/3] StockTwits: discovery (trending + strategies)...")
            _count(ingest_stocktwits_discovery())
            print("\n[3/3] Reddit: discovery mode (hot + ticker extraction)...")
            _count(ingest_reddit_with_discovery())
            print("\n=== DONE ===")

        rows_measured = rows_from_results(_results)
        label = "NOT_MEASURED" if rows_measured is None else rows_measured
        print(f"[social_ingest] rows_produced={label}")
        try:
            if _run_id: run_complete(_run_id, rows_processed=rows_measured)
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        if lane_id:
            _receipt_lib().write_lane_receipt(lane_id, ok=False, exit_code=1, started_at=started,
                                              script="social_ingest.py", error=f"{type(_e).__name__}: {_e}")
        raise

    failed = run_failed(_results)
    rc = 1 if failed else 0
    if lane_id:
        _receipt_lib().write_lane_receipt(lane_id, ok=not failed, exit_code=rc, started_at=started,
                                          script="social_ingest.py",
                                          summary={"source": source, "discover": discover,
                                                   "rows_produced": rows_measured,
                                                   "per_source": _per_source(source, discover, _results)})
    return rc


if __name__ == "__main__":
    sys.exit(main())
