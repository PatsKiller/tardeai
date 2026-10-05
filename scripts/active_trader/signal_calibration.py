#!/usr/bin/env python3
"""What the engine is learning: which signals separated alerts that worked from ones that were stopped.

Reads the learning records (trade_learning.jsonl, type=decision) over the last N sessions and, per
signal and per numeric feature, compares outcomes. Writes
<journal dir>/learning/calibration_report.json with findings and PROPOSED threshold changes.
It never edits config: every proposal says "operator ratifies". Below `min_sample` decisions it
reports "insufficient sample" and proposes nothing.

  python scripts/active_trader/signal_calibration.py            # print report
  python scripts/active_trader/signal_calibration.py --apply    # also write the report file
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from active_trader import momentum_alerts as ma
    from active_trader import trade_learning as tl
except ModuleNotFoundError:  # pragma: no cover
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader import trade_learning as tl

CONTRACT = "active-trader-signal-calibration-v1"
DEFAULTS = {"sessions": 20, "min_sample": 30, "min_bucket": 8, "min_edge": 0.15}
# feature → (config key it would tune, direction: "min" = a floor the engine requires, "max" = a ceiling)
FEATURE_KNOBS = {"depth_ratio": ("active_trader_alerts.min_depth_ratio_armed", "min"),
                 "buy_ratio": ("active_trader_alerts.min_buy_ratio", "min"),
                 "spread_bps": ("active_trader_alerts.max_spread_bps", "max"),
                 "risk_pct": ("min_stop.pct_of_price", "min")}


def _rate(rows) -> Optional[float]:
    return round(sum(1 for r in rows if r["outcome"]["result"] == "WORKED") / len(rows), 3) if rows else None


def _avg(vals) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def calibrate(records: list[Mapping[str, Any]], *, sessions: int, min_sample: int, min_bucket: int,
              min_edge: float, now: Optional[float] = None) -> dict:
    dec = [r for r in records if r.get("type") == "decision" and (r.get("outcome") or {}).get("result")]
    days = sorted({r.get("session_date") for r in dec if r.get("session_date")})[-sessions:]
    dec = [r for r in dec if r.get("session_date") in days]
    out: dict[str, Any] = {"contract": CONTRACT, "generated_at": now or time.time(), "sessions": days,
                           "decisions": len(dec), "min_sample": min_sample, "worked_rate": _rate(dec),
                           "signals": {}, "features": {}, "proposals": [],
                           "note": "PROPOSALS ONLY — config is unchanged until the operator ratifies."}
    if len(dec) < min_sample:
        out["status"] = "insufficient sample"
        return out
    out["status"] = "ok"
    names = sorted({k for r in dec for k in (r.get("signals") or {})})
    for n in names:
        on = [r for r in dec if (r.get("signals") or {}).get(n) is True]
        off = [r for r in dec if (r.get("signals") or {}).get(n) is False]
        s = {"on": {"n": len(on), "worked_rate": _rate(on), "avg_best_exit_pct": _avg(r["outcome"].get("best_exit_pct") for r in on),
                    "avg_rule_exit_pct": _avg(r["outcome"].get("rule_exit_pct") for r in on)},
             "off": {"n": len(off), "worked_rate": _rate(off), "avg_rule_exit_pct": _avg(r["outcome"].get("rule_exit_pct") for r in off)}}
        if len(on) >= min_bucket and len(off) >= min_bucket:
            edge = (s["on"]["worked_rate"] or 0) - (s["off"]["worked_rate"] or 0)
            s["edge"] = round(edge, 3)
            if edge >= min_edge:
                out["proposals"].append({"type": "confirmation", "signal": n, "edge": s["edge"],
                                         "proposal": f"treat {n} as entry confirmation (worked {s['on']['worked_rate']:.0%} on vs {s['off']['worked_rate']:.0%} off)",
                                         "status": "PROPOSED — operator ratifies"})
            elif edge <= -min_edge:
                out["proposals"].append({"type": "veto", "signal": n, "edge": s["edge"],
                                         "proposal": f"treat {n} as a veto (worked {s['on']['worked_rate']:.0%} on vs {s['off']['worked_rate']:.0%} off)",
                                         "status": "PROPOSED — operator ratifies"})
        out["signals"][n] = s
    for f, (knob, direction) in FEATURE_KNOBS.items():
        w = [r["features"].get(f) for r in dec if r["outcome"]["result"] == "WORKED" and (r.get("features") or {}).get(f) is not None]
        st = [r["features"].get(f) for r in dec if r["outcome"]["result"] in ("STOPPED", "AT_OR_BELOW_STOP") and (r.get("features") or {}).get(f) is not None]
        row = {"worked_median": round(median(w), 3) if w else None, "stopped_median": round(median(st), 3) if st else None,
               "n_worked": len(w), "n_stopped": len(st), "knob": knob}
        out["features"][f] = row
        if len(w) >= min_bucket and len(st) >= min_bucket:
            wm, sm = row["worked_median"], row["stopped_median"]
            if (direction == "min" and wm > sm) or (direction == "max" and wm < sm):
                out["proposals"].append({"type": "threshold", "knob": knob, "feature": f,
                                         "proposed_value": round((wm + sm) / 2, 3),
                                         "why": f"worked median {wm} vs stopped median {sm}",
                                         "status": "PROPOSED — operator ratifies"})
    return out


def report_path(base: Optional[Path] = None) -> Path:
    return (base or ma.journal_dir()) / "learning" / "calibration_report.json"


def read_report(base: Optional[Path] = None) -> Optional[dict]:
    p = report_path(base)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        import scalp_shadow_logger as L
        raw = (L.load_config().get("active_trader_learning") or {})
    except Exception:  # noqa: BLE001
        raw = {}
    params = {k: raw.get(k, v) for k, v in DEFAULTS.items()}
    rep = calibrate(tl.read_records(), **params)
    if a.apply:
        p = report_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
        tmp.replace(p)
    print(json.dumps(rep, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
