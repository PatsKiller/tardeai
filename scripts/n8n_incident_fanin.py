#!/usr/bin/env python3
"""n8n_incident_fanin.py — one list of open incidents from the receipts that already exist.

Roadmap Phase 1 (2026-10-07). Reads, never checks: the breach detector's per-lane rows,
the five `--alert` timer receipts, the bridge watchdog, the n8n lab watchdog, the lab
backup receipt, and (2026-10-09) the P16 activation-attribution and P18 workflow-drift receipts. Every open finding becomes ONE coordination event on lane `incident-fanin`
(idempotent per source+item+UTC day), walked to ARTIFACT_WRITTEN with a reference to the
source receipt. A finding that disappears is closed with a `consumer_ack` from
`recovery-observer`. Operator acks (Telegram) are a separate, later hook.

    python3 scripts/n8n_incident_fanin.py --dry-run
    python3 scripts/n8n_incident_fanin.py --apply

Receipt: $TRADEAI_STATE_ROOT/data/runtime/n8n_incident_fanin_last.json (N8nIncidentFanin@v1)
The gateway must run with `--allow-lane incident-fanin`; otherwise every event is refused
`unknown_lane` and the receipt says so.

AUTHORITY: READ_ONLY_ADVISORY. No send, no restart, no remediation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_gateway_client import GatewayClient, walk_to_artifact  # noqa: E402
from scripts.lib.n8n_pilot_observations import served_sha, state_root  # noqa: E402

# Source of truth: scripts/n8n_run_executor.py LAST_REL (the heartbeat sits beside, not inside, n8n_runs/).
# Kept as a literal so this reader does not import the executor entrypoint; the drift test
# tests/test_n8n_migration_board_20261008.py asserts executor, board and fan-in agree.
EXECUTOR_LAST_REL = "data/runtime/n8n_run_executor_last.json"

SCHEMA = "N8nIncidentFanin@v1"
NO_CONSUMER_REASON = (
    "Roadmap Phase 1 incident fan-in. Consumed by the coordination projection route once the gateway runs; "
    "no cron line exists until the operator installs it (lane n8n-incident-fanin, NEVER_SCHEDULED)."
)
LANE = "incident-fanin"
# This script's own receipt, relative to the state root. scripts/incident_notifier.py reads it from here.
RECEIPT_REL = "data/runtime/n8n_incident_fanin_last.json"
NOTES: dict[str, str] = {}   # per-source availability notes, copied onto the receipt (2026-10-08)
LANE_REGISTRY_RECEIPT_REL = "data/runtime/n8n_lane_registry_drift_last.json"
AUTHORITY = "READ_ONLY_ADVISORY"
SEV = {"NO_OUTPUT": "P2", "SILENT": "P2", "HUNG": "P1", "FAILING": "P1", "BACKLOG": "P2", "MEMORY_UNREACHABLE": "P1",
       "SLO_MISS": "P2", "UNGOVERNED": "P3"}


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _tail_jsonl(path: Path, max_bytes: int = 2_000_000) -> list[dict]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            chunk = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    rows = []
    for ln in chunk.splitlines()[1 if size > max_bytes else 0:]:
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows


SCALP_RECEIPT_REL = "data/runtime/trade_ai_scalp_live_last.json"   # scripts/run_trade_ai_scalp_live.py receipt_path()
SCALP_STALL_MIN = 12          # > two 5-min cycles plus the 295 s run budget
SCALP_RTH_MIN = (9 * 60 + 30 + SCALP_STALL_MIN, 16 * 60)   # ET minutes; the first cycle needs time to land


def _scalp_lane_findings(root: Path, now: datetime) -> list[dict[str, Any]]:
    """trade-ai-scalp-live:STALLED (P2) when the receipt's last_ok_at is older than SCALP_STALL_MIN in RTH."""
    from zoneinfo import ZoneInfo

    et = now.astimezone(ZoneInfo("America/New_York"))
    minute = et.hour * 60 + et.minute
    if et.weekday() >= 5 or not SCALP_RTH_MIN[0] <= minute < SCALP_RTH_MIN[1]:
        return []
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from market_session import is_trading_day
        if not is_trading_day():
            return []
    except Exception:  # noqa: BLE001 — a broken calendar check fails open to the weekday rule
        pass
    doc = _load(root / SCALP_RECEIPT_REL)
    if doc is None:
        NOTES["scalp_lane_source"] = "no_receipt"
        return []
    try:
        age_min = (now - datetime.fromisoformat(str(doc.get("last_ok_at")))).total_seconds() / 60
    except Exception:  # noqa: BLE001 — no ok yet today reads as stalled
        age_min = None
    NOTES["scalp_lane_source"] = f"ok:last_ok_age_min={None if age_min is None else round(age_min, 1)}"
    if age_min is not None and age_min <= SCALP_STALL_MIN:
        return []
    day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return [{"source": "scalp_lane", "item": "trade-ai-scalp-live:STALLED", "severity": "P2",
             "detail": f"no completed scalp cycle for {'?' if age_min is None else round(age_min)} min "
                       f"(last_ok_at {doc.get('last_ok_at')}, status {doc.get('status')})",
             "artifact_rel": SCALP_RECEIPT_REL, "store": "data/runtime", "detected_at": day}]


def _scalp_cycle_findings(root: Path, now: datetime) -> list[dict[str, Any]]:
    """ScalpCycleReceipt@v1 rules (scripts/lib/scalp_cycle_monitor.py): P2 MISSED_CYCLES on 2 consecutive missed
    RTH slots, P1 NO_CYCLES_30M on 30 min of RTH without an ok cycle. Outside RTH it is always quiet.

    A MISSING ledger during RTH is "no cycles", not silence: the lane not running at all is exactly what the P1 is
    for. Only the P1 can fire then (P2 needs per-slot evidence), and not while the legacy last-run receipt shows an
    ok cycle inside the P1 window (the promote day: the first ledger record is at most one slot away)."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        import scalp_cycle_monitor as scm
        import scalp_cycle_receipt as scr
        from zoneinfo import ZoneInfo

        day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        has_ledger = scr.ledger_path(day, root).exists()
        doc = scm.evaluate(scr.read_day(day, root) if has_ledger else [], now, day=day)
    except Exception as e:  # noqa: BLE001 — a broken monitor is a note, not a page
        NOTES["scalp_cycle_source"] = f"error:{type(e).__name__}"
        return []
    if has_ledger:
        NOTES["scalp_cycle_source"] = f"ok:{doc['slots_ok']}/{doc['slots_due']}"
        return list(doc["incidents"])
    NOTES["scalp_cycle_source"] = "no_ledger"
    legacy = _load(root / SCALP_RECEIPT_REL) or {}
    try:
        legacy_age_min = (now - datetime.fromisoformat(str(legacy.get("last_ok_at")))).total_seconds() / 60
    except Exception:  # noqa: BLE001 — no legacy ok reads as no cycles
        legacy_age_min = None
    if legacy_age_min is not None and legacy_age_min < scm.P1_GAP_MIN:
        return []
    return [i for i in doc["incidents"] if i["severity"] == "P1"]


PREV_RECEIPT: dict[str, Any] | None = None   # main() parks the previous fan-in receipt here before collect()


def collect(root: Path, now: datetime, prev: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Open findings, each {source, item, severity, detail, artifact_rel, store}.

    `prev` is the previous fan-in receipt (this script's own last file) for the sources that diff a counter
    across runs (relay auth failures); it defaults to PREV_RECEIPT, None on the first run or without a receipt."""
    if prev is None:
        prev = PREV_RECEIPT
    rt = root / "data" / "runtime"
    out: list[dict[str, Any]] = []
    # 1. breach detector per-lane rows (OPEN, today or yesterday by breach_id day)
    # The breach ledger is append-only and rows never flip to CLOSED, so "open" means: detected in
    # the last 48 h (the detector re-emits a breach_id per lane+kind+day while it persists).
    latest: dict[str, dict] = {}
    for r in _tail_jsonl(rt / "supervisor_breaches.jsonl"):
        if r.get("state") != "OPEN":
            continue
        try:
            age_h = (now - datetime.fromisoformat(str(r.get("detected_at")))).total_seconds() / 3600
        except Exception:
            continue
        if age_h > 48:
            continue
        latest[f"{r.get('lane_id')}:{r.get('kind')}"] = r
    for r in latest.values():
        kind = str(r.get("kind") or "")
        out.append({"source": "breach_detector", "item": f"{r.get('lane_id')}:{kind}", "severity": SEV.get(kind, "P3"),
                    "detail": str(r.get("evidence") or "")[:160], "artifact_rel": "data/runtime/supervisor_breaches.jsonl",
                    "store": "data/runtime", "detected_at": r.get("detected_at")})
    # 2. --alert timer receipts
    specs = [
        ("expected_services", "expected_services_last_run.json", "off_items", "P1"),
        ("data_source_health", "data_source_health_last_run.json", "off_items", "P2"),
        ("served_copy_split", "served_copy_split_last_run.json", "split_items", "P1"),
        ("data_plausibility", "data_plausibility_last_run.json", "blocking_items", "P2"),
    ]
    for src, fn, key, sev in specs:
        doc = _load(rt / fn)
        if not doc:
            continue
        for item in doc.get(key) or []:
            out.append({"source": src, "item": str(item), "severity": sev, "detail": f"{src} ran_at {doc.get('ran_at')}",
                        "artifact_rel": f"data/runtime/{fn}", "store": "data/runtime", "detected_at": doc.get("ran_at")})
    doc = _load(rt / "gap_resolution_last_run.json")
    if doc:
        for cat, items in (doc.get("findings") or {}).items():
            n = len(items) if isinstance(items, list) else (items if isinstance(items, int) else 0)
            if n:
                out.append({"source": "gap_resolution", "item": f"{cat}:{n}", "severity": "P3",
                            "detail": f"{n} findings ran_at {doc.get('ran_at')}", "artifact_rel": "data/runtime/gap_resolution_last_run.json",
                            "store": "data/runtime", "detected_at": doc.get("ran_at")})
    # 3. watchdogs
    doc = _load(rt / "cio_bridge_watchdog.json")
    if doc and (doc.get("alert_needed") or str(doc.get("status") or "").lower() not in {"ok", "healthy", ""}):
        out.append({"source": "cio_bridge_watchdog", "item": str(doc.get("status")), "severity": "P1",
                    "detail": f"consecutive_wedged={doc.get('consecutive_wedged')}", "artifact_rel": "data/runtime/cio_bridge_watchdog.json",
                    "store": "data/runtime", "detected_at": doc.get("checked_at")})
    doc = _load(rt / "n8n_lab_watchdog_last.json")
    if doc and doc.get("ok") is False:
        out.append({"source": "n8n_lab_watchdog", "item": "healthz", "severity": "P2", "detail": str(doc.get("reason") or doc.get("status")),
                    "artifact_rel": "data/runtime/n8n_lab_watchdog_last.json", "store": "data/runtime", "detected_at": doc.get("as_of")})
    # 3b. database hygiene (report_db_hygiene.py, nightly): every finding stays open until fixed
    doc = _load(rt / "db_hygiene_last.json")
    if doc:
        for f in doc.get("findings") or []:
            out.append({"source": "db_hygiene", "item": f"{f.get('code')}:{f.get('item')}", "severity": str(f.get("severity") or "P3"),
                        "detail": str(f.get("detail") or "")[:160], "artifact_rel": "data/runtime/db_hygiene_last.json",
                        "store": "data/runtime", "detected_at": doc.get("as_of")})
    # 3c. lane-registry drift (Phase 2 PR-B, 2026-10-08): the gate's findings between CI runs. Pure
    # library calls over the live registry + crontab + timer names; fail-soft, never a crash of the fan-in.
    NOTES.pop("lane_registry_source", None)
    try:
        import subprocess as _sp
        from scripts.lib.lane_registry import discover_systemd, load_registry
        from scripts.lib.lane_registry_drift import findings as _drift_findings
        if os.environ.get("TRADEAI_FANIN_LANE_REGISTRY", "1") == "0":
            raise RuntimeError("disabled_by_env")        # hermetic callers (tests) opt out of probing the host
        reg = load_registry(ROOT / "config" / "lane_registry.json")
        _cron = _sp.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
        if _cron.returncode != 0:
            raise RuntimeError("no_crontab")             # CI runners and fresh hosts: nothing to compare against
        cron_text = _cron.stdout
        units = [str(u.get("expression") or "") for u in discover_systemd()]
        drift = _drift_findings(reg, cron_text, units)
        NOTES["lane_registry_source"] = f"ok:{len(drift)}"
    except Exception as exc:   # noqa: BLE001 — a broken source is a note on the receipt, not a crash
        drift = []
        NOTES["lane_registry_source"] = f"unavailable:{type(exc).__name__}:{str(exc)[:80]}"
    for f in drift:
        out.append({"source": "lane_registry", "code": f["code"], "item": f["item"], "severity": f["severity"], "detail": f["detail"][:160],
                    "artifact_rel": LANE_REGISTRY_RECEIPT_REL, "store": "data/runtime",
                    "detected_at": now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()})   # stable per UTC day = stable payload
    # 3d. notification outbox (Phase 2 PR-A, 2026-10-08): withdrawn sends, sends stuck pending > 30 min, suppression
    # spike. Read through the projection with a 3 s statement timeout; no DB -> no findings, receipt says so.
    out.extend(_outbox_findings(now))
    # 3e. n8n run ledger (scheduler-of-record program, stream G, 2026-10-08): a RUN_FAILED / RUN_TIMEOUT on a lane
    # whose scheduler of record is n8n is a P2 (plan rollback trigger); an executor receipt older than 2x the
    # shortest n8n cadence is a P1 (executor stalled). Closes itself on the next RUN_DONE because the finding
    # disappears. Env opt-out keeps CI fixtures without a ledger stable (same reason as lane_registry's no_crontab).
    out.extend(_runs_findings(root, now))
    # 3f. n8n run relay (observability gaps PR, 2026-10-08): the relay's last file carries cumulative counts.
    # auth_failures rising by >= RELAY_AUTH_FAILURE_STEP since the previous fan-in receipt is a P2 (a bad or
    # rotated-out bearer is being presented); a relay last file older than 2x the shortest n8n cadence while
    # the executor is running n8n lanes and the unit is expected is a P1 (relay down: n8n cannot ask for runs).
    # Clears on the next file with no new failures. TRADEAI_FANIN_RELAY=0 opts out, like the runs source.
    out.extend(_relay_findings(root, now, prev))
    # 3g. Trade-AI scalp scan (operator 2026-10-09 "n8n drives a governed lane"): no completed cycle for
    # SCALP_STALL_MIN in RTH on a trading day is a P2. One event per UTC day; clears on the next ok receipt.
    out.extend(_scalp_lane_findings(root, now))
    # 3h. Scalp cycle ledger (n8n maturity B4, 2026-10-09): per-slot ScalpCycleReceipt@v1 rules, market-hours aware.
    out.extend(_scalp_cycle_findings(root, now))
    # 3i. Dead-letter queue + breakers (n8n maturity B5 follow-up, 2026-10-09): one P2 per unreleased dead letter,
    # one P2 per open breaker. Ledger tables first (read-only), ExecutorStatus@v1 as the cross-check / fallback.
    out.extend(_dlq_findings(root, now))
    # 3j. n8n governance checks (AGENTS.md 3.0.0 §23.10 P16/P18, 2026-10-09): host-side cron receipts of
    # scripts/check_n8n_activation_grants.py and scripts/check_n8n_workflow_drift.py. See _governance_findings.
    out.extend(_governance_findings(root, now, prev))
    # 3k. LLM failure diagnosis (REMEDIATION_PLAN §6 R4/R5, 2026-10-10): the diagnoser's escalations (P1 low confidence,
    # refused action or failed remediation; P2 suggestion / approval) and its own liveness (a stale, failed or
    # blind diagnoser is a P1). The diagnoser never sends; the incident notifier carries these. See _diagnosis_findings.
    out.extend(_diagnosis_findings(root, now))
    doc = _load(root / "backups" / "n8n" / "n8n_lab_backup_last.json")
    if doc:
        try:
            age_h = (now - datetime.fromisoformat(str(doc.get("as_of")))).total_seconds() / 3600
        except Exception:
            age_h = None
        if doc.get("ok") is False or (age_h is not None and age_h > 48):
            out.append({"source": "n8n_lab_backup", "item": "stale_or_failed", "severity": "P2",
                        "detail": f"ok={doc.get('ok')} age_h={None if age_h is None else round(age_h, 1)}",
                        "artifact_rel": "backups/n8n/n8n_lab_backup_last.json", "store": "persistent-state", "detected_at": doc.get("as_of")})
    return out


OUTBOX_SOURCE_STATUS: dict[str, Any] = {"status": "not_run"}
# The executor's heartbeat. Source of truth: scripts/n8n_run_executor.py LAST_REL (data/runtime/, NOT the
# n8n_runs/ receipt dir). Measured live on 72b0ce6be (2026-10-08): this read pointed at n8n_runs/ so
# executor:stalled and relay:down could never fire. Kept as the identical literal rather than an import
# because importing the executor pulls the ledger + gateway modules into the fan-in at import time.
EXECUTOR_LAST_REL = "data/runtime/n8n_run_executor_last.json"
RUNS_STALE_FACTOR = 2.0
RUNS_FAILURE_STATES = ("RUN_FAILED", "RUN_TIMEOUT")


def _runs_findings(root: Path, now: datetime) -> list[dict[str, Any]]:
    """Latest run per n8n-scheduled lane from the ledger `runs` table (read-only projection) + executor liveness."""
    NOTES.pop("runs_source", None)
    try:
        if os.environ.get("TRADEAI_FANIN_RUNS", "1") == "0":
            raise RuntimeError("disabled_by_env")
        from scripts.lib.lane_registry import load_registry
        from scripts.lib.n8n_coordination_projection import RUNS_RECEIPT_DIR, project_runs
        reg = load_registry(ROOT / "config" / "lane_registry.json")
        n8n_lanes = {str(r.get("lane_id")): r for r in reg.get("lanes") or []
                     if (r.get("scheduler") or {}).get("kind") == "n8n" and r.get("state") == "ACTIVE"}
        if not n8n_lanes:
            NOTES["runs_source"] = "ok:no_n8n_lanes"
            return []
        proj = project_runs(limit=500, now=now)
        if proj.get("status") != "OK":
            raise RuntimeError(str(proj.get("status")))
        latest: dict[str, dict[str, Any]] = {}
        for it in proj.get("items") or []:          # newest first
            lane = str(it.get("lane_id") or "")
            if lane in n8n_lanes and lane not in latest:
                latest[lane] = it
        found: list[dict[str, Any]] = []
        for lane, it in sorted(latest.items()):
            st = str(it.get("state") or "")
            if st in RUNS_FAILURE_STATES:
                found.append({"source": "runs", "item": f"{lane}:{st}", "severity": "P2",
                              "detail": f"run {it.get('run_id')} {it.get('mode')} exit={it.get('exit_code')} duration_s={it.get('duration_s')}"[:160],
                              "artifact_rel": str(it.get("receipt_ref") or f"{RUNS_RECEIPT_DIR}/{it.get('run_id')}.json"),
                              "store": "data/runtime", "detected_at": it.get("finished_at") or it.get("requested_at")})
        exec_rel = EXECUTOR_LAST_REL
        exec_doc = _load(root / exec_rel)
        cadences = [float(r["expected_cadence_hours"]) for r in n8n_lanes.values() if r.get("expected_cadence_hours")]
        if exec_doc and cadences:
            ts = exec_doc.get("finished_at") or exec_doc.get("as_of") or exec_doc.get("at")
            try:
                age_h = (now - _stable(ts, now)).total_seconds() / 3600
            except Exception:  # noqa: BLE001
                age_h = None
            if age_h is not None and age_h > RUNS_STALE_FACTOR * min(cadences):
                found.append({"source": "runs", "item": "executor:stalled", "severity": "P1",
                              "detail": f"executor_last age_h={age_h:.1f} > {RUNS_STALE_FACTOR}x shortest n8n cadence {min(cadences)}h",
                              "artifact_rel": exec_rel, "store": "data/runtime",
                              "detected_at": now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()})
        NOTES["runs_source"] = f"ok:{len(found)}:n8n_lanes={len(n8n_lanes)}:executor_receipt={'yes' if exec_doc else 'no'}"
        return found
    except Exception as exc:  # noqa: BLE001 — a broken source is a note on the receipt, not a crash
        NOTES["runs_source"] = f"unavailable:{type(exc).__name__}:{str(exc)[:80]}"
        return []


LEDGER_REL = "data/governance/n8n_coordination_ledger.sqlite"   # n8n_coordination_projection.ledger_path()
EXECUTOR_STATUS_SCHEMA = "ExecutorStatus@v1"                      # n8n_run_executor STATUS_SCHEMA (executor v2)


def _dlq_ledger_rows(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """(unreleased dead letters, open breakers) from the ledger, opened read-only (mode=ro, no migration).
    None when the file or the B5.4 tables are absent (pre-#1594 ledger)."""
    import sqlite3

    from scripts.lib.n8n_coordination_ledger import breaker_is_open

    if not path.exists():
        return None
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"dead_letters", "breakers"} <= tables:
            return None
        dead = [dict(r) for r in conn.execute(
            "SELECT slot_key, lane_id, mode, attempts, last_state, last_reason, dead_at FROM dead_letters"
            " WHERE released_at IS NULL ORDER BY dead_at, slot_key")]
        brk = [dict(r) for r in conn.execute(
            "SELECT lane_id, opened_at, consecutive, released_at FROM breakers ORDER BY lane_id")]
        return dead, [b for b in brk if breaker_is_open(b)]
    finally:
        conn.close()


def _dlq_findings(root: Path, now: datetime) -> list[dict[str, Any]]:
    """P2 `dlq:<slot_key>` per unreleased dead letter, P2 `breaker:<lane>` per open breaker.

    A finding stays open until the operator releases it (n8n_dlq.py release) or a RUN_DONE auto-releases the
    breaker; then it disappears and the fan-in closes it. The ledger is the record of truth; the executor's
    ExecutorStatus@v1 (`breakers_open`, `dlq_24h`) adds breakers the ledger read missed and, when the ledger cannot
    be read, stands in: its breakers and one aggregate `dlq:status_count` finding. TRADEAI_FANIN_DLQ=0 opts out."""
    NOTES.pop("dlq_source", None)
    if os.environ.get("TRADEAI_FANIN_DLQ", "1") == "0":
        NOTES["dlq_source"] = "unavailable:disabled_by_env"
        return []
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    ledger = Path(explicit) if explicit else root / LEDGER_REL
    try:
        rows = _dlq_ledger_rows(ledger)
        ledger_note = "ok" if rows is not None else "absent"
    except Exception as exc:  # noqa: BLE001 — a broken source is a note on the receipt, not a crash
        rows = None
        ledger_note = f"error:{type(exc).__name__}"
    status = _load(root / EXECUTOR_LAST_REL)
    if not (isinstance(status, dict) and status.get("schema") == EXECUTOR_STATUS_SCHEMA):
        status = None
    day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    found: list[dict[str, Any]] = []
    dead, breakers = rows if rows is not None else ([], [])
    for d in dead:
        found.append({"source": "dlq", "item": f"dlq:{d.get('slot_key')}", "severity": "P2",
                      "detail": f"{d.get('lane_id')} {d.get('mode') or ''} {d.get('last_state') or ''} "
                                f"{d.get('last_reason') or ''} attempts {d.get('attempts')}"[:160],
                      "artifact_rel": LEDGER_REL, "store": "persistent-state",
                      "detected_at": d.get("dead_at") or day})
    open_lanes = {str(b.get("lane_id")): b for b in breakers}
    ledger_lanes = set(open_lanes)
    for lane in (status or {}).get("breakers_open") or []:
        open_lanes.setdefault(str(lane), {"lane_id": str(lane), "opened_at": None, "consecutive": None})
    for lane, b in sorted(open_lanes.items()):
        found.append({"source": "dlq", "item": f"breaker:{lane}", "severity": "P2",
                      "detail": f"breaker open: {b.get('consecutive')} consecutive dead slots; lane paused"[:160],
                      "artifact_rel": LEDGER_REL if lane in ledger_lanes else EXECUTOR_LAST_REL,
                      "store": "persistent-state" if lane in ledger_lanes else "data/runtime",
                      "detected_at": b.get("opened_at") or day})
    status_dlq = (status or {}).get("dlq_24h")
    if rows is None and isinstance(status_dlq, int) and status_dlq > 0:
        found.append({"source": "dlq", "item": "dlq:status_count", "severity": "P2",
                      "detail": f"executor reports {status_dlq} dead letter(s) in 24 h; ledger {ledger_note}",
                      "artifact_rel": EXECUTOR_LAST_REL, "store": "data/runtime", "detected_at": day})
    NOTES["dlq_source"] = (f"ledger:{ledger_note}:dead={len(dead)}:breakers={len(breakers)}:"
                           f"status={'yes' if status else 'no'}:status_dlq_24h={status_dlq}")
    return found


RELAY_LAST_REL = "data/runtime/n8n_relay/n8n_run_relay_last.json"
RELAY_UNIT = "tradeai-n8n-run-relay.service"
RELAY_AUTH_FAILURE_STEP = 3        # auth_failures must rise by at least this much between two fan-in receipts
RELAY_STALE_FACTOR = 2.0           # relay last file older than this x the shortest n8n cadence = down
EXPECTED_SERVICES_PATH = ROOT / "config" / "expected_services.json"
RELAY_COUNTS: dict[str, Any] = {}  # copied onto the receipt so the next fan-in can diff auth_failures


def _relay_unit_expected(path: Path = None) -> bool:
    doc = _load(path or EXPECTED_SERVICES_PATH) or {}
    return any(str(u.get("unit") or "") == RELAY_UNIT for u in doc.get("units") or [] if isinstance(u, dict))


def _relay_findings(root: Path, now: datetime, prev: dict[str, Any] | None) -> list[dict[str, Any]]:
    """relay:auth_failures (P2) and relay:down (P1) from the relay's last file; counts are kept on the receipt."""
    global RELAY_COUNTS
    NOTES.pop("relay_source", None)
    RELAY_COUNTS = {}
    try:
        if os.environ.get("TRADEAI_FANIN_RELAY", "1") == "0":
            raise RuntimeError("disabled_by_env")
        doc = _load(root / RELAY_LAST_REL)
        if not doc:
            NOTES["relay_source"] = "ok:no_relay_last"       # never started here: expected_services reports the unit
            return []
        last = doc.get("last") or {}
        counts = doc.get("counts") or {}
        auth = int(counts.get("auth_failures") or 0)
        RELAY_COUNTS = {"auth_failures": auth, "requested": int(counts.get("requested") or 0),
                        "refused": int(counts.get("refused") or 0), "last_at": last.get("at"), "as_of": now.isoformat()}
        found: list[dict[str, Any]] = []
        prev_counts = (prev or {}).get("relay_counts") or {}
        prev_auth = prev_counts.get("auth_failures")
        if prev_auth is not None:
            delta = auth - int(prev_auth)                       # negative after a relay restart (counters reset)
            if delta >= RELAY_AUTH_FAILURE_STEP:
                found.append({"source": "relay", "item": "relay:auth_failures", "severity": "P2",
                              "detail": (f"auth_failures {int(prev_auth)}->{auth} (+{delta}) since fan-in {prev_counts.get('as_of')}; "
                                         f"last {last.get('state')}/{last.get('reason')} at {last.get('at')}")[:160],
                              "artifact_rel": RELAY_LAST_REL, "store": "data/runtime",
                              "detected_at": last.get("at") or now.isoformat()})
        from scripts.lib.lane_registry import load_registry
        reg = load_registry(ROOT / "config" / "lane_registry.json")
        cadences = [float(r["expected_cadence_hours"]) for r in reg.get("lanes") or []
                    if (r.get("scheduler") or {}).get("kind") == "n8n" and r.get("state") == "ACTIVE"
                    and r.get("expected_cadence_hours")]
        exec_doc = _load(root / EXECUTOR_LAST_REL)
        executor_running = False
        if exec_doc and cadences:
            ets = exec_doc.get("finished_at") or exec_doc.get("as_of") or exec_doc.get("at")
            executor_running = (now - _stable(ets, now)).total_seconds() / 3600 <= RUNS_STALE_FACTOR * min(cadences)
        relay_age_h = (now - _stable(last.get("at"), now)).total_seconds() / 3600 if last.get("at") else None
        if (executor_running and relay_age_h is not None and relay_age_h > RELAY_STALE_FACTOR * min(cadences)
                and _relay_unit_expected()):
            found.append({"source": "relay", "item": "relay:down", "severity": "P1",
                          "detail": (f"relay last file age_h={relay_age_h:.1f} > {RELAY_STALE_FACTOR}x shortest n8n cadence "
                                     f"{min(cadences)}h while the executor runs {len(cadences)} n8n lane(s); unit {RELAY_UNIT} expected")[:160],
                          "artifact_rel": RELAY_LAST_REL, "store": "data/runtime",
                          "detected_at": now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()})
        NOTES["relay_source"] = (f"ok:{len(found)}:auth_failures={auth}:prev={prev_auth}:"
                                 f"executor_running={'yes' if executor_running else 'no'}")
        return found
    except Exception as exc:  # noqa: BLE001 — a broken source is a note on the receipt, not a crash
        NOTES["relay_source"] = f"unavailable:{type(exc).__name__}:{str(exc)[:80]}"
        return []


# (fan-in source, receipt, lane_registry lane_id, cadence hours when the registry row has none)
GOVERNANCE_SOURCES = (
    ("n8n_activation_grants", "data/runtime/n8n_activation_grants_last.json", "n8n-activation-grants", 0.5),
    ("n8n_workflow_drift", "data/runtime/n8n_workflow_drift_last.json", "n8n-workflow-drift-check", 1.0),
)
GOVERNANCE_STALE_FACTOR = 3.0      # receipt older than 3x the lane cadence = the check has stopped


def _governance_lane(lane_id: str) -> dict[str, Any] | None:
    """The lane_registry row, or None. Separate so tests can stub it without a registry file."""
    from scripts.lib.lane_registry import load_registry
    reg = load_registry(ROOT / "config" / "lane_registry.json")
    return next((r for r in reg.get("lanes") or [] if r.get("lane_id") == lane_id), None)


def _governance_rows(source: str, doc: dict[str, Any]) -> list[tuple[str, str, str, Any]]:
    """(item, severity, detail, detected_at) per finding, derived from the receipt rows (not its own
    fanin_findings) so the fan-in owns severity. Same map as the checkers' fanin_severity / fanin_findings."""
    out: list[tuple[str, str, str, Any]] = []
    if source == "n8n_activation_grants":
        for r in doc.get("activations") or []:
            st = str(r.get("status") or "")
            if st not in {"UNGRANTED_ACTIVATION", "UNGRANTED_ACTIVATION_REGULARISED", "NAMED_IN_OTHER_TIER",
                          "NAME_ONLY_GRANT"}:
                continue
            # P1 only while the LATEST activation is ungranted and the workflow is live; a regularised window
            # (earlier ungranted, latest granted) stays reported as P3 with its start/end.
            sev = "P1" if st == "UNGRANTED_ACTIVATION" and r.get("currently_active") else "P3"
            win = r.get("ungranted_window") or {}
            detail = f"{r.get('name')} activated {r.get('activated_at')} active={bool(r.get('currently_active'))}"
            if win:
                detail += f" ungranted {win.get('start')}..{win.get('end')}"
            # severity is part of the item: a same-day P3 -> P1 escalation gets its own idempotency key
            out.append((f"{r.get('workflow_id')}:{st}:{sev}", sev, detail, r.get("activated_at")))
    else:
        for r in doc.get("workflows") or []:
            st = str(r.get("status") or "")
            if st in {"DRIFT", "MISSING_IN_GIT"}:
                out.append((f"{r.get('id')}:{st}:P2", "P2", f"{r.get('name')} {','.join(r.get('diffs') or [])}", None))
            if r.get("placeholder_unsubstituted"):
                out.append((f"{r.get('id')}:placeholder_unsubstituted:P2", "P2",
                            f"{r.get('name')} still carries the relay URL placeholder", None))
    return out


def _governance_findings(root: Path, now: datetime, prev: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """P16 activation attribution + P18 git-vs-live drift, read from their receipts.

    Severity: UNGRANTED_ACTIVATION of a currently active workflow P1; ungranted-but-off, name-only and
    other-tier attribution P3; DRIFT / MISSING_IN_GIT / unsubstituted relay placeholder P2 (the executor
    still refuses any lane outside the allowlist, so drift cannot widen what runs on the host).
    Liveness, like the relay source: a missing receipt is only a note until the lane is scheduled
    (registry row ACTIVE with a scheduler); then missing, or older than GOVERNANCE_STALE_FACTOR x cadence,
    is a P2 `receipt:missing` / `receipt:stale`. A stale receipt of an unscheduled lane (a hand run) is
    not read at all. Dedupe is the fan-in's usual source|item|UTC day key; detected_at is the activation
    time or the UTC day start so the payload is stable. TRADEAI_FANIN_GOVERNANCE=0 opts out.
    A broken source (unreadable registry row, malformed receipt) is a note, and also a P2
    `governance:source_unavailable` when the lane is scheduled or the previous fan-in receipt already
    recorded that source unavailable (2 consecutive runs). The env opt-out never alarms."""
    if prev is None:
        prev = PREV_RECEIPT
    prev_notes = (prev or {}).get("source_notes") or {}
    found: list[dict[str, Any]] = []
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    for source, rel, lane_id, default_cadence in GOVERNANCE_SOURCES:
        key = f"{source}_source"
        NOTES.pop(key, None)
        scheduled = False
        if os.environ.get("TRADEAI_FANIN_GOVERNANCE", "1") == "0":
            NOTES[key] = "unavailable:RuntimeError:disabled_by_env"
            continue
        try:
            row = _governance_lane(lane_id) or {}
            scheduled = row.get("state") == "ACTIVE" and (row.get("scheduler") or {}).get("kind") not in (None, "", "none")
            cadence = float(row.get("expected_cadence_hours") or default_cadence) if scheduled else default_cadence
            stale_h = GOVERNANCE_STALE_FACTOR * cadence
            doc = _load(root / rel)
            if not doc:
                if scheduled:
                    found.append({"source": source, "item": "receipt:missing", "severity": "P2",
                                  "detail": f"lane {lane_id} is scheduled but {rel} is missing or unreadable",
                                  "artifact_rel": rel, "store": "data/runtime", "detected_at": day0})
                NOTES[key] = f"ok:no_receipt:scheduled={'yes' if scheduled else 'no'}"
                continue
            age_h = (now - _stable(doc.get("as_of"), now)).total_seconds() / 3600 if doc.get("as_of") else None
            stale = age_h is None or age_h > stale_h
            if stale and not scheduled:
                NOTES[key] = f"ok:stale_unscheduled:age_h={None if age_h is None else round(age_h, 1)}"
                continue
            if stale:
                found.append({"source": source, "item": "receipt:stale", "severity": "P2",
                              "detail": (f"{rel} age_h={None if age_h is None else round(age_h, 1)} > "
                                         f"{GOVERNANCE_STALE_FACTOR}x cadence {cadence}h (lane {lane_id})"),
                              "artifact_rel": rel, "store": "data/runtime", "detected_at": day0})
            rows = _governance_rows(source, doc)
            for item, sev, detail, detected in rows:
                found.append({"source": source, "item": item, "severity": sev, "detail": detail[:160],
                              "artifact_rel": rel, "store": "data/runtime", "detected_at": detected or day0})
            NOTES[key] = (f"ok:{len(rows)}:verdict={doc.get('verdict')}:age_h={None if age_h is None else round(age_h, 2)}:"
                          f"scheduled={'yes' if scheduled else 'no'}{':stale' if stale else ''}")
        except Exception as exc:  # noqa: BLE001 — a broken source is a note on the receipt, not a crash
            NOTES[key] = f"unavailable:{type(exc).__name__}:{str(exc)[:80]}"
            repeated = str(prev_notes.get(key) or "").startswith("unavailable:") and "disabled_by_env" not in str(prev_notes.get(key))
            if scheduled or repeated:
                found.append({"source": source, "item": "governance:source_unavailable", "severity": "P2",
                              "detail": (f"{NOTES[key]} (lane {lane_id} scheduled={'yes' if scheduled else 'unknown/no'}, "
                                         f"previous run unavailable={'yes' if repeated else 'no'})")[:160],
                              "artifact_rel": rel, "store": "data/runtime", "detected_at": day0})
    return found


DIAGNOSIS_SOURCE = "n8n_failure_diagnosis"
DIAGNOSIS_RECEIPT_REL = "data/runtime/n8n_failure_diagnosis_last.json"
DIAGNOSIS_LANE = "n8n-failure-diagnosis"
DIAGNOSIS_DEFAULT_CADENCE_H = 5 / 60
DIAGNOSIS_STALE_FACTOR = 3.0
DIAGNOSIS_BLIND_CYCLES = 2


def _diagnosis_findings(root: Path, now: datetime) -> list[dict[str, Any]]:
    """The diagnoser's receipt (scripts/n8n_failure_diagnosis.py). Escalations are passed through at the priority the
    diagnoser chose (P1/P2), one item per incident key, until the diagnoser drops them (its SIEM row closed).
    Liveness (R5), only once the lane is scheduled: receipt missing or older than 3x cadence, ok false, or
    `consecutive_blind` >= 2 (eligible incidents, no model call, not deferred) is a P1. Escalations from a receipt
    older than 24 h are not passed through (the stale receipt is the finding). TRADEAI_FANIN_DIAGNOSIS=0 opts out."""
    key = "diagnosis_source"
    NOTES.pop(key, None)
    if os.environ.get("TRADEAI_FANIN_DIAGNOSIS", "1") == "0":
        NOTES[key] = "unavailable:RuntimeError:disabled_by_env"
        return []
    found: list[dict[str, Any]] = []
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        row = _governance_lane(DIAGNOSIS_LANE) or {}
    except Exception as exc:  # noqa: BLE001 — a broken registry read is a note, never a crash
        row = {}
        NOTES[key] = f"registry_unavailable:{type(exc).__name__}"
    sched = row.get("scheduler") or {}
    # A shadow-stage dispatcher row runs the diagnoser with --dry-run, which writes no receipt: liveness starts at
    # canary/cutover (or a cron/systemd line), never while it is only shadowed.
    scheduled = (row.get("state") == "ACTIVE" and sched.get("kind") not in (None, "", "none")
                 and sched.get("stage") != "shadow")
    cadence = float(row.get("expected_cadence_hours") or DIAGNOSIS_DEFAULT_CADENCE_H)
    doc = _load(root / DIAGNOSIS_RECEIPT_REL)
    base = {"source": DIAGNOSIS_SOURCE, "artifact_rel": DIAGNOSIS_RECEIPT_REL, "store": "data/runtime"}
    if not doc:
        if scheduled:
            found.append({**base, "item": "diagnoser:receipt_missing", "severity": "P1",
                          "detail": f"lane {DIAGNOSIS_LANE} is scheduled but its receipt is missing", "detected_at": day0})
        NOTES.setdefault(key, f"ok:no_receipt:scheduled={'yes' if scheduled else 'no'}")
        return found
    age_h = (now - _stable(doc.get("as_of"), now)).total_seconds() / 3600 if doc.get("as_of") else None
    if scheduled:
        if age_h is None or age_h > DIAGNOSIS_STALE_FACTOR * cadence:
            found.append({**base, "item": "diagnoser:receipt_stale", "severity": "P1",
                          "detail": f"age_h={None if age_h is None else round(age_h, 2)} > {DIAGNOSIS_STALE_FACTOR}x "
                                    f"cadence {round(cadence, 3)}h", "detected_at": day0})
        if doc.get("ok") is False:
            found.append({**base, "item": "diagnoser:cycle_not_ok", "severity": "P1",
                          "detail": f"source_notes={json.dumps(doc.get('source_notes') or {})[:120]}",
                          "detected_at": day0})
        if int(doc.get("consecutive_blind") or 0) >= DIAGNOSIS_BLIND_CYCLES:
            found.append({**base, "item": "diagnoser:blind", "severity": "P1",
                          "detail": f"{doc.get('consecutive_blind')} cycles with eligible incidents and no diagnosis",
                          "detected_at": day0})
    passed = 0
    if age_h is not None and age_h <= 24:
        for e in doc.get("escalations") or []:
            sev = str(e.get("priority") or "P2")
            if sev not in ("P1", "P2"):
                continue
            found.append({**base, "item": f"escalate:{e.get('lane')}/{e.get('key')}", "severity": sev,
                          "detail": str(e.get("detail") or e.get("reason") or "")[:160],
                          "detected_at": e.get("at") or doc.get("as_of")})
            passed += 1
    NOTES[key] = (f"ok:escalations={passed}:age_h={None if age_h is None else round(age_h, 2)}:"
                  f"scheduled={'yes' if scheduled else 'no'}")
    return found


def _outbox_findings(now: datetime) -> list[dict[str, Any]]:
    """Anomalies from scripts/lib/notification_outbox_projection; fail-soft and recorded in the receipt."""
    global OUTBOX_SOURCE_STATUS
    try:
        from scripts.lib.notification_outbox_projection import anomalies, load_outbox
        model = load_outbox(hours=24, timeout_s=3.0, now=now)
        OUTBOX_SOURCE_STATUS = {"status": model.get("status"), "note": model.get("note"), "total": model.get("total")}
        if model.get("status") != "OK":
            return []
        found = []
        for a in anomalies(model):
            found.append({**a, "artifact_rel": "data/runtime/n8n_incident_fanin_last.json", "store": "data/runtime"})
        return found
    except Exception as exc:  # noqa: BLE001
        OUTBOX_SOURCE_STATUS = {"status": "unavailable", "note": f"{type(exc).__name__}: {str(exc)[:120]}"}
        return []


def idem_key(f: dict[str, Any], day: str) -> str:
    return "inc-" + hashlib.sha256(f"{f['source']}|{f['item']}|{day}".encode("utf-8")).hexdigest()[:24]


def _stable(ts: Any, fallback: datetime) -> datetime:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return fallback


def build_event(f: dict[str, Any], *, day: str, now: datetime, sha: str) -> dict[str, Any]:
    key = idem_key(f, day)
    now = _stable(f.get("detected_at"), now)   # payload must not drift between runs
    return {"event_id": f"evt-{LANE}-{key}", "source_project": "trade-ai", "lane_id": LANE, "schema_version": "event-reference/v0",
            "origin_sha": sha, "subject_key": f"sev={f['severity']};src={f['source']};item={f['item']}"[:200],
            "source_timestamp": now.isoformat(), "deadline": now.replace(hour=23, minute=59, second=0, microsecond=0).isoformat(),
            "artifact_ref": f"{f['store']}:{f['artifact_rel']}", "authority_class": "coordination_read",
            "correlation_id": f"corr-{key}", "idempotency_key": key}


def write_lane_registry_receipt(root: Path, drift: list[dict[str, Any]], now: datetime, sha: str) -> Path:
    """The durable artifact a lane_registry incident references (apply mode only)."""
    p = root / LANE_REGISTRY_RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "N8nLaneRegistryDrift@v1", "authority": AUTHORITY, "as_of": now.isoformat(), "served_sha": sha or None,
           "source_note": NOTES.get("lane_registry_source"), "findings": drift}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--receipt", default=None)
    args = ap.parse_args(argv)
    root = state_root()
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    sha = served_sha() or ""
    out = Path(args.receipt) if args.receipt else (root / RECEIPT_REL)
    prev = _load(out) or {}
    global PREV_RECEIPT
    PREV_RECEIPT = prev
    findings = collect(root, now)
    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    rows: list[dict[str, Any]] = []
    gateway: dict[str, Any] = {}
    prev_open: set[str] = set()
    prev_open = {r["idempotency_key"] for r in prev.get("incidents", []) if r.get("idempotency_key") and r.get("state") == "ARTIFACT_WRITTEN"}
    client = None
    if args.apply:
        client = GatewayClient(caller_id="tradeai-incident-fanin")
        gateway = {"url": client.url, "has_key": client.has_key, "healthz": client.healthz()}
    current_keys: set[str] = set()
    if args.apply:
        write_lane_registry_receipt(root, [f for f in findings if f["source"] == "lane_registry"], now, sha)
    for f in findings:
        ev = build_event(f, day=day, now=now, sha=sha)
        current_keys.add(ev["idempotency_key"])
        row = {**{k: f[k] for k in ("source", "item", "severity", "detail", "detected_at")}, "idempotency_key": ev["idempotency_key"],
               "event_id": ev["event_id"], "ops": []}
        if client is None:
            row["state"] = "DRY_RUN"
        else:
            st = client.status(ev["idempotency_key"])
            if st.get("state") == "UNREACHABLE":
                acc = st
            elif st.get("state") == "REFUSED" and st.get("reason") == "unknown_event":
                acc = client.accept_event(ev)
            else:
                acc = {"state": st.get("state"), "reason": st.get("reason"), "duplicate": True}
            row["ops"].append({"op": "accept_event", "state": acc.get("state"), "reason": acc.get("reason"), "duplicate": acc.get("duplicate")})
            if acc.get("state") == "ACCEPTED" or (acc.get("duplicate") and acc.get("state") not in {"REFUSED", "CONSUMED"}):
                ref = {"store": f["store"], "ref": f["artifact_rel"], "as_of": now.isoformat()}
                p = root / f["artifact_rel"]
                try:
                    ref["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
                except OSError:
                    pass
                row["ops"].extend(walk_to_artifact(client, ev["idempotency_key"], ref))
            row["state"] = row["ops"][-1].get("state") if row["ops"] else "UNKNOWN"
            if acc.get("state") == "CONSUMED":
                row["state"] = "CONSUMED"   # already acknowledged earlier today; still open at the source
        rows.append(row)
    recovered: list[dict[str, Any]] = []
    for key in sorted(prev_open - current_keys):
        rec = {"idempotency_key": key, "ops": []}
        if client is not None:
            r = client.transition("consumer_ack", key, consumer_receipt={"consumer": "recovery-observer", "receipt_id": now.isoformat()})
            rec["ops"].append({"op": "consumer_ack", "state": r.get("state"), "reason": r.get("reason")})
            rec["state"] = r.get("state")
        else:
            rec["state"] = "DRY_RUN"
        recovered.append(rec)
    receipt = {"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "mode": "apply" if args.apply else "dry-run",
               "served_sha": sha or None, "state_root": str(root), "gateway": gateway, "open": len(findings), "by_severity": by_sev,
               "incidents": rows, "recovered": recovered, "outbox_source": OUTBOX_SOURCE_STATUS, "source_notes": dict(NOTES),
               # the relay baseline survives a run where the relay source was off or broken (no false +delta later)
               "relay_counts": dict(RELAY_COUNTS) or prev.get("relay_counts") or None,
               "ok": (not args.apply) or all(r.get("state") not in {"UNREACHABLE", "REFUSED", "UNKNOWN"} for r in rows)}
    if args.apply:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(receipt, indent=1, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, out)
    print(json.dumps({"mode": receipt["mode"], "open": len(findings), "by_severity": by_sev, "recovered": len(recovered), "ok": receipt["ok"],
                      "sample": [(r["severity"], r["source"], r["item"][:60]) for r in rows[:8]]}, default=str))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
