"""n8n lane remediation catalogue (REMEDIATION_PLAN §6 R2; operator decision 4, 2026-10-09 23:38 ET).

The LLM failure diagnoser (scripts/n8n_failure_diagnosis.py) may only CHOOSE an ``action_id`` from the failing
lane's row in ``config/n8n_remediation_catalogue.json``. This module builds that file from the verified cron
inventory (``inventory_base.csv`` + ``enrich_S*.csv``), the lane registry and the run allowlist, and validates it.
It never executes anything: execution lives in the diagnoser's deterministic handlers, which accept only the
handler names in ``HANDLERS``.

Allowed actions are drawn ONLY from safe, idempotent operations that already exist:

* ``rerun_dry_run``        one run request, mode ``dry_run``, through the gateway's ``coordination/run`` path
                           (``n8n_coordination_gateway.host_run_request``: same validation, same RunRequested row as
                           n8n gets — never a direct ledger insert). The executor runs the lane's own allowlist argv
                           under the lane's own lock and clamps the mode to the lane's stage (§23.11); nothing here
                           spawns.
* ``rerun_dry_then_live``  the same, ``dry_run`` first; a ``live`` request only after that dry run is ``RUN_DONE``.
                           Only for lanes whose registry row is at ``scheduler.stage == "cutover"`` (operator "Ok"
                           2026-10-10 ~00:35 ET): a shadow/canary lane, or one with no stage, never gets a live rerun
                           from the diagnoser — the diagnoser re-checks the stage at request time and the executor's
                           stage clamp runs a shadow lane dry whatever was requested.
* ``reap_orphan_run``      a RUNNING row with no live owner, overdue by 2x its timeout, finishes ``RUN_TIMEOUT``
                           ``executor_lost`` through ``LedgerRunStore.finish`` — the executor v2 reaper's own receipt
                           shape (``n8n_run_executor.ExecutorV2.reap``); the installed v1 executor has no reaper.

Everything else is ``suggest_only``: written to the SIEM row and escalated for a human. Never in the catalogue:
broker/order/stop/secret actions, sends, deletes, crontab/systemd edits, unit restarts, DLQ releases.

Not offered, with the reason recorded in the file: clearing a stale lock. ``scripts/cleanup_stale_locks.sh`` is
report-only since 2026-10-09 (audit B_self_healing #7): flock(2) locks never block once their holder is gone, and
deleting the path opened a real double-run race.

Severity is PROPOSED from the inventory (no severity column exists there, V9 G4) by the rule in
``proposed_severity``; the operator reviews the generated file before activation (decision 4).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "N8nRemediationCatalogue@v1"
ENTRY_SCHEMA = "N8nLaneRemediation@v1"
SUGGEST_ONLY = "suggest_only"
SEVERITIES = ("Critical", "High", "Medium", "Low")
AUTO_SEVERITIES = frozenset({"Medium", "Low"})          # V9 §6.4: Critical/High -> human approval, never an action
HANDLERS = frozenset({"ledger_request_run", "ledger_reap_orphan"})
ACTION_IDS = ("rerun_dry_run", "rerun_dry_then_live", "reap_orphan_run")
MAX_PER_INCIDENT = 1
MAX_PER_LANE_PER_DAY = 3
ORPHAN_TIMEOUT_FACTOR = 2.0
#: The installed executor runs one worker (V9 M11): an automatic rerun may hold it at most this long
#: (V8 W1: a 300 s dry-run timeout delayed three live lanes by 4m42s). Longer lanes need a human.
MAX_AUTO_TIMEOUT_S = 600
SELFTEST_LANE = "n8n-selftest-fail"
DIAGNOSIS_LANE = "n8n-failure-diagnosis"

# Mirrors tests/test_agents_policy_4_1_0_amendment.py (§23.14 dispatcher eligibility); the gateway and pipeline
# manifest token lists are imported, these three are the test's own literals.
DAEMON_TOKENS = ("--daemon", "--loop", "--forever", "--watch", "--serve")
SECRET_TOKENS = ("render_env", "sm-render", "sm_render", "secrets/", "rotation_daemon", "bws ", "bitwarden")
SENDER_TOKENS = ("send_telegram", "telegram", "notify", "--send", "email", "gog ")
#: §23.14 + V9 §6.3: the never-list lanes and the single 4.0.0 live exception get escalate only.
NEVER_LANES = frozenset({"trade-ai-scalp-live"})

#: business_function (enrich_S*.csv) -> proposed severity before the overrides in proposed_severity().
FUNCTION_SEVERITY = {
    "alerts-ops": "Critical",          # REMEDIATION_PLAN §5: "alert/notification paths dead" is Critical
    "trading-adjacent": "Critical",    # broker-, stop- or order-adjacent
    "portfolio data": "High",          # holdings/positions sync, operator-facing
    "reporting": "High",               # briefs and reports, operator-facing
    "research": "Medium",              # research / enrichment / ingest
    "governance": "Medium",
    "monitoring": "Low",
    "maintenance": "Low",
    "other": "Low",
}
RISK_FLOOR = {"High": "High", "Medium": "Medium"}       # migration_risk raises (never lowers) the function severity
_RANK = {s: i for i, s in enumerate(SEVERITIES)}

LOCK_CLEAR_NOTE = (
    "clear_stale_lock is not offered: scripts/cleanup_stale_locks.sh is report-only since 2026-10-09 (audit "
    "B_self_healing #7) — flock(2) files never block once the holder exits, and deleting the path opened a "
    "double-run race. A lock problem is a suggestion for a human."
)


# ---------------------------------------------------------------- inventory


def load_inventory(inventory_dir: Path) -> dict[str, dict[str, str]]:
    """inv_id -> merged row (inventory_base.csv overlaid with the enrich_S*.csv judgement columns)."""
    inventory_dir = Path(inventory_dir)
    with (inventory_dir / "inventory_base.csv").open(encoding="utf-8", newline="") as fh:
        rows = {r["inv_id"]: dict(r) for r in csv.DictReader(fh)}
    for path in sorted(inventory_dir.glob("enrich_S*.csv")):
        with path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("inv_id") in rows:
                    rows[r["inv_id"]].update({k: v for k, v in r.items() if v not in (None, "")})
    return rows


def critical_path_ids(inventory_dir: Path) -> dict[str, str]:
    """inv_id -> critical path name (analysis/critical_paths.csv); empty when the file is absent."""
    p = Path(inventory_dir) / "analysis" / "critical_paths.csv"
    try:
        with p.open(encoding="utf-8", newline="") as fh:
            return {r["inv_id"]: str(r.get("path") or "") for r in csv.DictReader(fh) if r.get("inv_id")}
    except OSError:
        return {}


def wave1_inv_ids(inventory_dir: Path) -> list[str]:
    p = Path(inventory_dir) / "refactor_wave1.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[str] = []
    for bucket in sorted(doc):
        out.extend(str(i) for i in (doc[bucket] or {}).get("inv_ids") or [])
    return out


def target_lanes(inventory: Mapping[str, Mapping[str, str]], allowlist_lanes: Iterable[str],
                 wave1: Iterable[str]) -> dict[str, list[str]]:
    """lane_id -> inv_ids. Scope (task): lanes n8n runs today (active n8n workflow rows + every run-allowlist lane,
    since n8n can request any of them) plus the refactor wave-1 lanes, plus the self-test lane."""
    lanes: dict[str, list[str]] = {}
    by_job: dict[str, list[str]] = {}
    for inv_id, r in inventory.items():
        by_job.setdefault(r.get("job_name") or "", []).append(inv_id)
    for inv_id, r in inventory.items():
        if r.get("source") == "n8n" and r.get("active") == "yes" and r.get("job_name"):
            lanes.setdefault(r["job_name"], [])
    for lane in allowlist_lanes:
        lanes.setdefault(lane, [])
    for inv_id in wave1:
        r = inventory.get(inv_id)
        if r and r.get("job_name"):
            lanes.setdefault(r["job_name"], [])
    for lane in lanes:
        lanes[lane] = sorted(by_job.get(lane, []))
    lanes.setdefault(SELFTEST_LANE, [])
    return dict(sorted(lanes.items()))


# ---------------------------------------------------------------- judgement


def proposed_severity(rows: list[Mapping[str, str]], critical_ids: Mapping[str, str], lane_id: str) -> tuple[str, str]:
    """(severity, basis). Most severe of: business_function map, migration_risk floor, critical-path membership."""
    if lane_id == SELFTEST_LANE:
        # Medium (SIEM WARN) on purpose: the scheduled diagnoser's default floor is WARN, so an R6 run proves the
        # scheduled path, not a hand run with --min-severity INFO. Still an auto-remediation severity.
        return "Medium", "selftest lane (harmless, fails on demand); WARN so the scheduled diagnoser sees it"
    best, basis = "Low", "default Low (no inventory row)"
    active = [r for r in rows if r.get("active") == "yes"] or list(rows)   # retired rows do not set severity
    for r in active:
        fn = (r.get("business_function") or "").strip()
        sev = FUNCTION_SEVERITY.get(fn, "Low")
        why = f"business_function={fn or 'UNKNOWN'}"
        floor = RISK_FLOOR.get((r.get("migration_risk") or "").strip())
        if floor and _RANK[floor] < _RANK[sev]:
            sev, why = floor, f"{why}; migration_risk={r.get('migration_risk')}"
        path = critical_ids.get(str(r.get("inv_id")))
        if path is not None:
            # REMEDIATION_PLAN §5 routing: the pre-open critical paths CP1/CP2 are Critical; the others raise to High.
            floor = "Critical" if path.startswith(("CP1", "CP2")) else "High"
            if _RANK[floor] < _RANK[sev]:
                sev = floor
            why = f"{why}; critical path {path.split(' ', 1)[0] or '?'} -> {floor}"
        if _RANK[sev] < _RANK[best] or basis.startswith("default"):
            best, basis = sev, f"{r.get('inv_id')}: {why}"
    return best, basis


def argv_problem(entry: Mapping[str, Any]) -> Optional[str]:
    """§23.14 token test over the full argv (command + dry + live args); None when clean."""
    from scripts.lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS
    from scripts.pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS

    argv = [str(t) for t in (*entry.get("command", []), *(entry.get("dry_run_arg") or []),
                             *(entry.get("live_arg") or []))]
    if not argv:
        return "no command"
    for tok in argv:
        if tok in DAEMON_TOKENS:
            return f"daemon flag {tok}"
        for forbidden in FORBIDDEN_COMMAND_TOKENS:
            if forbidden in tok:
                return f"FORBIDDEN_COMMAND_TOKENS {forbidden}"
        low = tok.strip().lower()
        for t in (t for t in re.split(r"[^a-z0-9]+", low) if t):
            if t in FORBIDDEN_ROUTE_TOKENS:
                return f"FORBIDDEN_ROUTE_TOKENS {t}"
        collapsed = low.replace("-", "").replace("/", "")
        for t in FORBIDDEN_ROUTE_TOKENS:
            if t in collapsed and t != "title":
                return f"FORBIDDEN_ROUTE_TOKENS {t}"
        for s in SECRET_TOKENS:
            if s.strip() in low:
                return f"secret token {s.strip()}"
    joined = " ".join(argv).lower()
    for s in SENDER_TOKENS:
        if s in joined:
            return f"sender token {s.strip()}"
    return None


def _argv(entry: Mapping[str, Any], mode: str) -> Optional[list[str]]:
    extra = entry.get("dry_run_arg" if mode == "dry_run" else "live_arg")
    if extra is None:
        return None
    return [str(t) for t in (*entry.get("command", []), *extra)]


def _known_issues(rows: list[Mapping[str, str]]) -> list[dict[str, str]]:
    out = []
    for r in rows:
        ki = (r.get("known_issues") or "").strip()
        cw = (r.get("custom_work_required") or "").strip()
        if ki or cw:
            out.append({"inv_id": r.get("inv_id", ""), "known_issues": ki[:600], "custom_work_required": cw[:400]})
    return out


def build_entry(lane_id: str, inv_rows: list[Mapping[str, str]], *, allow: Optional[Mapping[str, Any]],
                registry_row: Optional[Mapping[str, Any]], critical_ids: Mapping[str, str],
                selftest_entry: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """One N8nLaneRemediation@v1 row. Pure."""
    severity, basis = proposed_severity(list(inv_rows), critical_ids, lane_id)
    sched = (registry_row or {}).get("scheduler") or {}
    allowlisted = allow is not None
    allow_source = "config/n8n_run_allowlist.json" if allowlisted else None
    if allow is None and selftest_entry is not None:
        allow, allow_source = selftest_entry, "PROPOSED (llm-remediation/PROPOSED_ROWS.md; not yet in the allowlist)"
    entry: dict[str, Any] = {
        "schema": ENTRY_SCHEMA, "lane_id": lane_id, "severity": severity, "severity_basis": basis,
        "inv_ids": [r.get("inv_id") for r in inv_rows],
        "classification": sorted({(r.get("classification") or "UNKNOWN") for r in inv_rows}) or ["UNKNOWN"],
        "migration_risk": sorted({(r.get("migration_risk") or "UNKNOWN") for r in inv_rows}) or ["UNKNOWN"],
        "known_issues": _known_issues(list(inv_rows)),
        "registry": {"present": registry_row is not None, "state": (registry_row or {}).get("state"),
                     "scheduler_kind": sched.get("kind"), "stage": sched.get("stage")},
        "allowlisted": allowlisted, "allowlist_source": allow_source,
        "actions": [], "default_action": SUGGEST_ONLY, "suggest_only_reason": None,
    }
    outside = " ".join((r.get("must_remain_outside_n8n") or "") for r in inv_rows).strip().lower()
    if lane_id in NEVER_LANES:
        entry["suggest_only_reason"] = "§23.14 never-list / 4.0.0 named exception: escalate only (V9 §6.3)"
        return entry
    if allow is None:
        entry["suggest_only_reason"] = ("no config/n8n_run_allowlist.json entry: the executor cannot run it; "
                                        "regenerate after its allowlist PR")
        return entry
    problem = argv_problem(allow)
    if problem:
        entry["suggest_only_reason"] = f"argv fails the §23.14 token test: {problem}"
        return entry
    if outside.startswith("yes"):
        entry["suggest_only_reason"] = "inventory must_remain_outside_n8n=yes"
        return entry
    auto = severity in AUTO_SEVERITIES
    approval = None if auto else f"severity {severity}: human approval (V9 §6.4)"
    if auto and float(allow.get("timeout_s") or 0) > MAX_AUTO_TIMEOUT_S:
        auto = False
        approval = (f"timeout_s {allow.get('timeout_s')} > {MAX_AUTO_TIMEOUT_S}: a rerun would hold the single "
                    "executor worker; human approval")
    common = {"lock": allow.get("lock"), "timeout_s": allow.get("timeout_s"),
              "output_signal": allow.get("output_signal"),
              "max_per_incident": MAX_PER_INCIDENT, "max_per_lane_per_day": MAX_PER_LANE_PER_DAY}
    dry = _argv(allow, "dry_run")
    live = _argv(allow, "live")
    if dry is not None:
        entry["actions"].append({
            "action_id": "rerun_dry_run", "handler": "ledger_request_run", "mode_sequence": ["dry_run"],
            "argv": {"dry_run": dry}, "auto": auto, "approval_reason": approval,
            "via": "coordination/run (host_run_request, mode=dry_run) -> tradeai-n8n-run-executor runs the allowlist argv under the lane lock, stage-clamped",
            "preconditions": ["lane in config/n8n_run_allowlist.json with dry_run_arg", "no REQUESTED/RUNNING row for the lane",
                              "per-incident and per-lane-day caps not reached"],
            **common,
        })
    cut_over = sched.get("stage") == "cutover" and (registry_row or {}).get("state") == "ACTIVE"
    if dry is not None and live is not None and cut_over:
        entry["actions"].append({
            "action_id": "rerun_dry_then_live", "handler": "ledger_request_run", "mode_sequence": ["dry_run", "live"],
            "argv": {"dry_run": dry, "live": live}, "auto": auto, "approval_reason": approval,
            "via": "coordination/run dry_run request; live request only after that run is RUN_DONE and only while the "
                   "registry stage is cutover; executor runs the allowlist argv, stage-clamped",
            "preconditions": ["registry scheduler.stage == cutover and state ACTIVE (re-checked at request time)",
                              "dry_run phase RUN_DONE", "no REQUESTED/RUNNING row for the lane",
                              "per-incident and per-lane-day caps not reached"],
            **common,
        })
    entry["actions"].append({
        "action_id": "reap_orphan_run", "handler": "ledger_reap_orphan", "mode_sequence": [],
        "argv": {}, "auto": True, "approval_reason": None,
        "via": "LedgerRunStore.finish(run_id, state=RUN_TIMEOUT, receipt.reason=executor_lost) — the executor v2 reaper's receipt",
        "preconditions": [f"row RUNNING and started_at + {ORPHAN_TIMEOUT_FACTOR:g} x timeout_s < now",
                          "heartbeat_at older than timeout_s (or absent)", "row pid not alive on this host"],
        **common,
    })
    if not any(a["auto"] for a in entry["actions"] if a["action_id"] != "reap_orphan_run"):
        entry["suggest_only_reason"] = approval or "no dry_run_arg: a rerun cannot be proven dry first"
    return entry


def build_catalogue(*, inventory_dir: Path, registry: Mapping[str, Any], allowlist: Mapping[str, Any],
                    as_of: str, selftest_entry: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    inventory = load_inventory(inventory_dir)
    crit = critical_path_ids(inventory_dir)
    allow = {str(x.get("lane_id")): x for x in allowlist.get("lanes") or []}
    reg = {str(r.get("lane_id")): r for r in registry.get("lanes") or []}
    lanes = target_lanes(inventory, allow, wave1_inv_ids(inventory_dir))
    entries = []
    for lane_id, inv_ids in lanes.items():
        entries.append(build_entry(lane_id, [inventory[i] for i in inv_ids], allow=allow.get(lane_id),
                                   registry_row=reg.get(lane_id), critical_ids=crit,
                                   selftest_entry=selftest_entry if lane_id == SELFTEST_LANE else None))
    src = Path(inventory_dir)
    digests = {}
    for name in ["inventory_base.csv", *sorted(p.name for p in src.glob("enrich_S*.csv")), "refactor_wave1.json"]:
        try:
            digests[name] = hashlib.sha256((src / name).read_bytes()).hexdigest()[:16]
        except OSError:
            digests[name] = "MISSING"
    return {
        "schema": SCHEMA, "as_of": as_of, "status": "PROPOSED — operator review before activation (decision 4)",
        "generated_by": "scripts/build_remediation_catalogue.py",
        "sources": {"inventory_dir": str(src).replace(str(Path.home()), "~", 1), "sha256_16": digests},
        "rules": {
            "action_ids": list(ACTION_IDS), "default_action": SUGGEST_ONLY, "handlers": sorted(HANDLERS),
            "auto_severities": sorted(AUTO_SEVERITIES), "max_per_incident": MAX_PER_INCIDENT,
            "max_per_lane_per_day": MAX_PER_LANE_PER_DAY, "orphan_timeout_factor": ORPHAN_TIMEOUT_FACTOR,
            "max_auto_timeout_s": MAX_AUTO_TIMEOUT_S,
            "never": "broker/order/stop/secret actions, sends, deletes, crontab/systemd edits, unit restarts, DLQ releases",
            "not_offered": LOCK_CLEAR_NOTE,
            "severity_rule": "most severe over the lane's active inventory rows of FUNCTION_SEVERITY[business_function], the migration_risk floor (High/Medium) and critical-path membership (CP1/CP2 Critical, CP3/CP4 High)",
            "function_severity": dict(FUNCTION_SEVERITY),
        },
        "summary": summarise(entries),
        "lanes": entries,
    }


def summarise(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    n_actions = sum(len(e.get("actions") or []) for e in entries)
    suggest = [e["lane_id"] for e in entries if not any(a.get("auto") for a in e.get("actions") or []
                                                        if a.get("action_id") != "reap_orphan_run")]
    by_sev: dict[str, int] = {}
    for e in entries:
        by_sev[e["severity"]] = by_sev.get(e["severity"], 0) + 1
    return {"lanes": len(entries), "actions": n_actions,
            "lanes_with_auto_rerun": len(entries) - len(suggest), "lanes_suggest_only": len(suggest),
            "by_severity": dict(sorted(by_sev.items(), key=lambda kv: _RANK.get(kv[0], 9)))}


# ---------------------------------------------------------------- consumer side


def validate_catalogue(doc: Mapping[str, Any]) -> list[str]:
    errs: list[str] = []
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema {doc.get('schema')!r} != {SCHEMA}")
    seen = set()
    for e in doc.get("lanes") or []:
        lane = e.get("lane_id")
        if not lane or lane in seen:
            errs.append(f"lane_id missing or duplicate: {lane!r}")
        seen.add(lane)
        if e.get("severity") not in SEVERITIES:
            errs.append(f"{lane}: severity {e.get('severity')!r}")
        if e.get("default_action") != SUGGEST_ONLY:
            errs.append(f"{lane}: default_action must be {SUGGEST_ONLY}")
        ids = set()
        for a in e.get("actions") or []:
            aid = a.get("action_id")
            if aid not in ACTION_IDS or aid in ids:
                errs.append(f"{lane}: action_id {aid!r} unknown or duplicate")
            ids.add(aid)
            if a.get("handler") not in HANDLERS:
                errs.append(f"{lane}/{aid}: handler {a.get('handler')!r} not in HANDLERS")
            if aid != "reap_orphan_run" and lane in NEVER_LANES:
                errs.append(f"{lane}: never-list lane carries {aid}")
            if aid == "rerun_dry_then_live" and (e.get("registry") or {}).get("stage") != "cutover":
                errs.append(f"{lane}: rerun_dry_then_live needs registry stage cutover")
            for mode, argv in (a.get("argv") or {}).items():
                if mode not in ("dry_run", "live") or not isinstance(argv, list):
                    errs.append(f"{lane}/{aid}: argv[{mode}] malformed")
                elif argv_problem({"command": argv}):
                    errs.append(f"{lane}/{aid}: argv[{mode}] fails the token test")
            if a.get("auto") and e.get("severity") not in AUTO_SEVERITIES and aid != "reap_orphan_run":
                errs.append(f"{lane}/{aid}: auto on a {e.get('severity')} lane")
    return errs


def load_catalogue(path: Path) -> dict[str, dict[str, Any]]:
    """lane_id -> entry; raises ValueError on an invalid file (the diagnoser then executes nothing)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = validate_catalogue(doc)
    if errs:
        raise ValueError("; ".join(errs[:5]))
    return {str(e["lane_id"]): e for e in doc.get("lanes") or []}


def lane_action(entry: Optional[Mapping[str, Any]], action_id: str) -> Optional[dict[str, Any]]:
    """The catalogue action for a lane, or None (unknown lane, unknown action, or suggest_only)."""
    if not entry or action_id == SUGGEST_ONLY:
        return None
    for a in entry.get("actions") or []:
        if a.get("action_id") == action_id:
            return dict(a)
    return None
