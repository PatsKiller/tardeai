#!/usr/bin/env python3
"""Phase 190E — Hermes open-position protection check (advisory only).

Reads the safe view hermes_v_open_position_protection_context and writes
hermes_validation_findings rows (deduped) for protection defects. Promotes
critical/urgent findings to hermes_alerts. Creates ADVISORY DEFECTS ONLY — never
mutates trades, stops, or orders.

Rules → finding_type:
  NAKED (no broker stop)                 -> open_position_no_broker_stop      (critical)
  broker stop exists, DB untracked       -> broker_stop_exists_db_untracked   (urgent)
  unrealized gain >= $250, no take-profit-> large_gain_no_take_profit         (urgent)
  stop submitted but unconfirmed         -> stop_note_unverified              (warning)
  protection metadata mismatch           -> protection_metadata_mismatch      (warning)
"""
import os, sys, json
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LARGE_GAIN_USD = 250.0


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


def evaluate(row):
    """Return list of (finding_type, severity, description, action)."""
    (tid, sym, strat, qty, entry, cur_px, upnl, planned_stop, stop_loss, bstop_id,
     verified_at, bstatus, tp_oid, tp_px, trailing, prot, defect, last_chk) = row
    upnl = float(upnl) if upnl is not None else 0.0
    out = []
    if prot == "NAKED":
        out.append(("open_position_no_broker_stop", "critical",
                    f"{sym}: open paper position with NO broker stop ({qty} sh).",
                    "Assign protective stop via operator review."))
    elif prot == "PROTECTED_UNRECORDED" or (bstop_id is None and stop_loss is not None):
        out.append(("broker_stop_exists_db_untracked", "urgent",
                    f"{sym}: broker stop exists but DB stop_order_id missing — protection unverifiable.",
                    "Run verify_paper_trade_broker_stops.py to persist stop_order_id."))
    if upnl >= LARGE_GAIN_USD and tp_px is None:
        out.append(("large_gain_no_take_profit", "urgent",
                    f"{sym}: large unrealized gain ${upnl:.0f} with no take-profit/profit protection.",
                    "Operator: set take-profit or convert to trailing stop."))
    if defect and "UNCONFIRMED" in str(defect):
        out.append(("stop_note_unverified", "warning",
                    f"{sym}: stop submitted but not broker-confirmed ({defect}).",
                    "Verify broker stop order; re-place if absent."))
    elif defect and defect not in (None, "stop_order_id_backfilled"):
        out.append(("protection_metadata_mismatch", "warning",
                    f"{sym}: protection metadata mismatch ({defect}).",
                    "Reconcile DB protection metadata with broker order book."))
    return out


def has_open_finding(cur, ftype, tid):
    cur.execute("""select 1 from hermes_validation_findings
                   where finding_type=%s and affected_table='paper_trades'
                   and affected_id=%s and status='open' limit 1""", (ftype, tid))
    return cur.fetchone() is not None


def run():
    load_env()
    conn = db(); cur = conn.cursor()
    cur.execute("select * from hermes_v_open_position_protection_context order by paper_trade_id")
    rows = cur.fetchall()
    written, promoted = [], []
    for row in rows:
        tid, sym = row[0], row[1]
        for ftype, sev, desc, action in evaluate(row):
            if has_open_finding(cur, ftype, tid):
                continue
            cur.execute("""insert into hermes_validation_findings
                (source, hermes_agent_name, finding_type, severity, symbol,
                 affected_table, affected_id, description, evidence_json,
                 recommended_action, auto_fixable, status, created_at, updated_at)
                values ('hermes','protection_check',%s,%s,%s,'paper_trades',%s,%s,%s,%s,false,'open',%s,%s)
                returning id""",
                (ftype, sev, sym, tid, desc,
                 json.dumps({"paper_trade_id": tid, "protection_status": row[16]}),
                 action, datetime.now(timezone.utc), datetime.now(timezone.utc)))
            fid = cur.fetchone()[0]
            written.append({"id": fid, "type": ftype, "sev": sev, "symbol": sym})
            if sev in ("critical", "urgent"):
                cur.execute("""insert into hermes_alerts
                    (source, hermes_agent_name, alert_type, severity, symbol, title,
                     description, evidence_json, recommended_action, related_finding_id,
                     status, created_at, updated_at)
                    values ('hermes','protection_check','portfolio_risk',%s,%s,%s,%s,%s,%s,%s,'active',%s,%s)
                    returning id""",
                    ("urgent" if sev == "critical" else sev, sym,
                     f"Protection defect: {ftype}", desc,
                     json.dumps({"finding_id": fid}), action, fid,
                     datetime.now(timezone.utc), datetime.now(timezone.utc)))
                aid = cur.fetchone()[0]
                cur.execute("update hermes_validation_findings set promoted_to_alert_id=%s, status='promoted' where id=%s",
                            (aid, fid))
                promoted.append({"finding": fid, "alert": aid})
    conn.commit()
    report = {"run_at": datetime.now(timezone.utc).isoformat(),
              "positions_checked": len(rows), "findings_written": written,
              "alerts_promoted": promoted}
    conn.close()
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
