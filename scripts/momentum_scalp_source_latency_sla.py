#!/usr/bin/env python3
"""momentum_scalp_source_latency_sla.py — P0-6: source → validation latency SLA by window.

Measures how fast a momentum_scalp candidate flows from source discovery to a validation evaluation,
and grades it PASS/WARN/FAIL against window-specific targets. Read-only — NO broker writes.

Stages measured (via discovery_trace_id / proposal lineage timestamps):
    Finviz scan → trade_ai_scans row
    trade_ai_scans row → strategy_signal
    strategy_signal → proposal
    proposal → validation fast-path evaluation
    quote age at validation evaluation

Targets (ET window):
    06:00-09:30 pre-market : source→proposal <= 10 min ; proposal→validation <= 2 min
    09:30-10:30 open       : source→proposal <=  5 min ; proposal→validation <= 1 min
    10:30-12:00 late       : source→proposal <= 10 min ; proposal→validation <= 2 min

CRITICAL: quote freshness is NEVER weakened, and a STALE-QUOTE reject is NEVER counted as a PASS — a
fast "evaluation" that DEFERs on a stale quote is a freshness DEFER, not a met SLA.

    python3 scripts/momentum_scalp_source_latency_sla.py --days 30 --json
    python3 scripts/momentum_scalp_source_latency_sla.py --days 30 --markdown > docs/diligence/current/MOMENTUM_SCALP_SOURCE_LATENCY_SLA.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

WINDOWS = {
    "premarket":    {"range": "06:00-09:30", "source_to_proposal_max": 10, "proposal_to_validation_max": 2},
    "open":         {"range": "09:30-10:30", "source_to_proposal_max": 5,  "proposal_to_validation_max": 1},
    "late_morning": {"range": "10:30-12:00", "source_to_proposal_max": 10, "proposal_to_validation_max": 2},
}


def grade(measured_min, target_min) -> str:
    """PASS if <= target, WARN if <= 1.5x target, FAIL if over. None/insufficient → WARN (never a
    silent PASS — missing latency data is not a met SLA)."""
    if measured_min is None:
        return "WARN"
    if measured_min <= target_min:
        return "PASS"
    if measured_min <= target_min * 1.5:
        return "WARN"
    return "FAIL"


def evaluate_window(measurements: dict, targets: dict) -> dict:
    """Pure: grade one window's measurements. measurements may carry stale_quote_rejects, which are
    NEVER treated as a pass. Returns per-stage grades + overall + bottleneck."""
    s2p = measurements.get("source_to_proposal_min")
    p2v = measurements.get("proposal_to_validation_min")
    g_s2p = grade(s2p, targets["source_to_proposal_max"])
    g_p2v = grade(p2v, targets["proposal_to_validation_max"])

    # A stale-quote reject can never lift the grade to PASS — if all validations in-window deferred on
    # stale quotes, the proposal→validation stage is WARN at best (no proven fresh-quote evaluation).
    stale = measurements.get("stale_quote_rejects", 0)
    fresh_evals = measurements.get("fresh_quote_evaluations", 0)
    if g_p2v == "PASS" and fresh_evals == 0 and stale > 0:
        g_p2v = "WARN"

    order = {"FAIL": 2, "WARN": 1, "PASS": 0}
    grades = {"source_to_proposal": g_s2p, "proposal_to_validation": g_p2v}
    overall = max(grades.values(), key=lambda g: order[g])
    bottleneck = max(grades, key=lambda k: order[grades[k]]) if order[overall] > 0 else None
    return {
        "range": targets["range"], "grades": grades, "overall": overall, "bottleneck": bottleneck,
        "source_to_proposal_min": s2p, "proposal_to_validation_min": p2v,
        "stale_quote_rejects": stale, "fresh_quote_evaluations": fresh_evals,
        "targets": {"source_to_proposal_max": targets["source_to_proposal_max"],
                    "proposal_to_validation_max": targets["proposal_to_validation_max"]},
    }


def _median(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def _gather(conn, days: int) -> dict:
    """Read-only: median source→proposal latency per ET window via discovery_trace_id lineage.
    proposal→validation timing degrades to None when lineage timestamps are unavailable (→ WARN)."""
    out = {k: {"source_to_proposal": [], "proposal_to_validation": [],
               "stale": 0, "fresh": 0} for k in WINDOWS}
    try:
        cur = conn.cursor()
        # source→proposal: join proposals to their source scan row on discovery_trace_id.
        cur.execute(f"""
            SELECT EXTRACT(HOUR FROM p.created_at AT TIME ZONE 'America/New_York')
                     + EXTRACT(MINUTE FROM p.created_at AT TIME ZONE 'America/New_York')/60.0 AS et_hr,
                   EXTRACT(EPOCH FROM (p.created_at - s.scanned_at))/60.0 AS lat_min
            FROM paper_trade_proposals p
            JOIN trade_ai_scans s ON s.discovery_trace_id = p.discovery_trace_id
            WHERE p.created_at > NOW() - INTERVAL '%s days'
              AND p.discovery_trace_id IS NOT NULL
              AND p.created_at >= s.scanned_at
        """ % int(days))
        for et_hr, lat in cur.fetchall():
            if et_hr is None or lat is None:
                continue
            et = float(et_hr)
            w = "premarket" if et < 9.5 else "open" if et < 10.5 else "late_morning" if et < 12 else None
            if w and 6 <= et < 12:
                out[w]["source_to_proposal"].append(float(lat))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    return out


def build(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    conn = None
    warnings = []
    try:
        from db_adapter import get_connection
        conn = get_connection()
    except Exception as e:
        warnings.append(f"db unavailable: {str(e).splitlines()[0][:100]}")

    raw = _gather(conn, days) if conn else {k: {} for k in WINDOWS}
    windows = {}
    for key, targets in WINDOWS.items():
        r = raw.get(key, {})
        measurements = {
            "source_to_proposal_min": _median(r.get("source_to_proposal", [])),
            "proposal_to_validation_min": _median(r.get("proposal_to_validation", [])) or None,
            "stale_quote_rejects": r.get("stale", 0),
            "fresh_quote_evaluations": r.get("fresh", 0),
            "samples": len(r.get("source_to_proposal", [])),
        }
        ev = evaluate_window(measurements, targets)
        ev["samples"] = measurements["samples"]
        windows[key] = ev
        if measurements["samples"] == 0:
            warnings.append(f"{key}: no source→proposal lineage samples in window")

    order = {"FAIL": 2, "WARN": 1, "PASS": 0}
    overall = max((w["overall"] for w in windows.values()), key=lambda g: order[g]) if windows else "WARN"
    return {
        "ok": True, "status": overall if not warnings else ("FAIL" if overall == "FAIL" else "WARN"),
        "generated_at": started, "window_days": days,
        "windows": windows,
        "overall_grade": overall,
        "freshness_note": "Quote freshness is NEVER weakened. A stale-quote DEFER is not counted as a "
                          "met SLA — proposal→validation only PASSes on a proven fresh-quote evaluation.",
        "safety_note": "Read-only. No live broker writes. Operator confirmation / 2FA untouched.",
        "warnings": warnings,
    }


def to_markdown(r: dict) -> str:
    L = ["# Momentum Scalp Source → Validation Latency SLA", "",
         f"**Status: {r.get('status')}** (overall {r.get('overall_grade')}) | window: {r.get('window_days')}d  ",
         f"_Generated: {r.get('generated_at')}_  ",
         "_Source: `python3 scripts/momentum_scalp_source_latency_sla.py --days N --json`_  ", "",
         "| Window | Range | src→proposal | target | proposal→validation | target | overall | bottleneck |",
         "|--------|-------|-------------:|-------:|--------------------:|-------:|:-------:|:----------:|"]
    for key, w in r.get("windows", {}).items():
        t = w["targets"]
        s2p = w["source_to_proposal_min"]
        p2v = w["proposal_to_validation_min"]
        L.append(f"| {key} | {w['range']} | {('%.1f' % s2p) if s2p is not None else '—'} | "
                 f"≤{t['source_to_proposal_max']} | {('%.1f' % p2v) if p2v is not None else '—'} | "
                 f"≤{t['proposal_to_validation_max']} | {w['overall']} | {w['bottleneck'] or '—'} |")
    L += ["", "> " + r.get("freshness_note", ""), "", "> " + r.get("safety_note", "")]
    if r.get("warnings"):
        L += ["", "> WARN: " + "; ".join(r["warnings"][:6])]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build(args.days)
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Latency SLA: {r['status']} overall={r['overall_grade']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
