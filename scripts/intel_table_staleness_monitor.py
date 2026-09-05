#!/usr/bin/env python3
"""Intel-table staleness monitor (2026-06-04).

Catches the silent-failure class that hid the dead catalyst_events for ~5 weeks: a write
that fails *inside* a green job, with consumers that degrade gracefully (empty->0, LEFT
JOIN->NULL) so nothing ever errors. Job-level monitors and Hermes could not see it.

Rule: for each (intel_table <- input_table) pair, if the INPUT got fresh rows in the last
STALE_HOURS but the INTEL table got ZERO, the intel pipeline is silently broken -> emit a
SIEM event into alert_events (alert_type='data_integrity', deduped) and optionally Telegram.

Read-only except for alert_events inserts. Never touches trading tables.

Usage:
  python3 scripts/intel_table_staleness_monitor.py          # check + emit SIEM (no telegram)
  python3 scripts/intel_table_staleness_monitor.py --send   # also send Telegram
  python3 scripts/intel_table_staleness_monitor.py --json
"""
import os, sys, json
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STALE_HOURS = 24
DEDUP_HOURS = 12
SIEM_ALERT_TYPE = "data_integrity"  # curated CHECK set; precise detail goes in parsed_payload

# (intel_table, intel_ts, input_table, input_ts, severity)
# Only pairs where the input being fresh implies the intel table SHOULD be getting rows.
PAIRS = [
    ("catalyst_events", "created_at", "news_articles", "created_at", "warning"),
    ("fused_signals",   "created_at", "catalyst_events", "created_at", "warning"),
]

# RI v3.1 (WS-F): absolute staleness — these feeds must produce within
# max_age_hours regardless of inputs. The external lanes died silently for two
# weeks (PROMPT.format crash) because nothing watched their output tables.
# (label, table, ts_col, where_sql, max_age_hours, severity)
ABSOLUTE = [
    ("external lane grok",    "hermes_external_research", "created_at", "lane='grok'",    96, "warning"),
    ("external lane chatgpt", "hermes_external_research", "created_at", "lane='chatgpt'", 96, "warning"),
    ("VIX close (regime)",    "market_regime_indicators", "created_at", "indicator_key='vix_close'", 30, "warning"),
]


def load_env():
    p = os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    for line in open(p):
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


def _count_since(cur, table, ts_col, hours):
    cur.execute(f"SELECT count(*) FROM {table} WHERE {ts_col} > %s",
                (datetime.now(timezone.utc) - timedelta(hours=hours),))
    return cur.fetchone()[0]


def detect(cur):
    findings = []
    for intel, intel_ts, inp, inp_ts, sev in PAIRS:
        try:
            input_fresh = _count_since(cur, inp, inp_ts, STALE_HOURS)
            intel_fresh = _count_since(cur, intel, intel_ts, STALE_HOURS)
        except Exception as e:
            cur.connection.rollback()
            findings.append({"intel": intel, "error": str(e)[:120]})
            continue
        if input_fresh > 0 and intel_fresh == 0:
            findings.append({
                "intel": intel, "input": inp, "severity": sev,
                "input_fresh_24h": input_fresh, "intel_fresh_24h": 0,
                "detail": f"{intel} got 0 rows in {STALE_HOURS}h while {inp} got {input_fresh} — pipeline silently broken",
            })
    for label, table, ts_col, where_sql, max_h, sev in ABSOLUTE:
        try:
            cur.execute(
                f"SELECT count(*) FROM {table} WHERE {where_sql} AND {ts_col} > %s",
                (datetime.now(timezone.utc) - timedelta(hours=max_h),))
            fresh = cur.fetchone()[0]
        except Exception as e:
            cur.connection.rollback()
            findings.append({"intel": f"{table}[{label}]", "error": str(e)[:120]})
            continue
        if fresh == 0:
            findings.append({
                "intel": f"{table}[{label}]", "input": "(absolute)", "severity": sev,
                "input_fresh_24h": None, "intel_fresh_24h": 0,
                "detail": f"{label}: no rows in {max_h}h — feed dead or auth/pipeline broken",
            })
    return findings


def recent_uid(cur, uid):
    cur.execute("SELECT 1 FROM alert_events WHERE alert_uid=%s AND created_at > %s LIMIT 1",
                (uid, datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)))
    return cur.fetchone() is not None


def emit_siem(cur, f):
    uid = f"intel_staleness:{f['intel']}"
    if recent_uid(cur, uid):
        return None
    payload = {**f, "monitor": "intel_table_staleness", "defect_type": "INTEL_TABLE_STALE"}
    cur.execute("""INSERT INTO alert_events
        (alert_uid, alert_type, symbol, severity, source_script, raw_text,
         parsed_payload, requires_agent_review, data_quality_status, created_at)
        VALUES (%s,%s,%s,%s,'intel_table_staleness_monitor.py',%s,%s,%s,'valid',%s) RETURNING id""",
        (uid, SIEM_ALERT_TYPE, None, f["severity"], f["detail"],
         json.dumps(payload), True, datetime.now(timezone.utc)))
    return cur.fetchone()[0]


def telegram(msg):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        scripts_dir = os.path.join(ROOT, "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram
        ok = bool(send_telegram(msg))
        try:
            if ROOT not in sys.path:
                sys.path.insert(0, ROOT)
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="intel_table_staleness_monitor", subject_key="ops:intel_staleness",
                retention_class="operational", severity="warning",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return ["send_telegram:ok" if ok else "send_telegram:fail"]
    except Exception as e:
        return [f"ERR:{e}"]


def run(send=False, as_json=False):
    load_env()
    conn = db(); cur = conn.cursor()
    findings = [f for f in detect(cur) if "error" not in f]
    emitted = []
    for f in findings:
        eid = emit_siem(cur, f)
        if eid:
            emitted.append({**f, "alert_id": eid})
    conn.commit()
    tg = []
    if send and emitted:
        lines = [f"- {e['intel']} STALE: {e['detail']}" for e in emitted]
        tg = telegram("Intel-table staleness (auto):\n" + "\n".join(lines) +
                      "\nRead-only monitor. Investigate the writer/cron.")
    report = {"run_at": datetime.now(timezone.utc).isoformat(),
              "stale_found": len(findings), "siem_emitted": emitted,
              "telegram_sent": tg, "send_enabled": send}
    conn.close()
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        if findings:
            print(f"[intel-staleness] {len(findings)} STALE table(s); {len(emitted)} SIEM emitted")
            for f in findings:
                print(f"  STALE: {f['detail']}")
        else:
            print("[intel-staleness] all tracked intel tables fresh")
    return report


if __name__ == "__main__":
    run(send="--send" in sys.argv, as_json="--json" in sys.argv)
