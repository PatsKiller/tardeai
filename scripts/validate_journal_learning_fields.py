#!/usr/bin/env python3
"""Validate journal learning field completeness for closed trades."""
import json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def validate():
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    cur = conn.cursor()

    fields = [
        "exit_reason", "closed_via", "pnl", "r_multiple", "hold_time_min",
        "entry_time", "exit_time", "closed_at", "stop_loss", "target_1",
        "max_favorable_excursion", "max_adverse_excursion", "entry_price", "exit_price",
    ]

    cur.execute(f"""
        SELECT COUNT(*) as total,
            {', '.join(f"COUNT(*) FILTER (WHERE {f} IS NOT NULL AND CAST({f} AS TEXT) != '') as has_{f}" for f in fields)}
        FROM paper_trades WHERE status = 'closed'
    """)
    row = cur.fetchone()
    total = row[0]

    results = {}
    for i, f in enumerate(fields):
        has = row[i + 1]
        pct = round(100 * has / max(total, 1), 1)
        results[f] = {"present": has, "missing": total - has, "pct": pct}

    # Stop geometry defects
    cur.execute("""
        SELECT COUNT(*) FROM paper_trades
        WHERE status = 'closed' AND stop_loss IS NOT NULL AND entry_price IS NOT NULL
          AND stop_loss >= entry_price
    """)
    stop_defects = cur.fetchone()[0]

    conn.close()

    print(f"Journal Learning Field Validation — {total} closed trades")
    print(f"{'Field':30s} {'Present':>8s} {'Missing':>8s} {'%':>6s} {'Status':>10s}")
    print("-" * 70)
    for f, v in results.items():
        status = "OK" if v["pct"] >= 90 else "WARN" if v["pct"] >= 50 else "CRITICAL"
        print(f"{f:30s} {v['present']:8d} {v['missing']:8d} {v['pct']:5.1f}% {status:>10s}")

    print(f"\nStop geometry defects (stop >= entry): {stop_defects}")
    return {"total": total, "fields": results, "stop_defects": stop_defects}


if __name__ == "__main__":
    validate()
