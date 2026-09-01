#!/usr/bin/env python3
"""READ-ONLY classifier for the two divergent holdings state trees.

Writes nothing to either tree. Emits a per-file table and a JSON plan.

Winner rule, stated before measuring:
  - only one side has the file            -> that side (nothing to lose)
  - one side strictly newer AND not smaller -> that side ("newer and not smaller")
  - anything else                          -> AMBIGUOUS (never auto-resolved)

A newer-but-SMALLER file is deliberately AMBIGUOUS: that is the signature of a
truncation or a failed write, and picking it destroys the fuller copy. AGENTS.md
rule 5 -- a machine picking one can destroy the other.
"""
import datetime
import json
import os
import sys

PROJ = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state"
PSTATE = "/home/johnclaw/trade-ai-releases/persistent-state/data/portfolios/state"
OUT = "/tmp/claude-1000/-home-johnclaw-tradeai-wt-final-operator-convergence/b2d27b06-d74b-4a76-a5db-48b7c862952c/scratchpad/reconcile_plan.json"

# Risk-critical files: never auto-resolved regardless of evidence. AGENTS.md 17.
RISK_CRITICAL = {"stops.json", "tax_lots.json", "holdings.json", "trade_journal.json",
                 "risk_management.json", "holdings_symbol_state.json"}


def ts(x):
    return datetime.datetime.fromtimestamp(x).strftime("%m-%d %H:%M") if x else "-"


def lines(path):
    """Line count for append-only stores; a lower count on a newer file is a red flag."""
    if not path.endswith((".jsonl", ".log")):
        return None
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return None


def main():
    names = sorted(set(os.listdir(PROJ)) | set(os.listdir(PSTATE)))
    rows = []
    same = 0
    for n in names:
        a, b = os.path.join(PROJ, n), os.path.join(PSTATE, n)
        fa, fb = os.path.isfile(a), os.path.isfile(b)
        if not (fa or fb):
            continue
        if fa and not fb:
            rows.append((n, "PROJ_ONLY", os.path.getsize(a), 0,
                         os.path.getmtime(a), 0, "PROJ", "only copy exists"))
            continue
        if fb and not fa:
            rows.append((n, "PSTATE_ONLY", 0, os.path.getsize(b),
                         0, os.path.getmtime(b), "PSTATE", "only copy exists"))
            continue
        sa, sb = os.path.getsize(a), os.path.getsize(b)
        ma, mb = os.path.getmtime(a), os.path.getmtime(b)
        try:
            if open(a, "rb").read() == open(b, "rb").read():
                same += 1
                continue
        except OSError as exc:
            rows.append((n, "UNREADABLE", sa, sb, ma, mb, "AMBIGUOUS", str(exc)[:40]))
            continue

        newer = "PROJ" if ma > mb else ("PSTATE" if mb > ma else "TIE")
        bigger = "PROJ" if sa > sb else ("PSTATE" if sb > sa else "TIE")

        if n in RISK_CRITICAL:
            win, why = "AMBIGUOUS", "risk-critical: operator decides (AGENTS 17)"
        elif newer != "TIE" and bigger in (newer, "TIE"):
            win, why = newer, "newer and not smaller"
        elif newer != "TIE":
            win, why = "AMBIGUOUS", f"newer={newer} but SMALLER - possible truncation"
        else:
            win, why = "AMBIGUOUS", "same mtime, different content"

        la, lb = lines(a), lines(b)
        if la is not None and lb is not None and win != "AMBIGUOUS":
            if (win == "PROJ" and la < lb) or (win == "PSTATE" and lb < la):
                win, why = "AMBIGUOUS", f"append-only store loses lines ({la} vs {lb})"
        rows.append((n, "DIFFER", sa, sb, ma, mb, win, why))

    print(f"{'file':40s} {'PROJ':>10s} {'PSTATE':>10s} {'P.mtime':>12s} {'S.mtime':>12s}  WINNER      WHY")
    print("-" * 128)
    for n, kind, sa, sb, ma, mb, win, why in rows:
        print(f"{n[:40]:40s} {sa:>10d} {sb:>10d} {ts(ma):>12s} {ts(mb):>12s}  {win:11s} {why}")

    cp = sum(1 for r in rows if r[6] == "PROJ")
    cs = sum(1 for r in rows if r[6] == "PSTATE")
    am = sum(1 for r in rows if r[6] == "AMBIGUOUS")
    print()
    print(f"identical (no action) : {same}")
    print(f"clear -> PROJ         : {cp}")
    print(f"clear -> PSTATE       : {cs}")
    print(f"AMBIGUOUS (operator)  : {am}")
    print(f"total needing a call  : {len(rows)}")

    json.dump([{"file": n, "kind": k, "proj_size": sa, "pstate_size": sb,
                "winner": w, "why": y} for n, k, sa, sb, _, _, w, y in rows],
              open(OUT, "w"), indent=1)
    print(f"\nplan -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
