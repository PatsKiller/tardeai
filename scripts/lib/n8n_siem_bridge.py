"""n8n -> Command Center SIEM bridge: pure logic (no DB, no network, no send).

REMEDIATION_PLAN §5 L2 (operator 2026-10-09 23:20 ET: "everything implemented on n8n must log/monitor into the
Command Center SIEM"). The n8n chain (relay, gateway, executor, incident fan-in, incident notifier) wrote no
``system_health_events`` rows; this module turns its two existing stores into SIEM rows:

* the coordination ledger ``runs`` table (RunReceipt@v1 per run, read with sqlite ``mode=ro``), and
* the incident fan-in receipt ``data/runtime/n8n_incident_fanin_last.json`` (N8nIncidentFanin@v1, read-only), and
* the failure diagnoser's own store ``data/runtime/n8n_diagnoses/diagnoses.jsonl`` (N8nLaneDiagnosis@v1, read-only;
  REMEDIATION_PLAN §6 R3). The diagnoser never writes ``system_health_events`` (AGENTS.md §9.4, one writer per
  store; operator "Ok" 2026-10-10 ~00:35 ET): this bridge folds the latest diagnosis of an open row's incident into
  that row's message (suffix after ``DIAG_MARKER``) and ``action_taken``, idempotently — the same diagnosis twice is a
  skip, and a changed finding drops it (new evidence, new incident key, new diagnosis).

One active row per (component ``n8n:<lane_id>``, event_type) — the dedupe key. A repeat with the same severity and
message is skipped; a changed one updates the open row in place; a finding that clears is resolved
(``lifecycle_state='resolved'``, the convention of ``/api/v2/admin/alert/resolve``) only when its source is healthy:
ledger kinds when the lane's latest finished run is good, fan-in kinds when the fan-in receipt is fresh.

Severity is stored in the table's own vocabulary (CRITICAL / URGENT / WARN / INFO; measured 2026-10-09: 884
CRITICAL, 782 WARN, 231 INFO, 26 legacy P1). Source: the lane registry row ``severity`` (Critical/High/Medium/Low)
when present, else the fan-in priority (P0/P1 -> CRITICAL, P2 -> WARN, P3 -> INFO).

AUTHORITY: READ_ONLY_ADVISORY over its inputs; its single write target is ``system_health_events`` rows whose
component starts ``n8n:`` (one declared writer, AGENTS.md §9.4). No Telegram: routing stays with the host SYSTEM
chokepoint (AGENTS.md §9.1, §23.3).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "N8nSiemBridge@v1"
NO_CONSUMER_REASON = (
    "REMEDIATION_PLAN §5 L2 SIEM bridge; its consumer is the Command Center SIEM (system_health_events). "
    "Not scheduled until the operator approves the n8n lane (siem-evidence/SCHEDULING.md)."
)
WRITER = "n8n_siem_bridge"
COMPONENT_PREFIX = "n8n:"
FANIN_RECEIPT_REL = "data/runtime/n8n_incident_fanin_last.json"
LEDGER_REL = "data/governance/n8n_coordination_ledger.sqlite"
RECEIPT_REL = "data/runtime/n8n_siem_bridge_last.json"
FANIN_LANE = "n8n-incident-fanin"
DIAGNOSES_REL = "data/runtime/n8n_diagnoses/diagnoses.jsonl"
DIAGNOSIS_SCHEMA = "N8nLaneDiagnosis@v1"
DIAGNOSES_TAIL_BYTES = 4 * 1024 * 1024   # the newest records only; one diagnosis per incident, a few per day
FANIN_MAX_AGE_H = 1.0  # fan-in runs */5; an hour without a receipt means the SIEM feed is blind

SEVERITY_RANK = {"CRITICAL": 0, "URGENT": 1, "WARN": 2, "INFO": 3}
REGISTRY_SEVERITY = {"critical": "CRITICAL", "high": "URGENT", "medium": "WARN", "low": "INFO"}
PRIORITY_SEVERITY = {"P0": "CRITICAL", "P1": "CRITICAL", "P2": "WARN", "P3": "INFO"}
OPEN_STATES = ("active", "acknowledged")

# Kinds decided by the coordination ledger: resolved only when the lane's latest finished run is good.
LEDGER_KINDS = frozenset({"RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED", "NO_RECEIPT", "STALE_OUTPUT"})
RUN_FAILURE_STATES = frozenset({"RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED"})
RUN_NEUTRAL_STATES = frozenset({"RUN_SKIPPED_LOCK", "REQUESTED", "RUN_REQUESTED", "RUNNING", "RUN_RUNNING"})
RUN_PRIORITY = {"RUN_FAILED": "P2", "RUN_TIMEOUT": "P2", "RUN_REFUSED": "P2", "NO_RECEIPT": "P2", "STALE_OUTPUT": "P2"}
RUN_ID_RE = re.compile(r"^n8n-wf-([A-Za-z0-9]+)-(\d+)$")
# Volatile timestamps (a receipt's ran_at moves every run) must not turn an unchanged incident into an UPDATE.
ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")

DEFAULT_REMEDIATION = {
    "RUN_FAILED": "Read the RunReceipt stderr_tail for this run, fix the lane runner, then prove recovery with a "
    "dry_run via coordination/run before the next live slot.",
    "RUN_TIMEOUT": "Lane exceeded its allowlist timeout_s: check for a hung dependency or lock, profile the runner, "
    "and raise timeout_s only with evidence.",
    "RUN_REFUSED": "Executor refused the run (allowlist/mode/env). Check config/n8n_run_allowlist.json for the lane "
    "and the receipt reason.",
    "NO_RECEIPT": "A run finished without a RunReceipt@v1 (or the receipt store is missing). Check the executor unit "
    "and the ledger; exit 0 is not evidence.",
    "STALE_OUTPUT": "The run finished but its output_signal did not advance. Check the lane's output path resolves "
    "to the served persistent-state (AGENTS.md §9.4).",
    "N8N_DOWN": "n8n is unreachable: check the n8n container and its healthz; the host cron fallbacks stay live.",
    "RELAY_DOWN": "The n8n run relay is down, so n8n cannot request runs: check tradeai-n8n-run-relay.service.",
    "EXECUTOR_STALLED": "The n8n run executor heartbeat is stale: check tradeai-n8n-run-executor.service.",
}
FALLBACK_REMEDIATION = "Open the source receipt named in this event, fix the cause, and let the next run clear it."


def _utc(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _kind(text: str) -> str:
    return re.sub(r"[^A-Z0-9_]+", "_", str(text or "").upper()).strip("_") or "FINDING"


def lane_kind(source: str, item: str) -> tuple[str, str]:
    """Map one fan-in incident (source, item) to (lane_id, kind) — the dedupe key's two halves."""
    item = str(item or "")
    if source == "runs" and item == "executor:stalled":
        return "n8n-run-executor", "EXECUTOR_STALLED"
    if source == "relay":
        return "n8n-run-relay", ("RELAY_DOWN" if item == "relay:down" else _kind(item.split(":", 1)[-1]))
    if source == "n8n_lab_watchdog":
        return "n8n-lab-watchdog", "N8N_DOWN"
    if source == "n8n_workflow_error" and item.startswith("wferr:") and len(item) > 6:
        return item[6:], "WORKFLOW_ERROR"  # fan-in groups per workflow: component n8n:<workflow_id> (gap 11)
    if source in ("breach_detector", "runs", "scalp_lane") and ":" in item:
        lane, kind = item.rsplit(":", 1)
        return lane, _kind(kind)
    if source == "gap_resolution":  # item is "<category>:<count>": the count must not churn the key
        return "gap_resolution", _kind(item.split(":", 1)[0])
    if source == "dlq" and item.startswith("breaker:"):
        return item.split(":", 1)[1], "BREAKER_OPEN"
    if ":" in item:
        code, subject = item.split(":", 1)
        return f"{source}/{subject}", _kind(code)
    return f"{source}/{item}" if item else source, _kind(source)


def severity_for(registry_row: Optional[dict], priority: str) -> tuple[str, str]:
    """(stored severity, basis). The registry row's own severity wins; else the fan-in priority."""
    reg = str((registry_row or {}).get("severity") or "").strip().lower()
    if reg in REGISTRY_SEVERITY:
        return REGISTRY_SEVERITY[reg], f"registry:{reg}"
    p = str(priority or "").upper()
    return PRIORITY_SEVERITY.get(p, "WARN"), f"priority:{p or 'unknown'}"


def remediation_for(registry_row: Optional[dict], kind: str) -> tuple[str, str]:
    reg = str((registry_row or {}).get("remediation") or "").strip()
    if reg:
        return reg, "registry"
    return DEFAULT_REMEDIATION.get(kind, FALLBACK_REMEDIATION), "default"


def parse_run_id(run_id: str, requested_by: str = "") -> tuple[Optional[str], Optional[str]]:
    """(n8n workflow id, n8n execution id) from ``n8n-wf-<wf>-<exec>`` / ``n8n:workflow:<wf>``."""
    m = RUN_ID_RE.match(str(run_id or ""))
    if m:
        return m.group(1), m.group(2)
    rb = str(requested_by or "")
    return (rb.split("n8n:workflow:", 1)[1] or None) if rb.startswith("n8n:workflow:") else None, None


def environment(release_link: Path) -> str:
    """Served release pin: readlink CURRENT basename (+ SOURCE_COMMIT short sha when present)."""
    try:
        target = Path(release_link).resolve(strict=True)
    except (OSError, RuntimeError):
        return "release:UNKNOWN"
    sha = ""
    for name in ("SOURCE_COMMIT", "GIT_SHA", "BUILD_SHA"):
        try:
            sha = (target / name).read_text(encoding="utf-8").strip()[:9]
        except OSError:
            continue
        if sha:
            break
    return f"release:{target.name}" + (f"@{sha}" if sha else "")


# ---------------------------------------------------------------- sources (read-only)


def read_ledger_runs(path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    """Newest-first runs rows from the coordination ledger, opened read-only (raises when unreadable)."""
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT run_id, lane_id, mode, state, requested_by, requested_at, finished_at, exit_code, duration_s, "
            "receipt_json FROM runs ORDER BY requested_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def latest_runs(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Latest decisive run per lane: neutral states (lock skip, still running) never decide health."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:  # newest first
        lane = str(r.get("lane_id") or "")
        if not lane or lane in out or str(r.get("state") or "") in RUN_NEUTRAL_STATES:
            continue
        out[lane] = r
    return out


def _receipt(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    try:
        doc = json.loads(row.get("receipt_json") or "")
    except (TypeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def run_verdict(row: dict[str, Any]) -> tuple[Optional[str], str]:
    """(failure kind or None when good, error excerpt) for one decisive run row."""
    state = str(row.get("state") or "")
    rec = _receipt(row)
    if state in RUN_FAILURE_STATES:
        bits = [
            f"reason={(rec or {}).get('reason')}" if (rec or {}).get("reason") else "",
            f"exit={row.get('exit_code')}",
            f"duration_s={row.get('duration_s')}",
        ]
        tail = str((rec or {}).get("stderr_tail") or (rec or {}).get("stdout_tail") or "").strip()
        if tail:
            bits.append(f"tail={tail[-240:]}")
        return state, " ".join(b for b in bits if b)
    if rec is None:
        return "NO_RECEIPT", f"state={state} exit={row.get('exit_code')} receipt_json missing or unparseable"
    before, after = rec.get("output_signal_mtime_before"), rec.get("output_signal_mtime_after")
    if (
        str(row.get("mode") or rec.get("mode")) == "live"
        and rec.get("output_signal")
        and before is not None
        and after is not None
        and float(after) <= float(before)
    ):
        return "STALE_OUTPUT", f"output_signal {rec.get('output_signal')} mtime did not advance ({after} <= {before})"
    return None, ""


# ---------------------------------------------------------------- findings


def _finding(
    lane: str,
    kind: str,
    *,
    priority: str,
    source: str,
    detail: str,
    detected_at: Any,
    registry: dict[str, dict],
    workflow_id: Optional[str],
    execution_id: Optional[str],
    run_id: Optional[str],
) -> dict[str, Any]:
    row = registry.get(lane)
    if workflow_id is None and row and (row.get("scheduler") or {}).get("kind") == "n8n":
        workflow_id = str((row.get("scheduler") or {}).get("expression") or "") or None
    sev, basis = severity_for(row, priority)
    rem, rem_src = remediation_for(row, kind)
    return {
        "lane_id": lane,
        "kind": kind,
        "component": f"{COMPONENT_PREFIX}{lane}"[:200],
        "event_type": kind,
        "severity": sev,
        "severity_basis": basis,
        "priority": priority,
        "source": source,
        "detail": str(detail or "")[:400],
        "detected_at": str(detected_at or ""),
        "workflow_id": workflow_id,
        "execution_id": execution_id,
        "run_id": run_id,
        "remediation": rem,
        "remediation_source": rem_src,
    }


def ledger_findings(latest: dict[str, dict[str, Any]], registry: dict[str, dict]) -> tuple[list[dict], set[str]]:
    """(findings, good lanes) from the latest decisive run per lane."""
    found, good = [], set()
    for lane, row in sorted(latest.items()):
        kind, excerpt = run_verdict(row)
        if kind is None:
            good.add(lane)
            continue
        wf, ex = parse_run_id(row.get("run_id"), row.get("requested_by"))
        found.append(
            _finding(
                lane,
                kind,
                priority=RUN_PRIORITY.get(kind, "P2"),
                source="ledger",
                detail=f"mode={row.get('mode')} {excerpt}",
                registry=registry,
                detected_at=row.get("finished_at") or row.get("requested_at"),
                workflow_id=wf,
                execution_id=ex,
                run_id=row.get("run_id"),
            )
        )
    return found, good


def fanin_findings(
    doc: Optional[dict], now: datetime, registry: dict[str, dict], latest: dict[str, dict[str, Any]]
) -> tuple[list[dict], bool, str]:
    """(findings, fan-in healthy, note). A missing or stale receipt is itself a finding and resolves nothing."""
    if not doc:
        f = _finding(
            FANIN_LANE,
            "NO_RECEIPT",
            priority="P1",
            source="fanin",
            registry=registry,
            detail=f"{FANIN_RECEIPT_REL} missing or unreadable: n8n incidents cannot reach the SIEM",
            detected_at=now.replace(minute=0, second=0, microsecond=0).isoformat(),
            workflow_id=None,
            execution_id=None,
            run_id=None,
        )
        return [f], False, "fanin:missing"
    as_of = _utc(doc.get("as_of"))
    age_h = None if as_of is None else (now - as_of).total_seconds() / 3600
    out: list[dict] = []
    healthy = age_h is not None and age_h <= FANIN_MAX_AGE_H and doc.get("ok") is not False
    if not healthy:
        out.append(
            _finding(
                FANIN_LANE,
                "STALE_OUTPUT",
                priority="P1",
                source="fanin",
                registry=registry,
                detail=f"fan-in receipt as_of={doc.get('as_of')} age_h="
                f"{'?' if age_h is None else round(age_h, 2)} ok={doc.get('ok')} "
                f"(max {FANIN_MAX_AGE_H}h)",
                detected_at=doc.get("as_of"),
                workflow_id=None,
                execution_id=None,
                run_id=None,
            )
        )
    for inc in doc.get("incidents") or []:
        lane, kind = lane_kind(str(inc.get("source") or ""), str(inc.get("item") or ""))
        run = latest.get(lane) or {}
        wf, ex = parse_run_id(run.get("run_id"), run.get("requested_by")) if run else (None, None)
        if inc.get("workflow_id"):  # a grouped workflow-error incident names its workflow and executions
            keys = [str(k) for k in inc.get("event_keys") or []]
            wf = str(inc["workflow_id"])
            ex = keys[-1].rsplit("-", 1)[-1] if keys else ex
        out.append(
            _finding(
                lane,
                kind,
                priority=str(inc.get("severity") or "P3"),
                registry=registry,
                source=f"fanin:{inc.get('source')}",
                detail=f"{inc.get('item')}: {inc.get('detail') or ''}",
                detected_at=inc.get("detected_at") or doc.get("as_of"),
                workflow_id=wf,
                execution_id=ex,
                run_id=run.get("run_id"),
            )
        )
    return out, healthy, f"fanin:{'ok' if healthy else 'stale'}:open={len(doc.get('incidents') or [])}"


def merge(findings: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """One finding per dedupe key; the most severe wins, ledger evidence preferred on a tie."""
    out: dict[tuple[str, str], dict] = {}
    for f in findings:
        k = (f["component"], f["event_type"])
        cur = out.get(k)
        if cur is None:
            out[k] = f
            continue
        a, b = SEVERITY_RANK.get(f["severity"], 9), SEVERITY_RANK.get(cur["severity"], 9)
        if a < b or (a == b and f["source"] == "ledger" and cur["source"] != "ledger"):
            out[k] = f
    return out


def message(f: dict[str, Any], env: str) -> str:
    """One line carrying everything an operator (or the notifier) needs; stable across identical runs."""

    def q(s: Any) -> str:
        return str(s or "").replace('"', "'").replace("\n", " ")[:400]

    return (
        f"[n8n] lane={f['lane_id']} kind={f['kind']} severity={f['severity']} ({f['severity_basis']}) "
        f"source={f['source']} workflow={f.get('workflow_id') or 'n/a'} execution={f.get('execution_id') or 'n/a'} "
        f"run={f.get('run_id') or 'n/a'} at={f.get('detected_at') or 'n/a'} env={env} "
        f'error="{q(f.get("detail"))}" remediation="{q(f.get("remediation"))}" '
        f"dedupe={f['component']}|{f['event_type']}"
    )[:1800]


# ---------------------------------------------------------------- plan


#: The diagnosis suffix this bridge renders onto an open row's message (REMEDIATION_PLAN §6 R3). The bridge is the
#: only writer of the row; scripts/n8n_failure_diagnosis.py writes its own store (DIAGNOSES_REL) and nothing else.
DIAG_MARKER = " \u2016 diag:"


def strip_diagnosis(msg: Any) -> str:
    """The finding part of a row message (everything before the diagnosis suffix)."""
    return str(msg or "").split(DIAG_MARKER, 1)[0]


def stable_text(msg: Any) -> str:
    """The WHOLE message (finding + any diagnosis suffix) with timestamps blanked: what decides skip vs update."""
    return ISO_TS_RE.sub("<ts>", str(msg or ""))


def finding_text(msg: Any) -> str:
    """The finding alone, timestamps blanked: what an incident key is computed from."""
    return ISO_TS_RE.sub("<ts>", strip_diagnosis(msg))


def incident_key(row_id: Any, severity: Any, message: Any) -> str:
    """One diagnosis per (SIEM row, finding): a re-written finding is new evidence; a timestamp or a folded
    diagnosis is not. The diagnoser keys its records with this; the bridge matches them with it."""
    h = hashlib.sha256(f"{severity}|{finding_text(message)}".encode("utf-8")).hexdigest()[:12]
    return f"siem{row_id}-{h}"


def read_diagnoses(path: Path, tail_bytes: int = DIAGNOSES_TAIL_BYTES) -> tuple[Optional[dict[str, dict]], str]:
    """(incident_key -> {"diagnosis": latest record, "remediation": latest record or None}, note).

    A missing file is an empty store (the diagnoser has not run yet); an unreadable one is None, and ``plan`` then
    keeps whatever suffix an unchanged row already shows instead of erasing it. Malformed lines are counted, skipped."""
    p = Path(path)
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()                       # drop the partial first line
            raw = fh.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return {}, "diagnoses:none"
    except OSError as exc:
        return None, f"diagnoses:unavailable:{type(exc).__name__}"
    out: dict[str, dict] = {}
    bad = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if not isinstance(rec, dict) or rec.get("schema") != DIAGNOSIS_SCHEMA or not rec.get("incident_key"):
            bad += 1
            continue
        slot = out.setdefault(str(rec["incident_key"]), {"diagnosis": None, "remediation": None})
        if rec.get("kind") == "diagnosis":
            slot["diagnosis"], slot["remediation"] = rec, None      # a newer diagnosis restarts the story
        elif rec.get("kind") == "remediation":
            slot["remediation"] = rec
        else:
            bad += 1
    out = {k: v for k, v in out.items() if v["diagnosis"] is not None}
    return out, f"diagnoses:ok:{len(out)}" + (f":bad_lines={bad}" if bad else "")


def diagnosis_suffix(view: dict[str, Any]) -> str:
    """The text appended after DIAG_MARKER (one line, bounded, no timestamps so it is stable across passes)."""
    d = view.get("diagnosis") or {}
    rem = view.get("remediation") or {}

    def q(v: Any) -> str:
        return str(v or "").replace('"', "'").replace("\n", " ")[:300]

    cost = d.get("cost_usd")
    parts = [
        f'cause="{q(d.get("cause"))}"', f"conf={d.get('confidence')}", f"action={d.get('action_id')}",
        f"outcome={d.get('outcome')}", f"model={d.get('provider') or 'n/a'}/{d.get('model_id') or 'n/a'}",
        f"cost_usd={'n/a' if cost is None else f'{float(cost):.4f}'}", f"latency_ms={d.get('latency_ms')}",
        f"cites={','.join(str(c) for c in d.get('citations') or [])[:200]}", f"key={d.get('incident_key')}",
    ]
    if d.get("escalation"):
        parts.append(f"escalated={d['escalation']}")
    if rem.get("outcome"):
        parts.append(f"remediation={str(rem['outcome']).replace(' ', '_')[:120]}")
        if rem.get("escalation"):
            parts.append(f"remediation_escalated={rem['escalation']}")
    return (DIAG_MARKER + " " + " ".join(parts))[:1300]


def diagnosis_action(view: dict[str, Any]) -> str:
    d, rem = view.get("diagnosis") or {}, view.get("remediation") or {}
    tail = f"; remediation -> {rem.get('outcome')}" if rem.get("outcome") else ""
    return f"{WRITER}: diagnosis folded (n8n_failure_diagnosis: {d.get('action_id')} -> {d.get('outcome')}{tail})"[:300]


def plan(
    findings: dict[tuple[str, str], dict],
    open_rows: list[dict[str, Any]],
    *,
    env: str,
    good_lanes: set[str],
    ledger_ok: bool,
    fanin_ok: bool,
    diagnoses: Optional[dict[str, dict]] = None,
) -> dict[str, list[dict]]:
    """Pure diff of wanted findings against the open n8n rows -> {insert, update, resolve, skip, hold}.

    ``diagnoses`` (``read_diagnoses``): the diagnosis whose incident key matches an open row's (id, severity,
    finding) is rendered onto that row; ``{}`` = none; ``None`` = store unreadable, so an unchanged row keeps the
    suffix it already shows. A new row has no id yet, so it never carries a diagnosis."""
    by_key: dict[tuple[str, str], list[dict]] = {}
    for r in open_rows:
        if (
            str(r.get("component") or "").startswith(COMPONENT_PREFIX)
            and str(r.get("lifecycle_state") or "active") in OPEN_STATES
        ):
            by_key.setdefault((r["component"], r["event_type"]), []).append(r)
    for rows in by_key.values():
        rows.sort(key=lambda r: int(r.get("id") or 0), reverse=True)
    out: dict[str, list[dict]] = {"insert": [], "update": [], "resolve": [], "skip": [], "hold": []}
    for key, f in sorted(findings.items()):
        msg = message(f, env)
        row = {
            "component": f["component"],
            "event_type": f["event_type"],
            "severity": f["severity"],
            "message": msg,
            "lane_id": f["lane_id"],
            "source": f["source"],
            "priority": f["priority"],
        }
        existing = by_key.get(key)
        if not existing:
            out["insert"].append(row)
            continue
        ex = existing[0]
        ikey = incident_key(ex.get("id"), f["severity"], msg)
        desired, folded = msg, None
        if diagnoses is None:
            old = str(ex.get("message") or "")
            if finding_text(old) == finding_text(msg):
                desired = msg + old[len(strip_diagnosis(old)):]
        elif ikey in diagnoses:
            desired, folded = msg + diagnosis_suffix(diagnoses[ikey]), ikey
        row = {**row, "message": desired, "incident_key": ikey, "diagnosis_folded": folded,
               "action_note": diagnosis_action(diagnoses[ikey]) if folded else None}
        if ex.get("severity") == f["severity"] and stable_text(ex.get("message")) == stable_text(desired):
            out["skip"].append({**row, "id": ex.get("id")})
        else:
            out["update"].append({**row, "id": ex.get("id"), "was_severity": ex.get("severity")})
    for key, rows in sorted(by_key.items()):
        if key in findings:
            continue
        comp, kind = key
        lane = comp[len(COMPONENT_PREFIX) :]
        if kind in LEDGER_KINDS and lane != FANIN_LANE:
            ok, why = ledger_ok and lane in good_lanes, "latest_run_good"
        elif kind in LEDGER_KINDS:  # the fan-in's own receipt: fresh again, or its lane's latest run is good
            ok, why = fanin_ok or (ledger_ok and lane in good_lanes), "fanin_receipt_fresh"
        else:
            ok, why = fanin_ok, "fanin_finding_cleared"
        for r in rows:
            item = {
                "id": r.get("id"),
                "component": comp,
                "event_type": kind,
                "severity": r.get("severity"),
                "reason": why if ok else "source_unhealthy_or_lane_not_good",
            }
            out["resolve" if ok else "hold"].append(item)
    return out


def counts(p: dict[str, list[dict]]) -> dict[str, Any]:
    def by_sev(rows: list[dict]) -> dict[str, int]:
        c: dict[str, int] = {}
        for r in rows:
            c[str(r.get("severity"))] = c.get(str(r.get("severity")), 0) + 1
        return dict(sorted(c.items(), key=lambda kv: SEVERITY_RANK.get(kv[0], 9)))

    return {k: {"n": len(v), "by_severity": by_sev(v)} for k, v in p.items()}
