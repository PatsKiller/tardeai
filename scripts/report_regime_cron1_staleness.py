#!/usr/bin/env python3
"""report_regime_cron1_staleness.py — Report market regime snapshot freshness and cron health.

Read-only. No trades. No orders.
"""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

from db_adapter import _get_conn

LOG_DIR = PROJ / "logs"


def run_report(verbose=False):
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_snapshot": None,
        "age_hours": None,
        "cron_found": False,
        "cron_line": None,
        "logs_found": {},
        "recommended_fix": None,
        "root_cause": None,
    }

    # --- Query latest market_regime_snapshots ---
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT snapshot_id, regime_label, confidence, generated_at "
                "FROM market_regime_snapshots ORDER BY generated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                snapshot_id, regime_label, confidence, generated_at = row
                report["latest_snapshot"] = {
                    "snapshot_id": snapshot_id,
                    "regime_label": regime_label,
                    "confidence": float(confidence) if confidence is not None else None,
                    "generated_at": generated_at.isoformat() if generated_at else None,
                }
                if generated_at:
                    if generated_at.tzinfo is None:
                        generated_at = generated_at.replace(tzinfo=timezone.utc)
                    age = datetime.now(timezone.utc) - generated_at
                    report["age_hours"] = round(age.total_seconds() / 3600, 2)
            else:
                report["root_cause"] = "no_snapshots_found"
            cur.close()
        except Exception as e:
            report["root_cause"] = f"query_error: {e}"
            conn.rollback()
    else:
        report["root_cause"] = "db_connection_failed"

    # --- Check crontab for regime entries ---
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "regime" in stripped.lower() or "classifier" in stripped.lower():
                    report["cron_found"] = True
                    report["cron_line"] = stripped
                    break
    except Exception:
        pass

    # --- Check log files ---
    for log_name in ["regime_collector.log", "regime_classifier.log"]:
        log_path = LOG_DIR / log_name
        report["logs_found"][log_name] = log_path.exists()

    # --- Determine recommended fix ---
    if report["root_cause"] is None:
        issues = []
        if report["age_hours"] is not None and report["age_hours"] > 24:
            issues.append(f"snapshot is {report['age_hours']:.1f}h stale (>24h)")
        if not report["cron_found"]:
            issues.append("no cron entry found for regime collector/classifier")
        if not any(report["logs_found"].values()):
            issues.append("no regime log files found")
        if issues:
            report["recommended_fix"] = "; ".join(issues)
        else:
            report["recommended_fix"] = "none — regime pipeline appears healthy"

    if verbose:
        print("=== Regime Cron Staleness Report ===")
        if report["latest_snapshot"]:
            snap = report["latest_snapshot"]
            print(f"  Latest: {snap['regime_label']} (conf={snap['confidence']}) at {snap['generated_at']}")
        else:
            print("  Latest: no snapshot found")
        print(f"  Age: {report['age_hours']}h")
        print(f"  Cron found: {report['cron_found']}")
        print(f"  Logs found: {report['logs_found']}")
        print(f"  Root cause: {report['root_cause']}")
        print(f"  Fix: {report['recommended_fix']}")

    return report


def main():
    p = argparse.ArgumentParser(description="Regime cron staleness report (read-only)")
    p.add_argument("--output-json", type=str, help="Path to write JSON report")
    p.add_argument("--output-md", type=str, help="Path to write Markdown report")
    p.add_argument("--verbose", action="store_true", help="Print verbose summary")
    args = p.parse_args()

    report = run_report(verbose=args.verbose)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"JSON written to {args.output_json}")

    if args.output_md:
        lines = [
            "# Regime Cron Staleness Report",
            f"Generated: {report['generated_at']}",
            "",
            "## Latest Snapshot",
        ]
        if report["latest_snapshot"]:
            snap = report["latest_snapshot"]
            lines.append(f"- **Label:** {snap['regime_label']}")
            lines.append(f"- **Confidence:** {snap['confidence']}")
            lines.append(f"- **Generated at:** {snap['generated_at']}")
        else:
            lines.append("- No snapshot found")
        lines.append(f"\n## Staleness\n- **Age:** {report['age_hours']}h")
        lines.append(f"\n## Cron\n- **Found:** {report['cron_found']}")
        if report["cron_line"]:
            lines.append(f"- **Line:** `{report['cron_line']}`")
        lines.append(f"\n## Logs\n")
        for k, v in report["logs_found"].items():
            lines.append(f"- {k}: {'exists' if v else 'missing'}")
        lines.append(f"\n## Root Cause\n- {report['root_cause'] or 'none'}")
        lines.append(f"\n## Recommended Fix\n- {report['recommended_fix'] or 'none'}")
        Path(args.output_md).write_text("\n".join(lines))
        print(f"Markdown written to {args.output_md}")


if __name__ == "__main__":
    main()
