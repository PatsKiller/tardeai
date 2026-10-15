#!/usr/bin/env python3
"""consolidation-health-audit-c3-20261015 — build / roll back / verify the C3 flip of the crontab (read-only tool).

The flip replaces the four weekday-morning F36 lines with ONE stage-runner line, in one act:

* each step's cron line (matched by its EXACT text, ``cron_line_verbatim`` in config/pipelines/health_audit.json) is
  commented in place as ``# RETIRED <date> c3-health-audit <step_id> <original>`` (never deleted);
* the runner line RUNNER_LINE is appended at the end of the table (below every NAME=value line the steps' env blocks
  name, so the runner inherits exactly what each step's own line had).

It never calls ``crontab -``; install.sh / rollback.sh do that, operator-run, under a ``cron`` grant.

    python3 flip_packet.py build    --crontab FILE --date YYYY-MM-DD --out DIR
    python3 flip_packet.py rollback --crontab FILE --out FILE
    python3 flip_packet.py verify   --crontab FILE [--expect-live]
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
MANIFEST = ROOT / "config" / "pipelines" / "health_audit.json"
TAG = "c3-health-audit"
TAG_RE = re.compile(r"^# RETIRED (\d{4}-\d{2}-\d{2}) " + re.escape(TAG) + r" (\S+) (.*)$")
RUNNER_LINE = (
    "30 7 * * 1-5 cd $PROJ && bash scripts/pipelines/run_health_audit_pipeline.sh --stage morning --apply "
    ">> logs/pipelines/health_audit_cron.log 2>&1  # TRADEAI_LANE health-audit-pipeline-morning"
)


def steps(manifest: Path = MANIFEST) -> list[dict]:
    m = json.loads(manifest.read_text(encoding="utf-8"))
    return [s for st in m["stages"].values() for s in st["steps"]]


def is_job(ln: str) -> bool:
    s = ln.strip()
    return (
        bool(s) and not s.startswith("#") and not ("=" in s.split()[0] and not s[0].isdigit() and not s.startswith("*"))
    )


def active_count(lines: list[str]) -> int:
    return sum(1 for ln in lines if is_job(ln))


def build(text: str, date: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    new, problems = list(lines), []
    if any(ln.rstrip() == RUNNER_LINE for ln in lines):
        problems.append("runner line already present")
    for st in steps():
        orig = st["cron_line_verbatim"].rstrip()
        hits = [i for i, ln in enumerate(lines) if ln.rstrip() == orig]
        if len(hits) != 1:
            problems.append(f"{st['id']}: original found {len(hits)} times as a live line (need exactly 1)")
            continue
        new[hits[0]] = f"# RETIRED {date} {TAG} {st['id']} {lines[hits[0]]}"
    new.append(RUNNER_LINE)
    return "\n".join(new) + "\n", problems


def rollback(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    want = {s["cron_line_verbatim"].rstrip(): s["id"] for s in steps()}
    live = {ln.rstrip() for ln in lines if is_job(ln)}
    out, n, problems = [], 0, []
    runner = 0
    for ln in lines:
        if ln.rstrip() == RUNNER_LINE:
            runner += 1
            continue
        m = TAG_RE.match(ln)
        if m and want.get(m.group(3).rstrip()) == m.group(2):
            n += 1
            if m.group(3).rstrip() in live:
                problems.append(f"already live (double schedule): {m.group(3)[:100]}")
            out.append(m.group(3))
            continue
        out.append(ln)
    if n != len(want) or runner != 1:
        problems.append(f"tagged lines {n}/{len(want)}, runner lines {runner}/1")
    return "\n".join(out) + "\n", problems


def verify(text: str, expect_live: bool) -> list[str]:
    lines = text.splitlines()
    problems = []
    runner = sum(1 for ln in lines if ln.rstrip() == RUNNER_LINE)
    for st in steps():
        orig = st["cron_line_verbatim"].rstrip()
        live = sum(1 for ln in lines if ln.rstrip() == orig)
        tagged = sum(1 for ln in lines if (m := TAG_RE.match(ln)) and m.group(3).rstrip() == orig)
        want = (1, 0) if expect_live else (0, 1)
        if (live, tagged) != want:
            problems.append(f"{st['id']}: live={live} tagged={tagged}, want {want}")
    if runner != (0 if expect_live else 1):
        problems.append(f"runner line count {runner}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("build", "rollback", "verify"))
    ap.add_argument("--crontab", required=True)
    ap.add_argument("--date", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--expect-live", action="store_true")
    a = ap.parse_args(argv)
    text = Path(a.crontab).read_text(encoding="utf-8")
    if a.action == "verify":
        problems = verify(text, a.expect_live)
        for p in problems:
            print("VERIFY FAILED:", p)
        if not problems:
            print(
                f"VERIFY OK: {'4 step lines live, no runner' if a.expect_live else '4 step lines retired, 1 runner line'};"
                f" active job lines {active_count(text.splitlines())}"
            )
        return 2 if problems else 0
    if a.action == "build":
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", a.date):
            print("REFUSED: --date YYYY-MM-DD required")
            return 2
        cand, problems = build(text, a.date)
        for p in problems:
            print("REFUSED:", p)
        if problems:
            return 2
        out = Path(a.out or ".")
        out.mkdir(parents=True, exist_ok=True)
        (out / "crontab.before.txt").write_text(text, encoding="utf-8")
        (out / "crontab.candidate.txt").write_text(cand, encoding="utf-8")
        (out / "crontab.candidate.sha256").write_text(hashlib.sha256(cand.encode()).hexdigest() + "\n")
        (out / "crontab.diff").write_text(
            "".join(
                difflib.unified_diff(
                    text.splitlines(True), cand.splitlines(True), "crontab.before.txt", "crontab.candidate.txt"
                )
            ),
            encoding="utf-8",
        )
        print(
            f"active job lines {active_count(text.splitlines())} -> {active_count(cand.splitlines())} "
            "(4 step lines retired, 1 runner line added)"
        )
        return 0
    restored, problems = rollback(text)
    for p in problems:
        print("REFUSED:", p)
    if problems:
        return 2
    if a.out:
        Path(a.out).write_text(restored, encoding="utf-8")
    print(f"rollback: active job lines {active_count(text.splitlines())} -> {active_count(restored.splitlines())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
