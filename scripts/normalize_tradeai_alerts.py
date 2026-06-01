#!/usr/bin/env python3
"""
TradeAI Alert SIEM-Lite Normalizer.
Reads from alert_events + notification_log + system_health_events,
normalizes into a JSONL event log with dedupe and severity classification.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

SEVERITY_MAP = {
    "STOP_TRIGGERED": "P1",
    "FEED_HEALTH": "P1",
    "PIPELINE_FAILURE": "P1",
    "DATA_QUALITY": "P2",
    "AGENT_STALENESS": "P2",
    "LLM_ESCALATION": "P2",
    "SYSTEM_HEALTH": "P2",
    "CLOSED_TRADE_REVIEW": "P2",
    "MARKET_REGIME_CHANGE": "P3",
    "LLM_ANALYSIS_COMPLETE": "P3",
    "EOD_REPORT": "P3",
}

def classify_event(alert_type, raw_text="", symbol=None):
    """Classify an alert into event_type and severity."""
    text = (raw_text or "").lower()
    if "stop" in text and ("triggered" in text or "hit" in text):
        return "STOP_TRIGGERED", SEVERITY_MAP.get("STOP_TRIGGERED", "P1")
    if "cookie" in text or "finviz" in text.lower() and "expired" in text:
        return "FEED_HEALTH", "P1"
    if "stale" in text and ("agent" in text or "maria" in text):
        return "AGENT_STALENESS", "P2"
    if "llm" in text and ("escalat" in text or "tier" in text):
        return "LLM_ESCALATION", "P2"
    if "data quality" in text or "zero" in text:
        return "DATA_QUALITY", "P2"
    if "output_invalid" in text or "locktimeout" in text:
        return "PIPELINE_FAILURE", "P1"
    if "exit reason" in text and ("blank" in text or "''" in text):
        return "CLOSED_TRADE_REVIEW", "P2"
    if alert_type == "strategic_alert":
        return "SYSTEM_HEALTH", "P2"
    if alert_type == "data_staleness":
        return "DATA_QUALITY", "P2"
    if alert_type == "stop_brief":
        return "STOP_TRIGGERED", "P1"
    return alert_type.upper() if alert_type else "UNKNOWN", "P3"

def dedupe_key(event_type, symbol, component):
    """Generate a dedupe key for suppression tracking."""
    return f"{event_type}:{symbol or 'sys'}:{component or 'unknown'}"

def normalize(days=7, dry_run=True):
    """Normalize alerts from the last N days."""
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    events = []

    # Source 1: alert_events
    cur.execute("""
        SELECT id, alert_uid, alert_type, symbol, severity, source_script,
               raw_text, data_quality_status, created_at
        FROM alert_events WHERE created_at > %s
        ORDER BY created_at DESC
    """, [cutoff])
    for row in cur.fetchall():
        aid, uid, atype, sym, sev, src, raw, dq, ts = row
        etype, esev = classify_event(atype, raw, sym)
        events.append({
            "event_id": f"ae-{aid}",
            "timestamp": ts.isoformat() if ts else None,
            "source_channel": "alert_events",
            "raw_source": src,
            "event_type": etype,
            "severity": esev,
            "symbol": sym,
            "component": src,
            "dedupe_key": dedupe_key(etype, sym, src),
            "raw_message_excerpt": (raw or "")[:200],
            "resolved_status": "unknown",
        })

    # Source 2: notification_log (Telegram messages)
    cur.execute("""
        SELECT id, channel, subject, body_summary, created_at
        FROM notification_log WHERE created_at > %s AND channel LIKE '%%telegram%%'
        ORDER BY created_at DESC
    """, [cutoff])
    for row in cur.fetchall():
        nid, chan, subj, body, ts = row
        text = (subj or "") + " " + (body or "")
        etype, esev = classify_event("telegram", text)
        events.append({
            "event_id": f"nl-{nid}",
            "timestamp": ts.isoformat() if ts else None,
            "source_channel": "notification_log",
            "raw_source": "telegram",
            "event_type": etype,
            "severity": esev,
            "symbol": None,
            "component": "telegram",
            "dedupe_key": dedupe_key(etype, None, "telegram"),
            "raw_message_excerpt": text[:200],
            "resolved_status": "unknown",
        })

    # Source 3: system_health_events
    cur.execute("""
        SELECT id, event_type, component, severity, message, created_at
        FROM system_health_events WHERE created_at > %s
        ORDER BY created_at DESC LIMIT 200
    """, [cutoff])
    for row in cur.fetchall():
        sid, setype, comp, ssev, msg, ts = row
        etype, esev = classify_event(setype or "", msg or "", None)
        events.append({
            "event_id": f"she-{sid}",
            "timestamp": ts.isoformat() if ts else None,
            "source_channel": "system_health_events",
            "raw_source": comp,
            "event_type": etype,
            "severity": esev,
            "symbol": None,
            "component": comp,
            "dedupe_key": dedupe_key(etype, None, comp),
            "raw_message_excerpt": (msg or "")[:200],
            "resolved_status": "unknown",
        })

    conn.close()

    # Sort by timestamp
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    # Dedupe analysis
    dedupe_groups = {}
    for e in events:
        dk = e["dedupe_key"]
        if dk not in dedupe_groups:
            dedupe_groups[dk] = {"count": 0, "first": e["timestamp"], "last": e["timestamp"], "severity": e["severity"]}
        dedupe_groups[dk]["count"] += 1
        dedupe_groups[dk]["last"] = e["timestamp"]

    # Mark suppressions (>3 of same type in window)
    for e in events:
        dk = e["dedupe_key"]
        g = dedupe_groups[dk]
        e["repeat_count"] = g["count"]
        e["first_seen"] = g["first"]
        e["last_seen"] = g["last"]
        e["suppression_status"] = "SUPPRESS_TO_DIGEST" if g["count"] > 3 else "SEND"

    # Severity summary
    sev_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "SUPPRESSED": 0}
    for e in events:
        if e["suppression_status"] == "SUPPRESS_TO_DIGEST":
            sev_counts["SUPPRESSED"] += 1
        else:
            sev_counts[e["severity"]] = sev_counts.get(e["severity"], 0) + 1

    # Write output
    out_dir = PROJECT_ROOT / "data" / "system_events"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "normalized_alert_events.jsonl"

    if not dry_run:
        with open(out_file, "w") as f:
            for e in events:
                f.write(json.dumps(e, default=str) + "\n")

    # Daily rollup
    today = datetime.now().strftime("%Y-%m-%d")
    rollup = {
        "date": today,
        "total_raw": len(events),
        "dedupe_groups": len(dedupe_groups),
        "severity": sev_counts,
        "top_dedupe": sorted(
            [{"key": k, **v} for k, v in dedupe_groups.items()],
            key=lambda x: -x["count"]
        )[:10],
        "immediate_alerts": sum(1 for e in events if e["suppression_status"] == "SEND" and e["severity"] in ("P0", "P1")),
        "digest_only": sum(1 for e in events if e["suppression_status"] == "SUPPRESS_TO_DIGEST"),
    }

    if not dry_run:
        daily_dir = out_dir / "daily"
        daily_dir.mkdir(exist_ok=True)
        (daily_dir / f"{today}_alert_rollup.json").write_text(json.dumps(rollup, indent=2, default=str))

    return events, rollup


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--apply", action="store_true", help="Write output files (default: dry-run)")
    args = ap.parse_args()

    events, rollup = normalize(days=args.days, dry_run=not args.apply)

    print(f"Total raw events: {rollup['total_raw']}")
    print(f"Dedupe groups: {rollup['dedupe_groups']}")
    print(f"Severity: {rollup['severity']}")
    print(f"Immediate alerts (P0/P1): {rollup['immediate_alerts']}")
    print(f"Digest-only (suppressed): {rollup['digest_only']}")
    print(f"Top dedupe groups:")
    for g in rollup["top_dedupe"][:5]:
        print(f"  {g['key']}: {g['count']}x")
    if not args.apply:
        print("\nDry-run mode. Use --apply to write files.")
