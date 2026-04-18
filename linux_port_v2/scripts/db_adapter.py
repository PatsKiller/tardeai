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
                result = None
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
