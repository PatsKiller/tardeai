#!/usr/bin/env python3
"""catalyst_calibration_monitor.py — track catalyst calibration multipliers as they sharpen.

READ-ONLY. Snapshots the per-type calibration (samples, hit_rate, weight_multiplier, trusted) from
data/runtime/catalyst_calibration.json into a 90-day time-series, computes day-over-day movement
(newly-trusted types, multiplier shifts, sample growth), and flags large swings. Lets you watch the
calibration loop sharpen. No mutation.

  python3 scripts/catalyst_calibration_monitor.py            # snapshot + append + status
  python3 scripts/catalyst_calibration_monitor.py --dry-run
"""
import sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CALIB = ROOT / "data" / "runtime" / "catalyst_calibration.json"
HIST = ROOT / "data" / "runtime" / "catalyst_calibration_history.json"
SHIFT = 0.10   # |Δ weight_multiplier| worth surfacing


def main():
    dry = "--dry-run" in sys.argv
    try:
        cal = json.loads(CALIB.read_text())
    except Exception as e:
        print(json.dumps({"status": "NO_CALIBRATION", "error": str(e)[:120]})); return
    by_type = cal.get("by_type", {})
    types = {t: {"samples": v.get("samples", 0), "hit_rate": v.get("hit_rate"),
                 "weight_multiplier": v.get("weight_multiplier", 1.0), "trusted": v.get("trusted", False)}
             for t, v in by_type.items()}
    snap = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "ts": datetime.now(timezone.utc).isoformat(),
            "total_settled": cal.get("total_settled_catalysts"), "credible_samples": cal.get("credible_samples"),
            "trusted_type_count": sum(1 for v in types.values() if v["trusted"]),
            "type_count": len(types), "types": types}

    hist = []
    try:
        hist = json.loads(HIST.read_text()).get("snapshots", [])
    except Exception:
        pass
    prev = hist[-1] if hist else None

    newly_trusted, lost_trust, shifts = [], [], []
    if prev:
        pt = prev.get("types", {})
        for t, v in types.items():
            old = pt.get(t)
            if v["trusted"] and not (old and old.get("trusted")):
                newly_trusted.append({"type": t, "samples": v["samples"], "multiplier": v["weight_multiplier"]})
            if old and old.get("trusted") and not v["trusted"]:
                lost_trust.append({"type": t})
            if old and abs(v["weight_multiplier"] - old.get("weight_multiplier", 1.0)) >= SHIFT:
                shifts.append({"type": t, "from": old.get("weight_multiplier"), "to": v["weight_multiplier"],
                               "samples": v["samples"]})
        snap["delta"] = {"credible_samples": (snap["credible_samples"] or 0) - (prev.get("credible_samples") or 0),
                         "trusted_type_count": snap["trusted_type_count"] - prev.get("trusted_type_count", 0)}
    snap["newly_trusted"], snap["lost_trust"], snap["multiplier_shifts"] = newly_trusted, lost_trust, shifts

    notes = []
    if newly_trusted:
        notes.append(f"{len(newly_trusted)} type(s) newly trusted: " + ", ".join(t["type"] for t in newly_trusted))
    if lost_trust:
        notes.append("lost trust (sample dropped below min): " + ", ".join(t["type"] for t in lost_trust))
    if shifts:
        notes.append(f"{len(shifts)} multiplier shift(s): " + ", ".join(f"{s['type']} {s['from']}→{s['to']}" for s in shifts[:5]))
    status = "SHARPENING" if (newly_trusted or (snap.get("delta", {}).get("credible_samples", 0) > 0)) else "STABLE"
    if lost_trust:
        status = "REGRESSED"
    snap["status"], snap["notes"] = status, notes

    if not dry:
        hist.append(snap); hist = hist[-90:]
        HIST.parent.mkdir(parents=True, exist_ok=True)
        HIST.write_text(json.dumps({"updated_at": snap["ts"], "snapshots": hist}, indent=2))
    print(json.dumps({k: snap[k] for k in ("date", "total_settled", "credible_samples", "trusted_type_count",
          "type_count", "status", "notes", "newly_trusted", "multiplier_shifts")}, indent=2))


if __name__ == "__main__":
    main()
