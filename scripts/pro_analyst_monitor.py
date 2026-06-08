#!/usr/bin/env python3
"""pro_analyst_monitor.py — track professional-analyst coverage as it expands.

READ-ONLY. Snapshots coverage metrics from data/runtime/pro_analyst_pills_latest.json into a 90-day
time-series, computes day-over-day deltas (newly-covered / lost-coverage symbols, coverage % by tier),
and flags growth/regression. Lets you watch the analyst layer's coverage expand. No mutation.

  python3 scripts/pro_analyst_monitor.py            # snapshot + append + status
  python3 scripts/pro_analyst_monitor.py --dry-run
"""
import sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"
HIST = ROOT / "data" / "runtime" / "pro_analyst_coverage_history.json"


def main():
    dry = "--dry-run" in sys.argv
    try:
        d = json.loads(SRC.read_text())
    except Exception as e:
        print(json.dumps({"status": "NO_READ_MODEL", "error": str(e)[:120]})); return
    pills = d.get("pills", [])
    covered = [p for p in pills if p.get("has_professional_coverage")]
    cov_syms = {p["symbol"] for p in covered}
    from collections import Counter
    div_counts = dict(Counter(p.get("divergence", "unavailable") for p in pills))
    divergent = {p["symbol"]: {"internal": p.get("internal_direction"), "street": p.get("street_direction")}
                 for p in pills if p.get("divergence") == "divergent"}
    # comparable (divergence resolvable: both sides known) = aligned + mixed + divergent
    comparable = sum(div_counts.get(k, 0) for k in ("aligned", "mixed", "divergent"))
    snap = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "ts": datetime.now(timezone.utc).isoformat(),
            "total_symbols": len(pills), "with_consensus": len(covered),
            "coverage_pct": round(len(covered) / len(pills) * 100, 1) if pills else 0.0,
            "stale": sum(1 for p in covered if p.get("stale")),
            "targets_only": sum(1 for p in covered if not p.get("recommendation_key") or p.get("recommendation_key") == "none"),
            "divergence_counts": div_counts, "comparable": comparable,
            "divergent": len(divergent), "divergent_symbols": divergent,
            "coverage_by_tier": {k: v.get("pct") for k, v in (d.get("coverage_by_tier") or {}).items()},
            "covered_symbols": sorted(cov_syms)}

    hist = []
    try:
        hist = json.loads(HIST.read_text()).get("snapshots", [])
    except Exception:
        pass
    prev = hist[-1] if hist else None
    newly, lost, newly_div, resolved_div = [], [], [], []
    if prev:
        prev_syms = set(prev.get("covered_symbols", []))
        newly = sorted(cov_syms - prev_syms)
        lost = sorted(prev_syms - cov_syms)
        prev_div = set((prev.get("divergent_symbols") or {}).keys())
        newly_div = sorted(set(divergent.keys()) - prev_div)
        resolved_div = sorted(prev_div - set(divergent.keys()))
        snap["delta"] = {"with_consensus": len(covered) - prev.get("with_consensus", 0),
                         "coverage_pct": round(snap["coverage_pct"] - prev.get("coverage_pct", 0), 1),
                         "comparable": comparable - prev.get("comparable", 0),
                         "divergent": len(divergent) - prev.get("divergent", 0)}
    snap["newly_covered"], snap["lost_coverage"] = newly, lost
    snap["newly_divergent"], snap["resolved_divergence"] = newly_div, resolved_div

    notes, status = [], "STABLE"
    if newly:
        notes.append(f"{len(newly)} newly covered: " + ", ".join(newly[:8])); status = "EXPANDING"
    if lost:
        notes.append(f"{len(lost)} lost coverage: " + ", ".join(lost[:8])); status = "REGRESSED"
    if newly_div:
        notes.append("NEW divergence (internal vs Street — review): " + ", ".join(f"{s}({divergent[s]['internal']}vs{divergent[s]['street']})" for s in newly_div[:6]))
    if resolved_div:
        notes.append(f"{len(resolved_div)} divergence resolved: " + ", ".join(resolved_div[:6]))
    if snap["stale"] > 0:
        notes.append(f"{snap['stale']} stale (>7d) — re-fetch needed")
    snap["status"], snap["notes"] = status, notes

    if not dry:
        hist.append(snap); hist = hist[-90:]
        HIST.parent.mkdir(parents=True, exist_ok=True)
        HIST.write_text(json.dumps({"updated_at": snap["ts"], "snapshots": hist}, indent=2))
    print(json.dumps({k: snap[k] for k in ("date", "with_consensus", "coverage_pct", "comparable",
          "divergence_counts", "divergent", "status", "notes", "newly_covered", "newly_divergent")}, indent=2))


if __name__ == "__main__":
    main()
