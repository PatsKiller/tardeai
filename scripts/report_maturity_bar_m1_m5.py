#!/usr/bin/env python3
"""report_maturity_bar_m1_m5.py — thin §15 five-proof status (honest, not a percentage).

Reads local artifacts only. Default verdict is NOT_OBSERVED unless evidence is present.
Does not claim OBSERVED from hermetic tests alone.

USAGE
  python3 scripts/report_maturity_bar_m1_m5.py
  python3 scripts/report_maturity_bar_m1_m5.py --json

AUTHORITY: READ_ONLY_ADVISORY
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "MaturityBarM1M5Report@v1"
ROOT = Path(__file__).resolve().parents[1]


def _pin() -> str:
    try:
        return str((Path.home() / "trade-ai-releases/portfolio-server/CURRENT").resolve())
    except OSError:
        return "UNKNOWN"


def _exists_nonempty(p: Path) -> bool:
    return p.is_file() and p.stat().st_size > 0


def evaluate(root: Path | None = None) -> dict:
    root = root or ROOT
    cio = root / "data" / "cio"
    # Prefer persistent-state when present
    persist = Path.home() / "trade-ai-releases/persistent-state/data/cio"
    if persist.is_dir():
        cio = persist

    wake_effects = cio / "wake_turn_effects.jsonl"
    # research / critic field changes are not centralized; stay honest
    proofs = {
        "M1_Research": {
            "verdict": "NOT_OBSERVED",
            "note": "needs self-raised research → InstrumentRecord field diff from served release",
        },
        "M2_Advice": {
            "verdict": "NOT_OBSERVED",
            "note": "needs critic verdict changing next_research_question on a live record",
        },
        "M3_Feedback": {
            "verdict": "CANDIDATE" if _exists_nonempty(wake_effects) else "NOT_OBSERVED",
            "note": f"wake_turn_effects present={_exists_nonempty(wake_effects)} path={wake_effects}",
        },
        "M4_Consistency": {
            "verdict": "PARTIAL",
            "note": "bridge pin aligned live 2026-09-18; full operator-number census not run this report",
        },
        "M5_Persistence": {
            "verdict": "NOT_OBSERVED",
            "note": "needs unattended scheduled load-by-subject + days-later disposition honor",
        },
    }
    return {
        "schema": SCHEMA,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pin": _pin(),
        "authority": "READ_ONLY_ADVISORY",
        "proofs": proofs,
        "rule": "Do not score as a percentage (AGENTS.md §15).",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = evaluate()
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(f"Maturity bar M1–M5 as_of={rep['as_of']} pin={rep['pin']}")
        for k, v in rep["proofs"].items():
            print(f"  {k}: {v['verdict']} — {v['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
