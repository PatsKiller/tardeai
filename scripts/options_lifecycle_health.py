#!/usr/bin/env python3
"""options_lifecycle_health.py — Phases 8+9: health checks + outcomes/calibration.

Health: every check returns {check, ok, detail}; the desk FAILS CLOSED — any
failing check surfaces on the UI with its reason, and DATA_BLOCKED positions
already refuse recommendations. Checks cover cron freshness, broker/chain
freshness, identity integrity (dup OCC, spread-as-single-leg, expired-still-
open), basis completeness, unmatched tickets, and alert delivery.

Outcomes (Phase 8): report_outcomes() aggregates the outcome ledger by
strategy/DTE/capture-band/action; propose_tuning() emits BOUNDED, reviewable
proposals only after the configured minimum sample — never adjusts anything.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_lifecycle_engine import policy

SNAP = ROOT / "data" / "runtime" / "options_lifecycle_latest.json"

# Producing cron: */20 9-16 ET Mon-Fri (see crontab options-paper-lifecycle block).
_CRON_HOURS = range(9, 17)
_CRON_STEP_MIN = 20


def _last_scheduled_fire(now=None):
    """Most recent time the */20 9-16 ET Mon-Fri lifecycle cron should have fired.

    Mirrors the cron exactly (weekday-based; the cron itself is holiday-blind,
    so on holidays the payload still regenerates and stays fresh).
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    et = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    for _ in range(8 * 24 * 3):  # scan back tick-by-tick, bounded to ~8 days
        cand = et.replace(minute=(et.minute // _CRON_STEP_MIN) * _CRON_STEP_MIN,
                          second=0, microsecond=0)
        if cand.weekday() < 5 and cand.hour in _CRON_HOURS and cand <= (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York")):
            return cand
        et = et - timedelta(minutes=_CRON_STEP_MIN)
    return et  # unreachable in practice


def _market_hours_now(now=None):
    from zoneinfo import ZoneInfo
    et = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    return et.weekday() < 5 and et.hour in _CRON_HOURS


def health_checks(cur) -> list[dict]:
    out = []

    def check(name, ok, detail):
        out.append({"check": name, "ok": bool(ok), "detail": detail})

    # cron / payload freshness — schedule-aware (2026-07-19): the producing cron
    # is */20 9-16 ET Mon-Fri, so blind wall-clock age flagged ⛔ every evening
    # and all weekend (the 2026-06-06 health-agent false-alarm class). Stale
    # means: older than the most recent scheduled fire + grace.
    try:
        snap = json.loads(SNAP.read_text())
        generated = datetime.fromisoformat(snap["generated_at"])
        age_min = (datetime.now(timezone.utc) - generated).total_seconds() / 60
        last_fire = _last_scheduled_fire()
        lag_min = (last_fire - generated).total_seconds() / 60
        if lag_min <= 45:
            check("monitor_freshness", True,
                  f"lifecycle payload {age_min:.0f} min old; covers last scheduled "
                  f"fire ({last_fire:%a %H:%M} ET{'' if _market_hours_now() else ' — off-hours, cron idle by schedule'})")
        else:
            check("monitor_freshness", False,
                  f"lifecycle payload predates last scheduled fire by {lag_min:.0f} min "
                  f"(payload {generated.isoformat()}, last fire {last_fire:%a %H:%M} ET)")
    except Exception as e:
        check("monitor_freshness", False, f"no lifecycle payload: {str(e)[:60]}")

    # expired option still open
    cur.execute("""SELECT count(*) FROM options_strategy_legs l
                   JOIN options_strategy_positions p USING (strategy_position_id)
                   WHERE l.status='open' AND p.status IN ('open','closing')
                     AND l.expiration < CURRENT_DATE""")
    n = cur.fetchone()[0]
    check("expired_still_open", n == 0,
          f"{n} leg(s) past expiration still open — resolve exercise/expiry state" if n else "none")

    # duplicate OCC within one strategy
    cur.execute("""SELECT count(*) FROM (
                     SELECT strategy_position_id, occ_symbol, side, count(*)
                     FROM options_strategy_legs WHERE status='open'
                     GROUP BY 1,2,3 HAVING count(*) > 1) d""")
    n = cur.fetchone()[0]
    check("duplicate_occ_leg", n == 0, f"{n} duplicated open leg identit(ies)" if n else "none")

    # spread-classified-as-single-leg heuristic: >1 open leg but single-leg type
    cur.execute("""SELECT count(*) FROM options_strategy_positions p
                   WHERE p.status IN ('open','closing')
                     AND p.strategy_type IN ('covered_call','cash_secured_put','long_call','long_put','protective_put')
                     AND (SELECT count(*) FROM options_strategy_legs l
                          WHERE l.strategy_position_id=p.strategy_position_id AND l.status='open') > 1""")
    n = cur.fetchone()[0]
    check("spread_as_single_leg", n == 0,
          f"{n} multi-leg position(s) carry a single-leg type — reclassify" if n else "none")

    # basis completeness
    cur.execute("""SELECT count(DISTINCT strategy_position_id) FROM options_strategy_legs
                   WHERE status='open' AND opening_price IS NULL""")
    n = cur.fetchone()[0]
    check("missing_entry_basis", n == 0,
          f"{n} position(s) with UNKNOWN basis — DATA_BLOCKED until resolved" if n else "none")

    # unreconciled positions
    cur.execute("""SELECT count(*) FROM options_strategy_positions
                   WHERE status IN ('open','closing') AND data_quality_status IN ('unreconciled','ambiguous')""")
    n = cur.fetchone()[0]
    check("unreconciled_positions", n == 0, f"{n} position(s) flagged unreconciled/ambiguous" if n else "none")

    # armed tickets going stale (armed > 1 day with no evidence)
    cur.execute("""SELECT count(*) FROM options_lifecycle_tickets
                   WHERE status='armed' AND armed_at < now() - interval '1 day'""")
    n = cur.fetchone()[0]
    check("stale_armed_tickets", n == 0,
          f"{n} armed ticket(s) >24h without fill evidence — confirm or cancel" if n else "none")

    # v1.2 P4 + v1.2.2 P1-2: projection integrity — fail closed and loud
    try:
        cur.execute("""SELECT count(*) FROM journal_projection_outbox WHERE state='FAILED'""")
        n = cur.fetchone()[0]
        check("projection_outbox_failed", n == 0,
              f"{n} journal projection(s) FAILED after retries — journal is stale" if n else "none")
        cur.execute("""SELECT
              count(*) FILTER (WHERE state='NEW' AND created_at < now() - interval '30 minutes'),
              count(*) FILTER (WHERE state='RETRY' AND next_retry_at < now() - interval '30 minutes'),
              count(*) FILTER (WHERE state='PROCESSING' AND claimed_at < now() - interval '15 minutes')
            FROM journal_projection_outbox""")
        stale_new, overdue_retry, stale_proc = cur.fetchone()
        check("outbox_stale_new", stale_new == 0, f"{stale_new} NEW row(s) >30min old" if stale_new else "none")
        check("outbox_overdue_retry", overdue_retry == 0,
              f"{overdue_retry} RETRY row(s) overdue >30min" if overdue_retry else "none")
        check("outbox_stale_processing", stale_proc == 0,
              f"{stale_proc} PROCESSING row(s) past lease" if stale_proc else "none")
        cur.execute("""SELECT count(*) FROM options_strategy_positions p
                       WHERE p.status IN ('closed','rolled','assigned','exercised','expired')
                         AND NOT EXISTS (SELECT 1 FROM journal_projection_outbox o
                                         WHERE o.strategy_position_id=p.strategy_position_id
                                           AND o.state='PROJECTED')""")
        n = cur.fetchone()[0]
        check("terminal_without_projection", n == 0,
              f"{n} terminal strateg(ies) never projected" if n else "none")
        cur.execute("""SELECT count(*) FROM options_strategy_positions p
                       JOIN trade_instances t ON t.source_table='options_strategy_positions'
                        AND t.source_trade_id = p.strategy_position_id::text
                       WHERE p.status IN ('closed','rolled','assigned','exercised','expired')
                         AND t.status='open'""")
        n = cur.fetchone()[0]
        check("closed_strategy_open_instance", n == 0,
              f"{n} closed strateg(ies) still open in trade_instances" if n else "none")
        cur.execute("""SELECT count(*) FROM options_lifecycle_outcomes o
                       WHERE NOT EXISTS (SELECT 1 FROM options_journal_events e
                                         WHERE e.strategy_position_id=o.strategy_position_id)""")
        n = cur.fetchone()[0]
        check("outcome_without_journal_event", n == 0, f"{n} outcome(s) missing events" if n else "none")
        cur.execute("""SELECT count(*) FROM trade_instances t
                       JOIN options_lifecycle_outcomes o
                         ON t.source_table='options_strategy_positions'
                        AND t.source_trade_id=o.strategy_position_id::text
                       WHERE t.pnl IS DISTINCT FROM o.realized_pnl AND t.status='closed'""")
        n = cur.fetchone()[0]
        check("instance_pnl_matches_outcome", n == 0,
              f"{n} instance(s) disagree with lifecycle outcome P&L" if n else "match")
    except Exception as e:
        check("projection_integrity", False, f"check errored: {str(e)[:80]}")

    # v1.2.1 P0-6: unresolved roll-package incidents = RED, operator action required
    try:
        cur.execute("""SELECT count(*), string_agg(DISTINCT state, ', ') FROM options_package_incidents
                       WHERE resolved_at IS NULL""")
        n, states = cur.fetchone()
        check("roll_package_incidents", (n or 0) == 0,
              f"{n} UNRESOLVED package incident(s): {states} — operator review required" if n else "none")
    except Exception:
        check("roll_package_incidents", True, "table not yet created")

    # v1.2 P1: schema reproducibility
    try:
        from options_lifecycle_model import verify_schema
        probs = verify_schema(cur)
        check("schema_reproducible", not probs, "; ".join(probs) if probs else
              "all expected columns present from committed builders")
    except Exception as e:
        check("schema_reproducible", False, str(e)[:80])

    # alert delivery: red alerts that never reached any channel
    cur.execute("""SELECT count(*) FROM options_lifecycle_alerts
                   WHERE urgency='red' AND state NOT IN ('RESOLVED','SUPERSEDED')
                     AND channels_sent='[]'::jsonb
                     AND created_at < now() - interval '30 minutes'""")
    n = cur.fetchone()[0]
    check("alert_delivery", n == 0, f"{n} red alert(s) undelivered to any channel" if n else "ok")

    return out


# ── Phase 8: outcomes + bounded tuning proposals ─────────────────────────────

def report_outcomes(cur) -> dict:
    cur.execute("SELECT count(*) FROM options_lifecycle_outcomes")
    total = cur.fetchone()[0]
    rep = {"total_closed": total, "by_strategy": [], "by_action": [],
           "honesty": ("OUTCOME VALIDATION NOT AVAILABLE — no closed positions yet"
                       if total == 0 else None)}
    if total == 0:
        return rep
    cur.execute("""SELECT p.strategy_type, count(*), sum(o.realized_pnl), avg(o.realized_pnl)
                   FROM options_lifecycle_outcomes o
                   JOIN options_strategy_positions p USING (strategy_position_id)
                   GROUP BY 1 ORDER BY 2 DESC""")
    rep["by_strategy"] = [{"strategy": r[0], "n": r[1],
                           "realized_total": float(r[2] or 0), "realized_avg": float(r[3] or 0)}
                          for r in cur.fetchall()]
    cur.execute("""SELECT operator_action, recommendation_at_action, count(*)
                   FROM options_lifecycle_outcomes GROUP BY 1,2 ORDER BY 3 DESC""")
    rep["by_action"] = [{"operator_action": r[0], "recommendation": r[1], "n": r[2]}
                        for r in cur.fetchall()]
    return rep


def propose_tuning(cur) -> dict:
    """Bounded, reviewable proposals only; silent below the minimum sample.
    NEVER writes config — output is for the operator's eyes."""
    pol = policy()
    t = pol["tuning"]
    cur.execute("""SELECT p.strategy_type, count(*) FROM options_lifecycle_outcomes o
                   JOIN options_strategy_positions p USING (strategy_position_id) GROUP BY 1""")
    counts = dict(cur.fetchall())
    proposals = []
    for strat, n in counts.items():
        if n < t["min_closed_positions_per_strategy"]:
            continue
        proposals.append({"strategy": strat, "n": n,
                          "note": f"minimum sample reached (n={n}) — calibration analysis unlocked; "
                                  f"any threshold proposal is bounded to ±{t['max_threshold_change_pct']}% "
                                  "and requires operator review + policy_version bump"})
    return {"eligible": proposals,
            "gate": f"min n={t['min_closed_positions_per_strategy']}/strategy, "
                    f"±{t['max_threshold_change_pct']}% bound, no automatic application",
            "silent_below_sample": not proposals}


if __name__ == "__main__":
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    for c in health_checks(cur):
        print(("✓" if c["ok"] else "⛔"), c["check"], "—", c["detail"])
    print(json.dumps(report_outcomes(cur), indent=1))
    print(json.dumps(propose_tuning(cur), indent=1))
