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

    # 5. scorer alive — the 2026-07-01 psycopg2 crash killed the scorer for a full day and nothing
    # noticed. hermes_scored_at is touched every run even when the history INSERT is skipped as
    # unchanged. Cron is 2x/hour; llm_priority_guard can defer it 06:00–12:00 ET, so alert past 8h.
    try:
        stale_h = _scalar(cur, "SELECT EXTRACT(epoch FROM NOW() - MAX(hermes_scored_at))/3600 "
                               "FROM watchlist_items WHERE status IN ('active','researched')")
        if stale_h is None or float(stale_h) > 8:
            issues.append(f"watchlist scorer silent for {float(stale_h or 999):.0f}h "
                          "(cron is 2x/hour — script is crashing or wedged; check logs/hermes_scorer.log)")
    except Exception as e:
        issues.append(f"scorer freshness check failed: {str(e)[:80]}")

    # 6. quality-score distribution collapse (Phase 4) — the old rule grade degenerated into two
    # point masses (0.30/0.62), which silently gutted research ranking. Alert if it re-collapses.
    try:
        cur.execute("""SELECT stddev(quality_score), count(DISTINCT quality_score)
                       FROM hermes_research_intelligence
                       WHERE quality_score IS NOT NULL AND created_at > NOW() - interval '30 days'""")
        sd, distinct = cur.fetchone()
        if sd is not None and (float(sd) < 0.03 or int(distinct or 0) <= 3):
            issues.append(f"quality_score distribution collapsed (stddev={float(sd):.4f}, "
                          f"{distinct} distinct values 30d) — grade is no longer discriminating; "
                          "check hermes_tag_engine quality blend")
    except Exception:
        pass

    # ── Phase 5.2 correctness watchdogs (liveness above; wrongness below) ──────
    # 7. score-write volume anomaly — event-driven scoring should stay ≤~8K rows/day; a spike
    # means the cap/skip regressed (the exact failure the audit found: 157K/day of duplicates).
    try:
        n = _scalar(cur, """SELECT count(*) FROM hermes_score_history
                            WHERE scored_at > NOW() - interval '24 hours'""")
        if n is not None and int(n) > 20000:
            issues.append(f"score-history writes {int(n)}/24h (>20K) — tier cap or no-change skip regressed")
    except Exception:
        pass
    # 8. external error-call burn — the breaker should hold this near zero
    try:
        cur.execute("""SELECT count(*) FILTER (WHERE status='error'), count(*)
                       FROM hermes_external_research WHERE created_at > NOW() - interval '24 hours'""")
        e, t = cur.fetchone()
        if t and t >= 20 and e / t > 0.20:
            issues.append(f"external error-calls {e}/{t} ({e/t*100:.0f}%) in 24h — lane breaker not holding")
    except Exception:
        pass
    # 9. promotion precision collapse — the learned gate should be pushing this UP over time
    try:
        cur.execute("""SELECT count(*) FILTER (WHERE verdict='hit'), count(*) FILTER (WHERE verdict='miss')
                       FROM hermes_outcome_ledger
                       WHERE subject_type='promotion' AND graded_at > NOW() - interval '30 days'""")
        h, m = cur.fetchone()
        if (h + m) >= 50 and h / (h + m) < 0.25:
            issues.append(f"promotion precision {h}/{h+m} ({h/(h+m)*100:.0f}%) over 30d graded — "
                          "promotion gates not filtering; review hermes_promotion_thresholds")
    except Exception:
        pass
    # 10. S0 (capital-exposed) scoring coverage — the crowd-out class of failure
    try:
        cur.execute("""SELECT count(*) FILTER (WHERE hermes_scored_at > NOW() - interval '6 hours'),
                              count(*)
                       FROM (SELECT DISTINCT UPPER(symbol) sym, MAX(hermes_scored_at) hermes_scored_at
                             FROM watchlist_items WHERE scope_tier='S0'
                               AND status IN ('active','researched') GROUP BY 1) s""")
        fresh, tot = cur.fetchone()
        if tot and fresh < tot * 0.8:
            issues.append(f"S0 scoring coverage {fresh}/{tot} (<80% fresh 6h) — holdings/positions "
                          "falling out of the scoring loop (crowd-out regression)")
    except Exception:
        pass

    # 11. Scope governor heartbeat — tier ledger owner (:07/:37 cron)
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
        from lib.hermes_scope_governor.health import check_scope_governor_health
        for f in check_scope_governor_health(conn):
            if f.get("severity") in ("critical", "warning"):
                issues.append(f["message"])
    except Exception as e:
        issues.append(f"scope governor health probe failed: {str(e)[:80]}")

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
    # Phase 5.2: correctness breaches open an escalation-queue item (the existing operator/coder
    # dispatch surface) — one per day, so a persistent breach can't flood the queue.
    try:
        from db_adapter import _execute
        import json as _json
        from datetime import date as _date
        _execute(
            """INSERT INTO escalation_queue (created_at, symbol, severity, category, trigger_rule,
                                             summary, evidence, status, expires_at)
               SELECT NOW(), NULL, 2, 'hermes_watchdog', 'hermes_pipeline_health',
                      %s, %s::jsonb, 'pending', NOW() + interval '7 days'
               WHERE NOT EXISTS (SELECT 1 FROM escalation_queue
                                 WHERE category='hermes_watchdog' AND created_at::date = %s)""",
            (f"Hermes watchdog: {len(issues)} issue(s) — " + "; ".join(i[:90] for i in issues[:3]),
             _json.dumps({"issues": issues}), _date.today()), fetch=None,
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
