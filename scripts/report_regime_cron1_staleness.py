#!/usr/bin/env python3
"""report_regime_cron1_staleness.py — Audit risk-regime pipeline staleness.

Read-only. No mutations. No trades. No orders.
"""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def main():
    p = argparse.ArgumentParser(description="Risk regime staleness audit (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)
    cur = conn.cursor()
    now = datetime.now(timezone.utc)

    # Latest snapshot
    cur.execute("""SELECT snapshot_id, generated_at, regime_label, confidence,
        trend_state, volatility_state, breadth_state, summary, stale_data, missing_data, inputs
        FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1""")
    cols = [d[0] for d in cur.description]
    snap_row = cur.fetchone()
    snap = dict(zip(cols, snap_row)) if snap_row else None

    snap_age_hours = None
    if snap and snap["generated_at"]:
        gen = snap["generated_at"]
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        snap_age_hours = round((now - gen).total_seconds() / 3600, 1)

    # Latest indicators
    cur.execute("SELECT COUNT(*), MAX(created_at) FROM market_regime_indicators")
    ind_count, ind_latest = cur.fetchone()

    # Rotation signals
    cur.execute("SELECT COUNT(*), MAX(created_at) FROM strategy_rotation_signals")
    sig_count, sig_latest = cur.fetchone()

    # Run log
    cur.execute("SELECT run_id, status, started_at, finished_at, indicators_read, snapshots_created, errors FROM risk_regime_run_log ORDER BY started_at DESC LIMIT 1")
    run_cols = [d[0] for d in cur.description]
    run_row = cur.fetchone()
    run = dict(zip(run_cols, run_row)) if run_row else None

    conn.close()

    # Script paths
    classifier_path = PROJ / "scripts" / "market_regime_classifier.py"
    collector_path = PROJ / "scripts" / "market_regime_collector.py"
    rotation_path = PROJ / "scripts" / "strategy_rotation_engine.py"
    wrapper_path = PROJ / "scripts" / "run_scheduled_risk_regime_classifier.sh"

    # Cron check
    try:
        cron_out = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        cron_text = cron_out.stdout
    except Exception:
        cron_text = ""
    has_cron = "market_regime_classifier" in cron_text or "run_scheduled_risk_regime_classifier" in cron_text
    has_wrapper_cron = "run_scheduled_risk_regime_classifier" in cron_text

    # Logs
    log_path = PROJ / "logs" / "regime_classifier.log"
    log_exists = log_path.exists()
    log_lines = []
    if log_exists:
        log_lines = log_path.read_text().strip().split("\n")[-5:]

    # Root cause classification
    root_cause = "unknown"
    if not has_cron:
        root_cause = "cron_missing"
    elif snap is None:
        root_cause = "classifier_runs_but_no_snapshot_write"
    elif snap_age_hours and snap_age_hours > 26:
        if run and run["status"] == "failed":
            root_cause = "cron_runs_but_classifier_fails"
        elif not run:
            root_cause = "classifier_runs_but_no_snapshot_write"
        else:
            root_cause = "stale_but_labeled_correctly"
    else:
        root_cause = "fresh"

    report = {
        "generated_at": now.isoformat(),
        "snapshot": {k: str(v) if not isinstance(v, (str, int, float, bool, type(None), list, dict)) else v
                     for k, v in snap.items()} if snap else None,
        "snapshot_age_hours": snap_age_hours,
        "indicators_count": ind_count,
        "indicators_latest": str(ind_latest) if ind_latest else None,
        "rotation_signals_count": sig_count,
        "rotation_signals_latest": str(sig_latest) if sig_latest else None,
        "latest_run": {k: str(v) if not isinstance(v, (str, int, float, bool, type(None), list, dict)) else v
                       for k, v in run.items()} if run else None,
        "classifier_exists": classifier_path.exists(),
        "collector_exists": collector_path.exists(),
        "rotation_engine_exists": rotation_path.exists(),
        "wrapper_exists": wrapper_path.exists(),
        "cron_found": has_cron,
        "wrapper_cron_found": has_wrapper_cron,
        "log_exists": log_exists,
        "log_tail": log_lines,
        "root_cause": root_cause,
        "recommended_fix": (
            "install cron" if root_cause == "cron_missing" else
            "fix dry_run parameter in save_snapshot call" if root_cause == "classifier_runs_but_no_snapshot_write" else
            "investigate classifier errors" if root_cause == "cron_runs_but_classifier_fails" else
            "none — snapshot is fresh" if root_cause == "fresh" else
            "investigate"
        ),
    }

    if args.verbose:
        print(f"Staleness Audit: root_cause={root_cause}")
        if snap:
            print(f"  Snapshot: {snap['regime_label']} conf={float(snap['confidence'] or 0):.0%} age={snap_age_hours:.1f}h")
        else:
            print("  Snapshot: NONE")
        print(f"  Indicators: {ind_count} | Signals: {sig_count}")
        print(f"  Cron: {'yes' if has_cron else 'NO'} | Wrapper cron: {'yes' if has_wrapper_cron else 'NO'}")
        if run:
            print(f"  Last run: {run['status']} at {run['started_at']}")
        print(f"  Fix: {report['recommended_fix']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Risk Regime Staleness Audit\n",
              f"**Root cause:** {root_cause}\n",
              f"**Recommended fix:** {report['recommended_fix']}\n"]
        if snap:
            md.append(f"| Metric | Value |")
            md.append(f"|--------|-------|")
            md.append(f"| regime | {snap['regime_label']} |")
            md.append(f"| confidence | {float(snap['confidence'] or 0):.0%} |")
            md.append(f"| age | {snap_age_hours:.1f}h |")
            md.append(f"| stale | {snap['stale_data']} |")
        md.append(f"\n## Pipeline")
        md.append(f"| Component | Status |")
        md.append(f"|-----------|--------|")
        md.append(f"| classifier | {'exists' if classifier_path.exists() else 'MISSING'} |")
        md.append(f"| collector | {'exists' if collector_path.exists() else 'MISSING'} |")
        md.append(f"| rotation | {'exists' if rotation_path.exists() else 'MISSING'} |")
        md.append(f"| cron | {'installed' if has_cron else 'MISSING'} |")
        md.append(f"| wrapper | {'exists' if wrapper_path.exists() else 'MISSING'} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
