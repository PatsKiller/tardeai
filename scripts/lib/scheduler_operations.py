"""Read-only SchedulerOperations@v1 projection of intent, host observations and receipts.

Consumer: GET /api/v2/scheduler-operations and the Command Center coordination route.
Discovery denial is unknown, shadow receipts never prove a business run, and a
fresh output cannot erase a failed run. No scheduler, credential or broker writes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.lib import cron_last_fire, lane_registry

SCHEMA = "SchedulerOperations@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
ROOT = Path(__file__).resolve().parents[2]
RECEIPT_KEYS = (
    "schema",
    "run_id",
    "lane_id",
    "mode",
    "state",
    "reason",
    "exit_code",
    "duration_s",
    "lock_skipped",
    "timed_out",
    "output_signal",
    "output_signal_mtime_before",
    "output_signal_mtime_after",
    "started_at",
    "finished_at",
    "code_sha",
    "code_root",
)
UNIT_PROPS = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "FragmentPath",
    "WorkingDirectory",
    "ExecStart",
    "Result",
    "ExecMainStatus",
    "MainPID",
    "ExecMainStartTimestamp",
    "ExecMainExitTimestamp",
    "NextElapseUSecRealtime",
    "TimersCalendar",
    "TimersMonotonic",
)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp(value: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError, ValueError):
        return None


def redact_command(value: str) -> str:
    # Only scheduling metadata is needed; never carry inline credentials or destinations.
    value = re.sub(
        r'(?i)(\b[\w]*(?:TOKEN|PASSWORD|SECRET|BEARER|API_KEY|HMAC_KEY|CREDENTIAL)[\w]*\s*=\s*)("[^"]*"|\x27[^\x27]*\x27|[^\s;]+)',
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r'(?i)(Bearer\s+)[^\s"\x27]+', r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(--(?:password|token|key|chat-id|account-id|account-number)[=\s]+)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(https?://)[^/@\s:]+:[^/@\s]+@", r"\1[REDACTED]@", value)
    return value


def parse_crontab(text: str, *, default_timezone: str | None = None) -> list[dict[str, Any]]:
    entries = []
    tz = default_timezone
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        env = re.match(r"^(\w+)\s*=\s*(.*)$", s)
        if env:
            if env[1] in ("CRON_TZ", "TZ"):
                tz = env[2].strip('"\x27')
            continue
        parts = s.split(None, 1 if s.startswith("@") else 5)
        if len(parts) != (2 if s.startswith("@") else 6):
            continue
        expression = parts[0] if s.startswith("@") else " ".join(parts[:5])
        command = parts[-1]
        entries.append(
            {
                "id": f"cron:{n}",
                "line_number": n,
                "kind": "cron",
                "expression": expression,
                "command": redact_command(command),
                "timezone": tz,
            }
        )
    return entries


def _read_command(argv: list[str]) -> dict[str, Any]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=12)
        return {
            "measured": p.returncode == 0,
            "as_of": iso(datetime.now(timezone.utc)),
            "stdout": p.stdout,
            "reason": None if p.returncode == 0 else f"exit:{p.returncode}",
            "command": argv,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "measured": False,
            "as_of": iso(datetime.now(timezone.utc)),
            "stdout": "",
            "reason": type(exc).__name__,
            "command": argv,
        }


def _systemd_timestamp(value: str | None) -> str | None:
    if not value or value in ("n/a", "infinity"):
        return None
    try:
        # systemctl formats in the host timezone. Use host conversion, never label ET text as UTC.
        d = datetime.strptime(" ".join(value.split()[1:3]), "%Y-%m-%d %H:%M:%S").astimezone()
        return iso(d)
    except ValueError:
        return None


def collect_host(*, openclaw_path: Path | None = None) -> dict[str, Any]:
    cron = _read_command(["crontab", "-l"])
    try:
        host_tz = Path("/etc/timezone").read_text().strip()
    except OSError:
        tz_path = str(Path("/etc/localtime").resolve())
        host_tz = tz_path.split("/zoneinfo/", 1)[1] if "/zoneinfo/" in tz_path else None
    cron["entries"] = parse_crontab(cron.pop("stdout"), default_timezone=host_tz)
    listed = _read_command(["systemctl", "--user", "list-unit-files", "--no-legend", "--no-pager"])
    declared_names = set()
    try:
        declared_names.update(
            r["unit"] for r in json.loads((ROOT / "config/expected_services.json").read_text())["units"]
        )
        declared_names.update(
            r["scheduler"]["expression"]
            for r in lane_registry.load_registry()["lanes"]
            if r.get("scheduler", {}).get("kind") == "systemd"
        )
    except (OSError, ValueError, KeyError):
        pass
    names = [
        s.split()[0]
        for s in listed.pop("stdout").splitlines()
        if s.split()
        and (
            s.split()[0] in declared_names
            or re.match(r"(tradeai-|trade-ai-|portfolio-|cio-|openclaw|hermes|system-health)", s)
        )
        and s.split()[0].endswith((".service", ".timer"))
    ]
    units: dict[str, Any] = {}
    if listed["measured"] and names:
        shown = _read_command(["systemctl", "--user", "show", *names, "--property=" + ",".join(UNIT_PROPS)])
        listed["measured"] = shown["measured"]
        for block in shown["stdout"].split("\n\n"):
            props = dict(s.split("=", 1) for s in block.splitlines() if "=" in s)
            if props.get("Id"):
                props["ExecStart"] = redact_command(props.get("ExecStart", ""))
                pid = props.get("MainPID", "0")
                if pid.isdigit() and pid != "0":
                    cwd = Path("/proc") / pid / "cwd"
                    if cwd.exists():
                        props["process_cwd"] = str(cwd.resolve())
                units[props["Id"]] = props
        # show may stop processing arguments at the first missing unit. Probe the
        # remaining installed names independently so one dangling link hides no peers.
        missing = [name for name in names if name not in units]

        def probe(name: str) -> tuple[str, dict[str, Any]]:
            return name, _read_command(["systemctl", "--user", "show", name, "--property=" + ",".join(UNIT_PROPS)])

        with ThreadPoolExecutor(max_workers=8) as pool:
            for name, result in pool.map(probe, missing):
                props = dict(s.split("=", 1) for s in result["stdout"].splitlines() if "=" in s)
                if props.get("Id") == name:
                    props["ExecStart"] = redact_command(props.get("ExecStart", ""))
                    pid = props.get("MainPID", "0")
                    if pid.isdigit() and pid != "0":
                        cwd = Path("/proc") / pid / "cwd"
                        if cwd.exists():
                            props["process_cwd"] = str(cwd.resolve())
                    units[name] = props
        # systemctl show exits 1 if any requested unit is absent. Retain individually
        # observed properties; an omitted row still remains unknown below.
        if units:
            listed["measured"] = True
            listed["coverage"] = "COMPLETE" if len(units) == len(names) else "PARTIAL"
        listed["reason"] = shown.get("reason")
    listed["units"] = units
    system_units = [
        r["scheduler"]["expression"]
        for r in lane_registry.load_registry()["lanes"]
        if r.get("scheduler", {}).get("kind") == "systemd" and r["scheduler"].get("scope") == "system"
    ]
    if system_units:
        system = _read_command(["systemctl", "show", *system_units, "--property=" + ",".join(UNIT_PROPS)])
        for block in system["stdout"].split("\n\n"):
            props = dict(s.split("=", 1) for s in block.splitlines() if "=" in s)
            if props.get("Id"):
                props["ExecStart"] = redact_command(props.get("ExecStart", ""))
                props["scope"] = "system"
                props["observed"] = True
                units["system:" + props["Id"]] = props
    path = openclaw_path or Path.home() / ".openclaw" / "cron" / "jobs.json"
    oc: dict[str, Any] = {"measured": False, "as_of": iso(datetime.now(timezone.utc)), "jobs": []}
    try:
        raw = json.loads(path.read_text())
        jobs = raw.get("jobs", []) if isinstance(raw, dict) else raw
        oc.update(
            measured=True,
            jobs=[{k: j.get(k) for k in ("id", "name", "agentId", "enabled", "schedule", "state")} for j in jobs],
        )
    except (OSError, ValueError, TypeError):
        oc["reason"] = "OpenClaw scheduling metadata unavailable"
    return {"cron": cron, "systemd": listed, "openclaw": oc, "n8n": collect_n8n()}


def collect_n8n() -> dict[str, Any]:
    """Host-side metadata SELECT only; n8n gets no TradeAI DB or secret authority."""
    query = """BEGIN READ ONLY; SET LOCAL statement_timeout='3s';
    SELECT coalesce(json_agg(json_build_object('id',id,'name',name,'active',active,
      'updated_at',"updatedAt",'schedules',(SELECT json_agg(n->'parameters'->'rule')
      FROM json_array_elements(nodes) n WHERE n->>'type'='n8n-nodes-base.scheduleTrigger'))),'[]')
    FROM workflow_entity; COMMIT;"""
    result = _read_command(
        [
            "docker",
            "exec",
            os.environ.get("N8N_DB_CONTAINER", "m8m-n8n-db"),
            "psql",
            "-X",
            "-U",
            "n8n",
            "-d",
            "n8n",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            query,
        ]
    )
    payload = "\n".join(s for s in result.pop("stdout").splitlines() if s not in ("BEGIN", "SET", "COMMIT"))
    try:
        result["workflows"] = json.loads(payload) if result["measured"] else []
        if not isinstance(result["workflows"], list):
            raise ValueError("invalid metadata")
    except (ValueError, TypeError):
        result.update(measured=False, workflows=[], reason="invalid workflow census")
    return result


def read_run_ledger(path: Path) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Open with mode=ro. This reader must not create or migrate a missing ledger."""
    if not path.is_file():
        return [], False, "ledger absent"
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY requested_at DESC LIMIT 10000")]
            for row in rows:
                receipt = json.loads(row.pop("receipt_json", None) or "{}")
                row["receipt"] = {k: receipt.get(k) for k in RECEIPT_KEYS} if receipt else None
            return rows, True, None
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return [], False, "ledger unreadable"


def _pctl(values: list[float], q: float) -> float | None:
    return round(sorted(values)[max(0, math.ceil(q * len(values)) - 1)], 4) if values else None


def read_lock_metrics(path: Path, now: datetime) -> dict[str, Any]:
    """Component telemetry is performance evidence, never a unique RunReceipt.

    Bound reads at 32 MiB. A truncated/incomplete window cannot produce 24h zeros.
    Commands are retained only after redaction, for matching the declared script.
    """
    groups: dict[str, Any] = {}
    starts: dict[str, datetime] = {}
    earliest = None
    try:
        with path.open("rb") as f:
            size = path.stat().st_size
            if size > 32 * 1024 * 1024:
                f.seek(size - 32 * 1024 * 1024)
                f.readline()
            for line in f:
                try:
                    r = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                at = timestamp(r.get("ts"))
                if not at or at > now:
                    continue
                earliest = min(at, earliest) if earliest else at
                if now - at >= timedelta(days=1):
                    continue
                component = str(r.get("component") or "")
                if not component:
                    continue
                g = groups.setdefault(
                    component,
                    {
                        "commands": set(),
                        "started": 0,
                        "completed": 0,
                        "failures": 0,
                        "skips": 0,
                        "durations": [],
                        "ambiguous": 0,
                    },
                )
                g["commands"].add(redact_command(str(r.get("command") or "")))
                event = r.get("event_type")
                if event == "started":
                    g["started"] += 1
                    if component in starts:
                        g["ambiguous"] += 1
                    starts[component] = at
                elif event == "completed":
                    g["completed"] += 1
                    g["failures"] += r.get("exit_code") != 0
                    if component in starts:
                        g["durations"].append((at - starts.pop(component)).total_seconds())
                elif event == "lock_skip":
                    g["skips"] += 1
        for g in groups.values():
            g["commands"] = sorted(g["commands"])
        return {
            "measured": True,
            "as_of": iso(now),
            "groups": groups,
            "complete_window": bool(earliest and now - earliest >= timedelta(days=1)),
            "path": str(path),
        }
    except OSError:
        return {"measured": False, "as_of": iso(now), "groups": {}, "reason": "lock telemetry unavailable"}


def receipt_proves_run(run: dict[str, Any], now: datetime) -> bool:
    receipt = run.get("receipt")
    # RunReceipt@v2 (executor v2, n8n maturity B5.5) is a strict superset of v1's fields.
    if not isinstance(receipt, dict) or receipt.get("schema") not in ("RunReceipt@v1", "RunReceipt@v2"):
        return False
    if not run.get("run_id") or not run.get("lane_id"):
        return False
    if any(receipt.get(k) != run.get(k) for k in ("run_id", "lane_id", "mode", "state", "exit_code")):
        return False
    finished = timestamp(receipt.get("finished_at"))
    return bool(
        finished
        and finished <= now
        and finished == timestamp(run.get("finished_at"))
        and not receipt.get("lock_skipped")
        and not receipt.get("timed_out")
    )


def _metrics(runs: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    recent = [
        r
        for r in runs
        if (t := timestamp(r.get("requested_at") or r.get("finished_at"))) and now - t < timedelta(days=1) and t <= now
    ]
    completed = [
        r for r in recent if r.get("state") == "RUN_DONE" and r.get("exit_code") == 0 and receipt_proves_run(r, now)
    ]
    durations = [float(r["duration_s"]) for r in completed if isinstance(r.get("duration_s"), (int, float))]
    measured = bool(runs)
    return {
        "requested_fires_24h": len(recent) if measured else None,
        "completed_fires_24h": len(completed) if measured else None,
        "failures_24h": sum(r.get("state") in ("RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED") for r in recent)
        if measured
        else None,
        "lock_skips_24h": sum(r.get("state") == "RUN_SKIPPED_LOCK" for r in recent) if measured else None,
        "p50_runtime_s": _pctl(durations, 0.5),
        "p95_runtime_s": _pctl(durations, 0.95),
        "observed_completion_ratio": len(completed) / len(recent) if recent else None,
        # No complete scheduling-history/retention coverage is assumed from a newest-N query.
        "expected_fires_24h": None,
        "completion_ratio": None,
        "missed_fires_24h": None,
        "duplicate_runs_24h": None,
        "slo_verdict": "NOT_MEASURED",
    }


def _cron_matches(lane: dict[str, Any], entry: dict[str, Any]) -> bool:
    marker = str(lane.get("scheduler", {}).get("match") or "")
    if not marker or marker not in entry.get("command", ""):
        return False
    # Multi-stage lanes sharing a runner are distinguished by their declared stage/cadence.
    # Compare schedules, not text: a registry expression may carry the command after its 5 fields.
    # A multi-line lane stores its schedules joined by " + "; the entry matches when it is one of them.
    expr = str(lane.get("scheduler", {}).get("expression") or "")
    schedules = [f for f in cron_last_fire.cron_schedules(expr) if cron_last_fire.parse(f)]
    if not schedules:
        return True
    if cron_last_fire.cron_fields(str(entry.get("expression") or "")) in schedules:
        return True
    # Fallback (review of #1623) = the pre-#1623 rule: a row whose expression is a bare schedule (exactly 5 fields
    # or one @alias) is matched strictly - that is how multi-stage lanes sharing a runner stay apart. A row whose
    # expression carries command text or " + " was never compared, so a marker-matching line stays attached to
    # it (e.g. portfolio-repricer's second `10 16 * * 1-5` line) instead of turning into an unregistered cron
    # until the registry lists every line of the lane.
    tokens = expr.split()
    bare = len(tokens) == 5 or (len(tokens) == 1 and tokens[0].startswith("@"))
    return not bare


def cron_collides(a: dict[str, Any], b: dict[str, Any], now: datetime) -> bool:
    """Candidate overlap; distinct declared time windows are not duplicate fires."""
    left, right = cron_last_fire.parse(a["expression"]), cron_last_fire.parse(b["expression"])
    if not left or not right or a.get("timezone") != b.get("timezone"):
        return True  # cannot prove disjointness
    if not set(left["minutes"]) & set(right["minutes"]) or not set(left["hours"]) & set(right["hours"]):
        return False
    return any(
        cron_last_fire._day_matches(left, now.date() + timedelta(days=i))
        and cron_last_fire._day_matches(right, now.date() + timedelta(days=i))
        for i in range(400)
    )


def schedule_label(value: Any) -> str | None:
    """Project known schedule forms as expressions, never scheduler JSON/repr."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        labels = [schedule_label(item) for item in value]
        return "; ".join(label for label in labels if label) or None
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("interval"), list):
        labels = []
        for item in value["interval"]:
            if isinstance(item, dict) and item.get("field") == "cronExpression":
                labels.append(item.get("expression") or item.get("cronExpression"))
        return "; ".join(label for label in labels if isinstance(label, str)) or None
    if value.get("kind") == "cron" and isinstance(value.get("expr"), str):
        tz = value.get("tz")
        return value["expr"] + (f" ({tz})" if isinstance(tz, str) and tz else "")
    if value.get("kind") == "at" and isinstance(value.get("at"), str):
        return "Once " + value["at"]
    if value.get("kind") == "every" and isinstance(value.get("everyMs"), (int, float)):
        return f"Every {value['everyMs'] / 1000:g}s" if value["everyMs"] > 0 else None
    return None


def _base_row(lane: dict[str, Any]) -> dict[str, Any]:
    sched = lane.get("scheduler") or {}
    return {
        "lane_id": lane.get("lane_id"),
        "domain": lane.get("business_domain") or lane.get("domain"),
        "owner": lane.get("owner"),
        "scheduler_type": sched.get("kind", "none"),
        "declared_state": lane.get("state"),
        "runtime_state": "NOT_MEASURED",
        "schedule": sched.get("cadence") or sched.get("expression"),
        "next_due": None,
        "last_requested": None,
        "last_started": None,
        "last_completed": None,
        "last_exit": None,
        "duration": None,
        "receipt": None,
        "output_signal": lane.get("output_signal"),
        "output_age": None,
        "freshness": "NOT_MEASURED",
        "lock_skips_24h": None,
        "failures_24h": None,
        "duplicate_scheduler": None,
        "scheduler_drift": None,
        "code_sha": None,
        "code_root": None,
        "code_root_evidence": "NOT_MEASURED",
        "consumer": lane.get("consumer"),
        "evidence_class": "SOURCE_ONLY",
        "evidence_sources": [],
        "scheduler_observations": [],
        "declared_in_registry": True,
        "timeline": [],
        "run_proven": False,
        "health_reason": None,
        "slo_verdict": "NOT_MEASURED",
    }


def build_projection(
    registry: dict[str, Any],
    observations: dict[str, Any],
    *,
    root: Path,
    now: datetime | None = None,
    runs: list[dict[str, Any]] | None = None,
    runs_measured: bool = False,
    db_query: Any = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cron = observations.get("cron") or {}
    sysd = observations.get("systemd") or {}
    n8n = observations.get("n8n") or {}
    oc = observations.get("openclaw") or {}
    entries = cron.get("entries") or []
    units = sysd.get("units") or {}
    workflow_by_id = {str(w.get("id")): w for w in n8n.get("workflows") or []}
    jobs_by_id = {str(j.get("id")): j for j in oc.get("jobs") or []}
    claimed_cron, claimed_units, claimed_jobs, claimed_workflows = set(), set(), set(), set()
    rows = []
    for lane in registry.get("lanes") or []:
        row = _base_row(lane)
        sched = lane.get("scheduler") or {}
        kind = sched.get("kind", "none")
        measured, present = False, None
        matched = [e for e in entries if _cron_matches(lane, e)]
        host_matches = [e for e in entries if sched.get("match") and sched["match"] in e.get("command", "")]
        if kind == "cron":
            measured = bool(cron.get("measured"))
            present = bool(matched) if measured else None
            row["scheduler_observations"] = matched
            claimed_cron.update(e["id"] for e in matched)
            same_commands = [e for e in host_matches if any(e.get("command") == m.get("command") for m in matched)]
            colliding = [
                e for e in same_commands if any(e["id"] != m["id"] and cron_collides(e, m, now) for m in matched)
            ]
            row["duplicate_scheduler"] = (len(matched) > 1 or bool(colliding)) if measured else None
            if len(same_commands) > len(matched):
                row["scheduler_observations"] = same_commands
                claimed_cron.update(e["id"] for e in same_commands)
            if host_matches and not matched:
                row["schedule_drift"] = True
                row["scheduler_observations"] = host_matches
                claimed_cron.update(e["id"] for e in host_matches)
        elif kind == "systemd":
            name = str(sched.get("expression") or "")
            if sched.get("scope") == "system":
                name = "system:" + name
            unit = units.get(name)
            measured = unit is not None and (bool(sysd.get("measured")) or bool(unit.get("observed")))
            if measured:
                present = unit.get("ActiveState") in ("active", "activating")
                row["scheduler_observations"] = [{"id": name, "kind": "systemd", "properties": unit}]
                row["next_due"] = _systemd_timestamp(unit.get("NextElapseUSecRealtime"))
                claimed_units.add(name)
                service = name.replace(".timer", ".service")
                if service in units:
                    claimed_units.add(service)
                    row["scheduler_observations"].append(
                        {"id": service, "kind": "executor", "properties": units[service]}
                    )
                    row["code_root"] = (
                        units[service].get("process_cwd") or units[service].get("WorkingDirectory") or None
                    )
                    row["code_root_evidence"] = "OBSERVED_HOST"
                    if units[service].get("ActiveState") == "failed":
                        row["unit_failed"] = True
                else:
                    row["code_root"] = unit.get("process_cwd") or unit.get("WorkingDirectory") or None
                    row["code_root_evidence"] = "OBSERVED_HOST"
                if unit.get("LoadState") == "not-found":
                    row["schedule_drift"] = True
                    row["health_reason"] = "running unit definition is missing; restart/recovery is not proven"
            row["duplicate_scheduler"] = bool(host_matches) if measured and cron.get("measured") else None
        elif kind == "n8n":
            workflow = workflow_by_id.get(str(sched.get("expression")))
            measured = bool(n8n.get("measured"))
            present = bool(workflow and workflow.get("active")) if measured else None
            if workflow:
                row["schedule"] = schedule_label(workflow.get("schedules"))
                claimed_workflows.add(str(workflow["id"]))
                row["scheduler_observations"] = [{"id": workflow["id"], "kind": "n8n", "active": workflow["active"]}]
            row["duplicate_scheduler"] = bool(host_matches) if cron.get("measured") else None
        elif kind == "openclaw":
            job = jobs_by_id.get(str(sched.get("expression")))
            measured = bool(oc.get("measured"))
            present = bool(job and job.get("enabled")) if measured else None
            if job:
                claimed_jobs.add(str(job["id"]))
                row["scheduler_observations"] = [{"id": job["id"], "kind": "openclaw", "enabled": job["enabled"]}]
        # Event-driven work has no periodic scheduler; retain that exception as explicit intent.
        if kind == "event":
            row["health_reason"] = "event trigger presence needs producer evidence"
        source_at = timestamp(observations.get(kind, {}).get("as_of"))
        if measured and source_at and not 0 <= (now - source_at).total_seconds() <= 300:
            measured, present = False, None
            row["health_reason"] = "scheduler observation expired or future-dated"
        if measured:
            row["evidence_class"] = "OBSERVED_N8N" if kind == "n8n" else "OBSERVED_HOST"
            row["scheduler_drift"] = bool(present != (row["declared_state"] == "ACTIVE") or row.get("schedule_drift"))
            row["evidence_sources"].append({"kind": kind, "as_of": observations.get(kind, {}).get("as_of")})
        if matched:
            command = matched[0].get("command", "")
            cd = re.search(r"\bcd\s+([/\w.\-]+)", command)
            row["code_root"] = cd[1] if cd else None
            row["code_root_evidence"] = "OBSERVED_HOST" if cd else "NOT_MEASURED"
            tz = matched[0].get("timezone")
            if tz:
                try:
                    nxt = cron_last_fire.next_fire(matched[0]["expression"], now.astimezone(ZoneInfo(tz)))
                    row["next_due"] = iso(nxt) if nxt else None
                except (ValueError, KeyError):
                    pass
        all_lane_runs = sorted(
            [r for r in runs or [] if r.get("lane_id") == row["lane_id"]],
            key=lambda r: r.get("requested_at") or r.get("finished_at") or "",
        )
        live_runs = [r for r in all_lane_runs if r.get("mode") == "live"]
        row.update(_metrics(live_runs, now))
        locks = observations.get("lock_telemetry") or {}
        lock_groups = [
            g
            for g in (locks.get("groups") or {}).values()
            if sched.get("match") and any(sched["match"] in c for c in g.get("commands", []))
        ]
        if not live_runs and len(lock_groups) == 1:
            g = lock_groups[0]
            if not g.get("ambiguous"):
                row.update(p50_runtime_s=_pctl(g["durations"], 0.5), p95_runtime_s=_pctl(g["durations"], 0.95))
            if locks.get("complete_window"):
                row.update(lock_skips_24h=g["skips"], failures_24h=g["failures"])
            observed_requests = g["started"] + g["skips"]
            row["observed_lock_skip_ratio"] = g["skips"] / observed_requests if observed_requests else None
            row["performance_evidence_class"] = "OBSERVED_HOST"
            row["performance_note"] = "component events; no unique run identity or expected-fire coverage"
        if live_runs:
            last = live_runs[-1]
            receipt = last.get("receipt")
            row.update(
                last_requested=last.get("requested_at"),
                last_started=last.get("started_at"),
                last_completed=last.get("finished_at"),
                last_exit=last.get("exit_code"),
                duration=last.get("duration_s"),
                receipt=last.get("run_id"),
                run_proven=receipt_proves_run(last, now),
                code_sha=(receipt or {}).get("code_sha"),
            )
            if (receipt or {}).get("code_root"):
                row.update(code_root=receipt["code_root"], code_root_evidence="OBSERVED_DB")
        row["timeline"] = [
            {
                k: r.get(k)
                for k in (
                    "run_id",
                    "mode",
                    "state",
                    "requested_at",
                    "started_at",
                    "finished_at",
                    "exit_code",
                    "duration_s",
                    "receipt",
                )
            }
            for r in reversed(all_lane_runs[-10:])
        ]
        sig = lane.get("output_signal") or {"kind": "none"}
        signal = (
            lane_registry.observe_signal(sig, root=root, db_query=db_query)
            if sig.get("kind") != "systemd_result"
            else {
                "readable": False,
                "last_output_at": None,
                "detail": "systemd_result is an exit status, not durable output proof",
            }
        )
        at = signal.get("last_output_at")
        age = (now - at).total_seconds() if isinstance(at, datetime) and at <= now else None
        row["output_age"] = round(age, 2) if age is not None else None
        row["output_at"] = iso(at) if isinstance(at, datetime) else None
        cadence_s = float(lane.get("expected_cadence_hours") or 0) * 3600
        row["freshness_sla_s"] = cadence_s * 2 if cadence_s else None
        finished = timestamp(row["last_completed"])
        run_age = (now - finished).total_seconds() if finished and finished <= now else None
        row["run_age"] = run_age
        row["run_freshness"] = (
            "FRESH"
            if run_age is not None and cadence_s and run_age <= cadence_s * 2
            else "STALE"
            if run_age is not None and cadence_s
            else "NOT_MEASURED"
        )
        row["freshness"] = (
            "FRESH"
            if age is not None and age <= cadence_s
            else "AGING"
            if age is not None and age <= cadence_s * 2
            else "STALE"
            if age is not None
            else "ABSENT"
            if signal.get("readable")
            else "NOT_MEASURED"
        )
        row["output_evidence_class"] = (
            ("OBSERVED_DB" if sig.get("kind") == "db_max" else "OBSERVED_HOST")
            if signal.get("readable")
            else "NOT_MEASURED"
        )
        row["health_reason"] = row["health_reason"] or signal.get("detail")
        inactive = row["declared_state"] != "ACTIVE"
        last_state = live_runs[-1].get("state") if live_runs else None
        if row.get("duplicate_scheduler") or row.get("schedule_drift") or (inactive and present):
            row["runtime_state"] = "DRIFT"
        elif inactive:
            row["runtime_state"] = "EXPECTED_SILENT" if measured and not present or kind == "none" else "NOT_MEASURED"
        elif measured and not present:
            row["runtime_state"] = "ORPHANED"
        elif last_state == "RUN_SKIPPED_LOCK":
            row["runtime_state"] = "RUN_SKIPPED_LOCK"
        elif last_state in ("RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED") or row.get("unit_failed"):
            row["runtime_state"] = "RUN_FAILED"
        elif sig.get("kind") == "none":
            row["runtime_state"] = "NO_SIGNAL" if measured else "NOT_MEASURED"
            row["health_reason"] = (
                sig.get("reason")
                or lane.get("no_signal_reason")
                or "NO_SIGNAL_WITH_REASON missing; no output proof declared"
            )
        elif not measured:
            row["runtime_state"] = "NOT_MEASURED"
        elif row["freshness"] in ("ABSENT", "STALE"):
            row["runtime_state"] = "SILENT"
        elif row["freshness"] == "AGING":
            row["runtime_state"] = "SLOW"
        elif (
            row["freshness"] == "FRESH"
            and row["run_proven"]
            and row["run_freshness"] == "FRESH"
            and last_state == "RUN_DONE"
        ):
            row["runtime_state"] = "LIVE" if live_runs[-1].get("exit_code") == 0 else "RUN_FAILED"
        else:
            row["runtime_state"] = "NOT_MEASURED"
        if row["p95_runtime_s"] and cadence_s and row["p95_runtime_s"] > cadence_s:
            row["slo_verdict"] = "CADENCE_LT_P95"
        if row["requested_fires_24h"] and (row["lock_skips_24h"] or 0) / row["requested_fires_24h"] > 0.05:
            row["slo_verdict"] = "LOCK_SKIP_GT_5_PERCENT"
        if (row.get("observed_lock_skip_ratio") or 0) > 0.05:
            row["slo_verdict"] = "LOCK_SKIP_GT_5_PERCENT"
        rows.append(row)
    for entry in entries:
        if entry["id"] in claimed_cron:
            continue
        digest = hashlib.sha256(entry["command"].encode()).hexdigest()[:12]
        row = _base_row(
            {
                "lane_id": f"unregistered-cron-{digest}-{entry['line_number']}",
                "state": "UNDECLARED",
                "scheduler": {"kind": "cron", "expression": entry["expression"]},
            }
        )
        row.update(
            runtime_state="ORPHANED",
            declared_in_registry=False,
            evidence_class="OBSERVED_HOST",
            scheduler_drift=True,
            scheduler_observations=[entry],
            health_reason="scheduled command has no lane row",
        )
        rows.append(row)
    for name, unit in units.items():
        if name in claimed_units or unit.get("ActiveState") not in ("active", "activating", "failed"):
            continue
        row = _base_row(
            {
                "lane_id": "unregistered-unit-" + name,
                "state": "UNDECLARED",
                "scheduler": {"kind": "systemd", "expression": name},
            }
        )
        row.update(
            runtime_state="ORPHANED",
            declared_in_registry=False,
            evidence_class="OBSERVED_HOST",
            scheduler_drift=True,
            scheduler_observations=[{"id": name, "kind": "systemd", "properties": unit}],
            code_root=unit.get("process_cwd") or unit.get("WorkingDirectory") or None,
            code_root_evidence="OBSERVED_HOST",
            health_reason="active/failed unit has no lane row",
        )
        rows.append(row)
    for workflow in n8n.get("workflows") or []:
        if str(workflow.get("id")) in claimed_workflows:
            continue
        row = _base_row(
            {
                "lane_id": "unregistered-n8n-" + str(workflow.get("id")),
                "state": "UNDECLARED",
                "scheduler": {"kind": "n8n", "expression": schedule_label(workflow.get("schedules"))},
            }
        )
        row.update(
            runtime_state="ORPHANED" if workflow.get("active") else "EXPECTED_SILENT",
            declared_in_registry=False,
            evidence_class="OBSERVED_N8N",
            scheduler_drift=bool(workflow.get("active")),
            scheduler_observations=[
                {
                    "id": workflow.get("id"),
                    "kind": "n8n",
                    "name": workflow.get("name"),
                    "active": workflow.get("active"),
                    "schedules": workflow.get("schedules"),
                }
            ],
            health_reason="workflow activation observed; no declared scheduling owner",
        )
        rows.append(row)
    for job in oc.get("jobs") or []:
        if str(job.get("id")) in claimed_jobs:
            continue
        row = _base_row(
            {
                "lane_id": "openclaw-" + str(job.get("id")),
                "owner": job.get("agentId"),
                "state": "UNDECLARED",
                "scheduler": {"kind": "openclaw", "expression": schedule_label(job.get("schedule"))},
            }
        )
        row.update(
            runtime_state="ORPHANED" if job.get("enabled") else "EXPECTED_SILENT",
            declared_in_registry=False,
            evidence_class="OBSERVED_HOST",
            scheduler_drift=bool(job.get("enabled")),
            scheduler_observations=[
                {
                    "id": job.get("id"),
                    "kind": "openclaw",
                    "name": job.get("name"),
                    "enabled": job.get("enabled"),
                    "schedule": job.get("schedule"),
                }
            ],
            health_reason="OpenClaw scheduling observed; no host output receipt or registry row",
        )
        rows.append(row)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": iso(now),
        "status": "OK",
        "rows": rows,
        "summary": dict(Counter(r["runtime_state"] for r in rows)),
        "sources": {k: {f: v.get(f) for f in ("measured", "as_of", "reason")} for k, v in observations.items()},
        "runs_measured": runs_measured,
        "state_root": str(root),
        "note": "LIVE requires scheduler presence, a host receipt and fresh output. Unknown measurements remain null.",
    }


def load_projection(
    *, registry_path: Path | None = None, root: Path | None = None, db_query: Any = None
) -> dict[str, Any]:
    root = root or lane_registry.state_root()
    registry = lane_registry.load_registry(registry_path)
    observations = collect_host()
    observations["lock_telemetry"] = read_lock_metrics(
        root / "logs/safe_flock_events.jsonl", datetime.now(timezone.utc)
    )
    runs, measured, reason = read_run_ledger(root / lane_registry.N8N_LEDGER_REL)
    result = build_projection(registry, observations, root=root, runs=runs, runs_measured=measured, db_query=db_query)
    result["run_source_reason"] = reason
    result["source_sha"] = (ROOT / "GIT_SHA").read_text().strip() if (ROOT / "GIT_SHA").is_file() else None
    return result
