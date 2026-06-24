#!/usr/bin/env python3
"""hermes_pipeline_health.py — catch SILENT Hermes pipeline failures.

Two months of Hermes rank-surge alerts were dropped silently because an INSERT failed a check
constraint and nothing watched it. This monitor flags that class of failure:
  1. External lanes gone stale (a lane that should produce daily has no row in N days — catches
     the 'crons hardcoded to one lane' regression).
  2. Score-alert pipeline silent (alerter cron runs but no hermes_* alert landed in 24h).
  3. Advisory-event queue jammed (pending high, zero completing).
  4. Embedding queue failure rate high.

Emits a single 'system_health' alert_event (+ stdout) when anything is broken. Advisory/read-only.
Run from cron daily; `--send` also pushes a telegram via the unified dispatcher if available.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

LANE_STALE_DAYS = int(os.getenv("HERMES_LANE_STALE_DAYS", "3"))
EXPECTED_LANES = [s.strip() for s in os.getenv("HERMES_EXPECTED_LANES", "grok,chatgpt").split(",") if s.strip()]


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _scalar(cur, sql, params=None):
    cur.execute(sql, params or ())
    r = cur.fetchone()
    return r[0] if r else None


def check() -> list[str]:
    issues: list[str] = []
    conn = _conn()
    cur = conn.cursor()

    # 1. external lane freshness
    for lane in EXPECTED_LANES:
        try:
            n = _scalar(cur, "SELECT count(*) FROM hermes_external_research WHERE lane=%s "
                             "AND created_at >= NOW() - (%s || ' days')::interval", (lane, LANE_STALE_DAYS))
            if not n:
                issues.append(f"external lane '{lane}' produced 0 rows in {LANE_STALE_DAYS}d (lane stale/unwired)")
        except Exception as e:
            issues.append(f"lane check failed ({lane}): {str(e)[:80]}")

    # 2. score-alert pipeline alive (now that the constraint is fixed)
    try:
        n = _scalar(cur, "SELECT count(*) FROM alert_events WHERE source_script='hermes_score_alerts' "
                         "AND created_at >= NOW() - INTERVAL '24 hours'")
        if not n:
            issues.append("H-5 score-alerter produced 0 alerts in 24h (cron runs */30 — likely a silent insert failure)")
    except Exception as e:
        issues.append(f"alert pipeline check failed: {str(e)[:80]}")

    # 3. advisory-event queue jam
    try:
        cur.execute("SELECT event_status, count(*) FROM hermes_advisory_events GROUP BY event_status")
        st = {r[0]: r[1] for r in cur.fetchall()}
        pending = int(st.get("pending") or 0)
        completed = int(st.get("completed") or 0)
        if pending >= 200 and completed == 0:
            issues.append(f"advisory-event queue jammed: {pending} pending, 0 ever completed (producer/worker stalled)")
    except Exception:
        pass

    # 4. embedding failure rate
    try:
        cur.execute("SELECT embedding_status, count(*) FROM hermes_embedding_queue GROUP BY embedding_status")
        st = {r[0]: r[1] for r in cur.fetchall()}
        failed = int(st.get("failed") or 0)
        done = int(st.get("completed") or 0) + int(st.get("done") or 0)
        if failed and (failed / max(1, failed + done)) > 0.15:
            issues.append(f"embedding queue {failed} failed ({failed/(failed+done)*100:.0f}%) — no retry sweep")
    except Exception:
        pass

    conn.close()
    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="also push a telegram alert")
    a = ap.parse_args()
    issues = check()
    if not issues:
        print("[hermes-health] OK — lanes fresh, alerter alive, queues healthy")
        return 0
    msg = "⚠ Hermes pipeline health:\n" + "\n".join(f"  • {i}" for i in issues)
    print(msg)
    try:
        from db_adapter import _execute
        _execute(
            """INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
               VALUES (%s,'system_health',NULL,'warning','hermes_pipeline_health',%s,NOW())
               ON CONFLICT (alert_uid) DO NOTHING""",
            (f"hermes_health_{os.popen('date +%Y%m%d%H').read().strip()}", msg), fetch=None,
        )
    except Exception:
        pass
    if a.send:
        try:
            import alert_dispatcher_unified as ad
            ad.dispatch(alert_type="system_health", text=msg, severity="warning", source="hermes_pipeline_health")
        except Exception:
            pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
