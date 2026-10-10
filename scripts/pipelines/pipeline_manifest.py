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
import re
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

# ── per-step environment (2026-10-10, operator "Yes" ~19:45 ET: fix the runner's whole-.env sourcing) ──────────
# A step must see exactly the environment its cron line had, never the runner's. Debian cron 3.0pl1 builds a
# job's environment from PAM (pam_env: /etc/environment, /etc/default/locale), then the cron defaults (HOME,
# LOGNAME, SHELL, PATH=/usr/bin:/bin) and the crontab's own NAME=value lines that PRECEDE the entry (vixie cron
# copies the environment at parse time, so an assignment applies only to the lines below it). Anything else a
# step needs (an inline VAR=..., `set -a; . ./.env`, a wrapper that sources a file) is in its verbatim command.
#: names cron itself gives every job on this host (values come from the runner's own cron-launched environment)
CRON_BASE_ENV = ("HOME", "LANG", "LOGNAME", "PATH", "SHELL")
#: variables bash adds by itself in both worlds (cron's /bin/bash -c and the runner's bash -c); never compared
SHELL_ADDED_ENV = ("PWD", "OLDPWD", "SHLVL", "_")
#: name prefixes that must never reach a step whose own cron line did not put them there (§0 rail 2)
BROKER_ENV_PREFIXES = ("ALPACA", "SCHWAB", "SNAPTRADE", "MOOMOO", "IBKR", "TASTY", "ROBINHOOD", "ETRADE", "TRADIER")
ENV_NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"

# Bounded concurrency (2026-10-10, premarket stage before C1 flip 4). A stage MAY carry
# `parallel: {"max_concurrency": N}`; then every step carries a `group` label. Groups run in manifest
# order with a barrier between them (group k+1 starts only after every step of group k ended); inside a
# group at most N steps run at once. A stage without `parallel` is serial exactly as before (each step is
# its own group, N = 1). Groups must be contiguous, and no two steps of one group may share a lock path
# (they would race for it and one would silently skip).
MAX_CONCURRENCY_CAP = 8
_LOCK_RE = re.compile(r"(?:\bflock\s+(?:-[A-Za-z]+\s+(?:\d+\s+)?)*|safe_flock\.sh\s+)(/\S+)")


def lock_paths(command: str) -> list[str]:
    """The flock / safe_flock lock files a step command takes (names only)."""
    return _LOCK_RE.findall(command or "")


def stage_concurrency(stage: dict) -> int:
    par = stage.get("parallel") if isinstance(stage, dict) else None
    if isinstance(par, dict) and isinstance(par.get("max_concurrency"), int):
        return par["max_concurrency"]
    return 1


def step_group(stage: dict, st: dict) -> str:
    return str(st.get("group") or st["id"]) if stage.get("parallel") else str(st["id"])
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
            errs.extend(f"{where}: {e}" for e in validate_env_spec(st.get("env")))
            dow = st.get("dow")
            if dow is not None and (not isinstance(dow, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in dow)):
                errs.append(f"{where}: dow must be a list of ints 0-6 (cron Sunday=0)")
        errs.extend(_validate_parallel(stage_name, stage, steps))
    return errs


def _validate_parallel(stage_name: str, stage: dict, steps: list) -> list[str]:
    par = stage.get("parallel")
    if par is None:
        return []
    where = f"stage {stage_name} parallel"
    if not isinstance(par, dict):
        return [f"{where}: must be an object"]
    n = par.get("max_concurrency")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_CONCURRENCY_CAP:
        return [f"{where}: max_concurrency must be an int 1-{MAX_CONCURRENCY_CAP}"]
    errs: list[str] = []
    order: list[str] = []
    locks: dict[str, dict[str, str]] = {}
    for st in steps:
        if not isinstance(st, dict):
            continue
        g = st.get("group")
        if not isinstance(g, str) or not g:
            errs.append(f"{where}: step {st.get('id')} has no group (every step needs one when parallel is set)")
            continue
        if order and order[-1] != g and g in order:
            errs.append(f"{where}: group {g} is not contiguous (step {st.get('id')})")
        if not order or order[-1] != g:
            order.append(g)
        for lk in lock_paths(str(st.get("command") or "")):
            other = locks.setdefault(g, {}).get(lk)
            if other:
                errs.append(f"{where}: group {g} steps {other} and {st.get('id')} share lock {lk}")
            locks[g][lk] = str(st.get("id"))
    return errs


def validate_env_spec(spec) -> list[str]:
    """Problems with a step's `env` block (None == absent, which the runner treats as the cron base only)."""
    import re
    if spec is None:
        return []
    if not isinstance(spec, dict) or spec.get("inherit") != "cron":
        return ["env must be an object with inherit: cron"]
    errs = []
    for key in ("cron_base", "crontab_vars", "inline", "sources", "wrappers"):
        v = spec.get(key, [])
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            errs.append(f"env.{key} must be a list of strings")
    for key in ("cron_base", "crontab_vars", "inline"):
        for n in spec.get(key) or []:
            if not re.match(ENV_NAME_RE, n):
                errs.append(f"env.{key}: bad name {n!r}")
    for n in (spec.get("crontab_vars") or []) + (spec.get("cron_base") or []):
        if any(n.upper().startswith(p) for p in BROKER_ENV_PREFIXES):
            errs.append(f"env passes broker name {n} from the runner; only the step's own command may source it")
    return errs


def step_env_names(st: dict) -> list[str]:
    """The names the runner hands a step (before bash adds SHELL_ADDED_ENV), in order."""
    # no env block: the cron base plus PROJ, which the runner's own `cd "$PROJ" && <command>` needs
    spec = st.get("env") or {"inherit": "cron", "cron_base": list(CRON_BASE_ENV), "crontab_vars": ["PROJ"]}
    out: list[str] = []
    for n in list(spec.get("cron_base") or []) + list(spec.get("crontab_vars") or []):
        if n not in out:
            out.append(n)
    return out


def stage_steps(manifest: dict, stage: str) -> list[dict]:
    stages = manifest.get("stages") or {}
    if stage not in stages:
        raise KeyError(f"stage {stage!r} not in manifest (have: {', '.join(stages)})")
    return list(stages[stage].get("steps") or [])


def plan_records(manifest: dict, stage: str) -> list[str]:
    """One SEP-delimited record per step: id, cron_line, timeout_s, dow-csv, log, group, env-names-csv, command."""
    spec = (manifest.get("stages") or {}).get(stage) or {}
    out = []
    for st in stage_steps(manifest, stage):
        dow = ",".join(str(d) for d in st["dow"]) if st.get("dow") else "*"
        out.append(SEP.join([
            str(st["id"]), str(st["cron_line"]), str(timeout_seconds(st["timeout"])), dow,
            str(st.get("log") or ""), step_group(spec, st), ",".join(step_env_names(st)),
            str(st["command"]).replace("\n", " "),
        ]))
    return out


def _p95(st: dict) -> tuple[float, bool]:
    me = st.get("measured") or {}
    v = me.get("p95_s")
    if isinstance(v, (int, float)):
        return float(v), bool(me.get("verified"))
    v = me.get("upper_bound_p95_s")
    if isinstance(v, (int, float)):
        return float(v), False
    return float(timeout_seconds(st.get("timeout", "0"))), False


def wave_plan(manifest: dict, stage: str, today_dow: int | None = None) -> dict:
    """Groups in run order with each group's p95 makespan under the stage's concurrency (greedy list
    scheduling, manifest order), the critical path (sum of group makespans) and the serial sum.
    p95 is the measured value, else the design's upper bound, else the step timeout."""
    spec = (manifest.get("stages") or {}).get(stage) or {}
    n = stage_concurrency(spec)
    groups: list[dict] = []
    serial = 0.0
    for st in stage_steps(manifest, stage):
        if today_dow is not None and st.get("dow") and today_dow not in st["dow"]:
            continue
        p, verified = _p95(st)
        serial += p
        g = step_group(spec, st)
        if not groups or groups[-1]["group"] != g:
            groups.append({"group": g, "steps": []})
        groups[-1]["steps"].append({"id": st["id"], "p95_s": p, "verified": verified})
    for g in groups:
        lanes = [0.0] * n
        for s in g["steps"]:
            i = lanes.index(min(lanes))
            lanes[i] += s["p95_s"]
        g["makespan_p95_s"] = round(max(lanes), 1)
    cp = round(sum(g["makespan_p95_s"] for g in groups), 1)
    return {"stage": stage, "max_concurrency": n, "groups": groups, "critical_path_p95_s": cp,
            "serial_p95_s": round(serial, 1)}


def format_wave_plan(plan: dict) -> list[str]:
    out = [f"[waves] stage={plan['stage']} max_concurrency={plan['max_concurrency']} groups={len(plan['groups'])} "
           f"critical_path_p95={plan['critical_path_p95_s']}s serial_p95={plan['serial_p95_s']}s"]
    for k, g in enumerate(plan["groups"], 1):
        ids = ", ".join(f"{s['id']}({s['p95_s']:g}{'' if s['verified'] else '≤'})" for s in g["steps"])
        out.append(f"[waves]  {k:2d}. {g['group']:<8} {g['makespan_p95_s']:>7}s  {ids}")
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
    sub.add_argument("--concurrency", metavar="STAGE", help="print the stage's max_concurrency (1 = serial)")
    sub.add_argument("--waves", metavar="STAGE", help="print the group/wave plan and p95 critical path")
    ap.add_argument("--dow", type=int, default=None, help="--waves: drop steps whose dow excludes this day")
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
    if args.concurrency is not None or args.waves is not None:
        stage = args.concurrency if args.concurrency is not None else args.waves
        if stage not in (manifest.get("stages") or {}):
            print(f"[manifest] stage {stage!r} not in manifest", file=sys.stderr)
            return 2
        if args.concurrency is not None:
            print(stage_concurrency(manifest["stages"][stage]))
        else:
            print("\n".join(format_wave_plan(wave_plan(manifest, stage, args.dow))))
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
