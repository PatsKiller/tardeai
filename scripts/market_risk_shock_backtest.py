#!/usr/bin/env python3
"""Backtest the shock-type classifier on the public-data scenario fixtures (read-only, nothing written or sent).

For every scenario in tests/fixtures/market_risk_scenarios/scenarios.json, classify each session close where SPY is at
least --min-dd percent below its 20-session high (a stress day), and print the class distribution and the dominant
class beside the expected class(es).

  python3 scripts/market_risk_shock_backtest.py [--min-dd 3]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import contract as c, policy as P, sectors, shock_type  # noqa: E402
from scripts.lib.market_risk.fixture_reader import FixtureReader, close_instant  # noqa: E402

EXPECT = {  # the coordinator's stated expectations (operator 2026-10-31), not fitted
    "covid2020": {"SYSTEMIC"},
    "banks2023": {"SECTOR", "CREDIT"},
    "carry2024": {"SYSTEMIC", "FACTOR"},
    "oct2026": {"SECTOR", "FACTOR"},
    "corrections2026": {"SECTOR", "FACTOR"},
}


def expected(sid: str) -> set[str]:
    if sid.startswith("bear2022") or "2022" in sid:
        return {"SECTOR", "FACTOR"}
    return EXPECT.get(sid, set())


def run(min_dd: float, with_observations: bool = True) -> list[dict]:
    policy = P.load_policy()
    rd = FixtureReader()
    scen = json.loads((ROOT / "tests/fixtures/market_risk_scenarios/scenarios.json").read_text())
    scen = scen.get("scenarios", scen) if isinstance(scen, dict) else scen
    out = []
    for s in scen:
        days = rd.sessions(start=date.fromisoformat(s["start"]), end=date.fromisoformat(s["end"]))
        if not days:
            continue
        px = {
            sym: {r["date"]: r["close"] for r in rd.daily_bars([sym], sessions=4000, end=close_instant(days[-1]))}
            for sym in ("SPY", "QQQ")
        }
        dates = sorted(px["SPY"])
        counts: Counter = Counter()
        for d in days:
            i = dates.index(d.isoformat())
            win = dates[max(0, i - 19) : i + 1]
            dd = min((px[s_][d.isoformat()] / max(px[s_][x] for x in win) - 1) * 100 for s_ in ("SPY", "QQQ"))
            if dd > -min_dd:
                continue
            ctx = c.EvalContext(now=close_instant(d), reader=rd, policy=policy)
            obs = []
            if with_observations:  # the live classifier sees the engine's category states; so does the backtest
                from scripts.lib.market_risk import registry

                obs = [o.to_dict() for o in registry.evaluate_all(ctx)]
            counts[shock_type.classify(sectors.measure(ctx), obs, policy)["class"]] += 1
        dom = counts.most_common(1)[0][0] if counts else None
        exp = expected(s["id"])
        out.append(
            {
                "id": s["id"],
                "stress_days": sum(counts.values()),
                "classes": dict(counts),
                "dominant": dom,
                "expected": sorted(exp),
                "match": (dom in exp) if exp and dom else None,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-dd", type=float, default=3.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sectors-only", action="store_true", help="classify without the engine's category states")
    a = ap.parse_args(argv)
    rows = run(a.min_dd, with_observations=not a.sectors_only)
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            print(
                f"{r['id']:16} stress_days={r['stress_days']:3} dominant={r['dominant']} expected={r['expected']} match={r['match']} {r['classes']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
