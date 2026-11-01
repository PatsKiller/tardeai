#!/usr/bin/env python3
"""Regenerate scripts/lib/market_risk/base_rates_table.json.gz — the deep brief's historical base rates.

  python3 scripts/market_risk_base_rates_build.py            # dry run: print the summary, write nothing
  python3 scripts/market_risk_base_rates_build.py --write    # write the table (deterministic: same input -> same bytes)

Input: the committed public 10-year daily fixture (tests/fixtures/market_risk_scenarios/bars.csv.gz). 2026 is held
out: only days dated 2016-2025 become rows, and a forward outcome is recorded only when its whole window ends by
2025-12-31. Never hand-edit the table. No position data (public market prices only).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import base_rates as br  # noqa: E402

BARS = ROOT / "tests" / "fixtures" / "market_risk_scenarios" / "bars.csv.gz"
HOLDOUT_START = date(2026, 1, 1)
FIRST_ROW = date(2016, 1, 1)
SYMBOLS = ("SPY", "QQQ", "SOXX", "SMH", "^VIX") + br.SECTOR_ETFS


def load_closes(path: Path = BARS) -> tuple[list[date], dict[str, dict[date, float]]]:
    by: dict[str, dict[date, float]] = defaultdict(dict)
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["symbol"] in SYMBOLS and r.get("close"):
                by[r["symbol"]][date.fromisoformat(r["date"])] = float(r["close"])
    cal = sorted(by["SPY"])
    return cal, by


def _r(x: float | None, nd: int = 5) -> float | None:
    return None if x is None else round(x, nd)


def build(cal: list[date], by: dict[str, dict[date, float]]) -> dict:
    hist: dict[str, list[float]] = {s: [] for s in SYMBOLS}
    rows: list[dict] = []
    in_sample = [d for d in cal if d < HOLDOUT_START]
    last_in = len(in_sample) - 1
    for i, d in enumerate(in_sample):
        for s in SYMBOLS:
            if d in by[s]:
                hist[s].append(by[s][d])
        if d < FIRST_ROW:
            continue
        f = br.features_at({s: hist[s] for s in SYMBOLS if hist[s]})
        o: dict[str, dict] = {}
        for s in br.INDEXES + br.GROUPS:
            c0 = by[s].get(d)
            if c0 is None:
                continue
            hs = br.HORIZONS if s in br.INDEXES else br.GROUP_HORIZONS
            o[s] = {}
            for h in hs:
                j = i + h
                if j <= last_in and in_sample[j] in by[s]:
                    o[s][str(h)] = _r(by[s][in_sample[j]] / c0 - 1.0)
        spy0 = by["SPY"][d]
        fut = [by["SPY"][x] for x in in_sample[i + 1 : i + 121] if x in by["SPY"]]
        if i + 20 <= last_in:
            o["SPY"]["drop5_20"] = int(min(fut[:20]) / spy0 - 1.0 <= -0.05)
        if i + 60 <= last_in:
            w = fut[:60]
            o["SPY"]["trough60"] = w.index(min(w)) + 1
        if i + 120 <= last_in:
            # sessions FROM the 60-session low back to the starting level (None: not regained within 120 sessions)
            w = fut[:60]
            t = w.index(min(w))
            rec = next((k - t for k in range(t + 1, 120) if fut[k] >= spy0), None)
            o["SPY"]["recover120"] = rec
        rows.append(
            {"d": d.isoformat(), "f": {k: (_r(v) if isinstance(v, float) else v) for k, v in f.items()}, "o": o}
        )
    return {
        "schema": br.TABLE_SCHEMA,
        "generated_from": "tests/fixtures/market_risk_scenarios/bars.csv.gz (public daily closes)",
        "holdout": "2026-01-01 onward (no rows, no forward windows into 2026)",
        "first_row": rows[0]["d"] if rows else None,
        "last_row": rows[-1]["d"] if rows else None,
        "rows": rows,
    }


def summary(table: dict) -> str:
    rows = table["rows"]
    lines = [f"rows {len(rows)} ({table['first_row']} .. {table['last_row']}); holdout: {table['holdout']}"]
    pats = Counter(r["f"].get("pattern") for r in rows)
    lines.append("pattern counts: " + ", ".join(f"{k}={v}" for k, v in sorted(pats.items(), key=lambda x: str(x[0]))))
    lines.append("pattern | n | SPY 5d median% | SPY 20d median% | SPY 20d share<0 % | P(further -5% in 20d) %")
    for pat in ("BROAD", "CONCENTRATED_TECH", "MIXED"):
        res = br.conditional({"pattern": pat}, min_n=1, table=table)
        if res.get("insufficient_history"):
            continue
        s5, s20 = res["SPY"]["5d"], res["SPY"]["20d"]
        p = res["spy_further_5pct_drop_within_20d"]["hit_rate_pct"]
        lines.append(
            f"{pat} | {res['n_days']} | {s5['median_pct']} | {s20['median_pct']} | {s20['share_negative_pct']} | {p}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    cal, by = load_closes()
    table = build(cal, by)
    if a.write:
        raw = json.dumps(table, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with open(br.TABLE_PATH, "wb") as out, gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0) as fh:
            fh.write(raw)
        br.load_table.cache_clear()
        print(f"wrote {br.TABLE_PATH} ({br.TABLE_PATH.stat().st_size} bytes)")
    print(summary(table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
