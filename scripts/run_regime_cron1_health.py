#!/usr/bin/env python3
"""run_regime_cron1_health.py — Read-only risk-regime health report.

Default: read-only. No mutations unless explicit flags.
"""
import argparse, json, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def main():
    p = argparse.ArgumentParser(description="Risk regime health report (default: read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--run-classifier-once", action="store_true", help="Run classifier once (apply)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)
    cur = conn.cursor()

    now = datetime.now(timezone.utc)

    # Latest snapshot
    cur.execute("SELECT snapshot_id, regime_label, confidence, stale_data, generated_at, summary FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
    snap = cur.fetchone()
    snap_data = None
    snap_age_hours = None
    if snap:
        snap_data = {"snapshot_id": snap[0], "regime": snap[1], "confidence": float(snap[2] or 0),
                     "stale": snap[3], "generated_at": str(snap[4]), "summary": snap[5]}
        gen = snap[4]
        if gen.tzinfo is None:
            from datetime import timezone as tz
            gen = gen.replace(tzinfo=tz.utc)
        snap_age_hours = round((now - gen).total_seconds() / 3600, 1)
        snap_data["age_hours"] = snap_age_hours

    # Latest run log
    cur.execute("SELECT run_id, status, started_at, finished_at, indicators_read, snapshots_created, errors FROM risk_regime_run_log ORDER BY started_at DESC LIMIT 1")
    run_row = cur.fetchone()
    run_data = None
    if run_row:
        run_data = {"run_id": run_row[0], "status": run_row[1], "started_at": str(run_row[2]),
                    "finished_at": str(run_row[3]), "indicators_read": run_row[4],
                    "snapshots_created": run_row[5], "errors": run_row[6]}

    # Indicators
    cur.execute("SELECT COUNT(*), MAX(created_at) FROM market_regime_indicators")
    ind_row = cur.fetchone()
    ind_count, ind_latest = ind_row[0], str(ind_row[1]) if ind_row[1] else None

    # Rotation signals
    cur.execute("SELECT COUNT(*), MAX(created_at) FROM strategy_rotation_signals")
    sig_row = cur.fetchone()
    sig_count, sig_latest = sig_row[0], str(sig_row[1]) if sig_row[1] else None

    # Cron check
    try:
        cron_out = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        cron_has_wrapper = "run_scheduled_risk_regime_classifier" in cron_out.stdout
        cron_has_original = "market_regime_classifier" in cron_out.stdout
    except Exception:
        cron_has_wrapper = False
        cron_has_original = False

    # Wrapper exists
    wrapper_exists = (PROJ / "scripts" / "run_scheduled_risk_regime_classifier.sh").exists()

    # Schema contract
    schema_ok = True
    try:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='market_regime_snapshots'")
        snap_cols = {r[0] for r in cur.fetchall()}
        required = {"snapshot_id", "generated_at", "regime_label", "confidence", "stale_data"}
        schema_ok = required.issubset(snap_cols)
    except Exception:
        schema_ok = False

    conn.close()

    # Health assessment
    stale_threshold = 26  # hours (allow for weekends/holidays)
    is_stale = snap_age_hours is not None and snap_age_hours > stale_threshold
    health = "healthy"
    if snap_data is None:
        health = "no_snapshot"
    elif is_stale:
        health = "stale"
    elif run_data and run_data["status"] == "failed":
        health = "last_run_failed"
    elif not schema_ok:
        health = "schema_mismatch"

    report = {
        "generated_at": now.isoformat(),
        "health": health,
        "snapshot": snap_data,
        "snapshot_stale": is_stale,
        "stale_threshold_hours": stale_threshold,
        "latest_run": run_data,
        "indicators_count": ind_count,
        "indicators_latest": ind_latest,
        "rotation_signals_count": sig_count,
        "rotation_signals_latest": sig_latest,
        "cron_wrapper_installed": cron_has_wrapper,
        "cron_original_installed": cron_has_original,
        "wrapper_exists": wrapper_exists,
        "schema_contract_ok": schema_ok,
        "recommended_action": (
            "none" if health == "healthy" else
            "run classifier" if health == "stale" else
            "investigate failure" if health == "last_run_failed" else
            "fix schema" if health == "schema_mismatch" else
            "seed initial snapshot"
        ),
    }

    if args.verbose:
        print(f"Risk Regime Health: {health.upper()}")
        if snap_data:
            print(f"  Snapshot: {snap_data['regime']} conf={snap_data['confidence']:.0%} age={snap_age_hours:.1f}h")
        else:
            print("  Snapshot: NONE")
        if run_data:
            print(f"  Last run: {run_data['status']} at {run_data['started_at']}")
        print(f"  Indicators: {ind_count} | Signals: {sig_count}")
        print(f"  Cron wrapper: {'installed' if cron_has_wrapper else 'NOT installed'}")
        print(f"  Cron original: {'installed' if cron_has_original else 'NOT installed'}")
        print(f"  Schema: {'OK' if schema_ok else 'MISMATCH'}")
        print(f"  Action: {report['recommended_action']}")

    if args.run_classifier_once and args.apply:
        print("\nRunning classifier once...")
        r = subprocess.run([str(PROJ / ".venv/bin/python"),
                            str(PROJ / "scripts/market_regime_classifier.py"),
                            "--apply", "--verbose"],
                           capture_output=True, text=True, cwd=str(PROJ))
        print(r.stdout)
        if r.stderr:
            print(r.stderr)
        report["one_shot_result"] = r.stdout.strip()

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Risk Regime Health: {health.upper()}\n"]
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        if snap_data:
            md.append(f"| regime | {snap_data['regime']} |")
            md.append(f"| confidence | {snap_data['confidence']:.0%} |")
            md.append(f"| age | {snap_age_hours:.1f}h |")
            md.append(f"| stale | {is_stale} |")
        md.append(f"| indicators | {ind_count} |")
        md.append(f"| signals | {sig_count} |")
        md.append(f"| cron wrapper | {'yes' if cron_has_wrapper else 'no'} |")
        md.append(f"| schema OK | {schema_ok} |")
        md.append(f"| action | {report['recommended_action']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
