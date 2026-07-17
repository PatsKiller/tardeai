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

def _load_dotenv_if_needed():
    """Load .env file into os.environ if DB_PASSWORD not already set.
    Handles cron context where env vars aren't inherited."""
    if os.getenv("DB_PASSWORD"):
        return  # already set
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if key.startswith("DB_") and key not in os.environ:
                    os.environ[key] = val

_load_dotenv_if_needed()


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

import threading as _threading

# THREAD-LOCAL connections (2026-06-29): the dashboard server is now multi-threaded, so a single
# shared connection would let concurrent requests corrupt each other's cursor/transaction state.
# Each thread gets its OWN connection. Single-threaded callers (crons) still get exactly one
# persistent connection (their main thread's), so their behavior is unchanged.
_tls = _threading.local()

def _get_conn():
    """Get or create a THREAD-LOCAL PostgreSQL connection (lazy, one per thread)."""
    import time as _time
    conn = getattr(_tls, "conn", None)
    if conn is not None and not conn.closed:
        # Server-side disconnects (idle_session_timeout reaper, PG restart) leave
        # conn.closed == 0 until an operation fails — so a long-idle daemon would fail
        # exactly one query per idle episode. Ping when this thread's conn has been
        # idle >60s AND no transaction is open (never roll back a caller's open txn);
        # a dead conn is rebuilt below instead of being handed out (2026-07-17,
        # prerequisite for the role-level idle_session_timeout backstop).
        try:
            import psycopg2.extensions as _pgext
            _idle = _time.time() - getattr(_tls, "last_used", 0.0)
            if _idle > 60 and conn.get_transaction_status() == _pgext.TRANSACTION_STATUS_IDLE:
                try:
                    with conn.cursor() as _pc:
                        _pc.execute("SELECT 1")
                    conn.rollback()
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
                    _tls.conn = None
        except Exception:
            pass
    if conn is not None and not conn.closed:
        # Self-heal a poisoned connection: if a prior handler swallowed a query error
        # without rollback, every later query on this thread fails with "current
        # transaction is aborted" forever (2026-07-14: Redeploy panel showed 0 events
        # all session on the affected worker thread). Roll back and hand out a clean txn.
        try:
            import psycopg2.extensions as _pgext
            if conn.get_transaction_status() == _pgext.TRANSACTION_STATUS_INERROR:
                conn.rollback()
        except Exception:
            pass
        _tls.last_used = _time.time()
        return conn
    try:
        import psycopg2
        import psycopg2.extras
        import sys as _sys
        # application_name = calling script, so pg_stat_activity / PG-log victims are
        # attributable (the 2026-07-04 idle-in-transaction audit had to guess offenders).
        _app = os.path.basename(_sys.argv[0] or "python")[:60] or "python"
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""),
            connect_timeout=10,
            application_name=_app,
        )
        conn.autocommit = False
        # Per-connection safety nets (2026-06-29 idle; lock/stmt added 2026-06-30 after a server hang).
        # The dashboard hung when an additive ALTER on a hot table queued behind an idle-in-transaction
        # AccessShareLock holder, cascading every query on that table and blocking the server's request
        # threads. Three guards so no single connection can wedge the box:
        #   • idle_in_transaction_session_timeout — a read left uncommitted can't hold a lock forever.
        #   • lock_timeout — a query waiting on a lock FAILS FAST (3s) instead of queuing the table behind a
        #     blocked DDL/lock (this is the anti-cascade guard; lock_timeout was 0/unbounded before).
        #   • statement_timeout — a runaway query is killed (180s) rather than pinning a thread indefinitely.
        # NOTE: these only cover db_adapter connections. Raw psycopg2.connect() callers are covered by the
        # role-level `ALTER ROLE trade_ai SET lock_timeout/idle_in_transaction_session_timeout/statement_timeout`
        # (see docs/runbooks/DB_HANG_PREVENTION.md) — the universal backstop.
        try:
            with conn.cursor() as _c:
                _c.execute("SET idle_in_transaction_session_timeout = '120s'")
                _c.execute("SET lock_timeout = '3s'")
                _c.execute("SET statement_timeout = '180s'")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        _tls.conn = conn
        _tls.last_used = _time.time()
        if os.getenv("DB_CONN_TRACE"):
            try:
                import traceback as _tb, threading as _th, datetime as _dt2
                _stack = " <- ".join(
                    f"{fr.name}:{fr.lineno}" for fr in _tb.extract_stack()[-8:-1])
                with open(os.path.join(os.path.dirname(__file__), "..", "logs", "db_conn_trace.log"), "a") as _tf:
                    _tf.write(f"{_dt2.datetime.now():%H:%M:%S} OPEN  {_th.current_thread().name} :: {_stack}\n")
            except Exception:
                pass
        return conn
    except Exception as e:
        print(f"  [db_adapter] PostgreSQL connection failed: {e}")
        print(f"  [db_adapter] Falling back to JSON")
        return None


def close_thread_conn():
    """Close + clear THIS thread's connection. Call at the end of a threaded request so the
    multi-threaded server doesn't accumulate one open DB connection per request thread."""
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _tls.conn = None
        if os.getenv("DB_CONN_TRACE"):
            try:
                import threading as _th, datetime as _dt2
                with open(os.path.join(os.path.dirname(__file__), "..", "logs", "db_conn_trace.log"), "a") as _tf:
                    _tf.write(f"{_dt2.datetime.now():%H:%M:%S} CLOSE {_th.current_thread().name}\n")
            except Exception:
                pass


# Alias for scripts that import get_connection
get_connection = _get_conn


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
    """Load portfolio holdings from canonical holdings.json.

    The DB `holdings` table was retired 2026-07-03: its writer stopped running 2026-04-19,
    so the DB-first read here served a months-stale portfolio to every USE_DB caller
    (portfolio_yaml_advisor et al.). holdings.json is the single source of truth — it is
    what the brokers' syncs write through protected_holdings_write.
    """
    path = Path(state_dir) / "holdings.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_holdings(portfolio: Dict, state_dir: Path) -> None:
    """Save portfolio holdings to canonical holdings.json (DB mirror retired 2026-07-03)."""
    path = Path(state_dir) / "holdings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # MANDATORY wipe-guard: never zero/overwrite a good holdings snapshot with a bad payload.
    from holdings_guard import protected_holdings_write
    protected_holdings_write(portfolio, source="db_adapter.save_holdings", target_path=str(path))


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

    # Sanity guard: reject snapshots that jump >30% from the most recent saved value
    if USE_DB and date_str and total_value > 0:
        try:
            prev = _execute(
                "SELECT total_value FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 1",
                fetch="one"
            )
            if prev:
                prev_val = float(prev.get("total_value", 0))
                if prev_val > 0:
                    drift_pct = abs(total_value - prev_val) / prev_val * 100
                    if drift_pct > 30:
                        print(f"  [db_adapter] ⛔ SNAPSHOT REJECTED: ${total_value:,.0f} vs prev ${prev_val:,.0f} ({drift_pct:.1f}% drift > 30% guard)")
                        return
        except Exception:
            pass  # If we can't check, allow the write

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

    # JSON fallback — with drift guard
    snap_dir = Path(state_dir) / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{date_str}.json"

    # Check previous JSON snapshot for drift before writing
    _prev_files = sorted(snap_dir.glob("*.json"), key=lambda f: f.name, reverse=True)
    _json_ok = True
    for _pf in _prev_files[:3]:
        if _pf.name == snap_path.name:
            continue
        try:
            _pd = json.loads(_pf.read_text())
            _pv = float(_pd.get("total_value", 0))
            if _pv > 0:
                _drift = abs(total_value - _pv) / _pv * 100
                if _drift > 25:
                    print(f"  [db_adapter] ⛔ JSON SNAPSHOT REJECTED: ${total_value:,.0f} vs prev ${_pv:,.0f} ({_drift:.1f}% drift > 25%)")
                    _json_ok = False
                break
        except Exception:
            continue

    if _json_ok:
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
    import math as _math

    def _fit(v, max_abs):
        """Coerce to float that FITS the numeric column; NaN/inf/garbage-overflow → None.
        Prevents one extreme Finviz value (e.g. ELOX beta -148303, ytd +1.28M) from failing the
        whole batch INSERT — the bug that silently killed this feeder on 2026-06-12."""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if not _math.isfinite(f) or abs(f) >= max_abs:
            return None
        return f

    def _clean_json(o):
        """Recursively replace non-finite floats with None so the jsonb column never rejects the payload."""
        if isinstance(o, float):
            return o if _math.isfinite(o) else None
        if isinstance(o, dict):
            return {k: _clean_json(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_clean_json(v) for v in o]
        return o

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
            _fit(data.get("rsi"), 1000), _fit(data.get("beta"), 1000),       # rsi numeric(5,2), beta numeric(6,3)
            _fit(data.get("sma20_pct"), 10000), _fit(data.get("sma50_pct"), 10000), _fit(data.get("sma200_pct"), 10000),
            _fit(data.get("perf_week_pct"), 10000), _fit(data.get("perf_month_pct"), 10000), _fit(data.get("perf_ytd_pct"), 10000),
            _fit(data.get("week52_high_pct"), 10000), _fit(data.get("week52_low_pct"), 10000),   # all _pct numeric(6,2)
            str(data.get("recom", ""))[:20] if data.get("recom") else None,
            json.dumps(_clean_json(_full_data), default=str),
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


def notification_already_logged(dedupe_key: str) -> bool:
    """Check if a notification with this dedupe_key already exists."""
    if not USE_DB:
        return False
    result = _execute(
        "SELECT COUNT(*) AS cnt FROM notification_log WHERE dedupe_key = %s",
        (dedupe_key,), fetch="one"
    )
    return (result or {}).get("cnt", 0) > 0


def save_notification_log_entry(entry: dict) -> None:
    """Save a notification log entry. Upsert by dedupe_key."""
    if not USE_DB:
        return
    _execute(
        """INSERT INTO notification_log
           (notification_date, notification_type, channel, subject, body_summary,
            recommendation_ids, escalation_ids, observation_ids, payload,
            status, dedupe_key, sent_at, error)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (dedupe_key) DO UPDATE SET
            status = EXCLUDED.status,
            sent_at = EXCLUDED.sent_at,
            error = EXCLUDED.error,
            payload = EXCLUDED.payload""",
        (entry["notification_date"], entry["notification_type"], entry["channel"],
         entry.get("subject"), entry.get("body_summary"),
         entry.get("recommendation_ids"), entry.get("escalation_ids"),
         entry.get("observation_ids"),
         json.dumps(entry.get("payload", {}), default=str),
         entry.get("status", "queued"), entry["dedupe_key"],
         entry.get("sent_at"), entry.get("error"))
    )


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


# ── MAINTENANCE / QUERY HELPERS ────────────────────────────────────────────

def expire_stale_escalations() -> list:
    """Mark pending escalations past their expires_at as expired. Returns list of expired rows."""
    return _execute(
        """UPDATE escalation_queue SET status = 'expired'
           WHERE status = 'pending' AND expires_at IS NOT NULL
           AND expires_at < CURRENT_DATE
           RETURNING id, symbol, trigger_rule""",
        fetch="all"
    ) or []


def expire_stale_drafts() -> list:
    """Mark draft recommendations past their expires_at as expired. Returns list of expired rows."""
    return _execute(
        """UPDATE advisor_recommendations SET status = 'expired'
           WHERE status = 'draft' AND expires_at IS NOT NULL
           AND expires_at < CURRENT_DATE
           RETURNING id, symbol, action""",
        fetch="all"
    ) or []


def expire_stale_ai_watchlist() -> list:
    """Mark active AI-generated watchlist items past their expires_at as expired. Returns list of expired rows."""
    return _execute(
        """UPDATE watchlist_items SET status = 'expired', updated_at = now()
           WHERE source_type = 'ai_generated' AND status = 'active'
           AND data->>'expires_at' IS NOT NULL
           AND data->>'expires_at' < CURRENT_DATE::text
           RETURNING id, symbol""",
        fetch="all"
    ) or []


_WATCHLIST_ACTIVE_STATUSES = (
    "active", "researched", "review", "queued", "researching", "tracking",
)
_WATCHLIST_SOURCE_ALIASES = {
    "ai_generated": "ai_discovered",
    "analyst_curated": "ai_watchlist",
}


def get_active_watchlist_symbols(source_types: list | None = None) -> list:
    """Return non-removed watchlist symbols in active lifecycle statuses.

    source_types filters watchlist_items.source (legacy aliases mapped).
    Each row has a 'symbol' key.
    """
    statuses = _WATCHLIST_ACTIVE_STATUSES
    ph_status = ",".join(["%s"] * len(statuses))
    srcs: list[str] = []
    for raw in source_types or []:
        mapped = _WATCHLIST_SOURCE_ALIASES.get(raw, raw)
        if mapped and mapped not in srcs:
            srcs.append(mapped)
    if srcs:
        ph_src = ",".join(["%s"] * len(srcs))
        sql = (
            f"SELECT DISTINCT symbol FROM watchlist_items "
            f"WHERE status IN ({ph_status}) AND source IN ({ph_src}) "
            f"AND symbol IS NOT NULL"
        )
        params: tuple = tuple(statuses) + tuple(srcs)
    else:
        sql = (
            f"SELECT DISTINCT symbol FROM watchlist_items "
            f"WHERE status IN ({ph_status}) AND symbol IS NOT NULL"
        )
        params = tuple(statuses)
    return _execute(sql, params, fetch="all") or []


def get_escalations_by_date_severity(date_str: str, severity: int) -> list:
    """Return escalation rows for a given date and severity level."""
    return _execute(
        "SELECT id, symbol, severity, trigger_rule, summary, evidence FROM escalation_queue WHERE created_at::date = %s AND severity = %s",
        (date_str, severity), fetch="all"
    ) or []


def get_high_confidence_drafts(date_str: str, min_confidence: float = 0.90) -> list:
    """Return recommendation drafts at or above confidence threshold for a given date."""
    return _execute(
        "SELECT id, symbol, action, rationale, confidence FROM advisor_recommendations WHERE recommendation_date = %s AND status = 'draft' AND confidence >= %s",
        (date_str, min_confidence), fetch="all"
    ) or []


# ── ACTION QUEUE HELPERS ────────────────────────────────────────────────────

def action_queue_already_exists(dedupe_key: str) -> bool:
    """Check if an action_queue item with this dedupe_key exists."""
    row = _execute("SELECT 1 FROM action_queue WHERE dedupe_key = %s", (dedupe_key,), fetch="one")
    return row is not None


def save_action_queue_entry(entry: dict) -> None:
    """Upsert one action_queue row. For STOP_REVIEW: update existing pending row instead of creating duplicates."""
    action = entry.get("action", "")
    if action == "STOP_REVIEW":
        # Check if a pending STOP_REVIEW already exists
        existing = _execute(
            "SELECT id FROM action_queue WHERE action='STOP_REVIEW' AND status='pending' LIMIT 1",
            fetch="one"
        )
        if existing:
            _execute(
                "UPDATE action_queue SET rationale=%(rationale)s, confidence=%(confidence)s WHERE id=%(id)s",
                {**entry, "id": existing["id"]}
            )
            return
    _execute(
        """INSERT INTO action_queue
           (recommendation_id, symbol, action, rationale, confidence, urgency, status, expires_at, dedupe_key)
           VALUES (%(recommendation_id)s, %(symbol)s, %(action)s, %(rationale)s, %(confidence)s,
                   %(urgency)s, %(status)s, %(expires_at)s, %(dedupe_key)s)
           ON CONFLICT (dedupe_key) DO NOTHING""",
        entry
    )


def get_pending_action_queue() -> list:
    """Return all pending action_queue items."""
    return _execute(
        """SELECT id, recommendation_id, symbol, action, rationale, confidence, urgency, status, expires_at, dedupe_key, created_at
           FROM action_queue WHERE status = 'pending'
           ORDER BY urgency = 'urgent' DESC, confidence DESC, created_at DESC""",
        fetch="all"
    ) or []


# ── SERVER / API HELPERS ────────────────────────────────────────────────────

def get_personal_snapshot_at_date(target_date: str) -> list:
    """Return the latest personal_history row per field as of target_date."""
    return _execute(
        """SELECT DISTINCT ON (field_name)
               field_name, value, effective_date, recorded_at, note, source
           FROM personal_history
           WHERE effective_date <= %s
           ORDER BY field_name, effective_date DESC, recorded_at DESC""",
        (target_date,), fetch="all"
    ) or []


def get_personal_field_history(field_name: str) -> list:
    """Return all history rows for a single personal field, ordered by recorded_at."""
    return _execute(
        """SELECT value, effective_date, recorded_at, note, source
           FROM personal_history
           WHERE field_name = %s
           ORDER BY recorded_at ASC""",
        (field_name,), fetch="all"
    ) or []


def save_personal_history_entry(field_name: str, value, data_type: str, category: str,
                                 effective_date: str, note: str, source: str = "modal_edit") -> bool:
    """Insert one personal_history row. Returns True on success."""
    result = _execute(
        """INSERT INTO personal_history
           (field_name, value, data_type, category, effective_date, note, source)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (field_name, value, data_type, category, effective_date, note, source)
    )
    return result is not None and result is not False


def get_db_table_stats() -> list:
    """Return pg_stat_user_tables stats for the health endpoint."""
    return _execute("""
        SELECT s.relname AS name,
               s.n_live_tup AS live_rows,
               s.n_dead_tup AS dead_rows,
               pg_size_pretty(pg_total_relation_size(s.schemaname||'.'||s.relname)) AS size,
               s.last_autovacuum::text,
               s.last_autoanalyze::text
        FROM pg_stat_user_tables s
        ORDER BY pg_total_relation_size(s.schemaname||'.'||s.relname) DESC
    """, fetch="all") or []


def get_recent_notifications(limit: int = 20) -> list:
    """Return recent notification_log rows for display."""
    return _execute(
        """SELECT notification_date, notification_type, channel, status, subject,
                  body_summary, sent_at::text, dedupe_key
           FROM notification_log
           ORDER BY created_at DESC LIMIT %s""",
        (limit,), fetch="all"
    ) or []


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
