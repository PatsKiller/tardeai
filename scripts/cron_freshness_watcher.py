#!/usr/bin/env python3
"""cron_freshness_watcher.py — auto-detect and restart stale cron jobs.

Runs every 5 minutes via cron/timer. Checks freshness of critical data sources
(timestamps in DB or files), and auto-retries any that exceed their thresholds
with flock guards (no duplicate runs). Logs to system_health_events DB table.

Safety: advisory by default. Never raises. Only runs allowlisted retry commands.
"""

import os, sys, json, time, subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load DB credentials from .env (same as db_adapter._load_dotenv_if_needed)
if not os.getenv("DB_PASSWORD"):
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'\"")
                if key.startswith("DB_") and key not in os.environ:
                    os.environ[key] = val
    # Load from env_bootstrap if available (tmpfs SM render)
    if not os.getenv("DB_PASSWORD"):
        try:
            _lib = str(PROJECT_ROOT / "scripts" / "lib")
            if _lib not in sys.path:
                sys.path.insert(0, _lib)
            from env_bootstrap import load_env
            load_env()
        except Exception:
            pass

# ── DB helper (lightweight, no db_adapter import to avoid pool contention) ────
def _db(sql, params=None, fetch=None):
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""),
            connect_timeout=8,
        )
        conn.autocommit = False
        try:
            with conn.cursor() as c:
                c.execute("SET lock_timeout = '3s'")
                c.execute("SET statement_timeout = '30s'")
                c.execute("SET idle_in_transaction_session_timeout = '60s'")
            conn.commit()
        except Exception:
            conn.rollback()
        try:
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
            print(f"[cron_watcher] DB error: {e}")
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[cron_watcher] DB connect failed: {e}")
        return None


def log_event(component: str, event_type: str, message: str, success: bool, action_taken: str = ""):
    """Log to system_health_events table."""
    _db(
        """INSERT INTO system_health_events (component, event_type, severity, message, action_taken, success, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
        (component, event_type, "LOW" if success else "MEDIUM", message, action_taken, success),
        fetch=None,
    )


# ── Freshness checks ──────────────────────────────────────────────────────────

CHECKS = [
    # (label, type, sql/filesystem_check, max_age_hours, retry_cmd)
    {
        "label": "finnhub",
        "check": "SELECT MAX(published_at) FROM news_articles WHERE source = 'finnhub'",
        "max_hours": 12.0,
        "retry_cmd": "flock -n /tmp/finnhub_ingest.lock .venv/bin/python scripts/data_ingest/news_ingest.py --source finnhub >> logs/finnhub_ingest.log 2>&1",
        "retry_timeout_s": 300,
    },
    {
        "label": "yahoo_finance",
        "check": "SELECT MAX(updated_at) FROM price_cache WHERE symbol IN ('SPY','QQQ')",
        "max_hours": 24.0,
        "retry_cmd": "flock -n /tmp/snapshot_daily.lock .venv/bin/python scripts/data_ingest/run_daily_snapshots.py >> logs/snapshot_daily.log 2>&1",
        "retry_timeout_s": 600,
    },
    {
        "label": "finviz",
        "check": "SELECT MAX(last_run) FROM finviz_screeners WHERE active",
        "max_hours": 6.0,
        "retry_cmd": "flock -n /tmp/finviz_scalp.lock .venv/bin/python scripts/run_finviz_momentum_scalp_scan.py >> logs/finviz_scalp.log 2>&1",
        "retry_timeout_s": 300,
    },
    {
        "label": "finviz_quote_cache",
        "check": None,  # file-based
        "file_check": PROJECT_ROOT / "data" / "portfolios" / "state" / "finviz_quote_cache.json",
        "max_hours": 6.0,
        "retry_cmd": "flock -n /tmp/finviz_quotes.lock .venv/bin/python scripts/data_ingest/refresh_finviz_quotes.py >> logs/finviz_quotes.log 2>&1",
        "retry_timeout_s": 300,
    },
    {
        "label": "watch_decision",
        "check": "SELECT EXTRACT(EPOCH FROM (NOW() - MAX(updated_at)))/3600.0 FROM watchlist_items WHERE updated_at IS NOT NULL",
        "max_hours": 8.0,
        "retry_cmd": "flock -n /tmp/watch_decision_scheduler.lock .venv/bin/python scripts/watch_decision_scheduler.py --run >> logs/watch_decision_scheduler.log 2>&1",
        "retry_timeout_s": 600,
    },
    {
        "label": "entry_planner",
        "check": "SELECT EXTRACT(EPOCH FROM (NOW() - MAX(updated_at)))/3600.0 FROM watchlist_items WHERE updated_at IS NOT NULL",
        "max_hours": 8.0,
        "retry_cmd": "flock -n /tmp/entry_planner.lock .venv/bin/python scripts/watchlist_entry_planner.py --main-lane --limit 40 --lane deepseek-flash --no-alert >> logs/entry_planner.log 2>&1",
        "retry_timeout_s": 600,
    },
    {
        "label": "schwab_sync",
        "check": "SELECT MAX(created_at) FROM trade_closed",
        "max_hours": 24.0,
        "retry_cmd": "flock -n /tmp/schwab_sync.lock .venv/bin/python scripts/schwab_positions_sync.py >> logs/schwab_sync.log 2>&1",
        "retry_timeout_s": 300,
    },
    {
        "label": "indicator_cache",
        "check": "SELECT EXTRACT(EPOCH FROM (NOW() - MAX(computed_at)))/3600.0 FROM indicator_confluence_cache",
        "max_hours": 48.0,
        "retry_cmd": "flock -n /tmp/indicator_cache_refresh.lock .venv/bin/python scripts/data_broker_indicator_refresh.py --operator-desks --limit 160 --sleep-ms 400 --max-age-hours 96 >> logs/indicator_refresh.log 2>&1",
        "retry_timeout_s": 600,
    },
]


def check_freshness():
    now = datetime.now(timezone.utc)
    issues_found = 0
    fixes_attempted = 0

    for cfg in CHECKS:
        label = cfg["label"]
        max_age_s = cfg["max_hours"] * 3600

        # Determine last timestamp
        last_ts = None
        if cfg.get("check"):
            row = _db(cfg["check"], fetch="one")
            if row:
                vals = list(row.values())
                if vals and vals[0]:
                    last_ts = vals[0]
                    if last_ts and hasattr(last_ts, "tzinfo") and last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
        elif cfg.get("file_check"):
            fp = cfg["file_check"]
            if fp.exists():
                last_ts = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)

        if last_ts is None:
            print(f"[cron_watcher] {label}: no data (never run?)")
            log_event("cron_freshness", f"{label}_missing", f"No data for {label} — never run?", False)
            issues_found += 1
            continue

        from datetime import datetime as _dt2
        if isinstance(last_ts, _dt2):
            # Datetime column — compute age directly
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            age_s = (now - last_ts).total_seconds()
            age_h = age_s / 3600
        else:
            # Numeric result from EXTRACT(EPOCH)/3600 — age in hours as Decimal
            age_h = float(last_ts)
            age_s = age_h * 3600

        if age_s < max_age_s:
            print(f"[cron_watcher] {label}: fresh ({age_h:.1f}h ago, max {cfg['max_hours']}h)")
            continue

        print(f"[cron_watcher] {label}: STALE ({age_h:.1f}h, max {cfg['max_hours']}h) — attempting retry")
        issues_found += 1
        fixes_attempted += _retry_job(cfg, label, age_h)

    return issues_found, fixes_attempted


def _retry_job(cfg, label, age_h):
    """Run a single retry command with timeout and logging."""
    retry_cmd = cfg["retry_cmd"]
    timeout = cfg.get("retry_timeout_s", 300)
    try:
        result = subprocess.run(
            retry_cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(PROJECT_ROOT),
        )
        ok = result.returncode == 0
        log_event("cron_freshness", f"{label}_retry",
                  f"{'OK' if ok else 'FAILED'}: {label} stale {age_h:.1f}h (exit={result.returncode})",
                  ok, f"flock {retry_cmd}")
        if not ok:
            print(f"  stderr: {result.stderr[:200]}")
        return 1 if ok else 0
    except subprocess.TimeoutExpired:
        log_event("cron_freshness", f"{label}_retry_timeout",
                  f"TIMEOUT: {label} retry exceeded {timeout}s", False)
        return 0
    except Exception as e:
        log_event("cron_freshness", f"{label}_retry_error",
                  f"ERROR: {label} retry failed: {e}", False)
        return 0


def main():
    print(f"[cron_watcher] {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} checking {len(CHECKS)} sources...")
    issues, fixes = check_freshness()
    print(f"[cron_watcher] done: {issues} stale, {fixes} retried")


if __name__ == "__main__":
    main()
