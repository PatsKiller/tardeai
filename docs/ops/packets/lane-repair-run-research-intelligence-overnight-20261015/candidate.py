#!/usr/bin/env python3
"""Build the candidate crontab for the RI overnight lane repair from the LIVE crontab. Writes only into --out.

    crontab -l > "$W/crontab.live"
    python3 candidate.py --crontab-file "$W/crontab.live" --out "$W"      # -> crontab.candidate, crontab.diff

Each change replaces ONE whole line matched by its exact text (never by line number, never by a glob), so a
crontab that drifted since 2026-10-15 is refused (exit 1) rather than half-edited. Exit 0 = every change applied
exactly once. Reads the crontab file only; never calls `crontab`, never installs.

Changes (README "Operator packet"; line numbers are the live crontab after the B-families install, 2026-10-15):
  C1  L735 RI `--phase full` 02:15 -> 00:15. 02:15 ET = 06:15 UTC sits in the official DeepSeek peak
      (06:00-10:00 UTC) the --official wrapper skips, so the line has logged PEAK_SKIP every night under EDT.
      00:15 ET is 04:15 UTC (EDT) / 05:15 UTC (EST): outside both official peak windows.
  C2  L736 RI `--phase archive` 05:15: drop the DeepSeek off-peak wrapper. The archive phase makes no model call
      (research_intelligence_refresh.py --archive), and 05:15 EDT = 09:15 UTC is peak, so it PEAK_SKIPped too.

Dropped (absorbed by the C1 B-families consolidation of 2026-10-15; the bound now lives in family_slot_jobs B2):
  C3/C4  were "add --budget-s 1500 --max-items-per-topic 12 to the standalone topic-ingestion lines (20:45
      weekdays, 02:45)". The b-families-top5 install retired both lines into
      `scripts/run_family_slot.py --family topic-ingestion`, so they no longer exist to edit. The same bound is
      now in the family's job definition (scripts/lib/family_slot_jobs.py TOPIC_INGEST_BOUND, both modes), which
      is served code: it takes effect with the release, with no crontab change.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

R = "/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT"
WRAP = 'bash "$HOME/.config/tradeai/bin/run_with_deepseek_offpeak.sh" --official -- '
GATE = f"bash {R}/scripts/non_trading_hours_gate.sh "
RI_SH = f"bash {R}/scripts/run_research_intelligence_overnight.sh"
RI_LOG = f">> {R}/logs/ri_overnight.log 2>&1"

CHANGES = [
    (
        "C1",
        f"15 2 * * * cd {R} && {WRAP}{GATE}{RI_SH} --phase full {RI_LOG}",
        f"15 0 * * * cd {R} && {WRAP}{GATE}{RI_SH} --phase full {RI_LOG}",
    ),
    (
        "C2",
        f"15 5 * * * cd {R} && {WRAP}{GATE}{RI_SH} --phase archive {RI_LOG}",
        f"15 5 * * * cd {R} && {GATE}{RI_SH} --phase archive {RI_LOG}",
    ),
]
#: C3/C4 (bound the standalone topic-ingestion lines) were dropped: absorbed by the C1 B-families consolidation;
#: bound now in family_slot_jobs B2 (TOPIC_INGEST_BOUND). See the module docstring.
DROPPED = ("C3", "C4")


def build(live: list[str], *, revert: bool = False) -> tuple[list[str], list[str]]:
    """(candidate lines, problems). Pure. revert=True maps every new line back to its old text."""
    out = list(live)
    problems: list[str] = []
    for cid, old, new in CHANGES:
        src, dst = (new, old) if revert else (old, new)
        hits = [i for i, line in enumerate(out) if line == src]
        if len(hits) != 1:
            problems.append(
                f"{cid}: expected exactly one line equal to the {'new' if revert else 'old'} text, found {len(hits)}"
            )
            continue
        out[hits[0]] = dst
    return out, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crontab-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--revert", action="store_true", help="build the rollback candidate from a crontab that has C1+C2")
    args = ap.parse_args(argv)
    live = Path(args.crontab_file).read_text(encoding="utf-8").splitlines()
    cand, problems = build(live, revert=args.revert)
    for p in problems:
        print(f"REFUSED {p}", file=sys.stderr)
    if problems:
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = "crontab.rollback" if args.revert else "crontab.candidate"
    (out / name).write_text("\n".join(cand) + "\n", encoding="utf-8")
    diff = list(difflib.unified_diff(live, cand, "crontab.live", name, lineterm="", n=0))
    (out / (name + ".diff")).write_text("\n".join(diff) + "\n", encoding="utf-8")
    print("\n".join(diff))
    print(f"changes={len(CHANGES)} lines_changed={sum(1 for a, b in zip(live, cand) if a != b)} wrote={out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
