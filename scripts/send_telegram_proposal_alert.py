#!/usr/bin/env python3
"""send_telegram_proposal_alert.py — Send proposal decision alerts via Telegram.

Default: dry-run. Requires --send for actual Telegram delivery.
Does NOT create trades. Does NOT submit orders. Does NOT approve proposals.

Usage:
    .venv/bin/python scripts/send_telegram_proposal_alert.py --symbol DWSN --dry-run --verbose
    .venv/bin/python scripts/send_telegram_proposal_alert.py --mode pending --send --verbose
"""
import argparse, json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

log = logging.getLogger("telegram_proposal_alert")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

ALERT_LOG = PROJ / "logs" / "proposal_alerts.log"


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


def _log_alert(alert_id, proposal_id, symbol, alert_type, urgency, sent, status, error=None):
    """Append to file-based alert audit log."""
    try:
        ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "alert_id": alert_id, "proposal_id": proposal_id,
            "symbol": symbol, "alert_type": alert_type,
            "urgency": urgency, "sent": sent, "status": status,
            "error": error,
        })
        with open(ALERT_LOG, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser(description="Send Telegram proposal alerts (default: dry-run)")
    p.add_argument("--symbol", type=str)
    p.add_argument("--proposal-id", type=int)
    p.add_argument("--mode", choices=["latest", "pending"], default="latest")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--send", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.send:
        args.dry_run = False

    from telegram_proposal_alert_policy import (
        build_proposal_alert_packet, should_send_alert, format_telegram_message,
        build_proposal_inline_keyboard
    )

    # Load proposals
    where = "WHERE ptp.status = 'PENDING'"
    params = []
    if args.symbol:
        where = "WHERE ptp.symbol = %s"
        params = [args.symbol]
    elif args.proposal_id:
        where = "WHERE ptp.id = %s"
        params = [args.proposal_id]

    proposals = _db_query(f"""
        SELECT ptp.*, per.readiness_state, per.quote_provider, per.quote_age_seconds,
               per.quote_execution_eligible, per.spread_pct, per.blockers as er_blockers
        FROM paper_trade_proposals ptp
        LEFT JOIN LATERAL (
            SELECT * FROM proposal_execution_readiness
            WHERE proposal_id = ptp.id ORDER BY created_at DESC LIMIT 1
        ) per ON true
        {where}
        ORDER BY ptp.created_at DESC LIMIT 10
    """, params) or []

    results = []
    sent_count = 0
    recent_keys = set()

    for pr in proposals:
        pr["execution_readiness"] = {
            "readiness_state": pr.get("readiness_state"),
            "quote_provider": pr.get("quote_provider"),
            "quote_age_seconds": pr.get("quote_age_seconds"),
            "quote_execution_eligible": pr.get("quote_execution_eligible"),
            "spread_pct": pr.get("spread_pct"),
        }
        pr["approval_blockers"] = []
        if pr.get("er_blockers"):
            bl = pr["er_blockers"]
            if isinstance(bl, str):
                try: bl = json.loads(bl)
                except: bl = [bl]
            pr["approval_blockers"] = [{"reason": b} if isinstance(b, str) else b for b in (bl or [])]

        packet = build_proposal_alert_packet(pr)
        check = should_send_alert(pr, recent_keys)
        message = format_telegram_message(packet)

        result = {
            "symbol": pr.get("symbol"), "proposal_id": pr.get("id"),
            "alert_type": packet["alert_type"], "urgency": packet["urgency"],
            "send_decision": check, "message_preview": message[:300],
        }

        if check["send"] and not args.dry_run:
            try:
                # ALERT-3: Route to dedicated proposal channel
                from telegram_alert_routing_policy import telegram_destination_for_alert, redact_telegram_destination
                dest = telegram_destination_for_alert(packet)
                result["destination"] = redact_telegram_destination(dest)

                from telegram_alert import send_telegram
                # Use dedicated chat_id if available, with optional thread_id
                import requests
                token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                if dest.get("chat_id") and token:
                    keyboard = build_proposal_inline_keyboard(packet)
                    payload = {"chat_id": dest["chat_id"], "text": message, "parse_mode": "Markdown"}
                    if keyboard:
                        payload["reply_markup"] = json.dumps(keyboard)
                    if dest.get("thread_id"):
                        payload["message_thread_id"] = int(dest["thread_id"])
                    resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=10)
                    ok = resp.ok
                    if not ok:
                        # Retry without Markdown (keep buttons)
                        payload.pop("parse_mode", None)
                        resp2 = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=10)
                        ok = resp2.ok
                else:
                    ok = send_telegram(message)  # Fallback to default

                result["sent"] = ok
                sent_count += 1 if ok else 0
                _log_alert(check["key"], pr.get("id"), pr.get("symbol"),
                          packet["alert_type"], packet["urgency"], ok, "sent" if ok else "send_failed")
            except Exception as e:
                result["sent"] = False
                result["error"] = str(e)[:100]
                _log_alert(check["key"], pr.get("id"), pr.get("symbol"),
                          packet["alert_type"], packet["urgency"], False, "error", str(e)[:100])
        else:
            result["sent"] = False
            result["mode"] = "dry_run" if args.dry_run else "suppressed"
            _log_alert(check["key"], pr.get("id"), pr.get("symbol"),
                      packet["alert_type"], packet["urgency"], False, "dry_run" if args.dry_run else "suppressed")

        recent_keys.add(check["key"])
        results.append(result)

        if args.verbose:
            log.info(f"  {pr.get('symbol')} [{packet['alert_type']}] {'SENT' if result.get('sent') else 'DRY_RUN'}")
            if args.verbose:
                print(f"\n--- Message Preview ---\n{message}\n---")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "send",
        "total_proposals": len(proposals),
        "alerts_sent": sent_count,
        "results": results,
    }

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Telegram Proposal Alert {'DRY RUN' if args.dry_run else 'SENT'}\n",
              f"Proposals: {len(proposals)} | Sent: {sent_count}\n"]
        for r in results:
            md.append(f"- {r['symbol']} [{r['alert_type']}] {'SENT' if r.get('sent') else 'DRY_RUN'}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
