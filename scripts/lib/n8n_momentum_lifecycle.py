"""Disabled momentum lifecycle monitor/planner; no subprocess, network or business writes.

The CLI consumes explicit snapshots. The proposed authenticated gateway adapter supplies
server-owned snapshots and Admission loaded from operative files, never caller arming flags.
Findings use the existing scalp_lane fan-in/SIEM shape. Recovery intents are proposals for
host_run_request, not commands; the disabled candidate creates none.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from scripts.lib.cron_schedule import cron_schedules, fires_between
from scripts.lib.n8n_retry_policy import class_verdict, load_policies, next_attempt_at

SCHEMA = "N8nMomentumLifecycle@v1"
NO_CONSUMER_REASON = "Candidate host monitor receipt, authenticated gateway readback and incident fan-in adapter; activation requires owner review."
MONITOR_REL = "data/runtime/momentum_lifecycle_last.json"
INPUT_REL = "data/runtime/momentum_lifecycle_inputs.json"
LEDGER_REL = "data/governance/n8n_coordination_ledger.sqlite"
ET = ZoneInfo("America/New_York")
SHA = re.compile(r"^[0-9a-f]{40}$")
# A reviewed config cannot widen this fence to proposal, promoter, sender or execution work.
RECOVERY_LANES = frozenset({"momentum-cache-reconcile"})
SAFE_CLASSES = frozenset({"monitor", "report", "hygiene"})


def stamp(value: Any) -> datetime | None:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Admission:
    registry: Mapping[str, dict]
    contracts: Mapping[str, dict]
    allowlist: Mapping[str, dict]
    policies: Any
    deployed_sha: str
    file_hashes: Mapping[str, str]
    diagnosis_catalogue: Mapping = field(default_factory=dict)


def load_admission(code_root: Path) -> Admission:
    """Server code root only. No environment, credentials, caller-provided review or arming."""
    names = ("lane_registry", "n8n_health_contracts", "n8n_run_allowlist", "n8n_retry_policies")
    docs, hashes = {}, {}
    for name in names:
        raw = (code_root / "config" / f"{name}.json").read_bytes()
        docs[name], hashes[name] = json.loads(raw), hashlib.sha256(raw).hexdigest()
    sha = (code_root / "SOURCE_COMMIT").read_text().strip()
    if not SHA.fullmatch(sha):
        raise ValueError("invalid deployed SOURCE_COMMIT")
    allow = docs["n8n_run_allowlist"]["lanes"]
    if isinstance(allow, list):
        allow = {x["lane_id"]: x for x in allow}
    return Admission(
        {x["lane_id"]: x for x in docs["lane_registry"]["lanes"]},
        {x["id"]: x for x in docs["n8n_health_contracts"]["contracts"]},
        allow, load_policies(code_root / "config" / "n8n_retry_policies.json"), sha, hashes,
        _document(code_root / "config/n8n_remediation_catalogue.json") or {},
    )


def _finding(lane: str, reason: str, day: str, severity: str = "P1") -> dict:
    # No caller text, symbols, account fields or logs are copied into incidents.
    return {"source": "scalp_lane", "item": f"{lane}:{reason.upper()}", "severity": severity,
            "detail": f"Momentum lifecycle evidence failed: {reason}",
            "detected_at": f"{day}T00:00:00+00:00", "store": "data/runtime",
            "artifact_rel": MONITOR_REL, "operator_action": severity == "P1",
            "notification_dedupe_minutes": 0 if severity == "P1" else None}


def _document(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def collect_server_snapshot(state_root: Path, candidate: Mapping, *, now: datetime,
                            statvfs_fn=os.statvfs) -> dict:
    """Fixed host-owned projections, read-only SQLite and capacity metadata; no probes or secret reads.

    The business writer must publish explicit run/SHA/population metadata at INPUT_REL.
    A cache timestamp or health-healer timestamp is never inferred to be business evidence.
    No log tail, prompt, bearer, cookie, broker payload or account field enters the projection.
    """
    doc = _document(state_root / INPUT_REL) or {}
    products = {}
    allowed_product_keys = {"available", "run_date", "run_id", "source_sha", "finished_at", "basis",
                            "business_status", "derived_from_run_id", "population_contract", "populations",
                            "notification_binding", "consumer_views", "projection_hash", "source_verdicts_preserved"}
    for spec in candidate.get("products", []):
        product = (doc.get("products") or {}).get(spec["id"])
        if isinstance(product, dict):
            products[spec["id"]] = {k: v for k, v in product.items() if k in allowed_product_keys}
    # Project actual existing owner snapshots when the host input adapter has not supplied
    # stronger evidence. Producer SHA, business basis and consumer acks remain unknown;
    # this read-only mapping must never turn cache availability into accepted business work.
    try:
        from scripts.lib.scanner_candidate_projection import read_candidate_snapshot
        shared = read_candidate_snapshot(state_root / "data/runtime/trade_ai_cache.json",
                                         state_root / "data/active_trader/momentum_alerts.jsonl", now=now)
        owner = shared.get("source_metadata", {}).get("TRADE_AI", {})
        summary = owner.get("summary") or {}
        counts = {"candidate_union_total": shared["candidate_count"]} if isinstance(shared.get("candidate_count"), int) else {}
        if isinstance(summary.get("scanned_count"), int):
            counts["summary_scanned_total"] = summary["scanned_count"]
        view = {k: shared.get(k) for k in ("run_id", "run_date", "source_sha", "finished_at",
            "projection_hash", "source_verdicts_preserved", "population_contract")}
        view.update(available=owner.get("status") == "AVAILABLE", basis="NOT_MEASURED",
                    business_status="NOT_MEASURED", populations=counts or None)
        products.setdefault("shared_signal_projection", view)
        cache = {**view, "population_contract": "separate_populations", "derived_from_run_id": shared.get("run_id")}
        products.setdefault("served_scan_cache", cache)
    except (ImportError, OSError, ValueError):
        pass
    auth = doc.get("credential_health") or {}
    snapshot = {"products": products, "credential_health": {
        k: auth[k] for k in ("secret_name", "status", "checked_at") if k in auth},
        "scalp_cycle_monitor": _document(state_root / "data/runtime/scalp_cycle_monitor_last.json"),
        "diagnosis_status": {}, "collection": {"inputs": "PRESENT" if doc else "NOT_MEASURED"}}
    diagnosis = _document(state_root / "data/runtime/n8n_failure_diagnosis_last.json") or {}
    snapshot["diagnosis_status"] = {k: diagnosis[k] for k in (
        "schema", "as_of", "status", "eligible", "diagnosed", "no_diagnosis", "actions", "consecutive_blind")
        if k in diagnosis}
    snapshot["storage_health"] = {"status": "NOT_MEASURED", "observed_at": now.isoformat(), "volumes": []}
    for path in (Path("/tmp"), state_root):
        try:
            stats = statvfs_fn(path)
            volume = {"scope": "lockfiles" if path == Path("/tmp") else "state",
                      "available_bytes": stats.f_bavail * stats.f_frsize,
                      "available_inodes": stats.f_favail}
            if volume["available_bytes"] == 0 or volume["available_inodes"] == 0:
                snapshot["storage_health"]["status"] = "FAILED"
            snapshot["storage_health"]["volumes"].append(volume)
        except OSError:
            snapshot["storage_health"]["volumes"].append({"scope": str(path), "status": "NOT_MEASURED"})
    # Positive free capacity alone does not ratify the required operating reserve.
    snapshot["storage_health"]["reserve_contract"] = "NOT_MEASURED"
    lane_ids = sorted({s["lane_id"] for s in candidate.get("watch", [])}
                      | {s["lane_id"] for s in candidate.get("recovery", {}).get("actions", [])})
    try:
        conn = sqlite3.connect(f"{(state_root / LEDGER_REL).resolve().as_uri()}?mode=ro", uri=True, timeout=3)
        try:
            conn.row_factory = sqlite3.Row
            columns = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
            core = [k for k in ("run_id", "lane_id", "mode", "state", "requested_at", "started_at",
                                "finished_at", "exit_code", "slot_key", "attempt", "receipt_json") if k in columns]
            local = now.astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
            rows = conn.execute(f"SELECT {','.join(core)} FROM runs WHERE lane_id IN "
                                f"({','.join('?' for _ in lane_ids)}) AND requested_at >= ? "
                                "ORDER BY requested_at ASC LIMIT 10001", (*lane_ids, local.astimezone(timezone.utc).isoformat())).fetchall()
            if len(rows) > 10000:
                raise ValueError("bounded census exceeded")
        finally:
            conn.close()
        clean = []
        for raw in rows:
            row = dict(raw)
            try:
                receipt = json.loads(row.pop("receipt_json", "") or "{}")
                if not isinstance(receipt, dict):
                    receipt = {}
            except (ValueError, TypeError):
                receipt = {}
            key = str(row.get("slot_key") or row.get("run_id") or "")
            matched = re.fullmatch(r"d:([a-z0-9-]+):(live|dry_run):(\d{8}T\d{4})(?::a\d+)?", key)
            row["slot_local"] = matched[3] if matched else receipt.get("slot_local")
            row["source_sha"] = receipt.get("code_sha")
            # A server slot key proves the requested slot, not a natural n8n trigger.
            row["trigger_kind"] = receipt.get("trigger_kind", "NOT_MEASURED")
            row["reason_code"] = receipt.get("reason_code")
            if row["reason_code"] is None and row.get("state") == "RUN_FAILED":
                tail = str(receipt.get("stderr_tail") or "")
                if "flock" in tail and "No space left on device" in tail:
                    row["reason_code"] = "LOCKFILE_CREATE_ENOSPC"
            row["reason"] = receipt.get("reason") if receipt.get("reason") in {
                "executor_lost", "run_lock_held", "lane_lock_held", "timeout", "invalid_argv"} else None
            row["receipt"] = {"run_id": receipt.get("run_id"), "lane_id": receipt.get("lane_id"),
                              "slot_local": receipt.get("slot_local"), "source_sha": receipt.get("code_sha"),
                              "exit_code": receipt.get("exit_code")}
            clean.append(row)
        snapshot["runs"] = clean
        snapshot["recovery_runs"] = [r for r in clean if r.get("lane_id") in RECOVERY_LANES]
        snapshot["collection"]["ledger"] = "READ_ONLY_SANITIZED"
    except (OSError, sqlite3.Error, ValueError):
        snapshot["runs"] = None
        snapshot["recovery_runs"] = []
        snapshot["collection"]["ledger"] = "NOT_MEASURED"
    return snapshot


def write_monitor(report: Mapping, state_root: Path) -> Path:
    """Only this monitor's health store; no business/cache/incident writes or action execution."""
    destination = state_root / MONITOR_REL
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def contract_body_digest(contract: Mapping) -> str:
    """Digest substantive operative content, excluding decision metadata and lifecycle status.

    Embedding the release SHA in a committed contract is self-referential. Review instead
    binds the exact contract body, while SOURCE_COMMIT and execution/output receipts
    independently bind the running release. This uses existing operative configuration;
    it introduces no new review authority or persistent review store.
    """
    body = {k: v for k, v in contract.items() if k not in {"review", "status"}}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def contract_review_proven(contract: Mapping) -> bool:
    """Server-loaded operative contract only. A digest proposal is not a review decision."""
    from scripts.lib.n8n_health_contracts import unknown_fields, validate_contract
    review = contract.get("review") or {}
    return (contract.get("status") == "REVIEWED" and not validate_contract(contract)
            and not unknown_fields(contract)
            and contract.get("ownership_confirmation") not in {"NOT_MEASURED", "UNRESOLVED"}
            and isinstance(review.get("reviewed_by"), str) and bool(review["reviewed_by"].strip())
            and isinstance(review.get("decision_ref"), str) and bool(review["decision_ref"].strip())
            and review.get("contract_body_sha256") == contract_body_digest(contract))


def recovery_admitted(admission: Admission, lane: str) -> bool:
    """Safe fixed catalogue target, operative content-bound review and existing runtime gates."""
    row = admission.registry.get(lane, {})
    allow = admission.allowlist.get(lane, {})
    return (lane in RECOVERY_LANES and row.get("state") == "ACTIVE"
            and row.get("scheduler", {}).get("stage") == "cutover"
            and row.get("dispatch", {}).get("class") in SAFE_CLASSES
            and contract_review_proven(admission.contracts.get(lane, {}))
            and allow.get("live_arg") is not None and allow.get("lock_kind") == "flock" and bool(allow.get("lock")))


def monitor_admitted(admission: Admission) -> bool:
    """Operative admission, never a caller supplied enabled/review boolean."""
    lane = "momentum-lifecycle-monitor"
    row, contract, allow = (admission.registry.get(lane, {}), admission.contracts.get(lane, {}),
                            admission.allowlist.get(lane, {}))
    return (row.get("state") == "ACTIVE" and row.get("scheduler", {}).get("stage") in {"canary", "cutover"}
            and row.get("dispatch", {}).get("class") == "monitor"
            and contract_review_proven(contract)
            and allow.get("live_arg") is not None and allow.get("lock_kind") == "flock"
            and allow.get("lock") == "/tmp/tradeai_momentum_lifecycle.lock")


def durable_view(code_root: Path, state_root: Path, *, now: datetime) -> dict:
    """Server-owned authenticated read projection; never caller-controlled paths or arming."""
    candidate = _document(code_root / "config/n8n_momentum_lifecycle_candidate.json") or {}
    admission = load_admission(code_root)
    stage = admission.registry.get("momentum-lifecycle-monitor", {}).get("scheduler", {}).get("stage")
    stage = stage if stage in {"shadow", "canary", "cutover"} else "NOT_MEASURED"
    if candidate.get("enabled") is not True:
        return {"state": "REFUSED", "reason": "momentum_lifecycle_disabled", "monitor_stage": stage}
    if not monitor_admitted(admission):
        return {"state": "REFUSED", "reason": "momentum_monitor_admission_unproven", "monitor_stage": stage}
    report = _document(state_root / MONITOR_REL)
    if report is None or report.get("schema") != SCHEMA:
        return {"state": "REFUSED", "reason": "momentum_monitor_not_measured"}
    as_of = stamp(report.get("as_of"))
    if as_of is None or not timedelta(0) <= now - as_of <= timedelta(minutes=10):
        return {"state": "REFUSED", "reason": "momentum_monitor_stale"}
    sha = (code_root / "SOURCE_COMMIT").read_text().strip()
    if report.get("source_sha") != sha:
        return {"state": "REFUSED", "reason": "momentum_monitor_deployed_sha_drift"}
    return dict(report)


def product_proof(product: Mapping[str, Any] | None, *, day: str, now: datetime,
                  sha: str, max_age_s: int, upstream: Mapping | None = None) -> list[str]:
    if not product or product.get("available") is not True:
        return ["output_not_measured"]
    reasons = []
    if product.get("run_date") != day:
        reasons.append("wrong_business_day")
    if not product.get("run_id"):
        reasons.append("run_identity_missing")
    if product.get("source_sha") != sha:
        reasons.append("output_source_sha_mismatch")
    finished = stamp(product.get("finished_at"))
    if finished is None or finished > now or (now - finished).total_seconds() > max_age_s:
        reasons.append("output_stale_or_unattributed")
    if product.get("basis") != "REAL_BUSINESS_OUTPUT" or product.get("business_status") != "ok":
        reasons.append("business_output_not_proven")
    if upstream and (product.get("derived_from_run_id") != upstream.get("run_id")
                     or product.get("run_date") != upstream.get("run_date")):
        reasons.append("upstream_run_binding_drift")
    # Different populations are valid: only enforce an explicitly declared partition.
    populations = product.get("populations")
    if populations is None:
        reasons.append("population_not_measured")
    elif not isinstance(populations, Mapping) or any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in populations.values()):
        reasons.append("invalid_population_measurement")
    elif product.get("population_contract") == "scan_partition":
        required = {"scanned_total", "classified_total", "manual_total"}
        if not required <= populations.keys():
            reasons.append("partition_not_measured")
        elif populations["classified_total"] + populations["manual_total"] != populations["scanned_total"]:
            reasons.append("population_partition_drift")
    binding = product.get("notification_binding")
    if binding is not None:
        keys = [binding.get(k) for k in ("body_subject", "link_subject", "footer_subject")]
        if not all(keys) or len(set(keys)) != 1:
            reasons.append("notification_source_binding_drift")
    consumers = product.get("consumer_views")
    if product.get("population_contract") == "shared_signal_union":
        if not isinstance(consumers, Mapping) or set(consumers) != {"active_trader", "trade_ai"}:
            reasons.append("shared_projection_consumers_not_measured")
        elif any(not isinstance(view, Mapping) or view.get("projection_hash") != product.get("projection_hash")
                 or view.get("run_id") != product.get("run_id") or view.get("run_date") != day
                 for view in consumers.values()):
            reasons.append("shared_projection_consumer_identity_drift")
        if not product.get("projection_hash") or product.get("source_verdicts_preserved") is not True:
            reasons.append("shared_projection_provenance_not_proven")
    return reasons


def _run_proof(run: Mapping, lane: str, slot: str, sha: str, now: datetime) -> str:
    if run.get("state") == "RUN_SKIPPED_LOCK":
        return "lock_skipped"
    if run.get("state") == "RUN_FAILED" and run.get("reason_code") == "LOCKFILE_CREATE_ENOSPC":
        return "lockfile_create_no_space"
    if run.get("trigger_kind") != "NATURAL_SCHEDULE":
        return "manual_or_unknown_trigger"
    if run.get("state") != "RUN_DONE" or run.get("exit_code") != 0:
        return "run_not_completed"
    requested, started, finished = (stamp(run.get(k)) for k in ("requested_at", "started_at", "finished_at"))
    receipt = run.get("receipt") or {}
    if not all((requested, started, finished)) or not requested <= started <= finished <= now:
        return "durable_chain_incomplete"
    if not run.get("run_id") or receipt.get("run_id") != run.get("run_id"):
        return "receipt_identity_missing"
    if receipt.get("lane_id") != lane or receipt.get("slot_local") != slot:
        return "receipt_slot_or_lane_mismatch"
    if receipt.get("source_sha") != sha or receipt.get("exit_code") != 0:
        return "receipt_sha_or_verdict_mismatch"
    return "receipt_chain_proven"


def evaluate(candidate: Mapping, snapshot: Mapping, admission: Admission, *, now: datetime,
             trading_day_fn, session_fn) -> dict:
    """No authority from candidate forecasts, caller booleans or zero-filled missing measurements."""
    now = stamp(now)
    if now is None:
        raise ValueError("aware now required")
    local = now.astimezone(ET)
    day = local.date().isoformat()
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    trading = bool(trading_day_fn(local))
    lanes, products, findings = [], {}, []
    run_rows = snapshot.get("runs")
    if not isinstance(run_rows, list) or not all(isinstance(r, Mapping) for r in run_rows):
        run_rows = None
    for spec in candidate.get("watch", []):
        lid = spec["lane_id"]
        reg = admission.registry.get(lid)
        expressions = cron_schedules((reg or {}).get("scheduler", {}).get("expression", ""))
        slots = []
        if (trading or spec.get("window") == "all_days") and reg and reg.get("state") == "ACTIVE":
            for expression in expressions:
                slots.extend(f for f in fires_between(expression, start - timedelta(microseconds=1), now, "America/New_York")
                             if spec.get("window") != "regular" or session_fn(f.at) == "regular")
        due = {f.slot_local: f for f in slots
               if f.at + timedelta(seconds=spec.get("completion_allowance_s", 300)) <= now}
        states = {}
        for slot in sorted(due):
            matching = [r for r in (run_rows or []) if r.get("lane_id") == lid and r.get("slot_local") == slot]
            outcomes = [_run_proof(r, lid, slot, admission.deployed_sha, now) for r in matching]
            states[slot] = ("not_measured" if run_rows is None else
                            "receipt_chain_proven" if "receipt_chain_proven" in outcomes else
                            outcomes[-1] if outcomes else "expected_fire_without_request")
            proven_ids = {r.get("run_id") for r, outcome in zip(matching, outcomes)
                          if outcome == "receipt_chain_proven"}
            if len(proven_ids) > 1:
                states[slot] = "duplicate_completed_run_effects_not_proven"
        failures = sorted({v for v in states.values() if v != "receipt_chain_proven"})
        if not reg or not expressions:
            failures.append("schedule_not_measured")
        for reason in failures:
            findings.append(_finding(lid, reason, day))
        measured_schedule = bool(reg and expressions)
        lanes.append({"lane_id": lid, "role": spec["role"], "expected_due": len(due) if measured_schedule else None,
                      "observed_requested": None if run_rows is None or not measured_schedule else sum(
                          r.get("lane_id") == lid and r.get("slot_local") in due for r in run_rows),
                      "slot_states": states, "requirements_missing": failures,
                      "business_acceptance": "NOT_MEASURED"})
    product_rows = snapshot.get("products") or {}
    for spec in candidate.get("products", []):
        # A six-AM contract is a business expectation, separate from the RTH scanner's schedule.
        required_after = start.replace(hour=spec.get("required_after_hour", 6))
        applicable = trading and now >= required_after + timedelta(seconds=spec.get("grace_s", 900))
        upstream = product_rows.get(spec.get("upstream")) if spec.get("upstream") else None
        reasons = product_proof(product_rows.get(spec["id"]), day=day, now=now,
                                sha=admission.deployed_sha, max_age_s=spec["max_age_s"], upstream=upstream
                                ) if applicable else []
        if applicable and spec.get("upstream") and not upstream:
            reasons.append("upstream_output_not_measured")
        products[spec["id"]] = {"applicable": applicable, "requirements_missing": reasons,
                               "status": "NOT_APPLICABLE" if not applicable else "UNPROVEN" if reasons else "PROVEN",
                               "populations": (product_rows.get(spec["id"]) or {}).get("populations")}
        for reason in reasons:
            findings.append(_finding(spec["id"], reason, day))
    # Reuse the actual ScalpCycleMonitor projection; never fabricate zero SLOs if it is absent.
    cycle = snapshot.get("scalp_cycle_monitor")
    if cycle is None:
        cycle_metrics = None
        if trading and session_fn(local) == "regular":
            findings.append(_finding("trade-ai-scalp-live", "cycle_monitor_not_measured", day))
    else:
        cycle_metrics = {k: cycle.get(k) for k in ("slots_due", "slots_ok", "ok_rate", "clean_day")}
        if cycle.get("schema") != "ScalpCycleMonitor@v1" or cycle.get("date") != day:
            findings.append(_finding("trade-ai-scalp-live", "cycle_monitor_identity_drift", day))
        elif stamp(cycle.get("as_of")) is None or not timedelta(0) <= now - stamp(cycle["as_of"]) <= timedelta(minutes=10):
            findings.append(_finding("trade-ai-scalp-live", "cycle_monitor_stale", day))
        else:
            # Keep the original monitor's already bounded incidents; no caller detail is forwarded.
            for incident in cycle.get("incidents", []):
                reason = str(incident.get("item", "")).rsplit(":", 1)[-1]
                if reason in {"MISSED_CYCLES", "NO_CYCLES_30M"}:
                    findings.append(_finding("trade-ai-scalp-live", reason, day, incident.get("severity", "P1")))
    credential_tasks = []
    auth = snapshot.get("credential_health") or {}
    if auth.get("secret_name") == "FINVIZ_COOKIE" and auth.get("status") in {"expired", "invalid", "missing"}:
        findings.append(_finding("finviz-credential", "credential_owner_action_required", day))
        credential_tasks.append({"type": "OPERATOR_TASK", "secret_name": "FINVIZ_COOKIE",
                                 "source_of_truth": "Bitwarden Secrets Manager",
                                 "surface": "Command Center System > secrets",
                                 "action": "Use existing authorized host render/validator flow, then verify ingestion outputs.",
                                 "n8n_secret_access": False, "automatic_cookie_or_secret_action": False})
    findings = list({(f["source"], f["item"]): f for f in findings}.values())
    storage = snapshot.get("storage_health") or {}
    if storage.get("status") == "FAILED":
        findings.append(_finding("momentum-storage", "storage_capacity_exhausted", day))
    return {"schema": SCHEMA, "as_of": now.isoformat(), "date": day, "source_sha": admission.deployed_sha,
            "candidate_enabled": candidate.get("enabled") is True, "lanes": lanes, "products": products,
            "scalp_cycle_metrics": cycle_metrics, "incidents": findings,
            "acceptance": "NOT_MEASURED", "recovery_intents": [],
            "credential_tasks": credential_tasks,
            "storage_health": storage, "diagnosis_status": snapshot.get("diagnosis_status") or {},
            "diagnosis_coverage": diagnosis_coverage(candidate, admission),
            "authority": "READ_ONLY_ADVISORY", "natural_cutover_proof": "NOT_MEASURED"}


def diagnosis_coverage(candidate: Mapping, admission: Admission) -> dict:
    """Use the existing governed diagnoser; never choose a model or widen its action catalogue."""
    from scripts.lib.n8n_remediation_catalogue import DIAGNOSIS_EXCLUDED_LANES
    catalogue = admission.diagnosis_catalogue
    entries = {e.get("lane_id"): e for e in catalogue.get("lanes", []) if isinstance(e, Mapping)}
    review = catalogue.get("review") or {}
    ready = (catalogue.get("status") == "REVIEWED" and bool(review.get("reviewed_by"))
             and bool(review.get("decision_ref"))
             and review.get("contract_body_sha256") == contract_body_digest(catalogue))
    return {"process_id": "n8n_lane_failure_diagnosis", "template_id": "lane_failure_diagnosis.v1",
            "catalogue_review": "PROVEN" if ready else "NOT_MEASURED", "model_selection_by_n8n": False,
            "lanes": [{"lane_id": spec["lane_id"],
                       "mode": "EXCLUDED_ESCALATE_ONLY" if spec["lane_id"] in DIAGNOSIS_EXCLUDED_LANES
                       else "CATALOGUE_REVIEW_HELD" if spec["lane_id"] in entries and not ready
                       else "EXISTING_GOVERNED_CATALOGUE" if spec["lane_id"] in entries
                       else "NO_CATALOGUE_ENTRY_ESCALATE_ONLY",
                       "execution": "existing host diagnoser only; gateway/executor retain admission"}
                      for spec in candidate.get("watch", [])]}


def plan_recovery(candidate: Mapping, report: Mapping, admission: Admission, *, snapshot: Mapping,
                  now: datetime) -> dict:
    """Bounded deterministic proposal. Runtime admission outranks candidate configuration."""
    now = stamp(now)
    if now is None:
        raise ValueError("aware now required")
    if not candidate.get("enabled") or not candidate.get("recovery", {}).get("armed"):
        return {"intents": [], "held": [{"reason": "retry_disarmed"}]}
    intents, held = [], []
    for spec in candidate.get("recovery", {}).get("actions", []):
        lid = spec["lane_id"]
        def hold(reason):
            held.append({"lane_id": lid, "reason": reason})
        if lid not in RECOVERY_LANES:
            hold("protected_or_unknown_recovery_lane")
            continue
        row = admission.registry.get(lid, {})
        dispatch = row.get("dispatch") or {}
        if not recovery_admitted(admission, lid):
            hold("operative_admission_not_proven")
            continue
        if report.get("source_sha") != admission.deployed_sha:
            hold("deployed_sha_drift")
            continue
        targets = report.get("products") or {}
        if targets.get(spec["product"], {}).get("status") != "UNPROVEN":
            continue
        if any(targets.get(dep, {}).get("status") != "PROVEN" for dep in spec.get("dependencies", [])):
            hold("dependency_output_not_proven")
            continue
        history = [r for r in snapshot.get("recovery_runs", []) if r.get("lane_id") == lid]
        policy = admission.policies.get(dispatch.get("retry_policy"))
        if not history:
            hold("no_durable_budget_slot")
            continue
        latest = max(history, key=lambda r: str(r.get("requested_at", "")))
        history = [r for r in history if r.get("slot_key") == latest.get("slot_key")]
        if any(not isinstance(r.get("attempt"), int) or isinstance(r.get("attempt"), bool)
               or not 1 <= r["attempt"] <= 9 for r in history):
            hold("budget_slot_or_receipt_not_proven")
            continue
        last = max(history, key=lambda r: int(r.get("attempt", 0)))
        key = str(last.get("slot_key") or "")
        finished = stamp(last.get("finished_at"))
        try:
            origin = datetime.strptime(key.rsplit(":", 1)[-1], "%Y%m%dT%H%M").replace(tzinfo=ET).astimezone(timezone.utc)
        except ValueError:
            origin = None
        klass = dispatch["class"]
        if (not key.startswith(f"d:{lid}:live:") or finished is None or origin is None
                or last.get("source_sha") != admission.deployed_sha or finished > now):
            hold("budget_slot_or_receipt_not_proven")
            continue
        if snapshot.get("storage_health", {}).get("status") != "PROVEN":
            hold("storage_or_lock_creation_not_proven")
            continue
        if class_verdict(last.get("state"), last.get("exit_code"), last.get("reason"), policy, klass) != "retryable":
            hold("existing_retry_policy_terminal")
            continue
        next_at = next_attempt_at(policy, int(last.get("attempt", 0)), finished, klass)
        if next_at is None:
            hold("retry_budget_exhausted")
            continue
        if now < next_at or now > origin + timedelta(minutes=policy.catchup_min):
            hold("retry_backoff_or_window")
            continue
        if any(r.get("state") in {"REQUESTED", "RUNNING"} for r in history):
            hold("recovery_already_inflight")
            continue
        # Stable per budget slot/attempt, independent of wall clock or polling count.
        attempt = int(last["attempt"]) + 1
        run_id = f"{key}:a{attempt}"
        intents.append({"lane_id": lid, "mode": "live", "run_id": run_id,
                        "requested_by": "host-momentum-lifecycle", "caller_id": "trade-ai-dispatch",
                        "attempt": attempt, "budget_slot_key": key, "operation": "coordination/run",
                        "execution": "existing dispatcher due key only; gateway validates due and persists original slot/attempt",
                        "submission_owner": "existing coordination/due dispatcher; host_run_request refuses server slot keys"})
    return {"intents": intents, "held": held}


def gateway_view(request: Mapping, *, candidate: Mapping, server_snapshot: Mapping,
                 admission: Admission, now: datetime, trading_day_fn, session_fn) -> dict:
    """Called only after existing HMAC coordination_read authentication in proposed adapter."""
    if set(request) - {"route", "operation", "claim", "signature"}:
        return {"state": "REFUSED", "reason": "unexpected_field"}
    if not candidate.get("enabled"):
        return {"state": "REFUSED", "reason": "typed_refusal:momentum_lifecycle_disabled"}
    report = evaluate(candidate, server_snapshot, admission, now=now,
                      trading_day_fn=trading_day_fn, session_fn=session_fn)
    # Read endpoint deliberately never submits its recovery proposals or runs gateway transitions.
    report["recovery"] = plan_recovery(candidate, report, admission, snapshot=server_snapshot, now=now)
    return report
