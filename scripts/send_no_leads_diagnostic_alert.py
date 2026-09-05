#!/usr/bin/env python3
"""send_no_leads_diagnostic_alert.py — Send no-leads diagnostic to Telegram.

Default: dry-run. No trades. No orders.

Usage:
    .venv/bin/python scripts/send_no_leads_diagnostic_alert.py --dry-run --verbose
"""
import argparse, json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
log = logging.getLogger("no_leads_diagnostic")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def main():
    p = argparse.ArgumentParser(description="No-leads diagnostic alert (default: dry-run)")
    p.add_argument("--since-hours", type=int, default=24)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--send", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.send: args.dry_run = False

    # Run root cause
    import subprocess
    rc = subprocess.run(
        [str(PROJ / ".venv/bin/python"), str(PROJ / "scripts/report_no_leads_root_cause.py"),
         "--since-hours", str(args.since_hours), "--output-json", "/dev/stdout"],
        capture_output=True, text=True, timeout=30
    )
    report = {}
    try: report = json.loads(rc.stdout)
    except: pass

    conclusion = report.get("conclusion", "unknown")
    explanation = report.get("explanation", "No data")
    run = report.get("latest_run") or {}

    msg = f"""\u2753 *No-Leads Diagnostic*

Run: {run.get('run_label', '?')} {run.get('status', '?')}
Scanned: {run.get('symbols_scanned', '?')} | GO: {report.get('go_count', '?')}
Pending proposals: {report.get('pending_proposals', '?')}
Incubator ready: {report.get('incubator_ready', '?')}
Watchpool active: {report.get('watchpool_active', '?')}

*Why no leads:* {conclusion.replace('_', ' ')}
{explanation}

_Diagnostic only — no trade, no order_"""

    result = {"conclusion": conclusion, "sent": False, "dry_run": args.dry_run}

    if not args.dry_run and conclusion != "system_producing":
        try:
            for line in Path(PROJ / '.env').read_text().splitlines():
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())
            from telegram_alert import send_telegram
            result["sent"] = bool(send_telegram(msg))
            try:
                if str(PROJ) not in sys.path:
                    sys.path.insert(0, str(PROJ))
                from lib.comms import CommunicationEvent, publish_communication
                publish_communication(CommunicationEvent(
                    direction="OUTBOUND", event_type="alert", message_class="ops",
                    producer="send_no_leads_diagnostic_alert",
                    subject_key="ops:no_leads_diagnostic",
                    retention_class="operational", severity="info",
                    sanitized_body=msg[:500], short_summary=msg[:120],
                ))
            except Exception:
                # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
                pass
        except Exception as e:
            result["error"] = str(e)[:80]

    if args.verbose:
        log.info(f"Diagnostic: {conclusion} — {'SENT' if result['sent'] else 'DRY_RUN'}")
        print(f"\n--- Message ---\n{msg}\n---")

    full_report = {"generated_at": datetime.now(timezone.utc).isoformat(), "root_cause": report, "result": result}
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(full_report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).write_text(f"# No-Leads Diagnostic\n\nConclusion: **{conclusion}**\n\n{explanation}")


if __name__ == "__main__":
    main()
