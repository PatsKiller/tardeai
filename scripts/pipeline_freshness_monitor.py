#!/usr/bin/env python3
"""pipeline_freshness_monitor.py — catch the insidious 'job runs but output is STALE' class.

The dashboard audit (2026-06-24) found several pipelines whose cron runs fine but whose OUTPUT is
days/weeks old — the UI then shows stale data as current with no cue. Examples: ticker_snapshot_daily
(RSI feeder, unscheduled), local-LLM proposal enrichment (runs but processes 0), agent-performance
(matches 0 outcomes), broker recon (legacy table gone). Nothing watched OUTPUT freshness.

This checks each registered pipeline's *output* freshness (not just whether its cron fired) and emits a
single 'system_health' alert_event + Health-hub-visible signal when any are stale. Advisory/read-only.

Registry entries: (name, kind, target, threshold_days, surfaced_on). kind ∈ {table, file}.
  table → "SELECT max(<tscol>) FROM <table> [WHERE <where>]"
  file  → mtime of a runtime file
Thresholds are env-tunable via PIPELINE_FRESHNESS_<NAME>_DAYS.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# name, kind, spec, default_threshold_days, surfaced_on
#   table spec: (table, tscol, where_or_None)
#   file  spec: relpath
REGISTRY = [
    ("ticker_snapshot_daily", "table", ("ticker_snapshot_daily", "snapshot_date", None), 2, "Strategy/Watchlist setup-advisory RSI bands"),
    ("setup_advisory",        "table", ("candidate_setup_advisory", "snapshot_date", None), 3, "Strategy → Incubator, Watchlist advisory pills"),
    # agent_performance: RETIRED — the decision_outcomes price-capture chain decayed (Apr) and the system
    #   is superseded by agent-calibration + rec-intel return-by-origin. Not monitored. (Operator decision
    #   2026-06-24; the older update_agent_performance cron is a harmless no-op left in place.)
    ("paper_trade_stats",     "file",  "data/paper_trading/paper_trade_statistics_latest.json", 1, "Strategy → Analytics, Home win-rate"),
    ("hermes_canonical",      "file",  "data/runtime/hermes_canonical_status_latest.json", 1, "Hermes/System lane statuses"),
    # broker_shadow_recon: RETIRED — superseded by the Manual ToS Desk live recon; intentionally not
    #   monitored (was a legacy schwab_shadow_recon_runs feed, last run 2026-06-12).
    ("morning_synthesis",     "table", ("llm_intelligence_cache", "generated_at", "section='morning_synthesis'"), 2, "Home → AI Briefing"),
    ("rotation_summary",      "file",  "data/runtime/rotation_summary_cache.json", 1, "Rotation Intelligence"),
    # Backtest integration — engine runs daily but its OUTPUTS went stale (aggregator unscheduled →
    # strategy_backtest_results 14d old; proposal engine PENDING-only + unscheduled → snapshots 34d old,
    # Backtest field blank on cards). Now scheduled; watched here so a re-break auto-remediates.
    ("strategy_backtest_results", "table", ("strategy_backtest_results", "created_at", None), 3, "Strategy backtest evidence / leaderboard"),
    ("proposal_backtest_snapshots", "table", ("proposal_backtest_snapshots", "created_at", None), 3, "Proposal card Backtest field"),
    ("trade_closed", "table", ("trade_closed", "close_date", None), 7, "TradeInView trade log / Schwab journal"),
    ("journal_trade_reviews", "table", ("journal_trade_reviews", "updated_at", None), 14, "TradeInView annotations / behavioral analytics"),
]


def _age_days_table(table, tscol, where):
    from db_adapter import _execute
    w = f" WHERE {where}" if where else ""
    try:
        r = _execute(f"SELECT EXTRACT(EPOCH FROM (NOW()-max({tscol})))/86400 AS d FROM {table}{w}", fetch="all")
        d = dict(r[0]).get("d") if r else None
        return float(d) if d is not None else None
    except Exception:
        return None  # missing table / col → treat as unknown (reported separately)


def _age_days_file(relpath):
    import time
    p = ROOT / relpath
    if not p.exists():
        return None
    return (time.time() - p.stat().st_mtime) / 86400.0


def _market_closure_grace_days():
    """Consecutive non-trading days (weekend/holiday) ending today. Daily pipelines only advance on
    trading days, so thresholds get this many extra days — house convention (see health_agent
    collect_data_quality): weekend-stale is excused and escalates naturally once trading resumes
    and the gap drops back to 0. E.g. Sat 2026-07-04 after the Fri Jul-3 holiday → grace 2."""
    try:
        from datetime import datetime, timedelta
        from market_session import is_trading_day
        d, grace = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0), 0
        while grace < 14 and not is_trading_day(d):
            grace += 1
            d -= timedelta(days=1)
        return grace
    except Exception:
        return 0


def check():
    stale, missing, ok = [], [], []
    grace = _market_closure_grace_days()
    for name, kind, spec, default_thr, surfaced in REGISTRY:
        thr = float(os.getenv(f"PIPELINE_FRESHNESS_{name.upper()}_DAYS", str(default_thr))) + grace
        age = _age_days_table(*spec) if kind == "table" else _age_days_file(spec)
        if age is None:
            missing.append({"name": name, "surfaced": surfaced, "reason": "no output / table/file absent"})
        elif age > thr:
            stale.append({"name": name, "age_days": round(age, 1), "threshold_days": thr, "surfaced": surfaced,
                          **({"grace_days": grace} if grace else {})})
        else:
            ok.append({"name": name, "age_days": round(age, 1)})
    return stale, missing, ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="also push a telegram alert")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    stale, missing, ok = check()

    if a.json:
        import json
        print(json.dumps({"stale": stale, "missing": missing, "ok": ok}, default=str))
    else:
        print(f"[pipeline-freshness] {len(ok)} fresh · {len(stale)} STALE · {len(missing)} missing")
        for s in stale:
            print(f"  ⚠ STALE  {s['name']:22s} {s['age_days']}d old (>{s['threshold_days']}d) → {s['surfaced']}")
        for m in missing:
            print(f"  ? MISSING {m['name']:22s} {m['reason']} → {m['surfaced']}")
        for o in ok:
            print(f"    ok     {o['name']:22s} {o['age_days']}d")

    if not stale and not missing:
        try:
            from alert_condition_state import observe
            observe("system_health:pipeline_freshness", "FRESH", alertable=False)
        except Exception:
            pass
        return 0

    lines = ["⚠ Pipeline freshness — stale dashboard data:"]
    for s in stale:
        lines.append(f"  • {s['name']}: {s['age_days']}d old (>{s['threshold_days']}d) — shown on {s['surfaced']}")
    for m in missing:
        lines.append(f"  • {m['name']}: {m['reason']} — {m['surfaced']}")
    msg = "\n".join(lines)

    try:
        from alert_condition_state import observe
        stale_names = ",".join(sorted(s["name"] for s in stale)) or "none"
        missing_names = ",".join(sorted(m["name"] for m in missing)) or "none"
        state = f"STALE:{stale_names}|MISSING:{missing_names}"
        obs = observe("system_health:pipeline_freshness", state, alertable=True)
    except Exception:
        obs = {"notify": True, "uid": "pipeline_freshness_transition", "action": "new"}

    if obs.get("notify"):
        try:
            from db_adapter import _execute
            _execute(
                """INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
                   VALUES (%s,'system_health',NULL,'warning','pipeline_freshness_monitor',%s,NOW())
                   ON CONFLICT (alert_uid) DO NOTHING""",
                (obs.get("uid") or "pipeline_freshness_transition", msg), fetch=None,
            )
        except Exception:
            pass
        if a.send:
            try:
                import alert_dispatcher_unified as ad
                ad.dispatch(alert_type="system_health", text=msg, severity="warning", source="pipeline_freshness_monitor")
            except Exception:
                pass
    else:
        print(f"[pipeline-freshness] unchanged stale set — suppressed ({obs.get('action')})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
