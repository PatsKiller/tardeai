#!/usr/bin/env python3
"""send_watchpool_maturity_alerts.py — Send watchpool maturity Telegram alerts.

Default: dry-run. Requires --send for delivery. No trades. No orders.

Usage:
    .venv/bin/python scripts/send_watchpool_maturity_alerts.py --dry-run --verbose
    .venv/bin/python scripts/send_watchpool_maturity_alerts.py --send --limit 3 --verbose
"""
import argparse, json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
log = logging.getLogger("watchpool_alerts")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

ALERT_LOG = PROJ / "logs" / "watchpool_alerts.log"


def _log_alert(key, symbol, alert_type, sent, status):
    try:
        ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERT_LOG, "a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "key": key,
                                "symbol": symbol, "alert_type": alert_type, "sent": sent, "status": status}) + "\n")
    except Exception:
        pass


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn: return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip([d[0] for d in cur.description], row)) if row else None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def main():
    p = argparse.ArgumentParser(description="Watchpool maturity alerts (default: dry-run)")
    p.add_argument("--mode", choices=["audit", "send"], default="audit")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--send", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.send: args.dry_run = False

    from watchpool_maturity_policy import (classify_watchpool_maturity, determine_watchpool_alert_type,
                                           build_watchpool_alert_packet, should_suppress_watchpool_alert,
                                           format_watchpool_telegram_message)

    candidates = _db_query("""
        SELECT symbol, strategy_id, latest_score as score, status, days_active,
               catalyst, catalyst_verified, rvol_latest as rvol
        FROM incubator_universe
        WHERE status='ACTIVE' AND latest_score >= 30
        ORDER BY latest_score DESC LIMIT %s
    """, [args.limit]) or []

    results = []
    sent_count = 0
    recent_keys = set()

    for c in candidates:
        alert_type = determine_watchpool_alert_type(c)
        if alert_type == "NO_ACTION":
            continue

        check = should_suppress_watchpool_alert(c, recent_keys)
        if not check["send"]:
            continue

        packet = build_watchpool_alert_packet(c)
        message = format_watchpool_telegram_message(packet)
        recent_keys.add(check["key"])

        result = {"symbol": c["symbol"], "alert_type": alert_type, "sent": False}

        if not args.dry_run:
            try:
                for line in Path(PROJ / '.env').read_text().splitlines():
                    if '=' in line and not line.strip().startswith('#'):
                        k, v = line.split('=', 1)
                        os.environ.setdefault(k.strip(), v.strip())
                from telegram_alert import send_telegram
                r_ok = bool(send_telegram(message))
                result["sent"] = r_ok
                sent_count += 1 if r_ok else 0
                try:
                    if str(PROJ) not in sys.path:
                        sys.path.insert(0, str(PROJ))
                    from lib.comms import CommunicationEvent, publish_communication
                    publish_communication(CommunicationEvent(
                        direction="OUTBOUND", event_type="alert", message_class="ops",
                        producer="send_watchpool_maturity_alerts",
                        subject_key=f"symbol:{(c.get('symbol') or 'unknown').upper()}",
                        retention_class="operational", severity="info",
                        entity_refs={"symbol": c.get("symbol")},
                        sanitized_body=message[:500], short_summary=message[:120],
                    ))
                except Exception:
                    # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
                    pass
            except Exception as e:
                result["error"] = str(e)[:80]
            _log_alert(check["key"], c["symbol"], alert_type, result["sent"], "sent" if result["sent"] else "error")
        else:
            _log_alert(check["key"], c["symbol"], alert_type, False, "dry_run")

        results.append(result)
        if args.verbose:
            log.info(f"  {c['symbol']} [{alert_type}] {'SENT' if result.get('sent') else 'DRY_RUN'}")

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": "dry_run" if args.dry_run else "send",
              "candidates": len(candidates), "alertable": len(results), "sent": sent_count, "results": results[:50]}

    if args.verbose:
        log.info(f"Summary: {len(candidates)} candidates, {len(results)} alertable, {sent_count} sent")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Watchpool Maturity Alerts {'DRY RUN' if args.dry_run else 'SENT'}\n",
              f"Candidates: {len(candidates)} | Alertable: {len(results)} | Sent: {sent_count}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
