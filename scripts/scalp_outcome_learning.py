#!/usr/bin/env python3
"""P1-3: Outcome-learning loop for Social / Momentum Scalp (ADVISORY ONLY).

Attributes closed paper trades back to their discovery context (source, route, catalyst
type, RVOL/float/time-of-day buckets, strategy) and derives BOUNDED advisory weights that
can only re-rank candidates — they NEVER unlock execution or bypass a deterministic gate.

Bounds: weight ∈ [0.5, 1.2]; a bucket needs ≥ MIN_SAMPLE closed trades before its weight
moves off neutral (1.0). Empty/low sample → neutral weights. Read-only, no broker writes.

    python3 scripts/scalp_outcome_learning.py --days 180 --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

WEIGHT_MIN, WEIGHT_MAX, WEIGHT_NEUTRAL = 0.5, 1.2, 1.0
MIN_SAMPLE = 5   # closed trades in a bucket before its weight moves off neutral


def _rvol_bucket(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "unknown"
    if v >= 8:
        return "rvol_8plus"
    if v >= 5:
        return "rvol_5to8"
    return "rvol_under5"


def _float_bucket(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "unknown"
    if v <= 10:
        return "float_under10m"
    if v <= 20:
        return "float_10to20m"
    return "float_over20m"


def _tod_bucket(dt):
    if not dt:
        return "unknown"
    try:
        h = dt.hour
    except Exception:
        return "unknown"
    if h < 11:
        return "morning"
    if h < 14:
        return "midday"
    return "afternoon"


def _bounded_weight(win_rate, n):
    """Map a bucket's win rate to a bounded advisory multiplier; neutral until MIN_SAMPLE."""
    if n < MIN_SAMPLE or win_rate is None:
        return WEIGHT_NEUTRAL
    # 50% win → 1.0; scale ±0.2 per 0.5 deviation, then clamp to [0.5, 1.2].
    w = WEIGHT_NEUTRAL + (win_rate - 0.5) * 0.8
    return round(max(WEIGHT_MIN, min(WEIGHT_MAX, w)), 3)


def learn(days: int = 180) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        return {"ok": False, "status": "WARN", "generated_at": started,
                "warnings": [f"no database: {e}"], "sample_size": 0,
                "weights": {}, "advisory_only": True,
                "note": "Outcome learning is advisory/ranking only; deterministic gates always win."}

    warnings = []
    rows = []
    try:
        cur.execute(f"""
            SELECT pnl, r_multiple, max_adverse_excursion, max_favorable_excursion,
                   hold_time_min, rvol_at_entry, float_m_at_entry, catalyst_verified,
                   entry_time, discovery_trace_id
            FROM paper_trades
            WHERE strategy_id = 'momentum_scalp' AND status = 'closed'
              AND entry_time > NOW() - INTERVAL '{int(days)} days'
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        warnings.append(f"paper_trades: {str(e).splitlines()[0][:120]}")

    n = len(rows)
    # Aggregate by bucket dimension.
    buckets: dict[str, dict] = {}

    def _add(dim, key, won, r):
        b = buckets.setdefault(dim, {}).setdefault(key, {"n": 0, "wins": 0, "r": []})
        b["n"] += 1
        b["wins"] += 1 if won else 0
        if r is not None:
            b["r"].append(r)

    pnls, rs, maes, mfes, holds = [], [], [], [], []
    for t in rows:
        pnl = t.get("pnl")
        won = (pnl is not None and float(pnl) > 0)
        r = None
        try:
            r = float(t["r_multiple"]) if t.get("r_multiple") is not None else None
        except (TypeError, ValueError):
            r = None
        if pnl is not None:
            pnls.append(float(pnl))
        if r is not None:
            rs.append(r)
        for k in ("max_adverse_excursion", "max_favorable_excursion", "hold_time_min"):
            try:
                v = float(t[k]) if t.get(k) is not None else None
            except (TypeError, ValueError):
                v = None
            if v is not None:
                (maes if k == "max_adverse_excursion" else
                 mfes if k == "max_favorable_excursion" else holds).append(v)

        _add("catalyst", "verified" if t.get("catalyst_verified") else "unverified", won, r)
        _add("rvol", _rvol_bucket(t.get("rvol_at_entry")), won, r)
        _add("float", _float_bucket(t.get("float_m_at_entry")), won, r)
        _add("time_of_day", _tod_bucket(t.get("entry_time")), won, r)
        _add("source", "social" if t.get("discovery_trace_id") else "non_social", won, r)

    def _finalize(b):
        wr = (b["wins"] / b["n"]) if b["n"] else None
        return {"n": b["n"], "win_rate": (round(wr, 4) if wr is not None else None),
                "avg_r": (round(statistics.mean(b["r"]), 4) if b["r"] else None),
                "weight": _bounded_weight(wr, b["n"])}

    weights = {dim: {k: _finalize(v) for k, v in keys.items()} for dim, keys in buckets.items()}

    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = sum(p for p in pnls if p < 0)
    overall = {
        "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 4) if pnls else None,
        "profit_factor": (round(gross_win / abs(gross_loss), 4) if gross_loss else None),
        "avg_r": round(statistics.mean(rs), 4) if rs else None,
        "avg_mae": round(statistics.mean(maes), 4) if maes else None,
        "avg_mfe": round(statistics.mean(mfes), 4) if mfes else None,
        "median_hold_min": round(statistics.median(holds), 1) if holds else None,
    }

    confidence = "high" if n >= 30 else "medium" if n >= MIN_SAMPLE else "low"
    return {
        "ok": True,
        "status": "PASS" if not warnings else "WARN",
        "generated_at": started,
        "window_days": days,
        "sample_size": n,
        "confidence": confidence,
        "overall": overall,
        "weights": weights,
        "weight_bounds": {"min": WEIGHT_MIN, "max": WEIGHT_MAX, "neutral": WEIGHT_NEUTRAL,
                          "min_sample": MIN_SAMPLE},
        "advisory_only": True,
        "warnings": warnings,
        "note": ("Advisory/ranking ONLY — weights re-rank candidates; they never unlock execution "
                 "or bypass a deterministic risk gate. Low sample → neutral (1.0) weights."),
    }


def to_markdown(rep: dict) -> str:
    L = ["# Scalp Outcome Learning (advisory)", "",
         f"**Status: {rep['status']}** | sample: {rep.get('sample_size')} "
         f"(confidence: {rep.get('confidence')})  ",
         f"_Generated: {rep['generated_at']}_  ", "",
         "Advisory/ranking only. Deterministic gates always win. Weights bounded "
         f"[{rep.get('weight_bounds',{}).get('min')}, {rep.get('weight_bounds',{}).get('max')}].", ""]
    ov = rep.get("overall", {})
    L += ["## Overall (closed momentum_scalp paper trades)", "",
          f"- Win rate: {ov.get('win_rate')}", f"- Profit factor: {ov.get('profit_factor')}",
          f"- Avg R: {ov.get('avg_r')} | Avg MAE: {ov.get('avg_mae')} | Avg MFE: {ov.get('avg_mfe')}",
          f"- Median hold (min): {ov.get('median_hold_min')}", ""]
    for dim, keys in (rep.get("weights") or {}).items():
        L += [f"## By {dim}", "", "| Bucket | n | win_rate | avg_R | weight |", "|--------|---|----------|-------|--------|"]
        for k, v in keys.items():
            L.append(f"| {k} | {v['n']} | {v['win_rate']} | {v['avg_r']} | {v['weight']} |")
        L.append("")
    if rep.get("warnings"):
        L += ["## Warnings", ""] + [f"- {w}" for w in rep["warnings"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--out", default="data/runtime/scalp_outcome_learning_latest.json")
    args = ap.parse_args()
    rep = learn(args.days)
    try:
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2, default=str))
    except Exception:
        pass
    if args.markdown:
        print(to_markdown(rep))
    elif args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(f"Scalp outcome learning: {rep['status']} sample={rep.get('sample_size')} "
              f"confidence={rep.get('confidence')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
