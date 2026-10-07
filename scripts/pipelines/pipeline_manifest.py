#!/usr/bin/env python3
"""pipeline_manifest.py — read, validate and plan a cron-consolidation pipeline manifest.

Cron tranche B (2026-10-07, ranks 5-7 of docs/implementation/n8n-parallel/13-cron-consolidation).
A manifest (`config/pipelines/<name>.json`, schema `PipelineManifest@v1`) lists, per stage, the
crontab lines a serial runner absorbs — each step's `command` is the VERBATIM cron command (its
own flock / safe_flock / timeout / env / LLM wrapper kept inside the step). The bash runners in
this directory call this module for three things only:

    --plan      print one record per runnable step (unit-separator delimited) for the stage
    --validate  structural check of a manifest (exit 1 on any problem)
    --summary   write the `PipelineRun@v1` summary JSON from the runner's step-result file

Nothing here executes a step. The runner executes nothing without `--apply` AND a non-empty
stage plan; `--dry-run` is its default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

NO_CONSUMER_REASON = (
    "PipelineManifest@v1 / PipelineRun@v1 / PipelineStepReceipt@v1 are consumed by the bash "
    "runners scripts/pipelines/run_after_close_pipeline.sh, run_premarket_data_pipeline.sh and "
    "run_hermes_pipeline.sh (via _manifest_runner.sh), which are NEVER_SCHEDULED skeletons until "
    "the tranche B install sequence (docs/implementation/n8n-parallel/proposals/"
    "cron-tranche-b-design.md) is approved. No Python module imports these schemas by design."
)

MANIFEST_SCHEMA = "PipelineManifest@v1"
RUN_SCHEMA = "PipelineRun@v1"
STEP_RECEIPT_SCHEMA = "PipelineStepReceipt@v1"
STEP_STATUSES = ("dry_run", "ok", "failed", "timeout", "skipped_dow", "skipped_lock")
SEP = "\x1f"

# Tokens that must never appear inside an absorbed step: broker/stop/order lines and the
# staggered broker syncs stay as their own cron lines (AGENTS.md §0 rails 1-2; study §5).
FORBIDDEN_COMMAND_TOKENS = (
    "market_day_gate.sh",
    "schwab_position_sync.py",
    "positions_sync.py",
    "schwab_transaction_ingest.py",
    "snaptrade_sync.py",
    "snaptrade_activity_ingest.py",
    "alpaca_live_read_sync",
    "moomoo",
    "place_order",
    "broker_stop_reconcile.py",
    "unified_stop_supervisor",
    "stop_drift_alert",
    "sync_basis_from_broker.py",
    "atm_position_reconciler.py",
    "holding_protection_advisor.py",
    "holdings_gain_guardian.py",
    "options_chain_snapshot.py",
    "schwab_econfirm_reconcile.py",
)

# The runner never wraps a stage in one of these; a step that needs one keeps it VERBATIM.
LLM_WRAPPERS = ("run_with_deepseek_offpeak.sh", "llm_priority_guard.sh")

REQUIRED_STEP_KEYS = ("id", "cron_line", "command", "timeout")
TIMEOUT_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}


def load(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def timeout_seconds(value: str | int) -> int:
    s = str(value).strip()
    unit = s[-1] if s and s[-1] in TIMEOUT_UNITS else ""
    num = s[:-1] if unit else s
    if not num.isdigit():
        raise ValueError(f"bad timeout {value!r}")
    return int(num) * TIMEOUT_UNITS[unit]


def validate(manifest: dict) -> list[str]:
    """Return a list of problems (empty == valid)."""
    errs: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errs.append(f"schema must be {MANIFEST_SCHEMA}")
    if not isinstance(manifest.get("pipeline"), str) or not manifest.get("pipeline"):
        errs.append("pipeline name missing")
    stages = manifest.get("stages")
    if not isinstance(stages, dict) or not stages:
        errs.append("stages must be a non-empty object")
        return errs
    seen_ids: set[str] = set()
    for stage_name, stage in stages.items():
        if not isinstance(stage, dict):
            errs.append(f"stage {stage_name}: not an object")
            continue
        steps = stage.get("steps")
        if not isinstance(steps, list):
            errs.append(f"stage {stage_name}: steps must be a list")
            continue
        for i, st in enumerate(steps):
            where = f"stage {stage_name} step[{i}]"
            if not isinstance(st, dict):
                errs.append(f"{where}: not an object")
                continue
            for k in REQUIRED_STEP_KEYS:
                if k not in st:
                    errs.append(f"{where}: missing {k}")
            sid = str(st.get("id", ""))
            if not sid or not all(c.isalnum() or c in "_-" for c in sid):
                errs.append(f"{where}: id must be [A-Za-z0-9_-]+")
            if sid in seen_ids:
                errs.append(f"{where}: duplicate id {sid}")
            seen_ids.add(sid)
            if not isinstance(st.get("cron_line"), int):
                errs.append(f"{where}: cron_line must be an int (crontab line number)")
            cmd = st.get("command")
            if not isinstance(cmd, str) or not cmd.strip():
                errs.append(f"{where}: command must be a non-empty string")
            else:
                for tok in FORBIDDEN_COMMAND_TOKENS:
                    if tok in cmd:
                        errs.append(f"{where}: command contains excluded token {tok}")
                verbatim = st.get("cron_line_verbatim")
                if isinstance(verbatim, str) and cmd.strip() not in verbatim:
                    errs.append(f"{where}: command is not a verbatim slice of cron_line_verbatim")
            try:
                timeout_seconds(st.get("timeout", ""))
            except ValueError as e:
                errs.append(f"{where}: {e}")
            dow = st.get("dow")
            if dow is not None and (not isinstance(dow, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in dow)):
                errs.append(f"{where}: dow must be a list of ints 0-6 (cron Sunday=0)")
    return errs


def stage_steps(manifest: dict, stage: str) -> list[dict]:
    stages = manifest.get("stages") or {}
    if stage not in stages:
        raise KeyError(f"stage {stage!r} not in manifest (have: {', '.join(stages)})")
    return list(stages[stage].get("steps") or [])


def plan_records(manifest: dict, stage: str) -> list[str]:
    """One SEP-delimited record per step: id, cron_line, timeout_s, dow-csv, log, command."""
    out = []
    for st in stage_steps(manifest, stage):
        dow = ",".join(str(d) for d in st["dow"]) if st.get("dow") else "*"
        out.append(SEP.join([
            str(st["id"]), str(st["cron_line"]), str(timeout_seconds(st["timeout"])), dow,
            str(st.get("log") or ""), str(st["command"]).replace("\n", " "),
        ]))
    return out


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_summary(manifest_path: str, stage: str, results_path: str, out_path: str, *,
                  dry_run: bool, started_at: str, log_path: str, apply_requested: bool) -> dict:
    manifest = load(manifest_path)
    steps = []
    if Path(results_path).exists():
        for line in Path(results_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                steps.append(json.loads(line))
    statuses = {s.get("status") for s in steps}
    if not steps:
        overall = "empty"
    elif dry_run:
        overall = "dry_run"
    elif statuses & {"failed", "timeout"}:
        overall = "degraded"
    else:
        overall = "ok"
    summary = {
        "schema": RUN_SCHEMA,
        "pipeline": manifest.get("pipeline"),
        "stage": stage,
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_of(manifest_path),
        "run_ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at": started_at,
        "dry_run": bool(dry_run),
        "apply_requested": bool(apply_requested),
        "executed_any": any(s.get("status") in ("ok", "failed", "timeout") for s in steps),
        "overall_status": overall,
        "step_count": len(steps),
        "steps": steps,
        "log": log_path,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(out_path).with_suffix(".tmp")
    tmp.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out_path)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest")
    sub = ap.add_mutually_exclusive_group(required=True)
    sub.add_argument("--plan", metavar="STAGE")
    sub.add_argument("--validate", action="store_true")
    sub.add_argument("--summary", metavar="STAGE")
    ap.add_argument("--results", help="--summary: step results jsonl written by the runner")
    ap.add_argument("--out", help="--summary: PipelineRun@v1 path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply-requested", action="store_true")
    ap.add_argument("--started-at", default="")
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)

    try:
        manifest = load(args.manifest)
    except Exception as e:  # unreadable manifest is a hard stop, never a silent empty plan
        print(f"[manifest] cannot read {args.manifest}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    errs = validate(manifest)
    if args.validate:
        for e in errs:
            print(f"[manifest] INVALID: {e}")
        if not errs:
            stages = manifest.get("stages") or {}
            total = sum(len(s.get("steps") or []) for s in stages.values())
            print(f"[manifest] OK {manifest.get('pipeline')} stages={len(stages)} steps={total}")
        return 1 if errs else 0
    if errs:
        for e in errs:
            print(f"[manifest] INVALID: {e}", file=sys.stderr)
        return 2
    if args.plan is not None:
        try:
            for rec in plan_records(manifest, args.plan):
                print(rec)
        except KeyError as e:
            print(f"[manifest] {e}", file=sys.stderr)
            return 2
        return 0
    if args.summary is not None:
        if not args.results or not args.out:
            print("[manifest] --summary needs --results and --out", file=sys.stderr)
            return 2
        write_summary(args.manifest, args.summary, args.results, args.out, dry_run=args.dry_run,
                      started_at=args.started_at, log_path=args.log, apply_requested=args.apply_requested)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
