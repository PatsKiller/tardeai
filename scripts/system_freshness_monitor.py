#!/usr/bin/env python3
"""System freshness & silent-failure monitor (2026-06-04).

Generalizes intel_table_staleness_monitor.py into a REGISTRY-driven monitor. Born from the
2026-06-04 staleness scan that found multiple multi-week silent failures (catalyst_events,
sentiment_observations, fused_signals, a learning batch) — each a write that failed inside a
green job, with consumers that degraded silently. Nothing was watching.

TRUST CONTRACT:
  DETECT broadly -> ESCALATE to operator (SIEM + Telegram for P0/P1) -> AUTO-FIX only the
  provably-safe, idempotent, reversible cases (re-running a DB-only, dedup-guarded classifier).
  NEVER auto-fix schema/column changes or anything writing to trading tables. Every auto-fix is
  logged AND escalated regardless of outcome, and capped per day.

Read-only except: alert_events (SIEM), and — for allowlisted entries only — invoking an
idempotent classifier via subprocess. It never issues DDL or writes trading tables itself.

Usage:
  python3 scripts/system_freshness_monitor.py            # detect + SIEM (no telegram, no autofix)
  python3 scripts/system_freshness_monitor.py --send     # + Telegram for P0/P1
  python3 scripts/system_freshness_monitor.py --auto-fix # + narrow safe auto-remediation
  python3 scripts/system_freshness_monitor.py --json
"""
import os, sys, json, subprocess
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
STATE = os.path.join(ROOT, "logs", "freshness_autofix_state.json")
DEDUP_HOURS = 12
SIEM_ALERT_TYPE = "data_integrity"
SEV_MAP = {"P0": "critical", "P1": "urgent", "P2": "warning", "P3": "info"}

# Only these remediations are allowed to run — DB-only, idempotent, dedup-guarded, reversible.
# Each capped at MAX_AUTOFIX_PER_DAY; never schema/column/trading writes.
SAFE_REMEDIATION = {
    "news_to_catalyst": ["scripts/news_to_catalyst.py"],
    "hermes_news_bridge": ["scripts/hermes_news_bridge.py"],
    "research_insight_extractor": ["scripts/research_insight_extractor.py"],
}
MAX_AUTOFIX_PER_DAY = 2

# REGISTRY — each entry declares an expected cadence; the engine flags deviations.
#   kind 'fresh'         : table must have a row newer than max_age_h
#   kind 'empty_vs_input': table has 0 rows in window_h while `input` got >0 (the catalyst bug)
#   kind 'logfile'       : a logfile must contain `needle` written within max_age_h (cron success)
# autofix: key into SAFE_REMEDIATION (optional). sev: P0..P3 by blast radius.
REGISTRY = [
    {"key": "news_ingestion_heartbeat", "kind": "logfile",
     "path": os.path.join(ROOT, "logs", "news_ingestion.log"),
     "needle": "[news] heartbeat ok", "max_age_h": 20, "sev": "P1"},
    {"key": "news_articles",            "kind": "fresh", "table": "news_articles",            "max_age_h": 24, "sev": "P1"},
    {"key": "catalyst_events",          "kind": "fresh", "table": "catalyst_events",          "max_age_h": 24, "sev": "P1", "autofix": "news_to_catalyst"},
    {"key": "catalyst_events_vs_news",  "kind": "empty_vs_input", "table": "catalyst_events", "input": "news_articles", "window_h": 24, "sev": "P1", "autofix": "news_to_catalyst"},
    {"key": "sentiment_observations",   "kind": "fresh", "table": "sentiment_observations",   "max_age_h": 24, "sev": "P2"},
    {"key": "fused_signals",            "kind": "fresh", "table": "fused_signals",            "max_age_h": 30, "sev": "P1", "weekday_only": True},
    {"key": "fused_signals_vs_catalyst","kind": "empty_vs_input", "table": "fused_signals",   "input": "catalyst_events", "window_h": 30, "sev": "P1", "weekday_only": True},
    {"key": "research_insights",        "kind": "fresh", "table": "research_insights",         "max_age_h": 26, "sev": "P2", "autofix": "research_insight_extractor"},
    {"key": "topic_ingestion",          "kind": "fresh", "table": "topic_monitor", "ts_col": "last_searched", "agg": "min", "max_age_h": 72, "sev": "P2"},  # OLDEST topic must be <72h (full cycle ~3 days at ~7 topics/run); no autofix (hits external news APIs, not DB-only)
    {"key": "hermes_research_intel",    "kind": "fresh", "table": "hermes_research_intelligence", "max_age_h": 12, "sev": "P2"},
    {"key": "ticker_prices",            "kind": "fresh", "table": "ticker_prices",            "max_age_h": 26, "sev": "P1", "weekday_only": True},
    {"key": "cio_decisions",            "kind": "fresh", "table": "cio_decisions",            "max_age_h": 30, "sev": "P2", "weekday_only": True},
    {"key": "drive_sync_mirror",        "kind": "logfile", "path": os.path.join(ROOT, "..", "..", "logs", "drive-sync.log"),
                                        "alt_path": "/home/johnclaw/logs/drive-sync.log", "needle": "sync done", "max_age_h": 26, "sev": "P3"},
]


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


def _count_since(cur, table, hours):
    cur.execute(f"SELECT count(*) FROM {table} WHERE created_at > %s",
                (datetime.now(timezone.utc) - timedelta(hours=hours),))
    return cur.fetchone()[0]


def _age_hours(cur, table, ts_col="created_at", agg="max"):
    # agg="max" -> newest row (is the pipeline alive?); agg="min" -> oldest row
    # (are ALL items fresh? — used for per-item tables like topic_monitor where one
    # fresh topic must not mask the rest being stale).
    agg = agg if agg in ("max", "min") else "max"
    cur.execute(f"SELECT extract(epoch from (now()-{agg}({ts_col})))/3600.0 FROM {table}")
    r = cur.fetchone()[0]
    return float(r) if r is not None else None


# Minimum weekday hours a lookback window must contain before a weekday-only
# check is meaningful. Below this the writer had no realistic opportunity to
# run, so an empty table is expected rather than a finding.
MIN_WEEKDAY_HOURS_IN_WINDOW = 6


def _window_covers_a_weekday(hours: float) -> bool:
    """Does the lookback window contain any hour the writer was scheduled to run?

    G1, 2026-08-31. The gate was `weekend = datetime.now().weekday() >= 5` -- it
    asked whether TODAY is Saturday, not whether the WINDOW contains weekday
    hours. At Monday 00:00 today is Monday, so the check ran against a 30-hour
    window that was entirely weekend, and paged "fused_signals 0 rows in 30h"
    against a writer scheduled weekdays only. Four consecutive Sat/Sun pairs read
    exactly 0 against 12k-20k every weekday.

    A correct implementation already exists in system_health_agent
    (_weekday_only_schedule + _is_trading_day_cached), which walks the schedule
    across the window rather than sampling one day.

    AGENTS.md §7, detector shape: the detector keyed on the calendar day and
    structurally could not see its own window.
    """
    now = datetime.now()
    step = timedelta(hours=1)
    t = now - timedelta(hours=max(1.0, float(hours)))
    weekday_hours = 0
    while t <= now:
        if t.weekday() < 5:
            weekday_hours += 1
        t += step
    # A single boundary hour is not an opportunity to produce. At Monday 00:00 a
    # 30h window contains one hour of Monday and 29 of weekend -- which is
    # exactly the false page this fixes. Require enough weekday time that a
    # weekday-scheduled writer could plausibly have run.
    return weekday_hours >= MIN_WEEKDAY_HOURS_IN_WINDOW


def detect(cur):
    findings = []
    for e in REGISTRY:
        if e.get("weekday_only"):
            # G1: ask whether the WINDOW contains weekday hours, not whether
            # today is a weekend. Skips only when the writer could not have run
            # at any point the window covers.
            _win = e.get("window_h") or e.get("max_age_h") or 24
            if not _window_covers_a_weekday(_win):
                continue
        try:
            if e["kind"] == "fresh":
                age = _age_hours(cur, e["table"], e.get("ts_col", "created_at"), e.get("agg", "max"))
                if age is None or age > e["max_age_h"]:
                    _lbl = "oldest item" if e.get("agg") == "min" else "last row"
                    _agetxt = "never" if age is None else f"{age:.1f}h{'' if e.get('agg')=='min' else ' ago'}"
                    findings.append({**_base(e), "detail": f"{e['table']} {_lbl} {_agetxt} (max {e['max_age_h']}h)"})
            elif e["kind"] == "empty_vs_input":
                inp = _count_since(cur, e["input"], e["window_h"])
                tgt = _count_since(cur, e["table"], e["window_h"])
                if inp > 0 and tgt == 0:
                    findings.append({**_base(e), "detail": f"{e['table']} 0 rows in {e['window_h']}h "
                                     f"while {e['input']} got {inp} — silently broken"})
            elif e["kind"] == "logfile":
                path = e["path"] if os.path.exists(e["path"]) else e.get("alt_path", e["path"])
                ok = _logfile_recent(path, e["needle"], e["max_age_h"])
                if not ok:
                    findings.append({**_base(e), "detail": f"{os.path.basename(path)} no '{e['needle']}' "
                                     f"in {e['max_age_h']}h (cron silent-fail?)"})
        except Exception as ex:
            cur.connection.rollback()
            findings.append({**_base(e), "detail": f"check error: {str(ex)[:80]}", "sev": "P2"})
    return findings


def _base(e):
    return {"key": e["key"], "sev": e["sev"], "autofix": e.get("autofix")}


def _logfile_recent(path, needle, max_age_h):
    if not os.path.exists(path):
        return True  # can't check -> don't false-alarm
    cutoff = datetime.now().timestamp() - max_age_h * 3600
    try:
        # cheap: check mtime first, then scan tail for the needle
        if os.path.getmtime(path) < cutoff:
            return False
        with open(path, errors="ignore") as f:
            tail = f.readlines()[-50:]
        return any(needle in ln for ln in tail)
    except Exception:
        return True


# ---- escalation ----
def recent_uid(cur, uid):
    cur.execute("SELECT 1 FROM alert_events WHERE alert_uid=%s AND created_at > %s LIMIT 1",
                (uid, datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)))
    return cur.fetchone() is not None


def emit_siem(cur, f, extra=None):
    uid = f"freshness:{f['key']}"
    if recent_uid(cur, uid):
        return None
    payload = {**f, "monitor": "system_freshness_monitor"}
    if extra:
        payload.update(extra)
    # Idempotent write: alert_uid is globally UNIQUE (alert_events_alert_uid_key), but rows are never
    # deleted — so after the DEDUP_HOURS window recent_uid() passes and a plain INSERT would hit the unique
    # constraint and crash. ON CONFLICT updates the existing row in place (no updated_at column exists; we
    # refresh created_at so the dedup window resets → one re-fire per window, matching insert semantics).
    cur.execute("""INSERT INTO alert_events
        (alert_uid, alert_type, symbol, severity, source_script, raw_text,
         parsed_payload, requires_agent_review, data_quality_status, created_at)
        VALUES (%s,%s,%s,%s,'system_freshness_monitor.py',%s,%s,%s,'valid',%s)
        ON CONFLICT (alert_uid) DO UPDATE SET
            severity = EXCLUDED.severity,
            raw_text = EXCLUDED.raw_text,
            parsed_payload = EXCLUDED.parsed_payload,
            requires_agent_review = EXCLUDED.requires_agent_review,
            data_quality_status = EXCLUDED.data_quality_status,
            created_at = EXCLUDED.created_at
        RETURNING id""",
        (uid, SIEM_ALERT_TYPE, None, SEV_MAP[f["sev"]], f["detail"],
         json.dumps(payload, default=str), f["sev"] in ("P0", "P1"), datetime.now(timezone.utc)))
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
            if ROOT not in sys.path:
                sys.path.insert(0, ROOT)
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="system_freshness_monitor", subject_key="ops:system_freshness",
                retention_class="operational", severity="urgent",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return ["send_telegram:ok" if ok else "send_telegram:fail"]
    except Exception as ex:
        return [f"ERR:{ex}"]


# ---- narrow safe auto-fix ----
def _load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def _save_state(s):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(s, open(STATE, "w"))
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def attempt_autofix(f, day):
    """Run an allowlisted idempotent remediation. Returns (attempted, result_str)."""
    name = f.get("autofix")
    if not name or name not in SAFE_REMEDIATION:
        return False, "no-safe-remediation"
    state = _load_state()
    k = f"{f['key']}:{day}"
    n = state.get(k, 0)
    if n >= MAX_AUTOFIX_PER_DAY:
        return False, f"cap-reached ({n}/{MAX_AUTOFIX_PER_DAY}) — escalate to human"
    try:
        cmd = [PY] + SAFE_REMEDIATION[name]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
        state[k] = n + 1
        _save_state(state)
        ok = r.returncode == 0
        return True, f"ran {name} (attempt {n+1}/{MAX_AUTOFIX_PER_DAY}) rc={r.returncode} " \
                     f"{(r.stdout.strip().splitlines() or ['(no output)'])[-1][:120]}"
    except Exception as ex:
        return True, f"ran {name} — ERROR {str(ex)[:100]}"


def run(send=False, auto_fix=False, as_json=False):
    load_env()
    conn = db(); cur = conn.cursor()
    findings = detect(cur)
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    emitted, fixes = [], []

    for f in findings:
        extra = None
        # Narrow safe auto-fix BEFORE escalating, so the alert reports what was tried.
        if auto_fix and f.get("autofix"):
            attempted, result = attempt_autofix(f, day)
            if attempted:
                fixes.append({"key": f["key"], "result": result})
                extra = {"auto_remediation": result}  # auto-fix is ALWAYS logged + escalated
        eid = emit_siem(cur, f, extra)
        if eid:
            emitted.append({**f, "alert_id": eid})
    conn.commit()

    # Telegram only for P0/P1 (out-of-band, must reach the operator)
    tg = []
    pages = [e for e in emitted if e["sev"] in ("P0", "P1")]
    if send and pages:
        lines = [f"- [{e['sev']}] {e['detail']}" +
                 (f"  | auto: {e.get('auto_remediation','')}" if e.get('auto_remediation') else "")
                 for e in pages]
        tg = telegram("SYSTEM FRESHNESS — silent-failure alert:\n" + "\n".join(lines) +
                      "\nVerify; this is the silent-failure watchdog.")
    conn.close()

    # Heartbeat for the independent dead-man's-switch checker (freshness_watchdog_heartbeat.py):
    # written only when this run completed, so it proves the WATCHDOG ITSELF is alive. If
    # FRESHNESS_HEARTBEAT_PING_URL is set, also ping an OFF-HOST uptime service — that external
    # layer is the only one that survives total-box death (the deepest "who watches the watchman").
    try:
        with open(os.path.join(ROOT, "logs", ".freshness_monitor.heartbeat"), "w") as _hb:
            _hb.write(now.isoformat())
    except Exception:
        pass
    _ping = os.environ.get("FRESHNESS_HEARTBEAT_PING_URL", "").strip()
    if _ping:
        try:
            import urllib.request
            urllib.request.urlopen(_ping, timeout=10)
        except Exception:
            pass

    report = {"run_at": now.isoformat(), "checked": len(REGISTRY), "findings": len(findings),
              "siem_emitted": len(emitted), "auto_fixes": fixes, "telegram_paged": tg,
              "detail": findings}
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        if findings:
            print(f"[freshness] {len(findings)}/{len(REGISTRY)} issues; {len(emitted)} SIEM; "
                  f"{len(fixes)} auto-fix; {len(pages)} P0/P1")
            for f in findings:
                print(f"  [{f['sev']}] {f['key']}: {f['detail']}")
            for fx in fixes:
                print(f"  auto-fix {fx['key']}: {fx['result']}")
        else:
            print(f"[freshness] all {len(REGISTRY)} registry entries fresh")
    return report


if __name__ == "__main__":
    run(send="--send" in sys.argv, auto_fix="--auto-fix" in sys.argv, as_json="--json" in sys.argv)
