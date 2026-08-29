#!/usr/bin/env python3
"""Derive the operator monthly series from the Ken French factors file.

Deterministic, offline, idempotent. Reads
`reference/library/series/ff_research_data_factors_monthly.csv` (as ingested in
Wave 3A.2) and writes the normalised shape `cio_seasonality_analytics` already
parses — `date,year,month,return_pct,cycle_label` — so the surface swap is a
path change, not a parser rewrite.

    total market return = Mkt-RF + RF

`cycle_label` is the mechanical `year % 4` label. No partisan content, ever.

    python3 scripts/build_french_monthly_normalized.py [--check]

`--check` regenerates in memory and diffs against the committed file, so CI or
a reviewer can prove the committed series is exactly what this script produces.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "reference" / "library" / "series" / "ff_research_data_factors_monthly.csv"
OUT = ROOT / "reference" / "library" / "series" / "us_equity_monthly_french_1926.csv"

CYCLE = {0: "election_year", 1: "post_election_year",
         2: "midterm_year", 3: "pre_election_year"}


def rows() -> list[tuple[int, int, float]]:
    out: list[tuple[int, int, float]] = []
    for line in SRC.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != 5 or len(parts[0]) != 6 or not parts[0].isdigit():
            continue
        try:
            mkt, rf = float(parts[1]), float(parts[4])
        except ValueError:
            continue
        if mkt <= -99.0:          # French's missing-value sentinel
            continue
        out.append((int(parts[0][:4]), int(parts[0][4:]), round(mkt + rf, 4)))
    return out


def render() -> str:
    lines = ["date,year,month,return_pct,cycle_label"]
    for year, month, ret in rows():
        lines.append(f"{year}-{month:02d}-01,{year},{month},{ret},{CYCLE[year % 4]}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = render()
    if args.check:
        if not OUT.exists():
            print(f"MISSING {OUT}")
            return 1
        same = OUT.read_text(encoding="utf-8") == text
        print("french_monthly_normalized:", "MATCH" if same else "DRIFT")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines()) - 1} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
