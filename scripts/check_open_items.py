#!/usr/bin/env python3
"""Validate docs/governance/OPEN_ITEMS.md — every known gap has an owner and a review date.

AGENTS.md 26.0.0 moved every broken, partial, pending or "named debt" item out of the operating standard into one
register. A gap with no owner is how the 25.0.1 file accumulated ~50 of them with no resolution. This check makes the
register's shape a gate:

  * every row has a unique id (OI-NNN), a severity (High/Medium/Low), an owner from the allowed set, a review date
    (YYYY-MM-DD), an action from the allowed set, and a status (open/in-progress/blocked/done);
  * a done row names its fix (a PR or commit) in the PR column.

``--overdue [--today YYYY-MM-DD]`` prints open rows whose review date has passed (report only; exit 0). Read-only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "governance" / "OPEN_ITEMS.md"

SEVERITIES = {"High", "Medium", "Low"}
OWNERS = {
    "operator",
    "coordinator",
    "platform",
    "portfolio",
    "research",
    "cio",
    "comms",
    "agents",
    "execution",
    "learning",
    "defense",
    "watch",
    "hermes",
    "n8n",
}
ACTIONS = {"Fix now", "Decide", "Track with owner", "Retire / accept", "Stale — delete text"}
STATUSES = {"open", "in-progress", "blocked", "done"}
COLUMNS = ["ID", "Severity", "Item", "Owner", "Review by", "Action", "Status", "PR", "Source"]


def parse_rows(text: str) -> list[dict[str, str]]:
    """Rows of the first table whose header is exactly COLUMNS."""
    lines = text.splitlines()
    rows: list[dict[str, str]] = []
    in_table = False
    for line in lines:
        if not line.startswith("|"):
            if in_table and rows:
                in_table = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells == COLUMNS:
            in_table = True
            continue
        if in_table and set("".join(cells)) <= set("-: "):
            continue
        if in_table:
            if len(cells) != len(COLUMNS):
                rows.append({"_error": f"wrong cell count ({len(cells)}): {line[:80]}"})
                continue
            rows.append(dict(zip(COLUMNS, cells)))
    return rows


def validate(text: str) -> list[str]:
    errors: list[str] = []
    rows = parse_rows(text)
    if not rows:
        return ["no register table (header must be: | " + " | ".join(COLUMNS) + " |)"]
    seen: set[str] = set()
    for r in rows:
        if "_error" in r:
            errors.append(r["_error"])
            continue
        rid = r["ID"]
        if not re.fullmatch(r"OI-\d{3}", rid):
            errors.append(f"{rid or '?'}: id must look like OI-NNN")
        if rid in seen:
            errors.append(f"{rid}: duplicate id")
        seen.add(rid)
        if r["Severity"] not in SEVERITIES:
            errors.append(f"{rid}: severity {r['Severity']!r} not in {sorted(SEVERITIES)}")
        if r["Owner"] not in OWNERS:
            errors.append(f"{rid}: owner {r['Owner']!r} not in the allowed set")
        try:
            dt.date.fromisoformat(r["Review by"])
        except ValueError:
            errors.append(f"{rid}: review date {r['Review by']!r} is not YYYY-MM-DD")
        if r["Action"] not in ACTIONS:
            errors.append(f"{rid}: action {r['Action']!r} not in {sorted(ACTIONS)}")
        if r["Status"] not in STATUSES:
            errors.append(f"{rid}: status {r['Status']!r} not in {sorted(STATUSES)}")
        if not r["Item"]:
            errors.append(f"{rid}: empty item")
        if r["Status"] == "done" and not re.search(r"#\d+|[0-9a-f]{7,40}", r["PR"]):
            errors.append(f"{rid}: done without a PR or commit reference")
    return errors


def overdue(text: str, today: dt.date) -> list[dict[str, str]]:
    out = []
    for r in parse_rows(text):
        if "_error" in r or r.get("Status") == "done":
            continue
        try:
            if dt.date.fromisoformat(r["Review by"]) < today:
                out.append(r)
        except ValueError:
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default=str(REGISTER))
    ap.add_argument("--overdue", action="store_true", help="list open rows past their review date (report only)")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD; default today (local)")
    args = ap.parse_args(argv)
    text = Path(args.path).read_text(encoding="utf-8")
    if args.overdue:
        today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
        for r in overdue(text, today):
            print(f"OVERDUE {r['ID']} {r['Review by']} {r['Owner']}: {r['Item'][:100]}")
        return 0
    errors = validate(text)
    for e in errors:
        print(f"OPEN_ITEMS: {e}")
    if not errors:
        print(f"OPEN_ITEMS ok: {len(parse_rows(text))} rows, every row has an owner and a review date")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
