#!/usr/bin/env python3
"""Dead-man's switch for the freshness watchdog (2026-06-04) — "who watches the watchman".

system_freshness_monitor.py cannot detect its OWN death (a dead process can't report itself).
This is the independent checker: it verifies the monitor wrote its heartbeat recently, and pages
the operator if not. It is deliberately SELF-CONTAINED (no import of the monitor) so that a broken
monitor can't also break its watcher — independence is the whole point.

Coverage (honest):
  - Catches: monitor cron removed / monitor code erroring / monitor silently not running, while
    this host + cron daemon are still alive. (The common case.)
  - Does NOT catch: total-host death (this script can't run either). That gap is covered only by
    the monitor's OWN off-host ping (FRESHNESS_HEARTBEAT_PING_URL) to an external uptime service —
    the terminating layer. This in-host checker is the no-external-dependency layer.
  - This checker is itself unwatched (turtles stop somewhere); the external ping is the terminus.

Read-only except alert_events (SIEM). Usage:
  python3 scripts/freshness_watchdog_heartbeat.py [--send]
"""
import os, sys, json
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEARTBEAT = os.path.join(ROOT, "logs", ".freshness_monitor.heartbeat")
# Monitor runs */20; alarm after ~3 missed cycles so a single hiccup doesn't page.
MAX_AGE_MIN = 70
DEDUP_HOURS = 6
SIEM_ALERT_TYPE = "data_integrity"


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def heartbeat_age_min():
    """Minutes since the monitor's last completed run; None if no heartbeat exists at all."""
    if not os.path.exists(HEARTBEAT):
        return None
    try:
        ts = open(HEARTBEAT).read().strip()
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except Exception:
        # fall back to file mtime if content unparseable
        last = datetime.fromtimestamp(os.path.getmtime(HEARTBEAT), tz=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 60.0


OFFHOST_PING = os.path.join(ROOT, "logs", ".offhost_ping.txt")


def offhost_ping_age_min():
    """Minutes since the in-network heartbeat receiver last got a ping from the monitor."""
    if not os.path.exists(OFFHOST_PING):
        return None
    try:
        ts = open(OFFHOST_PING).read().strip()
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except Exception:
        last = datetime.fromtimestamp(os.path.getmtime(OFFHOST_PING), tz=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 60.0


def telegram(msg):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
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
                producer="freshness_watchdog_heartbeat", subject_key="ops:freshness_watchdog",
                retention_class="operational", severity="critical",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return ["send_telegram:ok" if ok else "send_telegram:fail"]
    except Exception as ex:
        return [f"ERR:{ex}"]


def emit_siem(cur, detail, uid="watchdog_dead:freshness_monitor"):
    cur.execute("SELECT 1 FROM alert_events WHERE alert_uid=%s AND created_at > %s LIMIT 1",
                (uid, datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)))
    if cur.fetchone():
        return None
    payload = {"monitor": "freshness_watchdog_heartbeat", "defect_type": "WATCHDOG_SILENT",
               "detail": detail}
    cur.execute("""INSERT INTO alert_events
        (alert_uid, alert_type, symbol, severity, source_script, raw_text,
         parsed_payload, requires_agent_review, data_quality_status, created_at)
        VALUES (%s,%s,%s,'critical','freshness_watchdog_heartbeat.py',%s,%s,TRUE,'valid',%s) RETURNING id""",
        (uid, SIEM_ALERT_TYPE, None, detail, json.dumps(payload), datetime.now(timezone.utc)))
    return cur.fetchone()[0]


def run(send=False):
    load_env()
    findings = []  # (uid_key, detail)

    # 1. monitor's own heartbeat file (is the monitor running at all?)
    age = heartbeat_age_min()
    if age is None or age > MAX_AGE_MIN:
        findings.append(("watchdog_dead:freshness_monitor",
            f"freshness monitor SILENT — last heartbeat {'never' if age is None else f'{age:.0f}m ago'} "
            f"(> {MAX_AGE_MIN}m). The silent-failure watchdog may itself be down — check the */20 cron."))

    # 2. off-host ping (in-network layer 3) — only if a ping URL is configured. Stale = the monitor
    #    isn't pinging, or the in-network receiver is down. NOTE: same-host, so covers monitor/
    #    process death, NOT total-box death (use an off-host healthchecks URL for that).
    if os.environ.get("FRESHNESS_HEARTBEAT_PING_URL", "").strip():
        page = offhost_ping_age_min()
        if page is None or page > MAX_AGE_MIN:
            findings.append(("watchdog_dead:offhost_ping",
                f"off-host heartbeat ping SILENT — receiver last got a ping "
                f"{'never' if page is None else f'{page:.0f}m ago'} (> {MAX_AGE_MIN}m). Monitor not "
                f"pinging, or the in-network receiver (heartbeat_receiver.py) is down."))

    if not findings:
        msg = f"monitor heartbeat {age:.0f}m"
        if os.environ.get("FRESHNESS_HEARTBEAT_PING_URL", "").strip():
            msg += f"; off-host ping {offhost_ping_age_min():.0f}m"
        print(f"[watchdog-heartbeat] OK — {msg}")
        return {"ok": True, "age_min": age}

    conn = db(); cur = conn.cursor()
    emitted = []
    for uid, detail in findings:
        eid = emit_siem(cur, detail, uid=uid)
        emitted.append((uid, eid, detail))
    conn.commit(); conn.close()
    tg = telegram("WATCHDOG DOWN (P0):\n" + "\n".join(f"- {d}" for _, _, d in emitted) +
                  "\nInvestigate immediately.") if send else []
    for uid, eid, detail in emitted:
        print(f"[watchdog-heartbeat] STALE [{uid.split(':')[-1]}] {detail} | SIEM={eid}")
    return {"ok": False, "findings": [u for u, _, _ in emitted], "telegram": tg}


if __name__ == "__main__":
    run(send="--send" in sys.argv)
