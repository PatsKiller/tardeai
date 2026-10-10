#!/usr/bin/env python3
"""build_n8n_health_contracts.py — draft N8nHealthContract@v1 rows from existing sources (never invents a fact).

Writes ``config/n8n_health_contracts.json``: one contract per lane n8n fires or is about to fire (registry rows at
shadow / canary / cutover, dispatch blocks, staged ``r1_pending`` rows, per-lane ``kind: n8n`` rows), the six generic
workflows (``docs/implementation/n8n-maturity/workflows/INDEX.json``) and the host monitors of the n8n chain
(SIEM bridge, failure diagnoser, incident notifier). Schema, rules and the gate: ``scripts/lib/n8n_health_contracts.py``
and ``scripts/check_n8n_health_contracts.py``; procedure: ``docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md``.

Sources, and what each contributes (nothing else is asserted; a missing fact is written ``UNKNOWN — needs owner``):

* ``config/lane_registry.json``             owner, stage, cadence (``expected_cadence_hours``), output_signal, class;
* ``config/n8n_run_allowlist.json``         runner argv, lock, timeout_s, dry_run_arg, LaneRunReceipt path;
* ``docs/.../cron-inventory/data/inventory.csv``  purpose, business_function, dependencies, inputs, outputs
                                            (verified inventory 2026-10-09; free text, marked ``inventory_text``);
* ``config/n8n_remediation_catalogue.json`` severity, catalogue actions, auto flags, diagnosis exclusion;
* the coordination ledger ``runs`` table (read with sqlite ``mode=ro``; optional) for the learned baseline:
  >= 14 finished LIVE runs -> ``LEARNED_PROVISIONAL`` p50/p95 duration and failure rate; fewer ->
  ``CLASS_DEFAULT_PROVISIONAL``. Dry-run fires never set a baseline (they do not do the work).

Every built contract is ``status: DRAFT``. A contract an owner has marked ``REVIEWED`` is kept byte for byte.

    python3 scripts/build_n8n_health_contracts.py --dry-run            # summary, writes nothing
    python3 scripts/build_n8n_health_contracts.py --write [--ledger PATH] [--as-of YYYY-MM-DD]

Exit 0 = ok, 1 = a source could not be read, 2 = usage. Reads only; its one write is the contracts file.
MBI_BEHAVIOR = 0: no broker, no send, no DB write, no crontab, no n8n.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import n8n_health_contracts as H  # noqa: E402

ALLOWLIST_PATH = ROOT / "config" / "n8n_run_allowlist.json"
CATALOGUE_PATH = ROOT / "config" / "n8n_remediation_catalogue.json"
INVENTORY_PATH = ROOT / "docs" / "implementation" / "n8n-maturity" / "cron-inventory" / "data" / "inventory.csv"
LEDGER_REL = Path("data") / "governance" / "n8n_coordination_ledger.sqlite"
REVIEW_DAYS = 14
UNKNOWN = H.UNKNOWN
FUNCTION_SEVERITY = {
    "alerts-ops": "Critical",
    "trading-adjacent": "Critical",
    "portfolio data": "High",
    "reporting": "High",
    "research": "Medium",
    "governance": "Medium",
    "monitoring": "Low",
    "maintenance": "Low",
    "other": "Low",
}  # mirrors scripts/lib/n8n_remediation_catalogue.py FUNCTION_SEVERITY (pinned by the test)
SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
SIEM_SEVERITY = {"Critical": "CRITICAL", "High": "URGENT", "Medium": "WARN", "Low": "INFO"}  # n8n_siem_bridge
TERMINAL = ("RUN_DONE", "RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED")
NOT_ENFORCED = (
    "not read at runtime yet: scripts/lib/n8n_siem_bridge.py severity_for() uses the registry row "
    "`severity`, else the fan-in priority (RUN_* = P2 -> WARN). Wiring the bridge, notifier and "
    "diagnoser to this contract is the next build item (N8N_MONITORING_AND_REMEDIATION_STANDARD.md §7)."
)


def _state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    return Path(env) if env else Path.home() / "trade-ai-releases" / "persistent-state"


def load_inventory(path: Path) -> dict[str, list[dict[str, str]]]:
    by_lane: dict[str, list[dict[str, str]]] = {}
    if not path.exists():
        return by_lane
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            lane = (row.get("registry_row") or "").strip()
            if lane:
                by_lane.setdefault(lane, []).append(row)
    return by_lane


def pick_inventory_row(rows: list[dict[str, str]], sched_kind: Optional[str]) -> Optional[dict[str, str]]:
    """The active inventory row of the scheduler that does the work today (crontab for cron rows, n8n for n8n)."""
    want = "n8n" if sched_kind == "n8n" else "crontab"
    active = [r for r in rows if r.get("active") == "yes"]
    for r in active:
        if r.get("source") == want:
            return r
    return active[0] if active else None


def ledger_runs(ledger: Optional[Path], lane: str) -> list[dict[str, Any]]:
    if not ledger or not ledger.exists():
        return []
    conn = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=3)
    try:
        cur = conn.execute(
            "SELECT state, mode, duration_s, attempt FROM runs WHERE lane_id = ? AND mode = 'live' "
            "AND state IN (?,?,?,?) ORDER BY requested_at DESC LIMIT 50",
            (lane, *TERMINAL),
        )
        return [{"state": s, "mode": m, "duration_s": d, "attempt": a} for s, m, d, a in cur.fetchall()]
    finally:
        conn.close()


def _pct(values: list[float], q: float) -> float:
    vs = sorted(values)
    if len(vs) == 1:
        return vs[0]
    k = (len(vs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vs) - 1)
    return round(vs[lo] + (vs[hi] - vs[lo]) * (k - lo), 3)


def baseline(
    runs: list[dict[str, Any]], *, cadence_h: Optional[float], timeout_s: Optional[int], cls: str, as_of: date
) -> dict[str, Any]:
    fresh = round(2 * cadence_h, 3) if cadence_h else None
    done = [r for r in runs if r["state"] == "RUN_DONE" and r["duration_s"] is not None]
    base: dict[str, Any] = {
        "freshness_degraded_after_h": fresh,
        "freshness_failed_after_h": round(3 * cadence_h, 3) if cadence_h else None,
        "freshness_rule": "degraded beyond 2x cadence (lane_registry.evaluate_lane SLOW), failed beyond 3x "
        "(incident fan-in stale threshold)",
        "timeout_s": timeout_s,
        "class": cls,
        "computed_on": as_of.isoformat(),
    }
    if len(done) >= H.MIN_LEARNED_RUNS:
        durs = [float(r["duration_s"]) for r in done]
        fails = sum(1 for r in runs if r["state"] != "RUN_DONE")
        base.update(
            {
                "basis": "LEARNED_PROVISIONAL",
                "source": f"coordination ledger runs: last {len(runs)} finished live runs ({len(done)} RUN_DONE)",
                "runs_considered": len(runs),
                "duration_p50_s": round(statistics.median(durs), 3),
                "duration_p95_s": _pct(durs, 0.95),
                "failure_rate": round(fails / len(runs), 4),
                "retried_runs": sum(1 for r in runs if (r.get("attempt") or 1) > 1),
            }
        )
    else:
        base.update(
            {
                "basis": "CLASS_DEFAULT_PROVISIONAL",
                "source": f"fewer than {H.MIN_LEARNED_RUNS} finished live runs in the coordination ledger "
                f"({len(done)}); class defaults: duration degraded above 80% of timeout_s, freshness 2x/3x "
                "cadence, any RUN_FAILED/RUN_TIMEOUT/RUN_REFUSED failed",
                "runs_considered": len(runs),
                "duration_degraded_above_s": round(0.8 * timeout_s, 1) if timeout_s else None,
            }
        )
    return base


def lane_severity(
    lane: str, cat: Optional[Mapping[str, Any]], inv: Optional[Mapping[str, str]], reg_row: Optional[Mapping[str, Any]]
) -> tuple[str, str]:
    if cat and cat.get("severity") in SEV_RANK:
        return cat["severity"], f"remediation catalogue ({cat.get('severity_basis')})"
    reg = str((reg_row or {}).get("severity") or "")
    if reg in SEV_RANK:
        return reg, "lane_registry.json row severity"
    fn = (inv or {}).get("business_function") or ""
    if fn in FUNCTION_SEVERITY:
        return FUNCTION_SEVERITY[fn], f"inventory {inv.get('inv_id')} business_function={fn} (catalogue rule)"
    return "Medium", "UNKNOWN — needs owner (default Medium)"


def alerting(sev: str, basis: str) -> dict[str, Any]:
    lower = {"Critical": "High", "High": "Medium", "Medium": "Low", "Low": "Low"}[sev]
    return {
        "lane_severity": sev,
        "severity_basis": basis,
        "failed": {"siem_severity": SIEM_SEVERITY[sev], "notifier_priority": "P1" if SEV_RANK[sev] <= 1 else "P2"},
        "degraded": {"siem_severity": SIEM_SEVERITY[lower], "notifier_priority": "P2" if sev == "Critical" else "P3"},
        "routing": "SIEM row n8n:<lane> by scripts/n8n_siem_bridge.py; Telegram only through scripts/incident_notifier.py "
        "(P1 at once, uncapped; P2 batched, held 22:00-07:00 ET, 24/day cap; P3 never sends)",
        "enforced": NOT_ENFORCED,
    }


def remediation(lane: str, cat: Optional[Mapping[str, Any]], excluded: frozenset) -> dict[str, Any]:
    if lane in excluded:
        return {
            "catalogue_entry": False,
            "diagnosis_excluded": True,
            "note": "DIAGNOSIS_EXCLUDED_LANES (scripts/lib/n8n_remediation_catalogue.py): never sent to an "
            "external model; failures still reach the SIEM and the operator",
        }
    if not cat:
        return {
            "catalogue_entry": False,
            "diagnosis_excluded": False,
            "note": "not in config/n8n_remediation_catalogue.json: the diagnoser skips it (lane_not_in_catalogue); "
            "regenerate with scripts/build_remediation_catalogue.py --write after its allowlist PR",
        }
    acts = [
        {
            "action_id": a.get("action_id"),
            "auto": bool(a.get("auto")),
            **({"approval_reason": a["approval_reason"]} if a.get("approval_reason") else {}),
        }
        for a in cat.get("actions") or []
    ]
    return {
        "catalogue_entry": True,
        "diagnosis_excluded": False,
        "actions": acts,
        "default_action": cat.get("default_action"),
        "suggest_only_reason": cat.get("suggest_only_reason"),
    }


def _edge(name: str, kind: str, direction: str, source: str) -> dict[str, str]:
    return {"name": name, "kind": kind, "direction": direction, "source": source}


def lane_contract(
    lane: str,
    why: str,
    row: Mapping[str, Any],
    entry: Optional[Mapping[str, Any]],
    inv: Optional[Mapping[str, str]],
    cat: Optional[Mapping[str, Any]],
    excluded: frozenset,
    runs: list[dict[str, Any]],
    as_of: date,
) -> dict[str, Any]:
    sched = row.get("scheduler") or {}
    pend = row.get("r1_pending") or {}
    stage = H.stage_of(row)
    disp = row.get("dispatch") or pend.get("dispatch") or {}
    cls = str(disp.get("class") or (runs and "report") or "UNKNOWN — needs owner")
    cadence_h = row.get("expected_cadence_hours")
    timeout_s = (entry or {}).get("timeout_s")
    receipt = (entry or {}).get("output_signal") or (pend.get("output_signal") or {}).get("path")
    reg_sig = (row.get("output_signal") or {}).get("path")
    shadow = stage == "shadow" or (disp.get("mode") == "dry_run")
    inv_id = (inv or {}).get("inv_id")
    purpose = (inv or {}).get("purpose") or ""
    edges = [
        _edge(
            "n8n -> relay 172.19.0.1:18092 -> gateway coordination/run -> tradeai-n8n-run-executor",
            "service",
            "calls",
            "AGENTS.md §23.3",
        )
    ]
    if entry:
        edges.append(
            _edge(
                " ".join(map(str, entry.get("command") or [])),
                "runner",
                "calls",
                "config/n8n_run_allowlist.json command",
            )
        )
        if entry.get("lock"):
            edges.append(
                _edge(
                    str(entry["lock"]),
                    "lock",
                    "read_write",
                    f"config/n8n_run_allowlist.json lock ({entry.get('lock_kind')})",
                )
            )
    if receipt:
        edges.append(_edge(str(receipt), "receipt", "write", "LaneRunReceipt / allowlist output_signal"))
    if reg_sig and reg_sig != receipt:
        edges.append(_edge(str(reg_sig), "output_signal", "write", "config/lane_registry.json output_signal"))
    for col, direction in (("dependencies", "read"), ("triggers_inputs", "read"), ("outputs_downstream", "write")):
        v = ((inv or {}).get(col) or "").strip()
        if v and not v.startswith("n/a"):
            edges.append(_edge(v, "inventory_text", direction, f"inventory {inv_id} {col} (DRAFT: free text)"))
    if len(edges) == 1 and not entry:
        edges.append(_edge(UNKNOWN, "unknown", "read", "no allowlist entry and no inventory row"))
    base = baseline(runs, cadence_h=cadence_h, timeout_s=timeout_s, cls=cls, as_of=as_of)
    fresh = base.get("freshness_degraded_after_h")
    learned = base["basis"] == "LEARNED_PROVISIONAL"
    dur_txt = (
        f"duration <= p95 {base.get('duration_p95_s')} s"
        if learned
        else f"duration <= {base.get('duration_degraded_above_s')} s (80% of timeout_s {timeout_s})"
    )
    if shadow:
        healthy = [
            {
                "check": "shadow_dry_run_done",
                "text": "every dispatcher fire of this lane ends RUN_DONE in mode dry_run "
                "(coordination ledger runs; the stage clamp turns any live request into dry_run)",
            },
            {
                "check": "dry_run_writes_nothing",
                "text": "the dry_run RunReceipt shows output_signal_mtime_after == "
                "output_signal_mtime_before (a dry run writes nothing, AGENTS.md §6)",
            },
            {
                "check": "cron_twin_output_fresh",
                "text": f"the live cron line keeps the registry output_signal "
                f"{reg_sig or UNKNOWN} fresh within {fresh} h (2x cadence)",
            },
            {"check": "duration_within_baseline", "text": dur_txt},
        ]
    else:
        healthy = [
            {"check": "last_live_run_done", "text": "the latest live run is RUN_DONE in the coordination ledger"},
            {
                "check": "output_advanced",
                "text": f"{receipt or reg_sig or UNKNOWN} advanced on that run "
                "(RunReceipt output_signal_mtime_after > before, or LaneRunReceipt ok_at moved)",
            },
            {"check": "fresh", "text": f"the output_signal is younger than {fresh} h (2x cadence)"},
            {"check": "duration_within_baseline", "text": dur_txt},
        ]
    degraded = [
        {
            "check": "late",
            "text": f"output_signal older than {fresh} h but younger than "
            f"{base.get('freshness_failed_after_h')} h (2x-3x cadence)",
        },
        {
            "check": "slow",
            "text": "duration above "
            + (f"p95 {base.get('duration_p95_s')} s" if learned else f"{base.get('duration_degraded_above_s')} s"),
        },
        {
            "check": "retried",
            "text": "a run needed attempt > 1 (retry_policy) or ended RUN_SKIPPED_LOCK in two "
            "consecutive slots (another scheduler holds the lock)",
        },
        {
            "check": "upstream_stale",
            "text": "an upstream input is stale: "
            + (((inv or {}).get("dependencies") or UNKNOWN)[:200] + " (not machine-checked yet)"),
        },
    ]
    if cls == "llm":
        degraded.append(
            {
                "check": "deferred_offpeak",
                "text": "the receipt counts deferred paid calls "
                "(lib/llm_deferral queued them for the next off-peak window)",
            }
        )
    failed = [
        {"check": "run_failed", "text": "a run ends RUN_FAILED, RUN_TIMEOUT or RUN_REFUSED (coordination ledger)"},
        {"check": "no_receipt", "text": "a finished run left no RunReceipt (exit 0 is not evidence)"},
        {"check": "stale", "text": f"output_signal older than {base.get('freshness_failed_after_h')} h (3x cadence)"},
        {"check": "breaker_or_dlq", "text": "a dead letter was written or the lane's breaker opened (3 failures)"},
    ]
    if shadow:
        failed.append({"check": "dry_run_wrote", "text": "a dry_run changed its output_signal or any durable state"})
    else:
        failed.append({"check": "stale_output", "text": "RUN_DONE but the output_signal did not advance"})
    sev, basis = lane_severity(lane, cat, inv, row)
    return {
        "schema": H.SCHEMA,
        "id": lane,
        "kind": "host_monitor" if lane in H.HOST_MONITOR_LANES else "lane",
        "workflow_id": sched.get("expression")
        if sched.get("kind") == "n8n"
        else ("tradeai-dispatcher" if (disp or stage) else None),
        "status": "DRAFT",
        "target_reason": why,
        "stage": stage,
        "purpose": {
            "text": purpose or UNKNOWN,
            "business_function": (inv or {}).get("business_function") or UNKNOWN,
            "source": f"inventory {inv_id}" if inv_id else "none",
        },
        "owner": row.get("owner") or (inv or {}).get("owner_stakeholder") or UNKNOWN,
        "connects_to": edges,
        "healthy": healthy,
        "degraded": degraded,
        "failed": failed,
        "baseline": base,
        "alerting": alerting(sev, basis),
        "remediation": remediation(lane, cat, excluded),
        "evidence": _evidence(lane, receipt or reg_sig),
        "review_by": (as_of + timedelta(days=REVIEW_DAYS)).isoformat(),
    }


def _evidence(lane: str, signal: Optional[str]) -> dict[str, Any]:
    return {
        "receipt": signal or UNKNOWN,
        "verify": [
            "sqlite3 'file:$STATE_ROOT/data/governance/n8n_coordination_ledger.sqlite?mode=ro' "
            f"\"SELECT state, mode, started_at, duration_s, verdict FROM runs WHERE lane_id='{lane}' "
            'ORDER BY requested_at DESC LIMIT 10"',
            f"psql read-only: SELECT severity, event_type, lifecycle_state, created_at FROM system_health_events "
            f"WHERE component = 'n8n:{lane}' ORDER BY created_at DESC LIMIT 10",
            f"stat / jq the receipt: {signal or UNKNOWN}",
        ],
        "never": "an n8n execution status: successful executions are soft-deleted (EXECUTIONS_DATA_SAVE_ON_SUCCESS="
        "none) and keep status 'running'; filter deletedAt IS NULL and prove work with the ledger",
    }


# ---------------------------------------------------------------- generic workflows and host monitors (curated)

GENERIC = {
    "dispatcher": (
        "Every minute, asks the gateway which registry lanes are due (GET /due?source=schedule) and posts "
        "one POST /run per due lane; it chooses nothing itself.",
        "design 02 §4",
    ),
    "event-router": (
        "Every minute and on a tradeai-nudge webhook, asks the gateway for event-due lanes "
        "(GET /due?source=event) and posts POST /run for each; never sees event payloads.",
        "design 02 §6",
    ),
    "heartbeat-watcher": (
        "Every 5 minutes, runs host lane heartbeat-watch through /due and /run and reads its last "
        "live run; that lane checks every registry row's output_signal against 2x cadence.",
        "design 02 §7",
    ),
    "incident-router": (
        "Every minute, runs the host incident lanes (n8n-incident-fanin, incident-notifier) through "
        "/due and /run; as the errorWorkflow of all six it posts each n8n workflow error to relay "
        "POST /event (lane n8n-workflow-error).",
        "design 02 §8",
    ),
    "digest-scheduler": (
        "Every 5 minutes, asks the gateway for digest-window lanes (GET /due?source=digest) and "
        "posts POST /run; the host preparers and senders do the work.",
        "design 02 §9",
    ),
    "approval-router": (
        "Every 5 minutes, runs host lane approval-escalate through /due and /run; it reads guard "
        "state through a read-only projection and never mints, approves or extends a grant.",
        "design 02 §10, AGENTS.md §23.14",
    ),
}


def generic_contract(wf: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    kind = str(wf.get("kind"))
    text, src = GENERIC.get(kind, (H.UNKNOWN, "none"))
    calls = [
        _edge(f"relay {c}", "relay_route", "calls", "workflows/INDEX.json relay_calls")
        for c in wf.get("relay_calls") or []
    ]
    calls.append(_edge("credential tradeai-run-relay (relay bearer)", "credential", "read", "AGENTS.md §23.5"))
    if wf.get("error_workflow"):
        calls.append(_edge(f"errorWorkflow {wf['error_workflow']}", "workflow", "calls", "workflows/INDEX.json"))
    critical = kind in ("dispatcher", "incident-router", "heartbeat-watcher")
    sev = "Critical" if critical else "High"
    return {
        "schema": H.SCHEMA,
        "id": str(wf["id"]),
        "kind": "generic_workflow",
        "workflow_id": str(wf["id"]),
        "status": "DRAFT",
        "target_reason": "generic workflow (AGENTS.md §23.11)",
        "stage": None,
        "state_note": "imported inactive; published 15:53 ET and unpublished 15:58 ET on 2026-10-10 (W0 rollback, "
        "grant f9c459a230d3bc58); re-import waits for the relay fix release (#1663/#1664)",
        "purpose": {"text": text, "business_function": "alerts-ops" if critical else "monitoring", "source": src},
        "owner": "platform",
        "connects_to": calls,
        "healthy": [
            {"check": "active", "text": "workflow_entity.active = true for this id (n8n DB, read-only)"},
            {
                "check": "relay_calls_seen",
                "text": "relay_log.jsonl shows this workflow's relay calls on every trigger "
                "(op:due lines; POST /run answers REQUESTED or duplicate)",
            },
            {
                "check": "no_error_executions",
                "text": "no execution with status 'error' and \"deletedAt\" IS NULL since the last check",
            },
        ],
        "degraded": [
            {
                "check": "partial_refusals",
                "text": "a tick posted runs but some came back refused or unreachable (Stop And Error with lane ids)",
            },
            {"check": "due_errors", "text": "GET /due returned items in errors[] (a registry row the gateway skipped)"},
            {"check": "slow_tick", "text": "an execution ran past half its executionTimeout"},
        ],
        "failed": [
            {
                "check": "error_executions",
                "text": "an execution with status 'error' (and deletedAt IS NULL), e.g. 403 "
                "bad_lane_filter or 404 relay_bad_path (the W0 rollback causes)",
            },
            {
                "check": "silent",
                "text": "no relay call from this workflow for 5 minutes while n8n is up "
                "(dispatcher:silent in the fan-in)",
            },
            {"check": "inactive", "text": "workflow_entity.active = false outside a granted rollback"},
        ],
        "baseline": {
            "basis": "CLASS_DEFAULT_PROVISIONAL",
            "source": "no live history: the six ran 5 minutes on 2026-10-10 before the rollback",
            "freshness_degraded_after_h": None,
            "freshness_failed_after_h": round(5 / 60, 3),
            "class": "generic_workflow",
            "computed_on": as_of.isoformat(),
        },
        "alerting": alerting(sev, "generic workflow: dispatcher/incident/heartbeat Critical, others High (DRAFT)"),
        "remediation": {
            "catalogue_entry": False,
            "diagnosis_excluded": False,
            "note": "workflow errors become gateway events on lane n8n-workflow-error (relay POST /event; the "
            "fan-in has no reader for them yet); rollback = unpublish + archive under a cron grant (packets/w0-import-six/rollback.sh)",
        },
        "evidence": {
            "receipt": "relay_log.jsonl + coordination ledger",
            "verify": [
                'docker exec m8m-n8n-db psql -U n8n -d n8n -tAc "SELECT id, active FROM workflow_entity '
                f"WHERE id = '{wf['id']}'\"",
                'docker exec m8m-n8n-db psql -U n8n -d n8n -tAc "SELECT status, count(*) FROM execution_entity '
                f'WHERE \\"workflowId\\" = \'{wf["id"]}\' AND \\"deletedAt\\" IS NULL GROUP BY 1"',
                'journalctl --user -u tradeai-n8n-run-relay --since -10min | grep -c \'"op": "due"\'',
            ],
            "never": "status 'running' with a deletedAt value is a soft-deleted success, not a hang",
        },
        "review_by": (as_of + timedelta(days=REVIEW_DAYS)).isoformat(),
    }


HOST = {
    "n8n-siem-bridge": {
        "purpose": "Every 5 minutes, turns n8n failures (ledger runs, fan-in incidents) into one deduplicated, "
        "self-resolving system_health_events row per n8n:<lane>|kind, and folds diagnoses into them.",
        "source": "scripts/n8n_siem_bridge.py docstring",
        "edges": [
            ("coordination ledger runs (sqlite mode=ro)", "store", "read"),
            ("data/runtime/n8n_incident_fanin_last.json", "receipt", "read"),
            ("data/runtime/n8n_diagnoses/diagnoses.jsonl", "store", "read"),
            ("system_health_events rows component n8n:* (single writer)", "table", "write"),
            ("data/runtime/n8n_siem_bridge_last.json (ok_at)", "receipt", "write"),
        ],
    },
    "n8n-failure-diagnosis": {
        "purpose": "Every 15 minutes, diagnoses up to 3 open n8n:* SIEM incidents through the governed bridge and "
        "runs only an auto catalogue action (dry-run rerun, orphan reap); escalates the rest.",
        "source": "scripts/n8n_failure_diagnosis.py docstring",
        "edges": [
            ("system_health_events n8n:* rows (READ ONLY transaction)", "table", "read"),
            ("config/n8n_remediation_catalogue.json", "config", "read"),
            ("coordination ledger runs (sqlite mode=ro)", "store", "read"),
            (
                "cio_governed_model_bridge via n8n_model_job (grok OAuth -> chatgpt OAuth -> deepseek FAST)",
                "external_provider",
                "calls",
            ),
            ("gateway coordination/run via host_run_request (dry_run reruns)", "service", "calls"),
            ("data/runtime/n8n_diagnoses/diagnoses.jsonl", "store", "write"),
            ("data/runtime/n8n_failure_diagnosis_last.json (ok_at, escalations)", "receipt", "write"),
        ],
    },
    "incident-notifier": {
        "purpose": "Every 5 minutes, sends open P1 incidents at once and P2 in batches (held 22:00-07:00 ET) to the "
        "SYSTEM ops Telegram family, with recovery messages; P3 never sends.",
        "source": "scripts/incident_notifier.py docstring",
        "edges": [
            ("data/runtime/n8n_incident_fanin_last.json", "receipt", "read"),
            ("coordination ledger (acks)", "store", "read"),
            ("send_system -> SYSTEM ops family Telegram chokepoint", "external_provider", "calls"),
            ("data/runtime/incident_notifier_last.json, incident_notifications.jsonl", "receipt", "write"),
            ("incident_notifier_state.json (dedupe)", "store", "read_write"),
        ],
    },
}


def host_contract(lane: str, row: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    h = HOST[lane]
    cadence_h = row.get("expected_cadence_hours")
    sig = (row.get("output_signal") or {}).get("path")
    c = lane_contract(lane, "host_monitor", row, None, None, None, frozenset(), [], as_of)
    c.update(
        {
            "kind": "host_monitor",
            "workflow_id": None,
            "purpose": {"text": h["purpose"], "business_function": "alerts-ops", "source": h["source"]},
            "connects_to": [_edge(n, k, d, h["source"]) for n, k, d in h["edges"]],
            "healthy": [
                {"check": "receipt_ok", "text": f"{sig} has ok: true and ok_at advanced on the natural schedule"},
                {"check": "fresh", "text": f"ok_at younger than {round(2 * cadence_h, 3) if cadence_h else UNKNOWN} h"},
                {"check": "not_blind", "text": "the receipt names no unavailable source (source_notes empty)"},
            ],
            "degraded": [
                {"check": "late", "text": "ok_at between 2x and 3x cadence old"},
                {
                    "check": "partial",
                    "text": "a source was unavailable or a capped/held/deferred item is on the receipt",
                },
            ],
            "failed": [
                {"check": "not_ok", "text": "receipt ok: false or exit 1 (a source unavailable or a write failed)"},
                {"check": "stale", "text": "ok_at older than 3x cadence (the fan-in raises P1 for this lane)"},
                {"check": "missing", "text": "no receipt while the registry row is ACTIVE"},
            ],
            "alerting": alerting("High", "lane_registry.json row severity High (bridge/diagnoser); notifier DRAFT"),
            "state_note": f"registry state {row.get('state')}",
        }
    )
    c["baseline"]["class"] = "monitor (host cron)"
    return c


def build(
    *,
    registry: Mapping[str, Any],
    allowlist: Mapping[str, Any],
    catalogue: Mapping[str, Any],
    inventory: Mapping[str, list[dict[str, str]]],
    index: Mapping[str, Any],
    ledger: Optional[Path],
    excluded: frozenset,
    as_of: date,
    existing: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    rows = {str(r.get("lane_id")): r for r in registry.get("lanes") or []}
    entries = {str(e.get("lane_id")): e for e in allowlist.get("lanes") or []}
    cats = {str(c.get("lane_id")): c for c in catalogue.get("lanes") or []}
    kept = {str(c.get("id")): c for c in (existing or {}).get("contracts") or [] if c.get("status") == "REVIEWED"}
    out: list[dict[str, Any]] = []
    for lane, why in sorted(H.registry_targets(registry).items()):
        if lane in kept:
            out.append(kept[lane])
            continue
        row = rows[lane]
        if lane in HOST:
            out.append(host_contract(lane, row, as_of))
            continue
        inv = pick_inventory_row(list(inventory.get(lane) or []), (row.get("scheduler") or {}).get("kind"))
        out.append(
            lane_contract(
                lane, why, row, entries.get(lane), inv, cats.get(lane), excluded, ledger_runs(ledger, lane), as_of
            )
        )
    for wf in sorted(index.get("workflows") or [], key=lambda w: str(w.get("id"))):
        out.append(kept.get(str(wf["id"])) or generic_contract(wf, as_of))
    grand = (
        sorted(
            set((existing or {}).get("grandfathered_draft") or [])
            | {c["id"] for c in out if c.get("status") == "DRAFT"}
        )
        if existing is None
        else sorted(set(existing.get("grandfathered_draft") or []))
    )
    return {
        "schema": H.FILE_SCHEMA,
        "as_of": as_of.isoformat(),
        "generated_by": "scripts/build_n8n_health_contracts.py",
        "standard": "docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md",
        "rules": {
            "unknown": H.UNKNOWN,
            "baseline_bases": list(H.BASELINE_BASES),
            "min_learned_runs": H.MIN_LEARNED_RUNS,
            "draft": "DRAFT = built from sources by this script; every inventory_text edge and every default is "
            "unreviewed. An owner flips status to REVIEWED after checking each field.",
            "grandfathered_draft": "lanes whose DRAFT contract existed when the gate landed (2026-10-10); any other "
            "lane needs a REVIEWED contract before its registry PR",
        },
        "grandfathered_draft": grand,
        "contracts": out,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--write", action="store_true")
    ap.add_argument(
        "--ledger", default=None, help="coordination ledger sqlite (read-only); default under the state root"
    )
    ap.add_argument("--no-ledger", action="store_true", help="skip learned baselines")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--out", default=str(H.CONTRACTS_PATH))
    args = ap.parse_args(argv)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    ledger = None if args.no_ledger else Path(args.ledger) if args.ledger else _state_root() / LEDGER_REL
    try:
        from scripts.lib.n8n_remediation_catalogue import DIAGNOSIS_EXCLUDED_LANES as EXCL

        out_path = Path(args.out)
        existing = H.load_json(out_path) if out_path.exists() else None
        doc = build(
            registry=H.load_json(H.REGISTRY_PATH),
            allowlist=H.load_json(ALLOWLIST_PATH),
            catalogue=H.load_json(CATALOGUE_PATH),
            inventory=load_inventory(INVENTORY_PATH),
            index=H.load_json(H.GENERIC_INDEX_PATH),
            ledger=ledger,
            excluded=frozenset(EXCL),
            as_of=as_of,
            existing=existing,
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"build_n8n_health_contracts: source unreadable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    res = H.check(doc, H.load_json(H.REGISTRY_PATH), H.load_json(H.GENERIC_INDEX_PATH), today=as_of)
    summary = {
        "mode": "write" if args.write else "dry_run",
        "ledger": str(ledger) if ledger else None,
        "ledger_present": bool(ledger and ledger.exists()),
        **res["counts"],
        "errors": len(res["errors"]),
    }
    if args.write:
        out_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
        summary["wrote"] = str(out_path)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
