#!/usr/bin/env python3
"""hermes_maturity_gates.py — Phase 5.3: the HONEST maturity board
(docs/design/HERMES_MATURITY_5_DESIGN.md §5.3).

Six dimensions, every gate computed live from the DB — nothing hardcoded. A dimension can
only show 5 when ALL its gates pass AND they have held for 30 consecutive daily snapshots
(hermes_maturity_history) — a 5 is earned by sample and time, never claimed. Until then the
best a dimension can show is 4 ("all gates pass, persistence accruing").

Imported by hermes_maturity_dashboard (UI section) and run daily by cron for the snapshot:

  python3 scripts/hermes_maturity_gates.py            # print board
  python3 scripts/hermes_maturity_gates.py --snapshot # also write today's history row
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PERSISTENCE_DAYS = 30


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _s(cur, sql, params=()):
    cur.execute(sql, params)
    r = cur.fetchone()
    return r[0] if r else None


def _gates_scope(cur):
    g = {}
    cap = 800
    try:
        import yaml
        cap = int((yaml.safe_load((PROJECT_ROOT / "config" / "hermes_scope_governor.yaml").read_text()) or {}).get("total_cap", 800))
    except Exception:
        pass
    live = _s(cur, """SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items
                      WHERE scope_tier IN ('S0','S1','S2') AND status IN ('active','researched')""") or 0
    g["universe_within_cap"] = {"pass": 0 < live <= cap, "value": live, "target": f"1..{cap}"}
    # holdings scored fresh (S0 cadence is 15m; give 4h slack for guard windows)
    tot = _s(cur, """SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items
                     WHERE scope_tier='S0' AND status IN ('active','researched')""") or 0
    fresh = _s(cur, """SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items
                       WHERE scope_tier='S0' AND status IN ('active','researched')
                         AND hermes_scored_at > NOW() - interval '4 hours'""") or 0
    g["s0_scoring_coverage"] = {"pass": tot > 0 and fresh >= tot * 0.98,
                                "value": f"{fresh}/{tot}", "target": ">=98% S0 scored <4h"}
    # trigger coverage: share of symbols scored in 24h that are governed-live (or event-driven)
    scored = _s(cur, "SELECT count(DISTINCT symbol) FROM hermes_score_history WHERE scored_at > NOW() - interval '24 hours'") or 0
    scored_live = _s(cur, """SELECT count(DISTINCT h.symbol) FROM hermes_score_history h
                             WHERE h.scored_at > NOW() - interval '24 hours'
                               AND EXISTS (SELECT 1 FROM watchlist_items wi
                                           WHERE UPPER(wi.symbol)=UPPER(h.symbol)
                                             AND wi.scope_tier IN ('S0','S1','S2'))""") or 0
    pct = (scored_live / scored) if scored else 0
    g["trigger_coverage"] = {"pass": pct >= 0.80, "value": round(pct, 3), "target": ">=0.80"}
    runs = _s(cur, "SELECT count(DISTINCT run_id) FROM scope_governor_audit WHERE created_at > NOW() - interval '24 hours'") or 0
    g["governor_active"] = {"pass": runs >= 1, "value": runs, "target": ">=1 run/24h"}
    return g


def _gates_research(cur):
    g = {}
    err = _s(cur, """SELECT COALESCE(count(*) FILTER (WHERE status='error')::float / NULLIF(count(*),0), 0)
                     FROM hermes_external_research WHERE created_at > NOW() - interval '24 hours'""") or 0
    g["external_error_rate"] = {"pass": float(err) < 0.02, "value": round(float(err), 3), "target": "<0.02"}
    tot = _s(cur, """SELECT count(DISTINCT UPPER(symbol)) FROM paper_trade_proposals
                     WHERE created_at > NOW() - interval '30 days'""") or 0
    prior = _s(cur, """SELECT count(DISTINCT UPPER(p.symbol)) FROM paper_trade_proposals p
                       WHERE p.created_at > NOW() - interval '30 days'
                         AND EXISTS (SELECT 1 FROM hermes_research_intelligence h
                                     WHERE UPPER(h.symbol)=UPPER(p.symbol) AND h.created_at < p.created_at
                                       AND h.created_at > p.created_at - interval '30 days')""") or 0
    pct = (prior / tot) if tot else 0
    g["proposals_with_prior_research"] = {"pass": pct >= 0.60, "value": round(pct, 3), "target": ">=0.60"}
    # T0 freshness SLA proxy: capital-exposed symbols with research <7d
    s0 = _s(cur, """SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items
                    WHERE scope_tier='S0' AND status IN ('active','researched')""") or 0
    s0_fresh = _s(cur, """SELECT count(DISTINCT UPPER(wi.symbol)) FROM watchlist_items wi
                          WHERE wi.scope_tier='S0' AND wi.status IN ('active','researched')
                            AND EXISTS (SELECT 1 FROM hermes_research_intelligence h
                                        WHERE UPPER(h.symbol)=UPPER(wi.symbol)
                                          AND h.created_at > NOW() - interval '7 days')""") or 0
    pct = (s0_fresh / s0) if s0 else 0
    g["s0_research_freshness"] = {"pass": pct >= 0.95, "value": round(pct, 3), "target": ">=0.95 <7d"}
    return g


def _gates_tagging(cur):
    g = {}
    fb = _s(cur, """SELECT COALESCE(count(*) FILTER (WHERE strategy_tags = ARRAY['general_research'])::float
                    / NULLIF(count(*),0), 1) FROM hermes_research_intelligence
                    WHERE created_at > NOW() - interval '30 days'""") or 1
    g["fallback_share"] = {"pass": float(fb) < 0.15, "value": round(float(fb), 3), "target": "<0.15"}
    # >=1 tag family with statistically significant positive lift at n>=50 (z > 1.96)
    cur.execute("""SELECT tag, n, lift, base_rate FROM hermes_tag_efficacy
                   WHERE n >= 50 AND lift IS NOT NULL AND base_rate IS NOT NULL""")
    sig = []
    for tag, n, lift, base in cur.fetchall():
        b = float(base)
        se = (b * (1 - b) / n) ** 0.5 if 0 < b < 1 else None
        if se and float(lift) / se > 1.96:
            sig.append(tag)
    g["significant_tag_lift"] = {"pass": bool(sig), "value": sig[:3], "target": ">=1 tag, n>=50, z>1.96"}
    sd = _s(cur, """SELECT stddev(quality_score) FROM hermes_research_intelligence
                    WHERE quality_score IS NOT NULL AND created_at > NOW() - interval '30 days'""")
    g["quality_discriminates"] = {"pass": sd is not None and float(sd) >= 0.03,
                                  "value": round(float(sd), 4) if sd is not None else None, "target": "stddev>=0.03"}
    return g


def _gates_efficiency(cur):
    g = {}
    rows_day = _s(cur, """SELECT count(*) FROM hermes_score_history
                          WHERE scored_at >= (CURRENT_DATE - 1) AND scored_at < CURRENT_DATE""") or 0
    g["score_rows_per_day"] = {"pass": rows_day <= 5000, "value": rows_day, "target": "<=5000"}
    mb = _s(cur, "SELECT pg_total_relation_size('hermes_score_history') / 1024 / 1024") or 0
    g["score_history_size_mb"] = {"pass": int(mb) <= 300, "value": int(mb), "target": "<=300MB"}
    err = _s(cur, """SELECT COALESCE(count(*) FILTER (WHERE status='error')::float / NULLIF(count(*),0), 0)
                     FROM hermes_external_research WHERE created_at > NOW() - interval '7 days'""") or 0
    g["error_call_rate_7d"] = {"pass": float(err) < 0.05, "value": round(float(err), 3), "target": "<0.05"}
    paid = _s(cur, """SELECT count(*) FROM hermes_external_research
                      WHERE created_at > NOW() - interval '30 days' AND lane_used='claude'
                        AND trigger_source NOT IN ('monthly_protection_meta_review','operator','manual')""") or 0
    g["no_unauthorized_paid_llm"] = {"pass": int(paid) == 0, "value": int(paid), "target": "0"}
    return g


def _gates_closed_loop(cur):
    g = {}
    # graded pairs with components available to the calibrator, per the weakest factor's gate
    pairs = _s(cur, """SELECT count(*) FROM hermes_outcome_ledger
                       WHERE components IS NOT NULL
                         AND ((subject_type IN ('promotion','external_rec') AND outcome_ret_20d IS NOT NULL)
                              OR (subject_type='trade' AND realized_r IS NOT NULL))""") or 0
    g["calibration_pairs"] = {"pass": pairs >= 20, "value": pairs, "target": ">=20 graded w/ components"}
    hits = _s(cur, "SELECT count(*) FROM hermes_outcome_ledger WHERE subject_type='promotion' AND verdict='hit'") or 0
    misses = _s(cur, "SELECT count(*) FROM hermes_outcome_ledger WHERE subject_type='promotion' AND verdict='miss'") or 0
    n = hits + misses
    g["promotion_sample_and_precision"] = {"pass": n >= 100 and hits > misses,
                                           "value": f"{hits}H/{misses}M (n={n})",
                                           "target": ">=100 graded AND precision>0.5"}
    graft = _s(cur, """SELECT count(*) FROM hermes_autotune_audit
                       WHERE action='auto_graft_weights_outcome'""") or 0
    g["outcome_graft_won"] = {"pass": int(graft) >= 1, "value": int(graft), "target": ">=1 evidence-gated graft"}
    retired = _s(cur, """SELECT count(*) FROM research_sources
                         WHERE notes ILIKE '%%OUTCOME_LEDGER retired%%' AND NOT active""") or 0
    g["source_retired_on_outcome"] = {"pass": int(retired) >= 1, "value": int(retired), "target": ">=1"}
    return g


def _gates_autonomy(cur):
    g = {}
    silent = _s(cur, """SELECT count(*) FROM alert_events
                        WHERE source_script IN ('hermes_pipeline_health') AND created_at > NOW() - interval '30 days'""") or 0
    g["no_pipeline_failures_30d"] = {"pass": int(silent) == 0, "value": int(silent), "target": "0 health alerts/30d"}
    props = _s(cur, "SELECT count(*) FROM config_change_proposals WHERE domain='hermes'") or 0
    autol = _s(cur, """SELECT count(*) FROM hermes_autotune_audit
                       WHERE run_at > NOW() - interval '30 days'""") or 0
    g["governance_channel_active"] = {"pass": int(props) + int(autol) >= 1,
                                      "value": f"proposals={props}, audited_auto_actions={autol}",
                                      "target": "config drift via proposals or audited auto-lane"}
    caught = _s(cur, """SELECT count(*) FROM escalation_queue
                        WHERE category='hermes_watchdog' AND created_at > NOW() - interval '30 days'""") or 0
    g["self_healing_caught_issue"] = {"pass": int(caught) >= 1, "value": int(caught), "target": ">=1 watchdog catch/30d"}
    return g


def _score(gates: dict, streak_days: int) -> int:
    """1-5 from gate pass share; 5 requires ALL gates AND >=PERSISTENCE_DAYS of history."""
    total = len(gates)
    passed = sum(1 for v in gates.values() if v.get("pass"))
    if passed == total:
        return 5 if streak_days >= PERSISTENCE_DAYS else 4
    share = passed / total if total else 0
    return 4 if share >= 0.75 else 3 if share >= 0.5 else 2 if share >= 0.25 else 1


def _streaks(cur):
    """dimension -> consecutive daily snapshots (ending yesterday/today) with all gates passing."""
    cur.execute("""CREATE TABLE IF NOT EXISTS hermes_maturity_history (
                     snapshot_date DATE PRIMARY KEY, gates JSONB, scores JSONB,
                     created_at TIMESTAMPTZ DEFAULT NOW())""")
    cur.execute("SELECT snapshot_date, gates FROM hermes_maturity_history ORDER BY snapshot_date DESC LIMIT %s",
                (PERSISTENCE_DAYS + 2,))
    rows = cur.fetchall()
    streaks: dict[str, int] = {}
    broken: set[str] = set()
    expected = None
    for d, gates in rows:
        if expected is not None and (expected - d).days != 1:
            break  # gap in daily snapshots ends every streak
        for dim, gd in (gates or {}).items():
            if dim in broken:
                continue
            if gd and all(v.get("pass") for v in gd.values()):
                streaks[dim] = streaks.get(dim, 0) + 1
            else:
                broken.add(dim)
        expected = d
    return streaks


def build_gates(cur) -> dict:
    dims = {
        "scope": _gates_scope(cur),
        "research": _gates_research(cur),
        "tagging": _gates_tagging(cur),
        "efficiency": _gates_efficiency(cur),
        "closed_loop": _gates_closed_loop(cur),
        "autonomy": _gates_autonomy(cur),
    }
    streaks = _streaks(cur)
    scores = {d: _score(g, streaks.get(d, 0)) for d, g in dims.items()}
    # Compounding evidence: score + gates-passed deltas vs the snapshot ~7 days ago. A maturing
    # system trends up; a wheel-spinner is flat. (Empty until history accumulates.)
    trend = {}
    try:
        cur.execute("""SELECT gates, scores FROM hermes_maturity_history
                       WHERE snapshot_date <= CURRENT_DATE - 7
                       ORDER BY snapshot_date DESC LIMIT 1""")
        row = cur.fetchone()
        if row:
            old_gates, old_scores = row
            for d, g in dims.items():
                now_pass = sum(1 for v in g.values() if v.get("pass"))
                then = old_gates.get(d) or {}
                then_pass = sum(1 for v in then.values() if v.get("pass"))
                trend[d] = {"score_delta": scores[d] - int((old_scores or {}).get(d, scores[d])),
                            "gates_passed_delta": now_pass - then_pass}
    except Exception:
        pass
    return {"dimensions": dims, "scores": scores,
            "persistence_days_required": PERSISTENCE_DAYS,
            "streak_days": streaks,
            "trend_vs_7d": trend or None,
            "overall": round(sum(scores.values()) / len(scores), 1),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "note": "5 requires ALL gates passing for 30 consecutive daily snapshots — earned, not claimed"}


def run(snapshot=False):
    conn = _conn(); cur = conn.cursor()
    board = build_gates(cur)
    if snapshot:
        cur.execute("""INSERT INTO hermes_maturity_history (snapshot_date, gates, scores)
                       VALUES (%s, %s::jsonb, %s::jsonb)
                       ON CONFLICT (snapshot_date) DO UPDATE SET gates=EXCLUDED.gates,
                         scores=EXCLUDED.scores, created_at=NOW()""",
                    (date.today(), json.dumps(board["dimensions"], default=str),
                     json.dumps(board["scores"])))
        conn.commit()
    print(json.dumps(board, indent=2, default=str))
    return board


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true")
    run(snapshot=ap.parse_args().snapshot)


if __name__ == "__main__":
    main()
