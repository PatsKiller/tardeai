"""
db_adapter.py — Cross-Platform Storage Adapter
Trade AI v12 + Portfolio Intelligence v1.2

Auto-detects platform:
  - Linux + DB credentials in .env  → PostgreSQL
  - Windows OR missing DB creds     → JSON files (unchanged behavior)

Drop-in replacement: all other scripts import from here instead of
reading/writing JSON directly. Function signatures are identical to
the original JSON patterns so no other logic changes are needed.

PostgreSQL tables (Linux only):
  holdings          ← holdings.json
  price_cache       ← price_cache.json
  portfolio_snapshots ← snapshots/*.json
  trade_ai_state    ← data/state.json
  run_summary       ← run_summary.json per run

Category-2 module output files (JSON on both platforms — not migrated):
  behavioral_analytics.json, correlation.json, dividend_calendar.json,
  performance_attribution.json, retirement_roadmap.json, stops.json,
  stress_test.json, tax_projection.json, technical_snapshot.json,
  trade_journal.json, trade_notes.json, watchlist.json, etc.
  These are computed fresh every run and owned by their single module.
"""
from __future__ import annotations
import json
import os
import platform
from pathlib import Path
from typing import Dict, Optional, Any

# ── Platform detection ────────────────────────────────────────────────────────

def _db_enabled() -> bool:
    """Return True if running on Linux with DB credentials configured."""
    if platform.system() != "Linux":
        return False
    return bool(
        os.getenv("DB_HOST") and
        os.getenv("DB_NAME") and
        os.getenv("DB_USER") and
        os.getenv("DB_PASSWORD")
    )

USE_DB = _db_enabled()

# ── PostgreSQL connection ─────────────────────────────────────────────────────

_conn = None

def _get_conn():
    """Get or create PostgreSQL connection (lazy, singleton)."""
    global _conn
    if _conn is None or _conn.closed:
        try:
            import psycopg2
            import psycopg2.extras
            _conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "trade_ai"),
                user=os.getenv("DB_USER", "trade_ai"),
                password=os.getenv("DB_PASSWORD", ""),
                connect_timeout=10,
            )
            _conn.autocommit = False
        except Exception as e:
            print(f"  [db_adapter] PostgreSQL connection failed: {e}")
            print(f"  [db_adapter] Falling back to JSON")
            return None
    return _conn


def _execute(sql: str, params=None, fetch: str = None):
    """Execute SQL. fetch='one'|'all'|None."""
    conn = _get_conn()
    if conn is None:
        return None
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            else:
                result = True
            conn.commit()
            return result
    except Exception as e:
        conn.rollback()
        print(f"  [db_adapter] SQL error: {e}")
        return None


# ── HOLDINGS ─────────────────────────────────────────────────────────────────

def load_holdings(state_dir: Path) -> Dict:
    """Load portfolio holdings. Returns full portfolio dict."""
    if USE_DB:
        rows = _execute(
            "SELECT data FROM holdings ORDER BY as_of DESC LIMIT 1",
            fetch="one"
        )
        if rows and rows.get("data"):
            return rows["data"]
        print("  [db_adapter] No holdings in DB — falling back to JSON")

    # JSON fallback
    path = Path(state_dir) / "holdings.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_holdings(portfolio: Dict, state_dir: Path) -> None:
    """Save portfolio holdings."""
    if USE_DB:
        as_of = portfolio.get("as_of", "")
        result = _execute(
            """INSERT INTO holdings (as_of, data)
               VALUES (%s, %s)
               ON CONFLICT (as_of) DO UPDATE SET data = EXCLUDED.data""",
            (as_of, json.dumps(portfolio, default=str))
        )
        if result is not None:
            return
        print("  [db_adapter] DB save failed — writing JSON backup")

    # JSON (always write on Windows; fallback on Linux)
    path = Path(state_dir) / "holdings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(portfolio, f, indent=2, default=str)


# ── PRICE CACHE ───────────────────────────────────────────────────────────────

def load_price_cache(state_dir: Path) -> Dict:
    """Load price cache. Returns {symbol: {date_str: price}} dict."""
    if USE_DB:
        rows = _execute(
            """SELECT symbol, price_date::text, close_price
               FROM price_cache
               WHERE price_date >= CURRENT_DATE - INTERVAL '2 years'
               ORDER BY symbol, price_date""",
            fetch="all"
        )
        if rows:
            cache: Dict[str, Dict[str, float]] = {}
            for row in rows:
                sym = row["symbol"]
                if sym not in cache:
                    cache[sym] = {}
                cache[sym][row["price_date"]] = float(row["close_price"])
            # Add meta key for compatibility
            cache["_meta"] = {}
            return cache
        print("  [db_adapter] No price cache in DB — falling back to JSON")

    # JSON fallback
    cache_path = Path(state_dir) / "price_cache.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"_meta": {}}


def save_price_cache(cache: Dict, state_dir: Path) -> None:
    """Save price cache."""
    if USE_DB:
        rows = []
        for sym, prices in cache.items():
            if sym.startswith("_") or not isinstance(prices, dict):
                continue
            for date_str, price in prices.items():
                if isinstance(price, (int, float)) and price > 0:
                    rows.append((sym, date_str, float(price)))

        if rows:
            conn = _get_conn()
            if conn:
                try:
                    import psycopg2.extras
                    with conn.cursor() as cur:
                        psycopg2.extras.execute_values(
                            cur,
                            """INSERT INTO price_cache (symbol, price_date, close_price)
                               VALUES %s
                               ON CONFLICT (symbol, price_date)
                               DO UPDATE SET close_price = EXCLUDED.close_price""",
                            rows
                        )
                    conn.commit()
                    return
                except Exception as e:
                    conn.rollback()
                    print(f"  [db_adapter] Price cache DB save failed: {e}")

    # JSON fallback
    cache_path = Path(state_dir) / "price_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, separators=(",", ":")),
        encoding="utf-8"
    )


# ── SNAPSHOTS ─────────────────────────────────────────────────────────────────

def load_snapshots(state_dir: Path) -> Dict[str, float]:
    """Load all portfolio snapshots. Returns {date_str: total_value}."""
    if USE_DB:
        rows = _execute(
            "SELECT snapshot_date::text, total_value FROM portfolio_snapshots ORDER BY snapshot_date",
            fetch="all"
        )
        if rows is not None:
            return {row["snapshot_date"]: float(row["total_value"]) for row in rows}
        print("  [db_adapter] No snapshots in DB — falling back to JSON")

    # JSON fallback
    snap_dir = Path(state_dir) / "snapshots"
    snapshots: Dict[str, float] = {}
    if snap_dir.exists():
        for f in snap_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                snapshots[d["date"]] = float(d["total_value"])
            except Exception:
                pass
    return snapshots


def save_snapshot(snapshot: Dict, state_dir: Path) -> None:
    """Save a single portfolio snapshot."""
    date_str = snapshot.get("date", "")
    total_value = float(snapshot.get("total_value", 0))
    source = snapshot.get("source", "live")

    if USE_DB and date_str and total_value > 0:
        result = _execute(
            """INSERT INTO portfolio_snapshots (snapshot_date, total_value, source, data)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (snapshot_date) DO UPDATE
               SET total_value = EXCLUDED.total_value,
                   source = EXCLUDED.source,
                   data = EXCLUDED.data""",
            (date_str, total_value, source, json.dumps(snapshot, default=str))
        )
        if result is not None:
            return
        print("  [db_adapter] Snapshot DB save failed — writing JSON backup")

    # JSON fallback
    snap_dir = Path(state_dir) / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{date_str}.json"
    snap_path.write_text(json.dumps(snapshot, indent=2, default=str))


# ── PERFORMANCE DAILY ────────────────────────────────────────────────────────

def save_performance_daily(perf: Dict) -> None:
    """Save today's computed period returns to performance_daily table."""
    if not USE_DB:
        return
    from datetime import date as _date
    snapshot_date = _date.today().isoformat()
    periods = perf.get("periods", {})
    total_value = perf.get("current_value", 0) or 0
    result = _execute(
        """INSERT INTO performance_daily
           (snapshot_date, total_value,
            change_1d_pct, change_1w_pct, change_1m_pct, change_3m_pct,
            change_6m_pct, change_ytd_pct, change_1y_pct, data)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (snapshot_date) DO UPDATE SET
            total_value = EXCLUDED.total_value,
            change_1d_pct = EXCLUDED.change_1d_pct,
            change_1w_pct = EXCLUDED.change_1w_pct,
            change_1m_pct = EXCLUDED.change_1m_pct,
            change_3m_pct = EXCLUDED.change_3m_pct,
            change_6m_pct = EXCLUDED.change_6m_pct,
            change_ytd_pct = EXCLUDED.change_ytd_pct,
            change_1y_pct = EXCLUDED.change_1y_pct,
            data = EXCLUDED.data""",
        (snapshot_date, total_value,
         periods.get("1D", {}).get("change_pct"),
         periods.get("1W", {}).get("change_pct"),
         periods.get("1M", {}).get("change_pct"),
         periods.get("3M", {}).get("change_pct"),
         periods.get("6M", {}).get("change_pct"),
         periods.get("YTD", {}).get("change_pct"),
         periods.get("1Y", {}).get("change_pct"),
         json.dumps(perf, default=str))
    )
    if result is not None:
        return
    print("  [db_adapter] performance_daily write failed")


# ── INTEL BRIEFS ─────────────────────────────────────────────────────────────

def save_intel_brief(brief: Dict) -> None:
    """Save a generated intel brief record to Postgres."""
    if not USE_DB:
        return
    _execute(
        """INSERT INTO intel_briefs
           (brief_date, brief_type, fund, docx_path, word_count, sections, triggers)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (brief_date, brief_type, fund)
           DO UPDATE SET docx_path = EXCLUDED.docx_path,
                         word_count = EXCLUDED.word_count,
                         sections = EXCLUDED.sections,
                         triggers = EXCLUDED.triggers""",
        (brief['brief_date'], brief['brief_type'], brief['fund'],
         brief.get('docx_path'), brief.get('word_count'),
         json.dumps(brief.get('sections', {})), json.dumps(brief.get('triggers', {})))
    )


# ── ACTION SIGNALS HISTORY ───────────────────────────────────────────────────

def save_signals_history(signals: list, signal_date: str) -> None:
    """Save today's per-ticker signals to action_signals_history table."""
    if not USE_DB:
        return
    rows = []
    for s in signals:
        rows.append((
            signal_date,
            s.get("symbol", ""),
            s.get("signal", ""),
            s.get("rule", ""),
            s.get("portfolio_pct"),
            s.get("market_value"),
            json.dumps({k: v for k, v in s.items()
                        if k not in ("symbol", "signal", "rule", "portfolio_pct", "market_value")},
                       default=str)
        ))
    if not rows:
        return
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO action_signals_history
                       (signal_date, symbol, signal, rule, portfolio_pct, market_value, data)
                       VALUES %s
                       ON CONFLICT (signal_date, symbol)
                       DO UPDATE SET signal = EXCLUDED.signal,
                                     rule = EXCLUDED.rule,
                                     portfolio_pct = EXCLUDED.portfolio_pct,
                                     market_value = EXCLUDED.market_value,
                                     data = EXCLUDED.data""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Signals history save failed: {e}")


# ── ADVISOR MEMORY (OpenClaw Phase A1) ───────────────────────────────────────

def save_dividend_history(payers: list, record_date: str) -> None:
    """Save today's per-ticker dividend data to dividend_history table."""
    if not USE_DB or not payers:
        return
    # Aggregate by symbol (same ticker may appear in multiple accounts)
    by_sym = {}
    for p in payers:
        sym = p.get("symbol", "")
        if not sym:
            continue
        if sym not in by_sym:
            by_sym[sym] = {"yield_pct": p.get("yield_pct"), "annual_income": 0, "entries": []}
        by_sym[sym]["annual_income"] += p.get("annual_income", 0) or 0
        by_sym[sym]["entries"].append(p)
    rows = []
    for sym, agg in by_sym.items():
        rows.append((
            record_date, sym,
            agg["yield_pct"],
            None,  # quarterly_amount
            round(agg["annual_income"], 2),
            None,  # ex_div_date
            None,  # pay_date
            json.dumps({"accounts": len(agg["entries"]),
                        "entries": agg["entries"]}, default=str)
        ))
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO dividend_history
                       (record_date, symbol, annual_yield_pct, quarterly_amount,
                        annual_income, ex_div_date, pay_date, data)
                       VALUES %s
                       ON CONFLICT (record_date, symbol)
                       DO UPDATE SET annual_yield_pct = EXCLUDED.annual_yield_pct,
                                     annual_income = EXCLUDED.annual_income,
                                     data = EXCLUDED.data""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Dividend history save failed: {e}")


def save_advisor_observations(observations: list) -> None:
    """Save rule-based observations to advisor_observations table."""
    if not USE_DB or not observations:
        return
    rows = []
    for o in observations:
        rows.append((
            o["observation_date"],
            o.get("symbol") or "",  # empty string, not NULL (for UNIQUE constraint)
            o["category"],
            o["observation"],
            json.dumps(o.get("evidence", {}), default=str),
            o["source"],
            o.get("confidence", 1.00),
            o.get("model", "rule"),
            o.get("freshness_hash"),
        ))
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO advisor_observations
                       (observation_date, symbol, category, observation, evidence,
                        source, confidence, model, freshness_hash)
                       VALUES %s
                       ON CONFLICT (observation_date, symbol, category, source)
                       DO UPDATE SET observation = EXCLUDED.observation,
                                     evidence = EXCLUDED.evidence,
                                     freshness_hash = EXCLUDED.freshness_hash""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Advisor observations save failed: {e}")


def save_ticker_snapshot_daily(snapshot_date: str, enrichment_cache: dict) -> None:
    """Save daily enrichment snapshot for all tickers in the cache."""
    if not USE_DB or not enrichment_cache:
        return
    from datetime import datetime as _dt
    rows = []
    for sym, data in enrichment_cache.items():
        if not isinstance(data, dict) or not sym or sym.startswith("_"):
            continue
        # Provenance/coverage block
        _all_fields = set(data.keys())
        _expected = {"rsi","beta","sma20_pct","sma50_pct","sma200_pct","perf_week_pct",
                     "perf_month_pct","perf_ytd_pct","week52_high_pct","week52_low_pct"}
        _present = _expected & _all_fields
        _missing = _expected - _all_fields
        _cached_at = data.get("cached_at", "")
        _cache_age = None
        if _cached_at:
            try:
                _cache_age = round((_dt.now() - _dt.fromisoformat(_cached_at)).total_seconds())
            except Exception:
                pass
        # Build full data payload with provenance
        _full_data = dict(data)
        _full_data["_provenance"] = {
            "source_timestamp": _cached_at,
            "source_fields_present": len(_all_fields),
            "source_fields_missing": sorted(_missing) if _missing else [],
            "cache_age_seconds": _cache_age,
        }
        rows.append((
            snapshot_date, sym, "finviz",
            data.get("rsi"), data.get("beta"),
            data.get("sma20_pct"), data.get("sma50_pct"), data.get("sma200_pct"),
            data.get("perf_week_pct"), data.get("perf_month_pct"), data.get("perf_ytd_pct"),
            data.get("week52_high_pct"), data.get("week52_low_pct"),
            str(data.get("recom", ""))[:20] if data.get("recom") else None,
            json.dumps(_full_data, default=str),
        ))
    if not rows:
        return
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO ticker_snapshot_daily
                       (snapshot_date, symbol, source, rsi, beta,
                        sma20_pct, sma50_pct, sma200_pct,
                        perf_week_pct, perf_month_pct, perf_ytd_pct,
                        week52_high_pct, week52_low_pct, analyst_recom, data)
                       VALUES %s
                       ON CONFLICT (snapshot_date, symbol)
                       DO UPDATE SET rsi = EXCLUDED.rsi, beta = EXCLUDED.beta,
                                     sma20_pct = EXCLUDED.sma20_pct, sma50_pct = EXCLUDED.sma50_pct,
                                     sma200_pct = EXCLUDED.sma200_pct,
                                     perf_week_pct = EXCLUDED.perf_week_pct,
                                     perf_month_pct = EXCLUDED.perf_month_pct,
                                     perf_ytd_pct = EXCLUDED.perf_ytd_pct,
                                     week52_high_pct = EXCLUDED.week52_high_pct,
                                     week52_low_pct = EXCLUDED.week52_low_pct,
                                     analyst_recom = EXCLUDED.analyst_recom,
                                     data = EXCLUDED.data""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Ticker snapshot daily save failed: {e}")


def save_article_index(articles: list) -> None:
    """Save article metadata to article_index. Dedupe by URL hash."""
    if not USE_DB or not articles:
        return
    import hashlib
    rows = []
    for a in articles:
        url = a.get("url", "")
        title = a.get("title", "")
        source = a.get("source", "unknown")
        pub = a.get("published_at", "")
        # Dedupe key
        if url:
            dk = hashlib.md5(url.encode()).hexdigest()[:20]
        else:
            dk = hashlib.md5(f"{title}|{source}|{str(pub)[:10]}".encode()).hexdigest()[:20]
        # Symbols array
        sym = a.get("symbol") or a.get("portfolio_symbol") or ""
        symbols = [sym] if sym else []
        # Build row
        rows.append((
            pub or None,
            title,
            url or None,
            source,
            a.get("provider"),
            symbols if symbols else None,
            a.get("portfolio_symbol"),
            a.get("llm_score") or a.get("relevance_score"),
            None,  # sentiment — not present in current pipeline
            a.get("impact_tier"),
            a.get("llm_category"),
            a.get("llm_urgency"),
            a.get("llm_summary") or a.get("summary"),
            json.dumps({k: v for k, v in a.items()
                        if k not in ("title", "url", "source", "provider", "published_at",
                                     "portfolio_symbol", "llm_score", "impact_tier",
                                     "llm_category", "llm_urgency", "llm_summary")}, default=str),
            dk,
        ))
    if not rows:
        return
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO article_index
                       (published_at, title, url, source, provider, symbols,
                        portfolio_symbol, relevance_score, sentiment, impact_tier,
                        llm_category, llm_urgency, summary, data, dedupe_key)
                       VALUES %s
                       ON CONFLICT (dedupe_key)
                       DO UPDATE SET relevance_score = EXCLUDED.relevance_score,
                                     impact_tier = EXCLUDED.impact_tier,
                                     llm_category = EXCLUDED.llm_category,
                                     llm_urgency = EXCLUDED.llm_urgency,
                                     summary = EXCLUDED.summary,
                                     data = EXCLUDED.data""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Article index save failed: {e}")


def save_advisor_recommendations(recommendations: list) -> None:
    """Save recommendation drafts. Upsert by dedupe_key."""
    if not USE_DB or not recommendations:
        return
    rows = []
    for r in recommendations:
        rows.append((
            r["recommendation_date"],
            r.get("symbol"),
            r["action"],
            r["rationale"],
            r["confidence"],
            r.get("model", "rule"),
            r.get("escalation_ids"),
            r.get("observation_ids"),
            json.dumps(r.get("evidence_summary", {}), default=str),
            r.get("status", "draft"),
            r.get("expires_at"),
            r["dedupe_key"],
        ))
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO advisor_recommendations
                       (recommendation_date, symbol, action, rationale, confidence,
                        model, escalation_ids, observation_ids, evidence_summary,
                        status, expires_at, dedupe_key)
                       VALUES %s
                       ON CONFLICT (dedupe_key)
                       DO UPDATE SET rationale = EXCLUDED.rationale,
                                     confidence = EXCLUDED.confidence,
                                     evidence_summary = EXCLUDED.evidence_summary""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Advisor recommendations save failed: {e}")


def save_yahoo_analyst_targets_history(snapshot_date: str, targets_payload: list) -> None:
    """Save Yahoo analyst target data to history table."""
    if not USE_DB or not targets_payload:
        return
    rows = []
    for t in targets_payload:
        rows.append((
            snapshot_date,
            t["symbol"],
            t.get("current_price"),
            t.get("target_mean_price"),
            t.get("target_high_price"),
            t.get("target_low_price"),
            t.get("target_median_price"),
            t.get("recommendation_mean"),
            t.get("recommendation_key"),
            t.get("number_of_analyst_opinions"),
            "yahoo",
            json.dumps(t, default=str),
        ))
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO yahoo_analyst_targets_history
                       (snapshot_date, symbol, current_price, target_mean_price,
                        target_high_price, target_low_price, target_median_price,
                        recommendation_mean, recommendation_key,
                        number_of_analyst_opinions, source, data)
                       VALUES %s
                       ON CONFLICT (snapshot_date, symbol)
                       DO UPDATE SET current_price = EXCLUDED.current_price,
                                     target_mean_price = EXCLUDED.target_mean_price,
                                     target_high_price = EXCLUDED.target_high_price,
                                     target_low_price = EXCLUDED.target_low_price,
                                     target_median_price = EXCLUDED.target_median_price,
                                     recommendation_mean = EXCLUDED.recommendation_mean,
                                     recommendation_key = EXCLUDED.recommendation_key,
                                     number_of_analyst_opinions = EXCLUDED.number_of_analyst_opinions,
                                     data = EXCLUDED.data""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Yahoo analyst targets save failed: {e}")


def save_analyst_consensus_history(snapshot_date: str, enrichment_cache: dict, quote_cache: dict = None) -> None:
    """Save daily analyst-consensus data per ticker."""
    if not USE_DB or not enrichment_cache:
        return
    rows = []
    _qc = quote_cache or {}
    for sym, data in enrichment_cache.items():
        if not isinstance(data, dict) or not sym or sym.startswith("_"):
            continue
        recom_raw = data.get("recom")
        recom_score = data.get("recom_score")
        analyst_rating = data.get("analyst_rating")
        # Target price from quote cache if available
        target_price = None
        if sym in _qc and isinstance(_qc[sym], dict):
            _tp = _qc[sym].get("target")
            if _tp and float(_tp) > 0:
                target_price = float(_tp)
        # Only store if ticker has any analyst-related data
        if recom_raw is None and recom_score is None and analyst_rating is None and target_price is None:
            continue
        _analyst_data = {
            "recom": recom_raw,
            "recom_score": recom_score,
            "analyst_rating": analyst_rating,
            "earnings_date": data.get("earnings_date"),
            "earnings_time": data.get("earnings_time"),
            "target_price": target_price,
            "cached_at": data.get("cached_at"),
        }
        rows.append((
            snapshot_date, sym,
            str(recom_raw)[:50] if recom_raw else None,
            float(recom_score) if recom_score is not None else None,
            str(analyst_rating)[:30] if analyst_rating else None,
            target_price,
            "finviz",
            json.dumps(_analyst_data, default=str),
        ))
    if not rows:
        return
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO analyst_consensus_history
                       (snapshot_date, symbol, recom_raw, recom_score, analyst_rating,
                        target_price, source, data)
                       VALUES %s
                       ON CONFLICT (snapshot_date, symbol)
                       DO UPDATE SET recom_raw = EXCLUDED.recom_raw,
                                     recom_score = EXCLUDED.recom_score,
                                     analyst_rating = EXCLUDED.analyst_rating,
                                     target_price = EXCLUDED.target_price,
                                     data = EXCLUDED.data""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Analyst consensus history save failed: {e}")


def save_watchlist_item(item: dict) -> None:
    """Upsert a single watchlist item by (symbol, source_type)."""
    if not USE_DB:
        return
    _execute(
        """INSERT INTO watchlist_items
           (symbol, source_type, thesis, target_intent, added_date, added_by,
            confidence, status, notes, data, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (symbol, source_type)
           DO UPDATE SET thesis = EXCLUDED.thesis,
                         target_intent = EXCLUDED.target_intent,
                         status = EXCLUDED.status,
                         notes = EXCLUDED.notes,
                         data = EXCLUDED.data,
                         updated_at = now()""",
        (item["symbol"], item.get("source_type", "user"),
         item.get("thesis"), item.get("target_intent"),
         item.get("added_date"), item.get("added_by", "user"),
         item.get("confidence"), item.get("status", "active"),
         item.get("notes"), json.dumps(item.get("data", {}), default=str))
    )


def remove_watchlist_item(symbol: str, source_type: str = "user") -> None:
    """Mark a watchlist item as removed."""
    if not USE_DB:
        return
    _execute(
        "UPDATE watchlist_items SET status = 'removed', updated_at = now() WHERE symbol = %s AND source_type = %s",
        (symbol, source_type)
    )


def load_watchlist_items(source_type: str = None, status: str = "active") -> list:
    """Load watchlist items from Postgres."""
    if not USE_DB:
        return []
    sql = "SELECT symbol, source_type, thesis, target_intent, added_date, status, notes FROM watchlist_items WHERE status = %s"
    params = [status]
    if source_type:
        sql += " AND source_type = %s"
        params.append(source_type)
    sql += " ORDER BY added_date DESC"
    result = _execute(sql, params, fetch="all")
    return [dict(r) for r in result] if result else []


def save_escalations(escalations: list) -> None:
    """Save escalation queue entries. Upsert by (observation_id, trigger_rule)."""
    if not USE_DB or not escalations:
        return
    rows = []
    for e in escalations:
        rows.append((
            e.get("observation_id"),
            e.get("symbol"),
            e["severity"],
            e["category"],
            e["trigger_rule"],
            e["summary"],
            json.dumps(e.get("evidence", {}), default=str),
            e.get("status", "pending"),
            e.get("expires_at"),
        ))
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO escalation_queue
                       (observation_id, symbol, severity, category, trigger_rule,
                        summary, evidence, status, expires_at)
                       VALUES %s
                       ON CONFLICT (observation_id, trigger_rule)
                       DO UPDATE SET severity = EXCLUDED.severity,
                                     summary = EXCLUDED.summary,
                                     evidence = EXCLUDED.evidence""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Escalation queue save failed: {e}")


# ── TRADE AI STATE (delta tracker) ───────────────────────────────────────────

def load_state(state_file: Path) -> Dict:
    """Load Trade AI delta tracking state."""
    if USE_DB:
        rows = _execute(
            """SELECT ticker, data FROM trade_ai_state
               WHERE run_date = (SELECT MAX(run_date) FROM trade_ai_state)""",
            fetch="all"
        )
        if rows:
            state = {}
            for row in rows:
                state[row["ticker"]] = row["data"]
            return state
        print("  [db_adapter] No state in DB — falling back to JSON")

    # JSON fallback
    path = Path(state_file)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: Dict, state_file: Path) -> None:
    """Save Trade AI delta tracking state."""
    if USE_DB:
        from datetime import date
        run_date = date.today().isoformat()
        conn = _get_conn()
        if conn:
            try:
                import psycopg2.extras
                rows = [(run_date, ticker, json.dumps(data, default=str))
                        for ticker, data in state.items()
                        if isinstance(data, dict)]
                with conn.cursor() as cur:
                    # Clear today's state first
                    cur.execute("DELETE FROM trade_ai_state WHERE run_date = %s", (run_date,))
                    if rows:
                        psycopg2.extras.execute_values(
                            cur,
                            """INSERT INTO trade_ai_state (run_date, ticker, data)
                               VALUES %s""",
                            rows
                        )
                conn.commit()
                return
            except Exception as e:
                conn.rollback()
                print(f"  [db_adapter] State DB save failed: {e}")

    # JSON fallback
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


# ── RUN SUMMARY ───────────────────────────────────────────────────────────────

def load_run_summary(path: Path) -> Dict:
    """Load a run summary."""
    if USE_DB:
        # Derive run_date and run_label from path: reports/{date}/{label}/run_summary.json
        try:
            parts = Path(path).parts
            run_date = parts[-3]
            run_label = parts[-2]
            row = _execute(
                "SELECT data FROM run_summary WHERE run_date = %s AND run_label = %s",
                (run_date, run_label),
                fetch="one"
            )
            if row and row.get("data"):
                return row["data"]
        except Exception:
            pass
        print("  [db_adapter] Run summary not in DB — falling back to JSON")

    # JSON fallback
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_run_summary(summary: Dict, path: Path) -> None:
    """Save a run summary."""
    if USE_DB:
        try:
            parts = Path(path).parts
            run_date = parts[-3]
            run_label = parts[-2]
            go_count = summary.get("go_count", 0)
            wait_count = summary.get("wait_count", 0)
            result = _execute(
                """INSERT INTO run_summary (run_date, run_label, go_count, wait_count, data)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (run_date, run_label)
                   DO UPDATE SET go_count=EXCLUDED.go_count,
                                 wait_count=EXCLUDED.wait_count,
                                 data=EXCLUDED.data""",
                (run_date, run_label, go_count, wait_count,
                 json.dumps(summary, default=str))
            )
            if result is not None:
                # Also write JSON for dashboard_generator_v2.py compatibility
                pass
        except Exception as e:
            print(f"  [db_adapter] Run summary DB save failed: {e}")

    # Always write JSON (dashboard_generator reads it directly by path)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(summary, indent=2), encoding="utf-8")


# ── Status helper ─────────────────────────────────────────────────────────────

def db_status() -> str:
    """Return human-readable storage backend status."""
    if USE_DB:
        conn = _get_conn()
        if conn:
            return f"PostgreSQL @ {os.getenv('DB_HOST')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME')}"
        return "PostgreSQL configured but connection failed — using JSON fallback"
    return f"JSON files (platform={platform.system()})"
