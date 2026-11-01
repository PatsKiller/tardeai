#!/usr/bin/env python3
"""Backtest the durable-leadership detector against a naive momentum baseline (rotation advisor).

Public daily bars only (``tests/fixtures/market_risk_scenarios/bars.csv.gz``). Evaluation dates every
``--step`` sessions. In-sample: signals whose forward window ends on or before 2025-12-31. 2026 is HELD OUT and reported
separately (thresholds are the policy's stated rule; nothing is fitted here).

For each horizon (20 / 60 / 120 sessions) it reports, for LEADERSHIP_CONFIRMED groups and for the baseline (the top-3
groups by 60-session return relative to SPY, the same universe), the number of signals, the hit rate (forward return
relative to SPY > 0) and the mean forward relative return; plus the false-confirmation rate (CONFIRMED with a negative
60-session forward relative return). Forward windows overlap when the step is shorter than the horizon; the report
says so. Read-only; no DB, no network.

  python3 scripts/market_risk_leadership_backtest.py [--step 20] [--json]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import leadership as L  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "market_risk_scenarios" / "bars.csv.gz"
IN_SAMPLE_END = "2025-12-31"
HOLDOUT_START = "2026-01-01"


def load_bars(path: Path = FIXTURE) -> dict[str, list]:
    out: dict[str, list] = {}
    with gzip.open(path, "rt") as fh:
        for r in csv.DictReader(fh):
            try:
                cl = float(r["close"])
            except (TypeError, ValueError):
                continue
            v = r.get("volume")
            out.setdefault(r["symbol"], []).append((r["date"], cl, float(v) if v not in (None, "") else None))
    for k in out:
        out[k].sort()
    return out


def _fwd_rel(panel: dict, key: str, i: int, h: int) -> float | None:
    idx = panel["groups"][key]["index"]
    b = panel["bench"]
    if i + h >= len(idx) or idx[i] is None or idx[i + h] is None or not b[i] or not b[i + h]:
        return None
    return (idx[i + h] / idx[i]) - (b[i + h] / b[i])


def _stats(xs: list[float]) -> dict:
    return {
        "n": len(xs),
        "hit_rate": round(sum(x > 0 for x in xs) / len(xs), 3) if xs else None,
        "mean_rel": round(mean(xs), 4) if xs else None,
    }


def run(step: int = 20, policy: dict | None = None, bars: dict | None = None) -> dict:
    policy = policy or load_policy()
    cfg = policy.get("leadership") or {}
    groups = L._groups(policy)  # noqa: SLF001
    bars = bars or load_bars()
    panel = L.build_panel(bars, groups, str(cfg.get("benchmark") or "SPY"))
    dates = panel["dates"]
    horizons = [int(h) for h in cfg.get("horizons") or [20, 60, 120]]
    start = int(cfg.get("min_history_sessions") or 260)
    res = {
        period: {
            "detector": {h: [] for h in horizons},
            "strategic": {h: [] for h in horizons},
            "baseline": {h: [] for h in horizons},
            "false_confirm": [],
            "classes": {},
        }
        for period in ("in_sample", "holdout_2026")
    }
    for i in range(start, len(dates), step):
        d = dates[i]
        period = "holdout_2026" if d >= HOLDOUT_START else "in_sample"
        ev = L.evaluate_panel(panel, i, policy)["groups"]
        for k, g in ev.items():
            res[period]["classes"][g["class"]] = res[period]["classes"].get(g["class"], 0) + 1
        conf = [k for k, g in ev.items() if g["class"] == "LEADERSHIP_CONFIRMED"]
        h_mid = horizons[1] if len(horizons) > 1 else horizons[0]
        ranked = sorted(
            [(k, (g["features"].get("rs_ret") or {}).get(h_mid)) for k, g in ev.items() if g["features"]],
            key=lambda kv: -(kv[1] if kv[1] is not None else -9),
        )
        base = [k for k, v in ranked[:3] if v is not None]
        for h in horizons:
            end_i = i + h
            if end_i >= len(dates):
                continue
            if period == "in_sample" and dates[end_i] > IN_SAMPLE_END:
                continue
            for k in conf:
                x = _fwd_rel(panel, k, i, h)
                if x is not None:
                    res[period]["detector"][h].append(x)
                    if ev[k].get("horizon") == "strategic":
                        res[period]["strategic"][h].append(x)
                    if h == h_mid:
                        res[period]["false_confirm"].append(x < 0)
            for k in base:
                x = _fwd_rel(panel, k, i, h)
                if x is not None:
                    res[period]["baseline"][h].append(x)
    out = {"step": step, "horizons": horizons, "fixture": str(FIXTURE.relative_to(ROOT)), "periods": {}}
    for period, r in res.items():
        out["periods"][period] = {
            "detector": {h: _stats(v) for h, v in r["detector"].items()},
            "detector_strategic": {h: _stats(v) for h, v in r["strategic"].items()},
            "baseline_top3_rs60": {h: _stats(v) for h, v in r["baseline"].items()},
            "false_confirmation_rate": round(sum(r["false_confirm"]) / len(r["false_confirm"]), 3)
            if r["false_confirm"]
            else None,
            "class_counts": r["classes"],
        }
    out["note"] = (
        f"evaluation every {step} sessions; forward windows overlap for horizons longer than the step, so n overstates "
        "independent observations. Relative return = group return minus SPY return over the horizon."
    )
    return out


def table(rep: dict) -> str:
    lines = []
    for period, r in rep["periods"].items():
        lines.append(f"[{period}] false confirmations (60s): {r['false_confirmation_rate']}")
        lines.append("horizon | confirmed n/hit/mean | strategic-only n/hit/mean | baseline top-3 n/hit/mean")
        for h in rep["horizons"]:
            d, s_, b = r["detector"][h], r["detector_strategic"][h], r["baseline_top3_rs60"][h]
            lines.append(
                f"{h:>7} | {d['n']}/{d['hit_rate']}/{d['mean_rel']} | {s_['n']}/{s_['hit_rate']}/{s_['mean_rel']}"
                f" | {b['n']}/{b['hit_rate']}/{b['mean_rel']}"
            )
        lines.append(f"classes: {r['class_counts']}")
    lines.append(rep["note"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="write the track-record artifact the card cites")
    a = ap.parse_args(argv)
    rep = run(a.step)
    if a.write:
        ins = rep["periods"]["in_sample"]
        ho = rep["periods"]["holdout_2026"]
        hs = ho["detector_strategic"][60]
        rep["summary"] = {
            "confirmed_hit_60": ins["detector"][60]["hit_rate"],
            "confirmed_n_60": ins["detector"][60]["n"],
            "baseline_hit_60": ins["baseline_top3_rs60"][60]["hit_rate"],
            "false_confirmation_rate": ins["false_confirmation_rate"],
            # R1: the 2026 holdout is part of the track record every surface shows
            "holdout_confirmed_hit_60": ho["detector"][60]["hit_rate"],
            "holdout_confirmed_n_60": ho["detector"][60]["n"],
            "holdout_baseline_hit_60": ho["baseline_top3_rs60"][60]["hit_rate"],
            "holdout_strategic_hits_60": round((hs["hit_rate"] or 0) * hs["n"]),
            "holdout_strategic_n_60": hs["n"],
            "holdout_false_confirmation_rate": ho["false_confirmation_rate"],
            "verdict": "no demonstrated edge over top-3 relative-strength momentum; worse than it in the 2026 holdout",
        }
        out = ROOT / "docs" / "audits" / "ROTATION_LEADERSHIP_BACKTEST_20261031.json"
        out.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(rep, indent=2) if a.json else table(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
