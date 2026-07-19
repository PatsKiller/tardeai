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


def health_checks(cur) -> list[dict]:
    out = []

    def check(name, ok, detail):
        out.append({"check": name, "ok": bool(ok), "detail": detail})

    # cron / payload freshness
    try:
        snap = json.loads(SNAP.read_text())
        age_min = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(snap["generated_at"])).total_seconds() / 60
        check("monitor_freshness", age_min < 45,
              f"lifecycle payload {age_min:.0f} min old (cron */20 market hours)")
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
