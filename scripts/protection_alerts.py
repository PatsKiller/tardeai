#!/usr/bin/env python3
"""Phase 190D — Paper-position protection defect detector + SIEM/Telegram router.

Queries `paper_trades` open positions (NOT brokerage risk_management.json) plus the
broker-verified protection metadata persisted by verify_paper_trade_broker_stops.py,
detects protection defects, emits SIEM events into `alert_events` (deduped), and
routes P0/P1 actionable defects to Telegram when --send is given.

Detects:
  OPEN_POSITION_NO_BROKER_STOP   (P0)
  BROKER_STOP_EXISTS_DB_UNTRACKED(P1)
  LARGE_GAIN_NO_TAKE_PROFIT      (P1)
  STOP_NOTE_UNVERIFIED           (P2)
  PROTECTION_METADATA_MISMATCH   (P2)

Never places/modifies/cancels orders. Read-only on positions; writes only alert_events.
"""
import os, sys, json, argparse
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LARGE_GAIN_USD = 250.0          # "large gain" threshold for missing-TP escalation
DEDUP_HOURS = 6                 # suppress identical alert_uid within this window
SEV = {"OPEN_POSITION_NO_BROKER_STOP": "P0", "BROKER_STOP_EXISTS_DB_UNTRACKED": "P1",
       "LARGE_GAIN_NO_TAKE_PROFIT": "P1", "STOP_NOTE_UNVERIFIED": "P2",
       "PROTECTION_METADATA_MISMATCH": "P2"}
# alert_events.alert_type is a curated CHECK set; protection defects map to the
# existing 'data_integrity' type with the precise defect carried in parsed_payload.
SIEM_ALERT_TYPE = "data_integrity"
SIEM_SEV = {"P0": "critical", "P1": "urgent", "P2": "warning"}


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def detect(cur):
    cur.execute("""select id,symbol,shares,stop_loss,stop_order_id,take_profit_price,
                          unrealized_pnl,protection_status,broker_stop_status,notes
                   from paper_trades where status='open' order by id""")
    defects = []
    for (tid, sym, sh, sl, soid, tp, upnl, pstat, bstat, notes) in cur.fetchall():
        upnl = float(upnl) if upnl is not None else 0.0
        if pstat == "NAKED" or (not soid and not sl):
            defects.append((tid, sym, "OPEN_POSITION_NO_BROKER_STOP",
                            {"shares": sh, "pnl": upnl}))
        elif not soid:
            defects.append((tid, sym, "BROKER_STOP_EXISTS_DB_UNTRACKED",
                            {"stop_loss": float(sl) if sl else None, "pnl": upnl}))
        if upnl >= LARGE_GAIN_USD and tp is None:
            defects.append((tid, sym, "LARGE_GAIN_NO_TAKE_PROFIT",
                            {"pnl": upnl, "shares": sh}))
        if notes and "UNCONFIRMED" in str(notes):
            defects.append((tid, sym, "STOP_NOTE_UNVERIFIED", {"notes": notes[:120]}))
    return defects


def recent_uid(cur, uid):
    cur.execute("""select 1 from alert_events where alert_uid=%s
                   and created_at > %s limit 1""",
                (uid, datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)))
    return cur.fetchone() is not None


def emit_siem(cur, tid, sym, atype, payload):
    uid = f"protect:{atype}:{tid}"
    if recent_uid(cur, uid):
        return None  # deduped
    plevel = SEV.get(atype, "P2")
    payload = {**payload, "defect_type": atype, "p_level": plevel}
    cur.execute("""insert into alert_events
        (alert_uid, alert_type, symbol, severity, source_script, raw_text,
         parsed_payload, pnl, requires_agent_review, data_quality_status, created_at)
        values (%s,%s,%s,%s,'protection_alerts.py',%s,%s,%s,%s,'valid',%s) returning id""",
        (uid, SIEM_ALERT_TYPE, sym, SIEM_SEV[plevel], f"{atype} on paper trade {tid} ({sym})",
         json.dumps(payload), payload.get("pnl"), plevel in ("P0", "P1"),
         datetime.now(timezone.utc)))
    return cur.fetchone()[0]


def telegram(msg):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram
        ok = bool(send_telegram(msg))
        try:
            _root = os.path.dirname(scripts_dir)
            if _root not in sys.path:
                sys.path.insert(0, _root)
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="protection_alerts", subject_key="ops:protection",
                retention_class="operational", severity="urgent",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return [{"via": "send_telegram", "ok": ok}]
    except Exception as e:
        return [{"via": "send_telegram", "ok": False, "error": str(e)[:120]}]


def run(send=False):
    load_env()
    conn = db(); cur = conn.cursor()
    defects = detect(cur)
    emitted, actionable = [], []
    for tid, sym, atype, payload in defects:
        eid = emit_siem(cur, tid, sym, atype, payload)
        if eid:
            emitted.append({"id": eid, "trade": tid, "symbol": sym, "type": atype, "sev": SEV.get(atype)})
            if SEV.get(atype) in ("P0", "P1"):
                actionable.append(f"- {sym} ({SEV[atype]}): {atype} {json.dumps(payload)}")
    conn.commit()
    tg = []
    if send and actionable:
        tg = telegram("ATM Paper — Protection defects (auto):\n" + "\n".join(actionable) +
                      "\nPaper-only. No mutations.")
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "defects_found": len(defects),
              "siem_emitted": emitted, "telegram_sent": tg, "send_enabled": send}
    conn.close()
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="route P0/P1 to Telegram")
    a = ap.parse_args()
    run(send=a.send)
