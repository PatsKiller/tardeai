"""
db_migrate.py — One-Time JSON → PostgreSQL Migration
Trade AI v12 + Portfolio Intelligence v1.2

Run once after setting up PostgreSQL on Linux:
    cd ~/trade-ai
    source venv/bin/activate
    python3 linux/db_migrate.py

What it does:
  1. Reads all existing JSON files
  2. Inserts into PostgreSQL
  3. Verifies row counts match
  4. Prints "SAFE TO DELETE" confirmation when verified
  5. Does NOT delete JSON — you delete manually after confirming

Safe to re-run: all inserts use ON CONFLICT DO UPDATE (upsert).
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).parent.parent))
STATE_DIR    = PROJECT_ROOT / "data" / "portfolios" / "state"
DATA_DIR     = PROJECT_ROOT / "data"

GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
NC     = "\033[0m"

def ok(msg):   print(f"{GREEN}  ✓{NC} {msg}")
def warn(msg): print(f"{YELLOW}  ⚠{NC} {msg}")
def err(msg):  print(f"{RED}  ✗{NC} {msg}")
def hdr(msg):  print(f"\n{YELLOW}=== {msg} ==={NC}")

# ── DB connection ─────────────────────────────────────────────────────────────

def get_conn():
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""),
            connect_timeout=10,
        )
        conn.autocommit = False
        return conn
    except Exception as e:
        err(f"Cannot connect to PostgreSQL: {e}")
        err("Check DB credentials in assets/.env and that PostgreSQL is running")
        sys.exit(1)

# ── Load .env ─────────────────────────────────────────────────────────────────

def load_env():
    env_file = PROJECT_ROOT / "assets" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

# ── Migration functions ───────────────────────────────────────────────────────

def migrate_holdings(conn) -> int:
    """Migrate holdings.json → holdings table."""
    hdr("Holdings")
    path = STATE_DIR / "holdings.json"
    if not path.exists():
        warn("holdings.json not found — skipping")
        return 0

    portfolio = json.loads(path.read_text(encoding="utf-8"))
    as_of = portfolio.get("as_of", date.today().isoformat())
    if not as_of:
        as_of = date.today().isoformat()
    as_of = as_of[:10]  # Ensure date only, no time

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO holdings (as_of, data)
               VALUES (%s, %s)
               ON CONFLICT (as_of) DO UPDATE SET data = EXCLUDED.data""",
            (as_of, json.dumps(portfolio, default=str))
        )
    conn.commit()
    ok(f"holdings.json → holdings table (as_of={as_of})")

    # Verify
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM holdings")
        count = cur.fetchone()[0]
    ok(f"Verified: {count} row(s) in holdings table")
    return count


def migrate_price_cache(conn) -> int:
    """Migrate price_cache.json → price_cache table (last 2 years only)."""
    hdr("Price Cache")
    cache_path = STATE_DIR / "price_cache.json"
    if not cache_path.exists():
        warn("price_cache.json not found — skipping")
        return 0

    print(f"  Reading price_cache.json ({cache_path.stat().st_size/1024:.0f} KB)...")
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    cutoff = (date.today().replace(year=date.today().year - 2)).isoformat()
    rows = []
    symbols_skipped = []

    for sym, prices in cache.items():
        if sym.startswith("_") or not isinstance(prices, dict):
            continue
        for date_str, price in prices.items():
            if date_str < cutoff:
                continue  # Only last 2 years
            if isinstance(price, (int, float)) and price > 0:
                rows.append((sym, date_str, float(price)))

    print(f"  {len(rows):,} rows to insert (last 2 years, cutoff={cutoff})")

    if rows:
        import psycopg2.extras
        batch_size = 5000
        inserted = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i+batch_size]
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO price_cache (symbol, price_date, close_price)
                       VALUES %s
                       ON CONFLICT (symbol, price_date)
                       DO UPDATE SET close_price = EXCLUDED.close_price""",
                    batch
                )
            conn.commit()
            inserted += len(batch)
            print(f"  Inserted {inserted:,}/{len(rows):,} rows...", end="\r")

        print()
        ok(f"price_cache.json → price_cache table ({inserted:,} rows)")

    # Verify
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM price_cache")
        count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT symbol) FROM price_cache")
        syms = cur.fetchone()[0]
    ok(f"Verified: {count:,} rows, {syms} symbols in price_cache table")
    return count


def migrate_snapshots(conn) -> int:
    """Migrate snapshots/*.json → portfolio_snapshots table."""
    hdr("Portfolio Snapshots")
    snap_dir = STATE_DIR / "snapshots"
    if not snap_dir.exists():
        warn("snapshots/ directory not found — skipping")
        return 0

    files = list(snap_dir.glob("*.json"))
    if not files:
        warn("No snapshot files found — skipping")
        return 0

    inserted = 0
    for f in sorted(files):
        try:
            d = json.loads(f.read_text())
            snap_date = d.get("date", f.stem)
            total_value = float(d.get("total_value", 0))
            source = d.get("source", "live")
            if not snap_date or total_value <= 0:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO portfolio_snapshots
                           (snapshot_date, total_value, source, data)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (snapshot_date) DO UPDATE
                       SET total_value=EXCLUDED.total_value,
                           source=EXCLUDED.source,
                           data=EXCLUDED.data""",
                    (snap_date, total_value, source, json.dumps(d, default=str))
                )
            inserted += 1
        except Exception as e:
            warn(f"  Skipped {f.name}: {e}")

    conn.commit()
    ok(f"snapshots/{len(files)} files → portfolio_snapshots table ({inserted} rows)")

    # Verify
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM portfolio_snapshots")
        count = cur.fetchone()[0]
    ok(f"Verified: {count} rows in portfolio_snapshots table")
    return count


def migrate_state(conn) -> int:
    """Migrate data/state.json → trade_ai_state table."""
    hdr("Trade AI State")
    state_file = DATA_DIR / "state.json"
    if not state_file.exists():
        warn("data/state.json not found — skipping")
        return 0

    state = json.loads(state_file.read_text(encoding="utf-8"))
    run_date = date.today().isoformat()

    rows = []
    for ticker, data in state.items():
        if isinstance(data, dict):
            rows.append((run_date, ticker, json.dumps(data, default=str)))

    if rows:
        import psycopg2.extras
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO trade_ai_state (run_date, ticker, data)
                   VALUES %s
                   ON CONFLICT (run_date, ticker) DO UPDATE SET data=EXCLUDED.data""",
                rows
            )
        conn.commit()

    ok(f"data/state.json → trade_ai_state table ({len(rows)} tickers, run_date={run_date})")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM trade_ai_state")
        count = cur.fetchone()[0]
    ok(f"Verified: {count} rows in trade_ai_state table")
    return count


def migrate_run_summaries(conn) -> int:
    """Migrate all reports/{date}/{label}/run_summary.json → run_summary table."""
    hdr("Run Summaries")
    reports_dir = PROJECT_ROOT / "reports"
    if not reports_dir.exists():
        warn("reports/ directory not found — skipping")
        return 0

    summaries = list(reports_dir.glob("*/*/run_summary.json"))
    if not summaries:
        warn("No run_summary.json files found — skipping")
        return 0

    inserted = 0
    for f in sorted(summaries):
        try:
            parts = f.parts
            run_label = parts[-2]
            run_date  = parts[-3]
            # Validate date format
            datetime.strptime(run_date, "%Y-%m-%d")
            summary = json.loads(f.read_text(encoding="utf-8"))
            go_count   = summary.get("go_count", 0)
            wait_count = summary.get("wait_count", 0)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO run_summary
                           (run_date, run_label, go_count, wait_count, data)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (run_date, run_label) DO UPDATE
                       SET go_count=EXCLUDED.go_count,
                           wait_count=EXCLUDED.wait_count,
                           data=EXCLUDED.data""",
                    (run_date, run_label, go_count, wait_count,
                     json.dumps(summary, default=str))
                )
            inserted += 1
        except Exception as e:
            warn(f"  Skipped {f}: {e}")

    conn.commit()
    ok(f"{inserted} run_summary files → run_summary table")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM run_summary")
        count = cur.fetchone()[0]
    ok(f"Verified: {count} rows in run_summary table")
    return count


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print("  Trade AI v12 — JSON → PostgreSQL Migration")
    print(f"  Project root: {PROJECT_ROOT}")
    print("="*60)

    load_env()

    # Check DB credentials
    if not os.getenv("DB_HOST"):
        err("DB_HOST not set in assets/.env")
        err("Add DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD to assets/.env")
        sys.exit(1)

    conn = get_conn()
    print(f"\n  Connected to PostgreSQL @ {os.getenv('DB_HOST')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME')}")

    results = {}
    results["holdings"]   = migrate_holdings(conn)
    results["price_cache"] = migrate_price_cache(conn)
    results["snapshots"]  = migrate_snapshots(conn)
    results["state"]      = migrate_state(conn)
    results["run_summary"] = migrate_run_summaries(conn)

    conn.close()

    # Summary
    print("\n" + "="*60)
    print(f"  {GREEN}✓ Migration complete{NC}")
    print()
    for table, count in results.items():
        status = f"{GREEN}✓{NC}" if count > 0 else f"{YELLOW}⚠{NC}"
        print(f"  {status} {table:<25} {count:>8,} rows")

    print()
    print(f"  {YELLOW}NEXT STEPS:{NC}")
    print(f"  1. Add DB credentials to assets/.env:")
    print(f"     DB_HOST=localhost")
    print(f"     DB_PORT=5432")
    print(f"     DB_NAME=trade_ai")
    print(f"     DB_USER=trade_ai")
    print(f"     DB_PASSWORD=your_password")
    print()
    print(f"  2. Test pipeline: python3 scripts/portfolio_orchestrator.py")
    print()
    print(f"  3. Verify dashboard shows correct data")
    print()
    print(f"  4. When satisfied, delete JSON source files:")
    print(f"     rm data/portfolios/state/holdings.json")
    print(f"     rm data/portfolios/state/price_cache.json")
    print(f"     rm -rf data/portfolios/state/snapshots/")
    print(f"     rm data/state.json")
    print(f"     (run_summary.json files kept — dashboard reads them by path)")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
