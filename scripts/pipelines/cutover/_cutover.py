#!/usr/bin/env python3
"""_cutover.py — flip one tranche B stage from --dry-run to --apply and retire its absorbed cron lines.

Called by cutover_<pipeline>_<stage>.sh / rollback_<pipeline>_<stage>.sh. Never deletes a line
(AGENTS.md §0 rail 6): every absorbed line is COMMENTED with `# RETIRED <date> tranche-b <stage> `
so `discover_commented_cron` records why, and a backup is taken before the single crontab write.

    _cutover.py cutover  <pipeline> <stage> [--dry-run|--apply] [--code-root DIR]
    _cutover.py rollback <pipeline> <stage> [--dry-run|--apply] [--backup FILE]

Env: CRONTAB_CMD (default `crontab`; tests point it at a fake), BACKUP_DIR (default
~/.local/state/tradeai/backups), CUTOVER_DATE (default today UTC).

Refuses (exit 2) unless: the stage line exists exactly once and is in --dry-run; every absorbed
line from the manifest is present verbatim and uncommented. --dry-run (default) prints the exact
lines and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CODE_ROOT = HERE.parent.parent.parent

PIPELINES = {
    "after_close": ("config/pipelines/after_close.json", "run_after_close_pipeline.sh", ""),
    "premarket": ("config/pipelines/premarket.json", "run_premarket_data_pipeline.sh", ""),
    "hermes_learning": ("config/pipelines/hermes_learning.json", "run_hermes_pipeline.sh", ""),
    "hermes_overnight": ("config/pipelines/hermes_overnight.json", "run_hermes_pipeline.sh",
                         "--manifest config/pipelines/hermes_overnight.json"),
}


def crontab_cmd() -> str:
    return os.environ.get("CRONTAB_CMD", "crontab")


def read_crontab() -> str:
    proc = subprocess.run([crontab_cmd(), "-l"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise SystemExit(f"REFUSED: {crontab_cmd()} -l failed: {proc.stderr.strip()[:120]}")
    return proc.stdout


def write_crontab(text: str) -> None:
    proc = subprocess.run([crontab_cmd(), "-"], input=text, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise SystemExit(f"FAILED: {crontab_cmd()} - rejected the new table: {proc.stderr.strip()[:200]}")


def backup_dir() -> Path:
    d = Path(os.environ.get("BACKUP_DIR") or (Path.home() / ".local/state/tradeai/backups"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def stage_regex(pipeline: str, stage: str) -> re.Pattern[str]:
    _, runner, extra = PIPELINES[pipeline]
    return re.compile(r"scripts/pipelines/" + re.escape(runner) + r"\s+" + (re.escape(extra) + r"\s+" if extra else "")
                      + r"--stage\s+" + re.escape(stage) + r"\s+--(dry-run|apply)\b")


def plan(pipeline: str, stage: str, text: str, code_root: Path) -> dict:
    manifest_rel, _, _ = PIPELINES[pipeline]
    manifest = json.loads((code_root / manifest_rel).read_text(encoding="utf-8"))
    spec = manifest["stages"][stage]
    absorbed = [str(st["cron_line_verbatim"]).rstrip() for st in spec["steps"]]
    lines = text.splitlines()
    pat = stage_regex(pipeline, stage)
    stage_idx = [i for i, ln in enumerate(lines) if not ln.lstrip().startswith("#") and pat.search(ln)]
    active = {ln.rstrip(): i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")}
    present = [a for a in absorbed if a in active]
    missing = [a for a in absorbed if a not in active]
    problems = []
    if len(stage_idx) != 1:
        problems.append(f"stage line found {len(stage_idx)} times (need exactly 1)")
    elif "--dry-run" not in lines[stage_idx[0]]:
        problems.append("stage line is not in --dry-run (already cut over?)")
    if missing:
        problems.append(f"{len(missing)} absorbed line(s) missing or already commented")
    return {"pipeline": pipeline, "stage": stage, "step_count": len(absorbed), "absorbed": absorbed, "present": present,
            "missing": missing, "stage_index": stage_idx[0] if len(stage_idx) == 1 else None,
            "stage_line": lines[stage_idx[0]] if len(stage_idx) == 1 else None, "problems": problems}


def apply_plan(p: dict, text: str, date: str) -> str:
    lines = text.splitlines()
    i = p["stage_index"]
    lines[i] = lines[i].replace("--dry-run", "--apply", 1)
    tag = f"# RETIRED {date} tranche-b {p['stage']} "
    absorbed = set(p["absorbed"])
    out = []
    for ln in lines:
        if ln.rstrip() in absorbed and not ln.lstrip().startswith("#"):
            out.append(tag + ln)
        else:
            out.append(ln)
    return "\n".join(out) + "\n"


def cmd_cutover(args: argparse.Namespace) -> int:
    text = read_crontab()
    p = plan(args.pipeline, args.stage, text, args.code_root)
    print(f"[cutover {p['pipeline']}/{p['stage']}] steps={p['step_count']} absorbed present={len(p['present'])} missing={len(p['missing'])}")
    for a in p["missing"]:
        print(f"  MISSING: {a[:150]}")
    if p["stage_line"]:
        print(f"  stage line: {p['stage_line'][:150]}")
    if p["problems"]:
        for q in p["problems"]:
            print(f"  REFUSED: {q}")
        return 2
    for a in p["absorbed"]:
        print(f"  would comment: {a[:140]}")
    if not args.apply:
        print("dry-run: nothing written")
        return 0
    date = os.environ.get("CUTOVER_DATE") or datetime.now(timezone.utc).date().isoformat()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bk = backup_dir() / f"crontab-{ts}-pre-cutover-{args.stage}.txt"
    bk.write_text(text, encoding="utf-8")
    new = apply_plan(p, text, date)
    write_crontab(new)
    after = read_crontab()
    commented = sum(1 for ln in after.splitlines() if ln.startswith(f"# RETIRED {date} tranche-b {args.stage} "))
    print(f"applied: backup={bk} stage=--apply commented={commented} (expected {p['step_count']})")
    return 0 if commented == p["step_count"] else 1


def cmd_rollback(args: argparse.Namespace) -> int:
    bk = args.backup
    if bk is None:
        cands = sorted(backup_dir().glob(f"crontab-*-pre-cutover-{args.stage}.txt"))
        if not cands:
            print(f"REFUSED: no backup crontab-*-pre-cutover-{args.stage}.txt under {backup_dir()}")
            return 2
        bk = cands[-1]
    text = bk.read_text(encoding="utf-8")
    pat = stage_regex(args.pipeline, args.stage)
    stage_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#") and pat.search(ln)]
    print(f"[rollback {args.pipeline}/{args.stage}] backup={bk} lines={len(text.splitlines())} stage_line_in_backup={len(stage_lines)}")
    if not args.apply:
        print("dry-run: nothing written")
        return 0
    cur = read_crontab()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (backup_dir() / f"crontab-{ts}-pre-rollback-{args.stage}.txt").write_text(cur, encoding="utf-8")
    write_crontab(text if text.endswith("\n") else text + "\n")
    print("restored")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["cutover", "rollback"])
    ap.add_argument("pipeline", choices=sorted(PIPELINES))
    ap.add_argument("stage")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--code-root", type=Path, default=Path(os.environ.get("CUTOVER_CODE_ROOT") or DEFAULT_CODE_ROOT))
    ap.add_argument("--backup", type=Path, default=None)
    args = ap.parse_args(argv)
    manifest_rel = PIPELINES[args.pipeline][0]
    stages = json.loads((args.code_root / manifest_rel).read_text(encoding="utf-8"))["stages"]
    if args.stage not in stages:
        print(f"REFUSED: unknown stage {args.stage!r} for {args.pipeline} (one of: {', '.join(stages)})")
        return 2
    return cmd_cutover(args) if args.action == "cutover" else cmd_rollback(args)


if __name__ == "__main__":
    sys.exit(main())
