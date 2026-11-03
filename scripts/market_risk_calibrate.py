#!/usr/bin/env python3
"""Derive Market Risk Engine thresholds by a stated rule from public history, never from the event being explained.

Rule (review of #2362, M5): every trigger is a percentile of its own daily distribution over the IN-SAMPLE window
2016-01-01..2025-12-31. 2026 is held out entirely; the backtest reports in-sample and out-of-sample separately.

* adverse-move triggers (WTI, dollar, 10-year, VIX jumps, HY OAS widening): the 95th percentile of the move,
  i.e. a WARN-level sub-signal fires on about 5% of in-sample sessions;
* complacency divergence: the index move at its 5th percentile, with VIX's same-day change in its weakest quartile
  on those days (no dependence on a <= 0.0% VIX change, which sits inside the snapshot-vs-close error);
* failed-retest tolerance: half the median absolute daily index move;
* IMPROVING inputs: the mirror-image percentile (5th for falling VIX / tightening spreads, 95th for HYG rallies).

Prints the table (and ``--json``); it never edits the policy file — values are copied in by a reviewed commit.
Offline: reads tests/fixtures/market_risk_scenarios only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk.fixture_reader import FixtureReader, close_instant  # noqa: E402

IN_START, IN_END = date(2016, 1, 1), date(2025, 12, 31)


def pct(values: list[float], q: float) -> float:
    v = sorted(values)
    if not v:
        return float("nan")
    k = (len(v) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def closes(r: FixtureReader, sym: str) -> list[tuple[date, float]]:
    rows = r.daily_bars([sym], sessions=10**6, end=close_instant(IN_END))
    return [
        (date.fromisoformat(x["date"]), float(x["close"])) for x in rows if date.fromisoformat(x["date"]) >= IN_START
    ]


def fred(r: FixtureReader, sid: str) -> list[tuple[date, float]]:
    rows = r.fred([sid], observations=10**6, end=close_instant(IN_END))
    out = []
    for x in rows:
        d = datetime.fromisoformat(str(x["as_of"])).date()
        if d >= IN_START and x.get("value") is not None:
            out.append((d, float(x["value"])))
    return out


def changes(s: list[tuple[date, float]], n: int, *, relative: bool) -> list[float]:
    out = []
    for i in range(n, len(s)):
        a, b = s[i - n][1], s[i][1]
        out.append(100.0 * (b / a - 1) if relative else b - a)
    return out


def calibrate(r: FixtureReader) -> dict:
    qqq, vix, hyg = closes(r, "QQQ"), closes(r, "^VIX"), closes(r, "HYG")
    hy, ust, wti, dxy = (fred(r, s) for s in ("BAMLH0A0HYM2", "DGS10", "DCOILWTICO", "DTWEXBGS"))
    q1 = changes(qqq, 1, relative=True)
    v1 = dict(zip([d for d, _ in vix[1:]], changes(vix, 1, relative=True)))
    qd = dict(zip([d for d, _ in qqq[1:]], q1))
    drop = pct(q1, 5)
    vix_on_drop = [v1[d] for d, x in qd.items() if x <= drop and d in v1]
    out = {
        "window": f"{IN_START}..{IN_END} (2026 held out)",
        "volatility.divergence_index_drop_pct": round(drop, 2),
        "volatility.divergence_vix_max_change_pct": round(pct(vix_on_drop, 25), 1),
        "volatility.vix_5d_change_pct": round(pct(changes(vix, 5, relative=True), 95), 1),
        "volatility.improving.vix_change_pct": round(pct(changes(vix, 10, relative=True), 5), 1),
        "technical.retest_tolerance_pct": round(pct([abs(x) for x in q1], 50) / 2, 2),
        "macro_credit.hy_oas_5d_bp": round(100 * pct(changes(hy, 5, relative=False), 95)),
        "macro_credit.hy_oas_20d_bp": round(100 * pct(changes(hy, 20, relative=False), 95)),
        "macro_credit.improving.hy_oas_20d_bp": round(-100 * pct(changes(hy, 20, relative=False), 5)),
        "macro_credit.ust10_20d_bp": round(100 * pct(changes(ust, 20, relative=False), 95)),
        "macro_credit.wti_20d_pct": round(pct(changes(wti, 20, relative=True), 95), 1),
        "macro_credit.dxy_20d_pct": round(pct(changes(dxy, 20, relative=True), 95), 1),
        "macro_credit.improving.hyg_20d_pct": round(pct(changes(hyg, 20, relative=True), 95), 1),
        "notes": {
            "hy_oas": f"FRED serves BAMLH0A0HYM2 from {hy[0][0] if hy else 'n/a'}; its in-sample window is that to {IN_END}",
            "vix_on_drop_days": len(vix_on_drop),
        },
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = calibrate(FixtureReader())
    if a.json:
        print(json.dumps(res, indent=1, sort_keys=True))
    else:
        for k, v in res.items():
            print(f"{k:45s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
