"""Classifier Health Check — daily monitoring for strategy-per-ticker inflation.

n8n refactor wave 1 (2026-10-10):
  * The result JSON is written through the persistent-state resolution layer
    (``durable_write_targets("data/monitoring/classifier_health.json", PROJECT_ROOT)``): the served
    persistent-state copy first, then the checkout/release copy the current registry row still
    reads. Before, it was written cwd-relative into the release-local ``CURRENT/data/monitoring/``,
    which the next deploy replaces with an empty dir (AGENTS.md §9.4).
  * A real run also writes ``<state_root>/data/runtime/classifier-health-check_last.json``
    (LaneRunReceipt@v1; ok_at only when the check ran).
  * Exit 0 = the check ran (a detected regression is a FINDING, carried in both files and printed);
    exit 1 = the check itself failed. Before 2026-10-10 a regression exited 1.
  * ``--dry-run`` runs the same read-only SELECTs, prints the result and the paths it would write,
    and writes nothing.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.append(str(PROJECT_ROOT))  # persistent_state_root imports scripts.lib.*
_ENV_FILE = PROJECT_ROOT / ".env"
# A missing .env (worktree / CI) no longer crashes at import; the DB connect then fails honestly (exit 1).
for line in _ENV_FILE.read_text().splitlines() if _ENV_FILE.exists() else []:
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

THRESHOLD = 3
LANE_ID = "classifier-health-check"
RESULT_REL = "data/monitoring/classifier_health.json"


def check():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
    # Read-only by construction: this check only SELECTs.
    conn.set_session(readonly=True)
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol, COUNT(DISTINCT strategy_id) AS sc,
                          ARRAY_AGG(DISTINCT strategy_id) AS strategies
                   FROM strategy_signals WHERE fired_at > NOW() - INTERVAL '1 day'
                   GROUP BY symbol HAVING COUNT(DISTINCT strategy_id) > %s
                   ORDER BY sc DESC LIMIT 10""",
        (THRESHOLD,),
    )
    violations = cur.fetchall()
    cur.execute("""SELECT COALESCE(MAX(sc), 0) FROM (
                     SELECT COUNT(DISTINCT strategy_id) AS sc
                     FROM strategy_signals WHERE fired_at > NOW() - INTERVAL '1 day'
                     GROUP BY symbol) x""")
    max_strats = cur.fetchone()[0]
    conn.close()
    return {
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "threshold": THRESHOLD,
        "violation_count": len(violations),
        "max_strategies_per_ticker_1d": max_strats,
        "regression_detected": max_strats > THRESHOLD,
        "top_violators": [{"symbol": v[0], "count": v[1], "strategies": list(v[2])} for v in violations[:5]],
    }


def result_targets():
    """Served persistent-state copy first, then the checkout/release copy (dual-write, §9.4)."""
    from lib.persistent_state_root import durable_write_targets

    return durable_write_targets(RESULT_REL, PROJECT_ROOT, require_persistent_dir=False)


def write_result(result, targets=None):
    from lib.atomic_json_store import atomic_write_json

    written = []
    for path in targets or result_targets():
        atomic_write_json(path, result, indent=2)
        written.append(str(path))
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="Classifier health check")
    ap.add_argument("--dry-run", action="store_true", help="run the SELECTs, print, write nothing")
    args = ap.parse_args(argv)
    from lib.lane_last_receipt import dry_run_report, now_iso, write_lane_receipt

    started = now_iso()
    try:
        result = check()
    except Exception as exc:  # noqa: BLE001 — recorded, then a non-zero exit (never swallowed)
        print(f"Classifier health: CHECK FAILED — {type(exc).__name__}: {str(exc)[:200]}")
        if not args.dry_run:
            write_lane_receipt(
                LANE_ID,
                ok=False,
                started_at=started,
                script="classifier_health_check.py",
                exit_code=1,
                summary={"error": f"{type(exc).__name__}: {str(exc)[:200]}"},
            )
        return 1
    print(json.dumps(result, indent=2))
    summary = {
        k: result[k] for k in ("checked_at", "violation_count", "max_strategies_per_ticker_1d", "regression_detected")
    }
    if args.dry_run:
        dry_run_report(LANE_ID, summary, would_write=[str(p) for p in result_targets()])
    else:
        try:
            summary["written"] = write_result(result)
        except Exception as exc:  # noqa: BLE001
            print(f"Classifier health: result write FAILED — {type(exc).__name__}: {exc}")
            write_lane_receipt(
                LANE_ID,
                ok=False,
                started_at=started,
                script="classifier_health_check.py",
                exit_code=1,
                summary={**summary, "error": f"write {type(exc).__name__}"},
            )
            return 1
        write_lane_receipt(
            LANE_ID, ok=True, started_at=started, script="classifier_health_check.py", exit_code=0, summary=summary
        )
    if result["regression_detected"]:
        print("\n!!! CLASSIFIER REGRESSION DETECTED !!!")
    else:
        print("\nClassifier health: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
