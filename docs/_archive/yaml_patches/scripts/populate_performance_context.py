#!/usr/bin/env python3
"""
populate_performance_context.py
================================
Reads paper trade performance from paper_performance_governance table
(or paper_trades + paper_trade_proposals if governance table not yet populated)
and writes per-strategy stats into the performance_context block of each
strategy YAML.

Designed to run nightly (e.g. 02:00 ET cron) after paper_performance_governance.py.

The LLM prompts read the performance_context block at proposal-analysis time
to inform evaluation:
  "swing_breakout has won 18 of 31 paper trades, PF 1.4 — proceed with confidence"
  vs
  "momentum_scalp has 4 of 12 wins, PF 0.7 — heightened scrutiny"

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/populate_performance_context.py --dry-run
    python3 scripts/populate_performance_context.py --apply

Cron entry (nightly at 02:30 ET):
    30 2 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && \\
        .venv/bin/python scripts/populate_performance_context.py --apply >> logs/perf_context.log 2>&1

Author: Trade AI v12 Session 33 patch package
Date: 2026-05-13
"""

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from ruamel.yaml import YAML
except ImportError:
    print("ERROR: ruamel.yaml not installed. Run: pip install ruamel.yaml --break-system-packages")
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary --break-system-packages")
    sys.exit(1)


def make_yaml():
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def get_db_conn():
    """Get DB connection from environment (.env)."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "trade_ai"),
    )


def fetch_governance_stats(conn) -> dict:
    """
    Try paper_performance_governance table first. Fall back to computing from
    paper_trades if that table is empty/missing.

    Returns: { strategy_id: stats_dict }
    """
    stats_by_strategy = {}

    # First try the governance table
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    strategy_id,
                    closed_trade_count,
                    win_rate,
                    avg_r_realized,
                    profit_factor,
                    max_drawdown_pct,
                    expectancy_per_trade,
                    best_trade_r,
                    worst_trade_r,
                    current_streak,
                    ready_for_review,
                    last_calculated
                FROM paper_performance_governance
            """)
            rows = cur.fetchall()
            for row in rows:
                stats_by_strategy[row["strategy_id"]] = dict(row)
            if stats_by_strategy:
                print(f"  Loaded governance stats for {len(stats_by_strategy)} strategies")
                return stats_by_strategy
    except psycopg2.Error as e:
        conn.rollback()
        print(f"  governance table query failed: {e}")
        print(f"  falling back to computing from paper_trades")

    # Fallback: compute from paper_trades directly
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    strategy_id,
                    COUNT(*) FILTER (WHERE status = 'closed') AS closed_count,
                    COUNT(*) FILTER (WHERE status = 'closed' AND realized_r > 0) AS wins,
                    AVG(realized_r) FILTER (WHERE status = 'closed') AS avg_r,
                    SUM(realized_pnl) FILTER (WHERE realized_pnl > 0) AS gross_profit,
                    SUM(realized_pnl) FILTER (WHERE realized_pnl < 0) AS gross_loss,
                    MAX(realized_r) FILTER (WHERE status = 'closed') AS best_r,
                    MIN(realized_r) FILTER (WHERE status = 'closed') AS worst_r,
                    MAX(updated_at) AS last_trade_at
                FROM paper_trades
                WHERE status = 'closed'
                GROUP BY strategy_id
            """)
            for row in cur.fetchall():
                closed = row["closed_count"] or 0
                wins = row["wins"] or 0
                wr = (wins / closed) if closed else None
                gp = float(row["gross_profit"] or 0)
                gl = abs(float(row["gross_loss"] or 0))
                pf = (gp / gl) if gl > 0 else None

                stats_by_strategy[row["strategy_id"]] = {
                    "closed_trade_count": closed,
                    "win_rate": wr,
                    "avg_r_realized": float(row["avg_r"]) if row["avg_r"] is not None else None,
                    "profit_factor": pf,
                    "max_drawdown_pct": None,  # would need separate calc
                    "expectancy_per_trade": (wr * (row["avg_r"] or 0)) if wr and row["avg_r"] else None,
                    "best_trade_r": float(row["best_r"]) if row["best_r"] is not None else None,
                    "worst_trade_r": float(row["worst_r"]) if row["worst_r"] is not None else None,
                    "current_streak": None,
                    "ready_for_review": (closed >= 30 and (pf or 0) >= 1.25 and (wr or 0) >= 0.50),
                    "last_calculated": row["last_trade_at"],
                }
            print(f"  Computed fallback stats for {len(stats_by_strategy)} strategies")
    except psycopg2.Error as e:
        conn.rollback()
        print(f"  fallback query also failed: {e}")
        return {}

    return stats_by_strategy


def update_yaml(yaml_path: Path, stats: dict, dry_run: bool, backup_dir: Path) -> bool:
    """Update the performance_context block in a single YAML."""
    yaml = make_yaml()
    try:
        with open(yaml_path, "r") as f:
            data = yaml.load(f)
    except Exception as e:
        print(f"  {yaml_path.stem}: YAML load failed: {e}")
        return False

    if data is None:
        return False

    # Ensure performance_context block exists
    if "performance_context" not in data:
        print(f"  {yaml_path.stem}: no performance_context block (run bulk_patch first)")
        return False

    ctx = data["performance_context"]

    # Update with stats
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ctx["last_updated"] = now
    ctx["closed_paper_trades"] = stats.get("closed_trade_count", 0)

    # Round floats to keep YAML clean
    def r(v, digits=4):
        if v is None:
            return None
        return round(float(v), digits)

    ctx["win_rate"] = r(stats.get("win_rate"))
    ctx["avg_r_realized"] = r(stats.get("avg_r_realized"))
    ctx["profit_factor"] = r(stats.get("profit_factor"))
    ctx["max_drawdown_pct"] = r(stats.get("max_drawdown_pct"))
    ctx["expectancy_per_trade"] = r(stats.get("expectancy_per_trade"))
    ctx["best_trade_r"] = r(stats.get("best_trade_r"))
    ctx["worst_trade_r"] = r(stats.get("worst_trade_r"))
    ctx["current_streak"] = stats.get("current_streak")
    ctx["ready_for_review"] = bool(stats.get("ready_for_review", False))

    if dry_run:
        print(f"  {yaml_path.stem}: would update — trades={ctx['closed_paper_trades']}, wr={ctx['win_rate']}, pf={ctx['profit_factor']}")
    else:
        backup_path = backup_dir / yaml_path.name
        shutil.copy2(yaml_path, backup_path)
        with open(yaml_path, "w") as f:
            yaml.dump(data, f)
        print(f"  {yaml_path.stem}: updated — trades={ctx['closed_paper_trades']}, wr={ctx['win_rate']}, pf={ctx['profit_factor']}")

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--config-dir", default="config/strategies")
    parser.add_argument("--backup-root", default="backups")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)

    print(f"populate_performance_context — {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"Started: {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 80)

    # Connect to DB
    conn = None
    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"DB connection failed: {e}")
        print("Soft-fail: skipping performance context update for this run.")
        print("The performance_context blocks remain in place (populated by bulk_patch run);")
        print("they just won't be refreshed with the latest stats until the DB is reachable.")
        return 0

    # Fetch stats
    print("Loading performance stats from database...")
    stats_by_strategy = fetch_governance_stats(conn)
    if not stats_by_strategy:
        print("WARN: no performance stats available — YAMLs will get empty context")

    # Backup directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(args.backup_root) / f"perf_context_{timestamp}"
    if args.apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        print(f"Backup dir: {backup_dir}")

    config_dir = Path(args.config_dir)
    yaml_files = sorted(config_dir.glob("*.yaml"))
    yaml_files = [
        f for f in yaml_files
        if not f.stem.startswith("_") and f.stem != "shared_risk_rules"
    ]

    print(f"\nUpdating {len(yaml_files)} strategy YAMLs:")
    print("-" * 80)

    updated = 0
    for yaml_path in yaml_files:
        strategy_id = yaml_path.stem
        stats = stats_by_strategy.get(strategy_id, {
            "closed_trade_count": 0,
            "win_rate": None,
            "avg_r_realized": None,
            "profit_factor": None,
            "max_drawdown_pct": None,
            "expectancy_per_trade": None,
            "best_trade_r": None,
            "worst_trade_r": None,
            "current_streak": None,
            "ready_for_review": False,
        })
        if update_yaml(yaml_path, stats, args.dry_run, backup_dir):
            updated += 1

    conn.close()

    print("-" * 80)
    print(f"Updated: {updated}/{len(yaml_files)} files")
    print(f"Finished: {datetime.now().isoformat(timespec='seconds')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
