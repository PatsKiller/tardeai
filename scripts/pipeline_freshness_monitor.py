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
    ("agent_performance",     "table", ("agent_performance_history", "period_end", None), 4, "Agents → Performance"),
    ("paper_trade_stats",     "file",  "data/paper_trading/paper_trade_statistics_latest.json", 1, "Strategy → Analytics, Home win-rate"),
    ("hermes_canonical",      "file",  "data/runtime/hermes_canonical_status_latest.json", 1, "Hermes/System lane statuses"),
    ("broker_shadow_recon",   "table", ("schwab_shadow_recon_runs", "started_at", None), 3, "Manual ToS Desk reconciliation"),
    ("morning_synthesis",     "table", ("llm_intelligence_cache", "generated_at", "section='morning_synthesis'"), 2, "Home → AI Briefing"),
    ("rotation_summary",      "file",  "data/runtime/rotation_summary_cache.json", 1, "Rotation Intelligence"),
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


def check():
    stale, missing, ok = [], [], []
    for name, kind, spec, default_thr, surfaced in REGISTRY:
        thr = float(os.getenv(f"PIPELINE_FRESHNESS_{name.upper()}_DAYS", str(default_thr)))
        age = _age_days_table(*spec) if kind == "table" else _age_days_file(spec)
        if age is None:
            missing.append({"name": name, "surfaced": surfaced, "reason": "no output / table/file absent"})
        elif age > thr:
            stale.append({"name": name, "age_days": round(age, 1), "threshold_days": thr, "surfaced": surfaced})
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
        return 0

    lines = ["⚠ Pipeline freshness — stale dashboard data:"]
    for s in stale:
        lines.append(f"  • {s['name']}: {s['age_days']}d old (>{s['threshold_days']}d) — shown on {s['surfaced']}")
    for m in missing:
        lines.append(f"  • {m['name']}: {m['reason']} — {m['surfaced']}")
    msg = "\n".join(lines)

    try:
        from db_adapter import _execute
        import time as _t
        _execute(
            """INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
               VALUES (%s,'system_health',NULL,'warning','pipeline_freshness_monitor',%s,NOW())
               ON CONFLICT (alert_uid) DO NOTHING""",
            (f"pipeline_freshness_{int(_t.time()//3600)}", msg), fetch=None,
        )
    except Exception:
        pass
    if a.send:
        try:
            import alert_dispatcher_unified as ad
            ad.dispatch(alert_type="system_health", text=msg, severity="warning", source="pipeline_freshness_monitor")
        except Exception:
            pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
