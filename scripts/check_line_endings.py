#!/usr/bin/env python3
"""Fail a change whose diff is mostly line-ending churn.

    python3 scripts/check_line_endings.py                 # staged changes
    python3 scripts/check_line_endings.py --range A..B    # a commit range
    python3 scripts/check_line_endings.py --json

On 2026-08-27 a "preserve CRLF" helper double-converted an already-CRLF file,
turning every `\r\n` into `\r\r\n` across 783 lines. Python parsed it, the tests
passed, and CI would have accepted it. The only symptom was that the insertion
count looked implausible for the edit -- 894 where ~112 was expected.

That symptom is mechanical, so it can be a gate. git counts a line as changed
when only its separator changed; `git diff -w` does not. A change whose real
diff dwarfs its whitespace-ignoring diff is line-ending churn, whatever else it
also contains.

Reported per file, because one converted file inside a large legitimate change
is exactly the case a repo-wide ratio would hide.

AUTHORITY: READ_ONLY_ADVISORY. Static analysis only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

SCHEMA = "LineEndingChurnCheck@v1"

NO_CONSUMER_REASON = (
    "this IS a CI gate; the workflow invokes it, nothing imports it. Same shape "
    "as check_dark_contracts.py -- which is the guard that caught this one."
)

# A file may legitimately gain whitespace-only lines (blank lines, reindent), so
# require both a ratio AND an absolute floor before failing. The observed
# incident was 783 churned vs 12 real on one file: ratio 65, absolute 771.
MIN_CHURN_LINES = 40      # below this, not worth arguing about
MIN_CHURN_RATIO = 5.0     # real diff at least 5x the whitespace-ignoring diff


def _numstat(args: list[str]) -> dict[str, int]:
    out = subprocess.run(["git", "diff", "--numstat", *args],
                         capture_output=True, text=True, check=True).stdout
    totals: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "-":
            continue          # binary
        add, dele, path = int(parts[0]), int(parts[1]), parts[2]
        totals[path] = add + dele
    return totals


def audit(diff_args: list[str]) -> dict:
    real = _numstat(diff_args)
    ignoring = _numstat(["-w", *diff_args])
    findings = []
    for path, real_lines in sorted(real.items()):
        substantive = ignoring.get(path, 0)
        churn = real_lines - substantive
        if churn < MIN_CHURN_LINES:
            continue
        ratio = real_lines / substantive if substantive else float("inf")
        if ratio < MIN_CHURN_RATIO:
            continue
        findings.append({
            "file": path,
            "real_diff_lines": real_lines,
            "substantive_lines": substantive,
            "whitespace_churn_lines": churn,
            "ratio": None if substantive == 0 else round(ratio, 1),
        })
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "files_examined": len(real),
        "findings": findings,
        "ok": not findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--range", dest="rng", help="commit range, e.g. origin/main..HEAD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    diff_args = [args.rng] if args.rng else ["--cached"]
    result = audit(diff_args)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"line-ending churn: none ({result['files_examined']} files examined)")
    else:
        print("LINE-ENDING CHURN DETECTED\n")
        for f in result["findings"]:
            print(f"  {f['file']}")
            print(f"    real diff        {f['real_diff_lines']} lines")
            print(f"    ignoring space   {f['substantive_lines']} lines")
            print(f"    churn            {f['whitespace_churn_lines']} lines"
                  + (f"  ({f['ratio']}x)" if f["ratio"] else ""))
        print("\nThe edit rewrote line endings. A 'preserve CRLF' helper that converts\n"
              "conditionally turns an already-CRLF file into \\r\\r\\n; write_text() on a\n"
              "CRLF file converts it to LF. Use scripts/lib/safe_text_edit.edit_text,\n"
              "which detects the existing style and refuses to change it.", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
