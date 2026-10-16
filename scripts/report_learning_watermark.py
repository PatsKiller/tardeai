#!/usr/bin/env python3
"""report_learning_watermark.py — READ-ONLY: learning watermark, consumer decisions and input staleness.

Cohort 2 of the n8n process consolidation (2026-10-16). For the two Hermes learning consumers in
config/learning_watermark.json it prints:
  * the current verified learning watermark (scripts/lib/learning_watermark.current_watermark) and its reason;
  * per consumer: its recorded state and what an EVENT fire and a CLOCK fire would decide now (pure; nothing
    recorded);
  * measured staleness from real history: for every live consumer step run of the hermes_overnight night stage
    (logs/pipelines/hermes_overnight/night_steps.jsonl), the input age at consumption = step time minus the newest
    corroborated learning completion before it; a step whose own log shows PEAK_SKIP at that minute consumed
    nothing (reported as peak_skipped, not as a consumption);
  * the projection once event-driven: input age = event-router dispatch lag measured on the ledger's existing
    run_done-triggered `e:` rows (started_at minus the as_of minute of the key) — the same router, gateway and
    executor path these lanes use.

AUTHORITY: READ_ONLY_ADVISORY. Reads files and the coordination ledger (sqlite mode=ro). No DB, no write, no send.
Usage: report_learning_watermark.py [--project-root DIR] [--ledger PATH] [--state-root DIR] [--now ISO] [--json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from dataclasses import asdict
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import learning_watermark as lw  # noqa: E402

NIGHT_STEPS_REL = "logs/pipelines/hermes_overnight/night_steps.jsonl"
NIGHT_MANIFEST_REL = "config/pipelines/hermes_overnight.json"
#: run_done-triggered event lanes already on the router (cohort 1 / W5): their e: rows measure the dispatch lag.
RUN_DONE_EVENT_LANES = ("news-to-catalyst", "research-insight-extractor")


def _pct(xs: list[float], q: float) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1)


def _hist_watermarks(cfg: dict, root: Path, now: datetime) -> list[datetime]:
    """Every corroborated cron-runner completion time of the upstream step (ascending)."""
    up = cfg["upstream"]
    steps = root / up["pipeline_step"]["steps_jsonl"]
    lines = steps.read_text(encoding="utf-8").splitlines() if steps.exists() else []
    co = up["corroboration"]
    stamps = lw._snapshot_stamps(root / co["dir"], co["glob"], co["stamp_format"])
    out = []
    for line in lines:
        wm, _ = lw.watermark_from_steps([line], stamps, cfg, now)
        if wm:
            out.append(lw.parse_ts(wm.at))
    return sorted(t for t in out if t)


def _peak_skips(log: Path) -> list[datetime]:
    out = []
    if not log.exists():
        return out
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "PEAK_SKIP gate=" in line:
            t = lw.parse_ts(line.split()[0])
            if t:
                out.append(t)
    return out


def measured_staleness(cfg: dict, root: Path, now: datetime) -> dict[str, Any]:
    marks = _hist_watermarks(cfg, root, now)
    manifest = json.loads((root / NIGHT_MANIFEST_REL).read_text(encoding="utf-8")) \
        if (root / NIGHT_MANIFEST_REL).exists() else json.loads((ROOT / NIGHT_MANIFEST_REL).read_text())
    step_of = {}
    for st in manifest["stages"]["night"]["steps"]:
        step_of[st["id"]] = st
    lane_step = {"hermes-discovery-yield-builder": "discovery_yield_builder",
                 "hermes-tag-lift-discovery": "tag_lift_discovery"}
    night = root / NIGHT_STEPS_REL
    lines = night.read_text(encoding="utf-8").splitlines() if night.exists() else []
    out: dict[str, Any] = {"learning_completions": [m.isoformat() for m in marks]}
    for lane, sid in lane_step.items():
        skips = _peak_skips(root / step_of[sid]["log"]) if sid in step_of else []
        runs = []
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("id") != sid or rec.get("dry_run") is not False or rec.get("status") != "ok":
                continue
            t = lw.parse_ts(rec.get("ts"))
            if t is None:
                continue
            prior = [m for m in marks if m <= t]
            skipped = any(abs((s - t).total_seconds()) <= 90 for s in skips)
            runs.append({"ts": t.isoformat(), "peak_skipped": skipped,
                         "input_age_h": round((t - prior[-1]).total_seconds() / 3600, 2) if prior else None})
        ages = [r["input_age_h"] for r in runs if not r["peak_skipped"] and r["input_age_h"] is not None]
        out[lane] = {"step": sid, "runs": runs, "consumptions": len(ages),
                     "peak_skipped": sum(1 for r in runs if r["peak_skipped"]),
                     "input_age_h_median": round(statistics.median(ages), 2) if ages else None,
                     "input_age_h_max": max(ages) if ages else None}
    return out


def event_dispatch_lag(ledger: Path) -> dict[str, Any]:
    if not ledger.exists():
        return {"n": 0, "note": "ledger not found"}
    conn = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=5)
    try:
        rows = conn.execute("SELECT run_id, started_at, finished_at FROM runs WHERE run_id LIKE 'e:%' "
                            "AND started_at IS NOT NULL").fetchall()
    finally:
        conn.close()
    lags, run_s = [], []
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
    for run_id, started, finished in rows:
        parts = run_id.split(":")
        if len(parts) < 4 or parts[1] not in RUN_DONE_EVENT_LANES:
            continue
        try:
            minute = datetime.strptime(parts[3], "%Y%m%dT%H%M").replace(tzinfo=tz).astimezone(timezone.utc)
        except ValueError:
            continue
        s, f = lw.parse_ts(started), lw.parse_ts(finished)
        if s:
            lags.append((s - minute).total_seconds())
        if s and f:
            run_s.append((f - s).total_seconds())
    return {"lanes": list(RUN_DONE_EVENT_LANES), "n": len(lags),
            "start_lag_s_median": _pct(lags, 0.5), "start_lag_s_p95": _pct(lags, 0.95), "start_lag_s_max": _pct(lags, 1.0),
            "note": "lag = executor start minus the as_of minute of the e: key (upper bound includes up to 60 s of "
                    "minute truncation); router polls GET /due?source=event every minute"}


def build(args) -> dict[str, Any]:
    cfg = lw.load_config()
    now = lw.parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    root = Path(args.project_root).resolve() if args.project_root else ROOT
    ledger = Path(args.ledger) if args.ledger else lw.default_ledger_path()
    wm, why = lw.current_watermark(cfg, project_root=root, ledger_path=ledger, now=now)
    consumers = {}
    for lane in cfg["consumers"]:
        st = lw.load_state(lw.state_path(lane, cfg, args.state_root))
        consumers[lane] = {
            "event_lane": cfg["consumers"][lane].get("event_lane"),
            "clock_guard": cfg["consumers"][lane]["clock_guard"],
            "state": {"consumed": st.get("consumed"), "last_decision": st.get("last_decision")},
            "event_now": asdict(lw.decide(lane, "event", wm, why, st, cfg, now)),
            "clock_now": asdict(lw.decide(lane, "clock", wm, why, st, cfg, now)),
        }
    return {"schema": "LearningWatermarkReport@v1", "computed_at": now.isoformat(), "project_root": str(root),
            "event_trigger_state": cfg["event_trigger_state"],
            "watermark": asdict(wm) if wm else None, "watermark_reason": why, "consumers": consumers,
            "measured": measured_staleness(cfg, root, now), "event_dispatch_lag": event_dispatch_lag(ledger)}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", default=None, help="tree whose logs/ and state/ are read (default: checkout)")
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--state-root", default=None)
    ap.add_argument("--now", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = build(args)
    if args.json:
        print(json.dumps(rep, indent=1, default=str))
        return 0
    print(f"learning watermark: {(rep['watermark'] or {}).get('id', 'none')} ({rep['watermark_reason']})")
    for lane, c in rep["consumers"].items():
        print(f"  {lane}: event -> {'RUN' if c['event_now']['run'] else 'no fire'} ({c['event_now']['reason']}); "
              f"clock -> {'RUN' if c['clock_now']['run'] else 'no-op'} ({c['clock_now']['reason']})")
        m = rep["measured"][lane]
        print(f"    measured: {m['consumptions']} consumptions, {m['peak_skipped']} PEAK_SKIP; input age median "
              f"{m['input_age_h_median']} h, max {m['input_age_h_max']} h")
    lag = rep["event_dispatch_lag"]
    print(f"  event dispatch lag (n={lag['n']}): median {lag.get('start_lag_s_median')} s, "
          f"p95 {lag.get('start_lag_s_p95')} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
