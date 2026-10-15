#!/usr/bin/env python3
"""lane-retire-wave1-20261015 — build, roll back and verify the RETIRE wave-1 crontab candidate (read-only tool).

Lines are matched by their EXACT original text (lines_to_retire.tsv `original`), never by line number, so the
packet survives line drift. A matched line is replaced in place by ``# RETIRED <date> retire-ld-w1 <reason> <original>``;
nothing else changes and nothing is deleted (AGENTS.md §0 rail 6). This tool never calls ``crontab -``: install.sh
and rollback.sh do that, operator-run, under a ``cron`` grant.

    python3 retire_packet.py build    --crontab <(crontab -l) --date YYYY-MM-DD [--tier-b] --out DIR
    python3 retire_packet.py rollback --crontab <(crontab -l) [--tier-b] --out FILE
    python3 retire_packet.py verify   --crontab <(crontab -l) [--tier-b]          # read-back after install
    python3 retire_packet.py verify   --crontab <(crontab -l) [--tier-b] --expect-live   # read-back after rollback

Exit 0 = ok, 2 = refused (a line is missing, duplicated or already retired).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAG = "retire-ld-w1"
TAG_RE = re.compile(r"^# RETIRED (\d{4}-\d{2}-\d{2}) " + re.escape(TAG) + r" (\S+) (.*)$")


def rows(tier_b: bool) -> list[dict[str, str]]:
    files = ["lines_to_retire.tsv"] + (["lines_to_retire_tier_b.tsv"] if tier_b else [])
    out = []
    for name in files:
        text = (HERE / name).read_text(encoding="utf-8").splitlines()
        for ln in text[1:]:
            if ln.strip():
                line, lane, reason, original = ln.split("\t", 3)
                out.append({"line": line, "lane_id": lane, "reason": reason, "original": original, "file": name})
    return out


def is_job(ln: str) -> bool:
    s = ln.strip()
    return (
        bool(s) and not s.startswith("#") and not ("=" in s.split()[0] and not s[0].isdigit() and not s.startswith("*"))
    )


def active_count(lines: list[str]) -> int:
    return sum(1 for ln in lines if is_job(ln))


def build(text: str, date: str, tier_b: bool) -> tuple[str, list[str]]:
    lines = text.splitlines()
    new = list(lines)
    problems = []
    changed = 0
    for r in rows(tier_b):
        orig = r["original"].rstrip()
        hits = [i for i, ln in enumerate(lines) if ln.rstrip() == orig]
        tagged = [i for i, ln in enumerate(lines) if (m := TAG_RE.match(ln)) and m.group(3).rstrip() == orig]
        if not hits and len(tagged) == 1:
            continue  # already retired by this packet (tier A installed earlier, tier B now)
        if len(hits) != 1 or tagged:
            problems.append(
                f"{r['lane_id']}: original found {len(hits)} times as a live line and {len(tagged)} "
                "times retired (need exactly 1 live, 0 retired)"
            )
            continue
        new[hits[0]] = f"# RETIRED {date} {TAG} {r['reason']} {lines[hits[0]]}"
        changed += 1
    if not problems and not changed:
        problems.append("nothing to retire: every packet line is already retired")
    return "\n".join(new) + "\n", problems


def rollback(text: str, tier_b: bool) -> tuple[str, list[str], int]:
    lines = text.splitlines()
    want = {r["original"].rstrip(): r["reason"] for r in rows(tier_b)}
    live = {ln.rstrip() for ln in lines if is_job(ln)}
    out, n, problems = [], 0, []
    for ln in lines:
        m = TAG_RE.match(ln)
        if m and m.group(3).rstrip() in want and want[m.group(3).rstrip()] == m.group(2):
            n += 1
            if m.group(3).rstrip() in live:
                problems.append(f"already live (double schedule): {m.group(3)[:120]}")
            out.append(m.group(3))
            continue
        out.append(ln)
    if n != len(want):
        problems.append(f"tagged lines {n} != expected {len(want)}")
    return "\n".join(out) + "\n", problems, n


def verify(text: str, tier_b: bool, expect_live: bool) -> list[str]:
    lines = text.splitlines()
    problems = []
    for r in rows(tier_b):
        orig = r["original"].rstrip()
        live = sum(1 for ln in lines if ln.rstrip() == orig)
        tagged = sum(1 for ln in lines if (m := TAG_RE.match(ln)) and m.group(3).rstrip() == orig)
        if expect_live and (live, tagged) != (1, 0):
            problems.append(f"{r['lane_id']}: expected live once and untagged, got live={live} tagged={tagged}")
        if not expect_live and (live, tagged) != (0, 1):
            problems.append(f"{r['lane_id']}: expected retired once and not live, got live={live} tagged={tagged}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("build", "rollback", "verify"))
    ap.add_argument("--crontab", required=True)
    ap.add_argument("--date", default="")
    ap.add_argument("--tier-b", action="store_true", help="also retire lines_to_retire_tier_b.tsv (operator YES rows)")
    ap.add_argument("--out", default="")
    ap.add_argument("--expect-live", action="store_true")
    a = ap.parse_args(argv)
    text = Path(a.crontab).read_text(encoding="utf-8")
    if a.action == "verify":
        problems = verify(text, a.tier_b, a.expect_live)
        for p in problems:
            print("VERIFY FAILED:", p)
        if not problems:
            n = len(rows(a.tier_b))
            print(
                f"VERIFY OK: {n} line(s) {'live' if a.expect_live else 'retired (commented, tagged ' + TAG + ')'}; "
                f"active job lines now {active_count(text.splitlines())}"
            )
        return 2 if problems else 0
    if a.action == "build":
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", a.date):
            print("REFUSED: --date YYYY-MM-DD required")
            return 2
        cand, problems = build(text, a.date, a.tier_b)
        for p in problems:
            print("REFUSED:", p)
        if problems:
            return 2
        out = Path(a.out or HERE)
        out.mkdir(parents=True, exist_ok=True)
        (out / "crontab.before.txt").write_text(text, encoding="utf-8")
        (out / "crontab.before.sha256").write_text(hashlib.sha256(text.encode()).hexdigest() + "\n")
        (out / "crontab.candidate.txt").write_text(cand, encoding="utf-8")
        (out / "crontab.candidate.sha256").write_text(hashlib.sha256(cand.encode()).hexdigest() + "\n")
        diff = difflib.unified_diff(
            text.splitlines(True), cand.splitlines(True), "crontab.before.txt", "crontab.candidate.txt"
        )
        (out / "crontab.diff").write_text("".join(diff), encoding="utf-8")
        print(
            f"active job lines {active_count(text.splitlines())} -> {active_count(cand.splitlines())} "
            f"({len(rows(a.tier_b))} retired); before {hashlib.sha256(text.encode()).hexdigest()[:12]} "
            f"candidate {hashlib.sha256(cand.encode()).hexdigest()[:12]}"
        )
        return 0
    restored, problems, n = rollback(text, a.tier_b)
    for p in problems:
        print("REFUSED:", p)
    if problems:
        return 2
    if a.out:
        Path(a.out).write_text(restored, encoding="utf-8")
    print(
        f"would uncomment {n} line(s); active job lines {active_count(text.splitlines())} -> "
        f"{active_count(restored.splitlines())}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
