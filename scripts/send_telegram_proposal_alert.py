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
    # _get_conn() returns a singleton connection with autocommit=False, so writes
    # MUST be committed and a failed statement MUST be rolled back — otherwise the
    # shared transaction is left aborted and poisons every later query on the conn.
    # fetch="none" is for write statements (UPDATE/INSERT/DELETE): it skips the
    # fetch (which raises on a no-result statement), commits, and returns rowcount.
    conn = None
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return [] if fetch == "all" else (0 if fetch == "none" else None)
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "none":
            rowcount = cur.rowcount
            cur.close()
            conn.commit()
            return rowcount
        if fetch == "one":
            row = cur.fetchone()
            result = dict(zip([d[0] for d in cur.description], row)) if row else None
            cur.close()
            conn.commit()
            return result
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        cur.close()
        conn.commit()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return [] if fetch == "all" else (0 if fetch == "none" else None)


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
        # ── Auto-reject stale entry prices — strategy-aware threshold, grace period for new proposals ──
        _entry = float(pr.get("proposed_entry") or 0)
        if _entry > 0:
            try:
                _created = pr.get("created_at")
                _age_min = 999.0
                if _created:
                    if hasattr(_created, 'timestamp'):
                        _age_min = (datetime.now(timezone.utc) - _created).total_seconds() / 60
                    elif isinstance(_created, str):
                        from dateutil.parser import parse as _dp0
                        _age_min = (datetime.now(timezone.utc) - _dp0(_created)).total_seconds() / 60
                # Let the operator review Telegram alerts before hygiene auto-rejects (esp. gap names).
                if _age_min >= 120:
                    from proposal_lifecycle import get_price_drift_threshold
                    _drift_max = get_price_drift_threshold(pr.get("strategy_id") or "")
                    from market_quote_provider import get_best_quote as _abq
                    _lq = _abq(pr.get("symbol", ""))
                    if _lq and _lq.get("last_price") and _lq["last_price"] > 0:
                        _drift = abs(float(_lq["last_price"]) - _entry) / _entry * 100
                        if _drift > _drift_max:
                            try:
                                from paper_trade_logger import reject_proposal
                                reject_proposal(pr["id"], f"auto_stale_price_drift_{_drift:.0f}pct")
                                print(f"  [alert] Auto-rejected #{pr['id']} {pr.get('symbol')}: "
                                      f"entry=${_entry:.2f} live=${_lq['last_price']:.2f} "
                                      f"({_drift:.1f}% > {_drift_max}% threshold)")
                            except Exception:
                                pass
                            continue
            except Exception:
                pass

        # ── Auto-reject proposals that have been BLOCKED for >30 min ──
        _action_state = pr.get("action_state") or ""
        _created = pr.get("created_at")
        if "BLOCKED" in _action_state.upper() and _created:
            try:
                _age_min = 30
                if hasattr(_created, 'timestamp'):
                    _age_min = (datetime.now(timezone.utc) - _created).total_seconds() / 60
                elif isinstance(_created, str):
                    from dateutil.parser import parse as _dp
                    _age_min = (datetime.now(timezone.utc) - _dp(_created)).total_seconds() / 60
                if _age_min > 30:
                    try:
                        from paper_trade_logger import reject_proposal
                        reject_proposal(pr["id"], f"auto_blocked_{_age_min:.0f}min")
                        print(f"  [alert] Auto-rejected blocked #{pr['id']} {pr.get('symbol')} ({_age_min:.0f}min blocked)")
                    except Exception:
                        pass
                    continue
            except Exception:
                pass

        # ── Dedup: skip if we already sent this exact proposal in last 30 min ──
        _alert_key = f"{pr.get('id')}:{pr.get('action_state')}"
        _last_alert = pr.get("last_alert_at")
        if _last_alert:
            try:
                if hasattr(_last_alert, 'timestamp'):
                    _since_alert = (datetime.now(timezone.utc) - _last_alert).total_seconds() / 60
                elif isinstance(_last_alert, str):
                    from dateutil.parser import parse as _dp2
                    _since_alert = (datetime.now(timezone.utc) - _dp2(_last_alert)).total_seconds() / 60
                else:
                    _since_alert = 999
                if _since_alert < 30:
                    continue  # Already alerted within 30 min
            except Exception:
                pass

        pr["execution_readiness"] = {
            "readiness_state": pr.get("readiness_state"),
            "quote_provider": pr.get("quote_provider"),
            "quote_age_seconds": pr.get("quote_age_seconds"),
            "quote_execution_eligible": pr.get("quote_execution_eligible"),
            "spread_pct": pr.get("spread_pct"),
        }
        if pr.get("er_blockers"):
            bl = pr["er_blockers"]
            if isinstance(bl, str):
                try: bl = json.loads(bl)
                except: bl = [bl]
            pr["approval_blockers"] = [{"reason": b} if isinstance(b, str) else b for b in (bl or [])]
        else:
            pr.setdefault("approval_blockers", [])
        pr.setdefault("approval_allowed", False)

        packet = build_proposal_alert_packet(pr)
        check = should_send_alert(pr, recent_keys)
        message = format_telegram_message(packet)

        result = {
            "symbol": pr.get("symbol"), "proposal_id": pr.get("id"),
            "alert_type": packet["alert_type"], "urgency": packet["urgency"],
            "send_decision": check, "message_preview": message[:300],
        }

        # ALERT-FATIGUE-1: Check central router before sending
        _router_ok = True
        try:
            from telegram_alert_router import should_send_telegram
            if not should_send_telegram(message):
                _router_ok = False
                result["suppressed_by_router"] = True
        except ImportError:
            pass

        if check["send"] and not args.dry_run and _router_ok:
            try:
                # Destination + keyboard via telegram_alert chokepoint (no raw Bot API).
                dest: dict = {}
                try:
                    from telegram_alert_routing_policy import (
                        telegram_destination_for_alert, redact_telegram_destination,
                    )
                    dest = telegram_destination_for_alert(packet) or {}
                    result["destination"] = redact_telegram_destination(dest)
                except Exception:
                    result["destination"] = {"configured": False}

                from telegram_alert import send_telegram
                try:
                    from telegram_proposal_alert_policy import build_proposal_inline_keyboard
                    keyboard = build_proposal_inline_keyboard(packet)
                except Exception:
                    keyboard = None
                chat_ids = [str(dest["chat_id"])] if dest.get("chat_id") else None
                thread_id = str(dest["thread_id"]) if dest.get("thread_id") else None
                ok = bool(send_telegram(
                    message,
                    reply_markup=keyboard,
                    chat_ids=chat_ids,
                    thread_id=thread_id,
                ))
                try:
                    root = str(PROJ)
                    if root not in sys.path:
                        sys.path.insert(0, root)
                    from lib.comms import CommunicationEvent, publish_communication
                    publish_communication(CommunicationEvent(
                        direction="OUTBOUND", event_type="alert",
                        message_class="proposal",
                        producer="send_telegram_proposal_alert",
                        subject_key=f"proposal:{pr.get('symbol') or 'unknown'}",
                        retention_class="operational", severity="urgent",
                        sanitized_body=message[:500], short_summary=message[:120],
                    ))
                except Exception:
                    # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
                    pass

                result["sent"] = ok
                sent_count += 1 if ok else 0
                _log_alert(check["key"], pr.get("id"), pr.get("symbol"),
                          packet["alert_type"], packet["urgency"], ok, "sent" if ok else "send_failed")
                # Update last_alert_at + alert_count for dedup
                if ok:
                    try:
                        _db_query("""UPDATE paper_trade_proposals
                            SET last_alert_at=NOW(), alert_count=COALESCE(alert_count,0)+1
                            WHERE id=%s""", [pr.get("id")], fetch="none")
                    except Exception:
                        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
                        pass
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
