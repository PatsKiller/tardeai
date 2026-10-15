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

Every new contract is ``status: DRAFT``. A contract an owner has marked ``REVIEWED`` is kept byte for byte.
Regeneration retains authored DRAFT limits, ownership declarations and historical review metadata; a proposed
body digest never becomes a review decision. Existing catalogue rows are not silently retired by this builder.

    python3 scripts/build_n8n_health_contracts.py --dry-run            # summary, writes nothing
    python3 scripts/build_n8n_health_contracts.py --write [--ledger PATH] [--as-of YYYY-MM-DD]

Exit 0 = ok, 1 = a source could not be read, 2 = usage. Reads only; its one write is the contracts file.
MBI_BEHAVIOR = 0: no broker, no send, no DB write, no crontab, no n8n.
"""

from __future__ import annotations

import argparse
import copy
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
    "partial source integration: scripts/n8n_incident_fanin.py _wferr_severity() consumes a workflow contract's "
    "failed.notifier_priority to raise the workflow-error priority floor. scripts/lib/n8n_siem_bridge.py "
    "severity_for() uses registry severity, else the fan-in priority. Full per-lane baseline, notification and "
    "diagnosis enforcement is not established by these declarations; runtime coverage remains NOT_MEASURED "
    "(N8N_MONITORING_AND_REMEDIATION_STANDARD.md §7)."
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


def _event_edge(t: Mapping[str, Any]) -> dict[str, str]:
    """W5: what an event trigger connects the lane to (design 02 §6, CONSOLIDATION_PLAN §E.4)."""
    if t.get("source") == "broker_as_of":
        return _edge(
            f"Data Broker domain {t.get('domain')} as_of (scripts/lib/data_broker/as_of_signal.py read_as_of) "
            "-> coordination/due source event -> tradeai-event-router",
            "event_trigger",
            "read",
            "config/lane_registry.json dispatch.triggers (broker_as_of)",
        )
    if t.get("source") == "run_done":
        return _edge(
            f"RUN_DONE of lane {t.get('lane_id')} in the coordination ledger -> coordination/due source event "
            "-> tradeai-event-router",
            "event_trigger",
            "read",
            "config/lane_registry.json dispatch.triggers (run_done)",
        )
    return _edge(
        f"trigger source {t.get('source')} (not computed by due yet)",
        "event_trigger",
        "read",
        "config/lane_registry.json dispatch.triggers",
    )


def _event_checks(healthy: list, degraded: list, failed: list, disp: Mapping[str, Any]) -> None:
    """W5 event-trigger checks, appended to a lane contract whose dispatch block has triggers."""
    mi = int(disp.get("min_interval_s") or 0)
    healthy.append(
        {
            "check": "event_fire_dry_run_done",
            "text": "each input as_of advance past the lane's receipt watermark yields at most one e:<lane>:dry_run:<as_of "
            "minute> run, which ends RUN_DONE or RUN_SKIPPED_LOCK (cron line held the lock) in the coordination ledger",
        }
    )
    degraded.append(
        {
            "check": "event_debounced_or_coalesced",
            "text": f"advances arrive faster than min_interval_s {mi} s or while a schedule run of the lane is due or in "
            "flight, so they coalesce into one later fire (expected under bursts; investigate if no e: run lands in a "
            "trading day with input advances)",
        }
    )
    failed.append(
        {
            "check": "trigger_source_unreadable",
            "text": "coordination/due reports errors[] trigger_source_unreadable for this lane (the domain as_of file is "
            "missing or malformed, or the as_of is in the future) for more than one input cadence",
        }
    )


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
    triggers = [t for t in (disp.get("triggers") or []) if isinstance(t, Mapping)]
    for t in triggers:
        edges.append(_event_edge(t))
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
    if triggers:
        _event_checks(healthy, degraded, failed_extra := [], disp)
    else:
        failed_extra = []
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
    failed.extend(failed_extra)
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


#: Per-workflow state as measured in n8n (read-only workflow_entity) and the W0 packets; the default stands for any
#: generic workflow without an entry. Facts only; a change of state is a change to this table.
GENERIC_STATE = {
    "dispatcher": "published 2026-10-10 17:14 ET (W0 re-run, grant c90266247a4c4cd4; packets/w0-import-six)",
    "event-router": "published 2026-10-10 18:40 ET (grant 4b3623125f6b6d7e; packets/w0-import-six)",
    "incident-router": "published 2026-10-10 18:44 ET (grant 4b3623125f6b6d7e; packets/w0-import-six)",
    "digest-scheduler": "published 2026-10-10 18:47 ET (grant 4b3623125f6b6d7e; packets/w0-import-six)",
    "heartbeat-watcher": "imported inactive and unpublished since 2026-10-10 15:58 ET (W0 rollback, grant "
    "f9c459a230d3bc58); the stored row predates F4 (saveManualExecutions true), so activation re-imports the file. "
    "Its lane heartbeat-watch (scripts/heartbeat_watch.py, registry stage shadow) lands by registry PR on branch "
    "n8nmat/heartbeat-watcher-activation; activation then waits for the owner's REVIEWED flip of this contract and the "
    "lane's, a promote, the shadow-fire proof and a cron grant. "
    "Activation packet: ~/n8n-maturity-verification/packets/heartbeat-watcher-activate",
    "approval-router": "HELD, imported inactive and unpublished since 2026-10-10 15:58 ET (W0 rollback, grant "
    "f9c459a230d3bc58): its GET /due filter names lane approval-escalate, which has no registry row",
}
GENERIC_STATE_DEFAULT = "state not recorded in build_n8n_health_contracts.GENERIC_STATE"

#: Extra contract facts for one generic workflow, merged after the shared ones (edges, criteria, remediation note).
GENERIC_EXTRA: dict[str, dict[str, Any]] = {
    "heartbeat-watcher": {
        "connects_to": [
            (
                "host lane heartbeat-watch (scripts/heartbeat_watch.py; registry stage shadow)",
                "lane",
                "calls",
                "design 02 §7",
            ),
            (
                "relay POST /event lane n8n-workflow-error (as this workflow's errorWorkflow posts it)",
                "relay_route",
                "calls",
                "scripts/n8n_run_relay.py EVENT_LANE",
            ),
            (
                "fan-in incident wferr:tradeai-heartbeat-watcher, P1 (WFERR_P1_WORKFLOWS) -> incident-notifier",
                "lane",
                "read",
                "scripts/n8n_incident_fanin.py _wferr_severity",
            ),
        ],
        "healthy": [
            {
                "check": "observe_mode_skip",
                "text": "while heartbeat-watch is at stage shadow (dispatch dry_run) every tick posts its run and "
                "'Assert heartbeat fresh' returns skipped=dispatched_dry_run: healthy, but it proves only the "
                "n8n -> relay -> gateway -> executor path, not lane freshness",
            },
            {
                "check": "live_run_fresh",
                "text": "at stage canary or cutover: GET /runs/heartbeat-watch/last?mode=live is RUN_DONE and "
                "finished within 600 s (MAX_AGE_S in the workflow)",
            },
        ],
        "failed": [
            {
                "check": "lane_unregistered",
                "text": "GET /due answers 403 bad_lane_filter when heartbeat-watch is not a registry row of the "
                "served release (the W0 cause; true until the lane's registry row is promoted, and "
                "check_n8n_relay_contract refuses lane_filter_unknown until then)",
            },
            {
                "check": "no_live_run",
                "text": "at stage canary or cutover: no live RUN_DONE of heartbeat-watch within 600 s (Stop And Error "
                "'no live RUN_DONE'), i.e. the executor, the lane or its receipt stopped",
            },
        ],
        "remediation_note": "Additive dead-man, not the P1 path (AGENTS.md §24.1): its only alert route is the "
        "health plane it watches (relay POST /event -> gateway -> fan-in, which itself runs on n8n -> incident-notifier "
        "on host cron), so it cannot page when the notifier or host cron is down; the host-side floor stays "
        "tradeai-n8n-lab-watchdog.timer, the notifier's own fan-in age check and supervisor-breach-detector.timer. "
        "Rollback = unpublish (packets/heartbeat-watcher-activate/rollback.sh) under the activation's cron grant.",
    },
}

WFERR_REMEDIATION = (
    "workflow errors become gateway events on lane n8n-workflow-error (relay POST /event); the fan-in reads them "
    "since #1679 as one incident wferr:<workflow_id> per UTC day (P1 for the dispatcher, incident router and "
    "heartbeat watcher; others P2 unless the contract raises them) and closes it 60 min after the last error"
)


def _workflow_source(wf: Mapping[str, Any]) -> dict[str, Any]:
    """Only a declared public source graph, never n8n state or credential data."""
    import re

    filename = wf.get("file")
    if not isinstance(filename, str) or not re.fullmatch(r"[a-z0-9-]+\.json", filename):
        return {}
    path = ROOT / "docs/implementation/n8n-maturity/workflows" / filename
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return source if isinstance(source, dict) and source.get("id") == wf.get("id") else {}


def generic_contract(
    wf: Mapping[str, Any], as_of: date, *, workflow_source: Optional[Mapping[str, Any]] = None
) -> dict[str, Any]:
    # Local import avoids the auditor -> builder.baseline module-level cycle.
    from scripts.audit_n8n_contract_baselines import source_values

    kind = str(wf.get("kind"))
    source = workflow_source if workflow_source is not None else _workflow_source(wf)
    values = source_values({"id": wf["id"], "kind": "generic_workflow"}, {}, {}, {wf["id"]: source})
    base = baseline(
        [],
        cadence_h=values.get("cadence_h", {}).get("value"),
        timeout_s=values.get("timeout_s", {}).get("value"),
        cls="generic_workflow",
        as_of=as_of,
    )
    base.update(
        source="Source-declared workflow schedule and settings.executionTimeout; empirical execution history NOT_MEASURED",
        source_declarations=values,
        runs_considered=None,
    )
    if base["timeout_s"] is None or base["freshness_degraded_after_h"] is None:
        base["collection_action"] = (
            "Collect this workflow's declared bounded executionTimeout and recurring schedule; owner review required before acceptance"
        )
    text, src = GENERIC.get(kind, (H.UNKNOWN, "none"))
    calls = [
        _edge(f"relay {c}", "relay_route", "calls", "workflows/INDEX.json relay_calls")
        for c in wf.get("relay_calls") or []
    ]
    calls.append(_edge("credential tradeai-run-relay (relay bearer)", "credential", "read", "AGENTS.md §23.5"))
    if wf.get("error_workflow"):
        calls.append(_edge(f"errorWorkflow {wf['error_workflow']}", "workflow", "calls", "workflows/INDEX.json"))
    extra = GENERIC_EXTRA.get(kind, {})
    calls += [_edge(*e) for e in extra.get("connects_to", ())]
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
        "state_note": GENERIC_STATE.get(kind, GENERIC_STATE_DEFAULT),
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
        ]
        + list(extra.get("healthy", [])),
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
        ]
        + list(extra.get("failed", [])),
        "baseline": base,
        "alerting": alerting(sev, "generic workflow: dispatcher/incident/heartbeat Critical, others High (DRAFT)"),
        "remediation": {
            "catalogue_entry": False,
            "diagnosis_excluded": False,
            "note": WFERR_REMEDIATION
            + "; "
            + extra.get(
                "remediation_note",
                "rollback = unpublish + archive under a cron grant (packets/w0-import-six/rollback.sh)",
            ),
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
    from scripts.audit_n8n_contract_baselines import positive_number, source_values

    h = HOST[lane]
    cadence_h = row.get("expected_cadence_hours")
    sig = (row.get("output_signal") or {}).get("path")
    values = source_values({"id": lane, "kind": "host_monitor"}, {lane: row}, {}, {})
    if positive_number(cadence_h):
        values["cadence_h"] = {
            "value": cadence_h,
            "path": "config/lane_registry.json",
            "pointer": f"lanes[{lane}].expected_cadence_hours",
        }
    timeout_s = values.get("timeout_s", {}).get("value")
    entry = {"timeout_s": timeout_s} if timeout_s else None
    c = lane_contract(lane, "host_monitor", row, entry, None, None, frozenset(), [], as_of)
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
    c["baseline"].update(
        source="Source-declared host monitor cadence and install-line timeout; empirical host execution history NOT_MEASURED",
        source_declarations=values,
        runs_considered=None,
    )
    if timeout_s is None:
        c["baseline"]["collection_action"] = (
            "Collect the host monitor's explicit bounded timeout from its owner-approved scheduler declaration"
        )
    return c


#: healthy/failed checks that belong to an authored expected_output rule (FW-M6), kept across regeneration.
OUTPUT_CHECKS = frozenset({"output_produced", "empty_output", "output_unverifiable"})


def _preserve_draft(generated: dict[str, Any], previous: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep authored limits and ownership; retain history without manufacturing review."""
    if not previous or previous.get("status") != "DRAFT":
        return generated
    from scripts.audit_n8n_contract_baselines import FIELDS, positive_number
    from scripts.lib.n8n_momentum_lifecycle import contract_body_digest

    old_base = previous.get("baseline") or {}
    if all(positive_number(old_base.get(field)) for field in FIELDS):
        generated["baseline"] = copy.deepcopy(old_base)
    else:
        # Existing valid numbers may be owner-set bounds; a source default cannot replace them.
        for field, value in old_base.items():
            if field not in FIELDS or positive_number(value):
                generated["baseline"][field] = copy.deepcopy(value)
    for field in ("owner", "ownership_confirmation"):
        if field in previous:
            generated[field] = copy.deepcopy(previous[field])
    # 2026-10-15 (FW-M6): the evidence-derived expected_output rule and its healthy/failed checks are authored
    # content, not a source default; a regeneration keeps them.
    if isinstance(previous.get("expected_output"), Mapping):
        generated["expected_output"] = copy.deepcopy(previous["expected_output"])
        for section in ("healthy", "failed"):
            have = {x.get("check") for x in generated.get(section) or [] if isinstance(x, Mapping)}
            generated[section] = list(generated.get(section) or []) + [
                copy.deepcopy(x)
                for x in previous.get(section) or []
                if isinstance(x, Mapping) and x.get("check") in OUTPUT_CHECKS and x.get("check") not in have
            ]
        basis = (previous.get("evidence") or {}).get("expected_output_basis")
        if basis and isinstance(generated.get("evidence"), dict):
            generated["evidence"]["expected_output_basis"] = basis
    if "review" in previous:
        generated["review"] = copy.deepcopy(previous["review"])
        if isinstance(generated["review"], dict) and "proposed_contract_body_sha256" in generated["review"]:
            generated["review"]["proposed_contract_body_sha256"] = contract_body_digest(generated)
    return generated


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
    workflow_sources: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    rows = {str(r.get("lane_id")): r for r in registry.get("lanes") or []}
    raw_entries = allowlist.get("lanes") or []
    entries = raw_entries if isinstance(raw_entries, Mapping) else {str(e.get("lane_id")): e for e in raw_entries}
    cats = {str(c.get("lane_id")): c for c in catalogue.get("lanes") or []}
    kept = {str(c.get("id")): c for c in (existing or {}).get("contracts") or [] if c.get("status") == "REVIEWED"}
    previous = {str(c.get("id")): c for c in (existing or {}).get("contracts") or []}
    out: list[dict[str, Any]] = []
    for lane, why in sorted(H.registry_targets(registry).items()):
        if lane in kept:
            out.append(copy.deepcopy(kept[lane]))
            continue
        row = rows[lane]
        if lane in HOST:
            out.append(_preserve_draft(host_contract(lane, row, as_of), previous.get(lane)))
            continue
        inv = pick_inventory_row(list(inventory.get(lane) or []), (row.get("scheduler") or {}).get("kind"))
        out.append(
            _preserve_draft(
                lane_contract(
                    lane, why, row, entries.get(lane), inv, cats.get(lane), excluded, ledger_runs(ledger, lane), as_of
                ),
                previous.get(lane),
            )
        )
    for wf in sorted(index.get("workflows") or [], key=lambda w: str(w.get("id"))):
        cid = str(wf["id"])
        if cid in kept:
            out.append(copy.deepcopy(kept[cid]))
        else:
            source = workflow_sources.get(cid, {}) if workflow_sources is not None else None
            out.append(_preserve_draft(generic_contract(wf, as_of, workflow_source=source), previous.get(cid)))
    generated_ids = {c["id"] for c in out}
    # Registry target changes do not authorize retiring contracts, including GET-only
    # observers and historical/retired rows. No host-run eligibility row is created.
    out.extend(copy.deepcopy(c) for cid, c in sorted(previous.items()) if cid not in generated_ids)
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
