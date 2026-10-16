#!/usr/bin/env python3
"""n8n_failure_diagnosis.py — lane `n8n-failure-diagnosis`: LLM diagnosis + bounded remediation of n8n failures.

REMEDIATION_PLAN §6 R1–R5 (operator decisions 2026-10-09 23:38 ET). One cycle:

1. Read the open ``n8n:*`` rows of ``system_health_events`` (READ ONLY transaction) written by the SIEM bridge.
2. For each row whose lane is in ``config/n8n_remediation_catalogue.json`` (at most --max-incidents, one diagnosis
   per incident, at most 3 per lane per day): build a grounded evidence pack from the row, the lane registry row,
   the catalogue row and the lane's recent coordination-ledger runs (RunReceipt@v1 incl. stderr/stdout tail) —
   lane metadata, error text and log lines only, scrubbed of secrets and portfolio fields (§2A decision 1).
3. Check deferral (lib/llm_deferral), the process's daily cap and the $0.05 per-call cap, then request the
   diagnosis through the governed capability path: ``n8n_model_job.run_model_job`` (process
   ``n8n_lane_failure_diagnosis``, template ``lane_failure_diagnosis.v1``, output ``lane_failure_diagnosis/v1``)
   -> ``cio_governed_model_bridge`` (grok OAuth -> chatgpt OAuth -> deepseek FAST; decision 2).
4. Validate the strict JSON verdict {cause, confidence, action_id, rationale, citations}; ``action_id`` must be in
   the lane's catalogue row (or ``suggest_only``) and every citation must name an evidence id.
5. Execute ONLY an auto catalogue action, through deterministic handlers. A rerun goes through the gateway's own
   ``coordination/run`` path (``n8n_coordination_gateway.host_run_request``: the same validation and the same
   RunRequested row n8n gets), never a direct ledger insert; the executor runs the lane's allowlist argv and clamps
   the mode to the lane's registry stage (§23.11: shadow runs dry_run). A LIVE rerun phase is requested only for a
   lane at ``scheduler.stage == "cutover"``; otherwise it is dropped and recorded. The reaper action is the
   executor's RUN_TIMEOUT executor_lost finish. Model text is never a command.
6. Write the diagnosis (cause, confidence, action, outcome, cost, model, citations, incident refs) to the
   diagnoser's OWN store ``data/runtime/n8n_diagnoses/diagnoses.jsonl`` (N8nLaneDiagnosis@v1, append-only) plus the
   receipt ``data/runtime/n8n_failure_diagnosis_last.json`` and the state file. It never writes
   ``system_health_events`` (one writer per store, AGENTS.md §9.4; operator "Ok" 2026-10-10 ~00:35 ET): the SIEM
   bridge folds the diagnosis into the ``n8n:<lane>`` row it owns on its next pass. Low confidence, a refused action
   and a failed remediation are escalated at P1 — and suggestions at P2 — through the receipt's ``escalations``,
   which the incident fan-in reads (source ``n8n_failure_diagnosis``); the incident notifier carries P1 to
   Telegram. This script never sends.

Self-healing tier (operator 2026-10-16 "yes make self healing now"; scripts/lib/n8n_self_heal.py,
docs/ops/n8n_self_healing.md), applied BEFORE the model path:

* Dedupe: every incident gets a failure ``signature`` (lane + event_type + normalized error tail). The first incident
  of a signature each day is the LEAD; the rest are ATTACHED to it (no model call, no escalation of their own), and
  the per-day model-call cap counts per signature, not per lane, so the budget is spent on distinct failures.
* Deterministic (no model): a lock skip covered by another run of the same slot and a failure followed by a later
  successful run auto-close (``covered`` / ``self_recovered``); RUN_TIMEOUT executor_lost goes to the reaper.
* Live heal: ``rerun_live_once`` (one per lane per day) for a TRANSIENT failure of an n8n-owned canary/cutover lane
  that is not a sender / P1 / broker-order-stop-options lane and has a semantic effect key (the executor's
  effect claim refuses a duplicate effect). Only through ``host_run_request``.
* Escalation: one per signature. P1 rides the receipt's ``escalations`` (fan-in -> notifier -> Telegram, once per
  signature, with what was tried); P2 goes to the receipt's ``digest`` list only, never an individual message.

Models: process ``n8n_lane_failure_diagnosis`` routes grok (OAuth) -> chatgpt (OAuth) -> deepseek, $0.05 per call.
The governed bridge has no Claude provider (cio_governed_model_bridge.py: grok / chatgpt / deepseek / gemini /
codex only), so operator decision 2's "DeepSeek or Claude" resolves to DeepSeek until one is provisioned (§17).

    python3 scripts/n8n_failure_diagnosis.py --dry-run [--fixture tests/fixtures/...json]
    python3 scripts/n8n_failure_diagnosis.py --apply

``--dry-run``: no model call (a recorded fixture answer stands in; default: suggest_only), no action, no DB write,
no file write; prints what it would do, including prompt bytes and the projected cost. Exit 0 = cycle complete;
1 = a source was unavailable or a write failed (the receipt says which); 2 = usage.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No broker, order, stop, secret, send, delete, crontab or systemd.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import lane_stage_clamp as S  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib import n8n_failure_diagnosis as D  # noqa: E402
from scripts.lib import n8n_model_job as M  # noqa: E402
from scripts.lib import n8n_remediation_catalogue as C  # noqa: E402
from scripts.lib import n8n_self_heal as H  # noqa: E402
from scripts.lib import n8n_siem_bridge as B  # noqa: E402

SCHEMA = D.SCHEMA
NO_CONSUMER_REASON = (
    "REMEDIATION_PLAN §6 diagnoser; consumers: the SIEM bridge (folds data/runtime/n8n_diagnoses/diagnoses.jsonl "
    "into its n8n:* rows) and the incident fan-in (source n8n_failure_diagnosis). Not scheduled until the operator "
    "merges its registry row (PROPOSED_ROWS.md)."
)
WRITER = "n8n_failure_diagnosis"
RECEIPT_REL = "data/runtime/n8n_failure_diagnosis_last.json"
STATE_REL = "data/runtime/n8n_failure_diagnosis_state.json"
DIAGNOSES_REL = B.DIAGNOSES_REL                             # this lane's own store; the SIEM bridge reads it
EVIDENCE_REL = "n8n_failure_diagnosis/evidence"            # under data/runtime (an n8n_model_job ALLOWED_STORE)
CATALOGUE = ROOT / "config" / "n8n_remediation_catalogue.json"
REGISTRY = ROOT / "config" / "lane_registry.json"
ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"
EFFECT_KEYS = ROOT / "config" / "n8n_effect_keys.json"
CUTOVER_POLICY = ROOT / "config" / "lane_cutover_policy.json"   # optional; absent on main 2026-10-16
#: Where a P2 escalation goes (operator 2026-10-16): the receipt's ``digest`` list, never the fan-in/Telegram path.
P2_ROUTE = "digest"
REQUESTED_BY = "host:n8n-failure-diagnosis"
CALLER_ID = "n8n-failure-diagnosis"
DIAGNOSED_KEEP_DAYS = 7
PENDING_GRACE_S = 300
#: The dry-run stand-in when no --fixture is given: a recorded, harmless answer (never a model call).
DEFAULT_FIXTURE = {"cause": "dry-run fixture: no model was called", "confidence": 0.0, "action_id": "suggest_only",
                   "rationale": "dry run", "citations": [], "recommendation": "NONE"}

SELECT_OPEN = (
    "SELECT id, component, event_type, severity, message, action_taken, lifecycle_state, created_at "
    "FROM system_health_events WHERE component LIKE 'n8n:%%' "
    "AND COALESCE(lifecycle_state,'active') IN ('active','acknowledged') ORDER BY id DESC"
)


# ---------------------------------------------------------------- environment


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def ledger_path(root: Path) -> Path:
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    return Path(explicit) if explicit else root / B.LEDGER_REL


def connect():  # pragma: no cover - exercised against the live DB only
    from db_adapter import _get_conn

    conn = _get_conn()
    conn.rollback()
    return conn


def _load_json(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def append_records(path: Path, records: list[dict[str, Any]]) -> None:
    """Append N8nLaneDiagnosis@v1 lines to the diagnoser's own store (single writer: this lane)."""
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in records)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())


def _atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_open_rows(conn) -> list[dict[str, Any]]:
    """READ ONLY transaction, then rollback: the only statements this lane ever sends to the database."""
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute(SELECT_OPEN)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) if not isinstance(r, dict) else dict(r) for r in cur.fetchall()]
    conn.rollback()
    return rows


def read_lane_runs(path: Path, lane: str, limit: int = 8) -> list[dict[str, Any]]:
    """Newest-first runs for one lane, sqlite mode=ro (raises when unreadable)."""
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM runs WHERE lane_id = ? ORDER BY requested_at DESC LIMIT ?", (lane, int(limit))).fetchall()]
    finally:
        conn.close()


def read_run(path: Path, run_id: str) -> Optional[dict[str, Any]]:
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if r is None else dict(r)
    finally:
        conn.close()


def pid_alive(pid: Any) -> bool:
    try:
        p = int(pid)
    except (TypeError, ValueError):
        return False
    if p <= 0:
        return False
    try:
        os.kill(p, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------- state


def empty_state() -> dict[str, Any]:
    return {"schema": "N8nFailureDiagnosisState@v1", "diagnosed": {}, "pending": {}, "escalations": {}, "days": {},
            "lane_last_remediation": {}}


def day_bucket(state: dict, now: datetime) -> dict[str, Any]:
    day = now.astimezone(timezone.utc).date().isoformat()
    b = state.setdefault("days", {}).setdefault(day, {"spend_usd": 0.0, "calls": 0, "lane_calls": {},
                                                      "lane_remediations": {}})
    for k in ("sig_calls", "signatures", "lane_live_heals"):   # 2026-10-16 self-healing fields (older buckets lack them)
        b.setdefault(k, {})
    return b


def prune_state(state: dict, now: datetime, open_ids: set[int]) -> None:
    cutoff = (now - timedelta(days=DIAGNOSED_KEEP_DAYS)).isoformat()
    state["diagnosed"] = {k: v for k, v in (state.get("diagnosed") or {}).items() if str(v.get("at")) >= cutoff}
    keep_days = {(now - timedelta(days=i)).date().isoformat() for i in range(3)}
    state["days"] = {k: v for k, v in (state.get("days") or {}).items() if k in keep_days}
    # an escalation lives while its SIEM row is open; the fan-in closes it when it disappears from the receipt
    state["escalations"] = {k: v for k, v in (state.get("escalations") or {}).items()
                            if v.get("siem_id") is None or int(v["siem_id"]) in open_ids
                            or any(_int(i) in open_ids for i in v.get("siem_ids") or [])}


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the model call (governed path)


def governed_diagnosis(pack: dict[str, Any], key: str, *, governed_call: Callable[..., dict], artifact_root: Path,
                       now: datetime) -> dict[str, Any]:
    """Write the pack into the artifact store under artifact_root and run it as an n8n model job. Returns
    {receipt, answer|None, latency_ms, prompt_bytes}. artifact_root is a throwaway dir on a dry run."""
    rel = f"{EVIDENCE_REL}/{key}.json"
    path = artifact_root / "data" / "runtime" / rel
    raw = (json.dumps(pack, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    job = {"process_id": D.PROCESS_ID, "template_id": D.TEMPLATE_ID, "output_schema_id": D.OUTPUT_SCHEMA_ID,
           "correlation_id": f"diag-{key}"[:64], "deadline": (now + timedelta(minutes=5)).isoformat(),
           "artifact_ref": {"store": "data/runtime", "ref": rel, "sha256": hashlib.sha256(raw).hexdigest()}}
    t0 = time.monotonic()
    receipt = M.run_model_job(job, governed_call=governed_call, now=now, root=artifact_root)
    latency_ms = int((time.monotonic() - t0) * 1000)
    answer = (receipt.get("artifact_out") or {}).get("body") if receipt.get("state") == "ARTIFACT_WRITTEN" else None
    return {"receipt": receipt, "answer": answer, "latency_ms": latency_ms, "prompt_bytes": len(raw),
            "artifact": {"store": "data/runtime", "ref": rel, "sha256": job["artifact_ref"]["sha256"]}}


def measured_cost(receipt: dict[str, Any]) -> Optional[float]:
    cost = receipt.get("cost") or {}
    ev = cost.get("provider_cost_event") or {}
    for v in (ev.get("calculated_cost_usd"), cost.get("cost_estimate_usd")):
        try:
            if v is not None:
                return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0 if cost.get("mock") else None


def fixture_call(answer: dict[str, Any]) -> Callable[..., dict]:
    """The dry-run stand-in for the bridge: returns the recorded answer, marks itself mock, never calls out."""
    def call(messages, **kw):
        call.seen.append({"messages": messages, **kw})
        return {"choices": [{"message": {"content": json.dumps(answer)}}],
                "_tradeai": {"governance_pass": True, "process_id": kw.get("process_id"), "mock": True,
                             "model_id": "fixture", "provider": "fixture", "cost_estimate": 0.0,
                             "request_id": kw.get("request_id")}}
    call.seen = []  # type: ignore[attr-defined]
    return call


# ---------------------------------------------------------------- one cycle (read-only up to the plan)


def _effect_owner_ro(ledger: Path, process: str) -> Optional[str]:
    """effect_owners.owner for one process, sqlite mode=ro; None when unreadable or absent (no live heal)."""
    try:
        conn = sqlite3.connect(f"{Path(ledger).resolve().as_uri()}?mode=ro", uri=True, timeout=3)
    except Exception:  # noqa: BLE001
        return None
    try:
        r = conn.execute("SELECT owner FROM effect_owners WHERE process = ?", (process,)).fetchone()
        return None if r is None else str(r[0])
    except Exception:  # noqa: BLE001 — no table yet = no owner = no live heal (fail closed)
        return None
    finally:
        conn.close()


def _failure_text(fields: dict, row: dict, runs: list[dict]) -> str:
    """The error text a failure is classified on: the SIEM error plus the failed run's receipt tail."""
    parts = [str(fields.get("error") or B.strip_diagnosis(row.get("message")))]
    rid = fields.get("run")
    for r in runs:
        if rid and r.get("run_id") == rid:
            try:
                rec = json.loads(r.get("receipt_json") or "") or {}
            except (TypeError, ValueError):
                rec = {}
            parts += [str(rec.get("reason") or ""), str(rec.get("stderr_tail") or "")[-800:]]
    return " ".join(parts)


def diagnose(rows: list[dict], *, catalogue: dict, registry: dict, state: dict, now: datetime, ledger: Path,
             governed_call: Callable[..., dict], artifact_root: Path, min_severity: str, max_incidents: int,
             deferral: Callable[[str], Any], effect_keys: Optional[dict] = None,
             effect_owner: Optional[Callable[[str], Optional[str]]] = None,
             cutover_policy: Optional[dict] = None) -> dict[str, Any]:
    """Every decision of the cycle. Writes nothing except the evidence pack under artifact_root."""
    out: dict[str, Any] = {"results": [], "skipped": [], "notes": {}}
    elig, skipped = D.eligible(rows, catalogue, min_severity=min_severity, done=state.get("diagnosed") or {})
    out["skipped"] = skipped
    today = day_bucket(json.loads(json.dumps(state)), now)   # a copy: the plan never mutates state
    spend, calls = float(today["spend_usd"]), int(today["calls"])
    sig_calls = dict(today["sig_calls"])
    leads = {sig: v.get("lead") for sig, v in (today["signatures"] or {}).items() if v.get("lead")}
    live_heals = dict(today["lane_live_heals"])
    effect_keys = effect_keys or {}
    effect_owner = effect_owner or (lambda process: _effect_owner_ro(ledger, process))
    stop_reason = None
    for row in elig:
        lane, key = D.lane_of(row), D.incident_key(row)
        fields = D.parse_message(row.get("message"))
        sig = H.signature(lane, row.get("event_type"), fields.get("error") or B.strip_diagnosis(row.get("message")))
        res: dict[str, Any] = {"incident_key": key, "siem_id": row.get("id"), "lane": lane,
                               "event_type": row.get("event_type"), "severity": row.get("severity"), "signature": sig}
        out["results"].append(res)
        lead = leads.get(sig)
        if lead and lead != key:
            # Dedupe (2026-10-16): one diagnosis per signature per day; the rest ride on the lead, at no cost.
            res.update(outcome="attached", attached_to=lead,
                       decision={"kind": "attach", "priority": None, "reason": "duplicate_signature", "action_id": None})
            continue
        leads[sig] = key
        if len([r for r in out["results"] if r.get("model_called")]) >= max_incidents or stop_reason:
            res.update(outcome="not_this_cycle", reason=stop_reason or "max_incidents")
            continue
        entry = catalogue[lane]
        try:
            runs = read_lane_runs(ledger, lane)
        except Exception as exc:  # noqa: BLE001 — a missing ledger is evidence too; the pack says so
            runs = []
            out["notes"]["ledger"] = f"unavailable:{type(exc).__name__}"
        # ---- deterministic tier: no model call
        dv = H.deterministic_verdict(row, fields=fields, runs=runs, now=now.timestamp())
        if dv and dv["kind"] == "auto_close":
            res.update(outcome=f"auto_closed:{dv['outcome']}", deterministic=dv, reason=dv["cause"],
                       decision={"kind": "auto_close", "priority": None, "reason": dv["outcome"], "action_id": None})
            continue
        if dv and dv["kind"] == "reap":
            action = C.lane_action(entry, "reap_orphan_run")
            if action:
                res.update(outcome="deterministic", deterministic=dv, reason=dv["cause"], _action=action,
                           decision={"kind": "execute", "priority": None, "reason": "deterministic:executor_lost",
                                     "action_id": "reap_orphan_run"})
                continue
        # ---- live heal: a transient failure of an n8n-owned canary/cutover lane, one live rerun per day
        res["failure_class"] = H.classify_failure(_failure_text(fields, row, runs), event_type=row.get("event_type"))
        live_action = C.lane_action(entry, H.LIVE_HEAL_ACTION)
        if live_action:
            spec = effect_keys.get(lane)
            ok, why = H.live_heal_gate(
                lane, registry_row=registry.get(lane), effect_spec=spec,
                effect_owner=effect_owner(str(spec.get("process"))) if spec else None,
                failure_class=res["failure_class"], catalogue_entry=entry, cutover_policy=cutover_policy,
                live_heals_today=int(live_heals.get(lane, 0)))
            res["live_heal_gate"] = why
            if ok and live_action.get("auto"):
                live_heals[lane] = live_heals.get(lane, 0) + 1
                res.update(outcome="deterministic", reason=f"transient failure: {H.LIVE_HEAL_ACTION}", _action=live_action,
                           decision={"kind": "execute", "priority": None, "reason": "deterministic:transient_live_heal",
                                     "action_id": H.LIVE_HEAL_ACTION})
                continue
        if sig_calls.get(sig, 0) >= D.MAX_CALLS_PER_LANE_DAY:
            res.update(outcome="no_diagnosis", reason="lane_daily_call_cap",
                       decision={"kind": "escalate", "priority": "P2", "reason": "lane_daily_call_cap"})
            continue
        pack = D.build_evidence(row, entry, registry_row=registry.get(lane), runs=runs, now=now.timestamp())
        violations = D.egress_violations(pack)
        res["evidence_ids"] = sorted(D.evidence_ids(pack))
        if violations:
            res.update(outcome="no_diagnosis", reason="egress_refused", egress_violations=violations[:5],
                       decision={"kind": "escalate", "priority": "P1", "reason": "egress_refused"})
            continue
        prompt_chars = len(json.dumps(pack, ensure_ascii=False)) + 2000
        projected = D.projected_cost_usd(prompt_chars)
        res["projected_cost_usd"] = projected
        if projected > D.PER_CALL_CAP_USD:
            res.update(outcome="no_diagnosis", reason="per_call_cost_cap",
                       decision={"kind": "escalate", "priority": "P2", "reason": "per_call_cost_cap"})
            continue
        if spend + projected > D.DAILY_CAP_USD or calls >= D.MAX_CALLS_PER_DAY:
            stop_reason = "process_daily_cap"
            res.update(outcome="no_diagnosis", reason="process_daily_cap",
                       decision={"kind": "escalate", "priority": "P2", "reason": "process_daily_cap"})
            continue
        dec = deferral(D.PROCESS_ID)
        run_after = getattr(dec, "run_after", None)
        res["deferral"] = {"defer": bool(getattr(dec, "defer", False)), "reason": getattr(dec, "reason", None),
                           "tier": getattr(dec, "tier", None),
                           "run_after": run_after.isoformat() if hasattr(run_after, "isoformat") else run_after}
        if getattr(dec, "defer", False):
            res.update(outcome="no_diagnosis", reason="deferred_offpeak",
                       decision={"kind": "escalate", "priority": "P2", "reason": "deferred_offpeak"})
            continue
        call = governed_diagnosis(pack, key, governed_call=governed_call, artifact_root=artifact_root, now=now)
        rcpt = call["receipt"]
        cost = measured_cost(rcpt)
        res.update(model_called=True, latency_ms=call["latency_ms"], prompt_bytes=call["prompt_bytes"],
                   evidence_artifact=call["artifact"], model_job_state=rcpt.get("state"),
                   model_job_reason=rcpt.get("reason"), cost_usd=cost,
                   provider=(rcpt.get("cost") or {}).get("provider"), model_id=(rcpt.get("cost") or {}).get("model_id"),
                   reservation_id=(rcpt.get("cost") or {}).get("reservation_id"),
                   cost_settlement=(rcpt.get("cost") or {}).get("settlement"))
        if cost is None:            # never fail open: an unmeasured call is charged at its projection
            res["cost_usd"], res["cost_basis"] = projected, "projected_unmeasured"
        else:
            res["cost_basis"] = "measured" if res.get("cost_settlement") == "MEASURED" else "bridge_estimate"
        calls += 1
        sig_calls[sig] = sig_calls.get(sig, 0) + 1
        spend += float(res["cost_usd"] or 0.0)
        if cost is not None and cost > D.PER_CALL_CAP_USD:
            stop_reason = "per_call_cost_cap_breached"
            res["cost_cap_breached"] = True
        if call["answer"] is None:
            res.update(outcome="no_diagnosis", reason=f"model_refused:{rcpt.get('reason')}",
                       decision={"kind": "escalate", "priority": "P2", "reason": f"model_refused:{rcpt.get('reason')}"})
            continue
        verdict = D.check_verdict(call["answer"], entry, D.evidence_ids(pack))
        res["verdict"] = verdict
        last = (state.get("lane_last_remediation") or {}).get(lane)
        recent = bool(last and str(last) >= (now - timedelta(hours=24)).isoformat())
        decision = D.decide(verdict, entry, lane_remediations_today=int(today["lane_remediations"].get(lane, 0)),
                            lane_recent_remediation=recent)
        if res.get("cost_cap_breached"):
            decision = {"kind": "escalate", "priority": "P1", "reason": "per_call_cost_cap_breached",
                        "action_id": decision.get("action_id")}
        res.update(decision={k: v for k, v in decision.items() if k != "action"}, outcome="diagnosed",
                   _action=decision.get("action"))
    out["spend_usd_after"], out["calls_after"] = round(spend, 6), calls
    return out


# ---------------------------------------------------------------- deterministic handlers (apply only)


def handle_request_run(store, *, lane: str, mode: str, run_id: str, allowlist: dict, now: float,
                       registry_rows: Optional[list] = None, live_stages: frozenset = frozenset({"cutover"})
                       ) -> dict[str, Any]:
    """One run request through the gateway's coordination/run path (``G.host_run_request``) — the same validation
    and REQUESTED row n8n gets; the executor runs the allowlist argv and clamps the mode to the lane's stage. A live
    request needs the lane at ``scheduler.stage == "cutover"`` (unknown registry = no live)."""
    if lane not in allowlist:
        return {"ok": False, "outcome": "precondition_unmet:lane_not_allowlisted"}
    entry = allowlist[lane]
    if entry.get("dry_run_arg" if mode == "dry_run" else "live_arg") is None:
        return {"ok": False, "outcome": f"precondition_unmet:mode_unavailable:{mode}"}
    if mode == "live" and S.lane_stage(lane, registry_rows) not in live_stages:
        stage = S.lane_stage(lane, registry_rows) or "unknown"
        need = "cutover" if live_stages == frozenset({"cutover"}) else "_or_".join(sorted(live_stages))
        return {"ok": False, "outcome": f"precondition_unmet:live_rerun_needs_stage_{need}:{stage}"}
    busy = [r for st in ("REQUESTED", "RUNNING") for r in store.list(state=st, lane_id=lane, limit=5)]
    if busy and not any(r.get("run_id") == run_id for r in busy):
        return {"ok": False, "outcome": f"precondition_unmet:lane_busy:{busy[0].get('run_id')}"}
    env = G.host_run_request(lane_id=lane, mode=mode, run_id=run_id, requested_by=REQUESTED_BY, caller_id=CALLER_ID,
                             run_store=store, run_allowlist=frozenset(allowlist), now=now)
    if env.get("state") == "REFUSED":
        return {"ok": False, "outcome": f"refused:{env.get('reason')}"}
    return {"ok": True, "outcome": f"requested:{mode}:{run_id}", "run_id": run_id,
            "duplicate": bool(env.get("duplicate")), "run_state": env.get("state")}


def handle_reap_orphan(store, *, lane: str, allowlist: dict, now: float) -> dict[str, Any]:
    """RUN_TIMEOUT executor_lost for a RUNNING row overdue by 2x timeout with a stale heartbeat and a dead pid."""
    timeout = float((allowlist.get(lane) or {}).get("timeout_s") or 0)
    if timeout <= 0:
        return {"ok": False, "outcome": "precondition_unmet:no_timeout"}
    reaped = []
    for r in store.list_running():
        if r.get("lane_id") != lane:
            continue
        started = D._ts(r.get("started_at") or r.get("requested_at"))
        hb = D._ts(r.get("heartbeat_at"))
        if started is None or now - started <= C.ORPHAN_TIMEOUT_FACTOR * timeout:
            continue
        if hb is not None and now - hb <= timeout:
            continue
        if pid_alive(r.get("pid")):
            continue
        receipt = {"schema": "RunReceipt@v1", "run_id": r["run_id"], "lane_id": lane, "mode": r.get("mode"),
                   "exit_code": None, "duration_s": round(max(0.0, now - started), 3), "lock_skipped": False,
                   "timed_out": False, "started_at": r.get("started_at"),
                   "finished_at": datetime.fromtimestamp(now, timezone.utc).isoformat(), "state": "RUN_TIMEOUT",
                   "reason": "executor_lost", "argv": None, "stdout_tail": None, "stderr_tail": None,
                   "authority": "READ_ONLY_ADVISORY", "reaped_by": WRITER,
                   "lost": {"pid": r.get("pid"), "heartbeat_at": r.get("heartbeat_at"), "overdue": True}}
        store.finish(r["run_id"], state="RUN_TIMEOUT", receipt=receipt, now=now)
        reaped.append(r["run_id"])
    if not reaped:
        return {"ok": False, "outcome": "precondition_unmet:no_orphan_running_row"}
    return {"ok": True, "outcome": f"reaped:{','.join(reaped)[:200]}"}


def _live_stages(action: dict) -> frozenset:
    """rerun_live_once (2026-10-16) is the one action allowed live at canary; every other live phase needs cutover."""
    return C.LIVE_HEAL_STAGES if action.get("action_id") == H.LIVE_HEAL_ACTION else frozenset({"cutover"})


def rerun_phases(action: dict, lane: str, registry_rows: Optional[list]) -> tuple[list[str], Optional[str]]:
    """(phases to run, dropped-live note). A live phase survives only for a lane at stage cutover (canary or
    cutover for rerun_live_once, whose gate already ran)."""
    phases = list(action.get("mode_sequence") or ["dry_run"])
    if "live" in phases and S.lane_stage(lane, registry_rows) not in _live_stages(action):
        return [p for p in phases if p != "live"] or ["dry_run"], f"stage={S.lane_stage(lane, registry_rows) or 'unknown'}"
    return phases, None


def execute_action(store, res: dict, *, allowlist: dict, now: float, registry_rows: Optional[list] = None
                   ) -> dict[str, Any]:
    action = res.get("_action") or {}
    handler = action.get("handler")
    if handler not in C.HANDLERS:            # the catalogue is data; only these two code paths exist
        return {"ok": False, "outcome": f"refused:unknown_handler:{handler}"}
    if handler == "ledger_reap_orphan":
        return handle_reap_orphan(store, lane=res["lane"], allowlist=allowlist, now=now)
    phases, dropped = rerun_phases(action, res["lane"], registry_rows)
    if dropped:
        res["live_phase_dropped"] = dropped
    res["_phases"] = phases
    mode = phases[0]
    return handle_request_run(store, lane=res["lane"], mode=mode, run_id=D.remediation_run_id(res["incident_key"], mode),
                              allowlist=allowlist, now=now, registry_rows=registry_rows,
                              live_stages=_live_stages(action))


def advance_pending(state: dict, *, ledger: Path, store_factory, allowlist: dict, now: datetime,
                    apply: bool, registry_rows: Optional[list] = None) -> list[dict[str, Any]]:
    """Walk each pending rerun one step: dry_run done -> live request (when the action has a live phase)."""
    events = []
    for key, p in list((state.get("pending") or {}).items()):
        try:
            row = read_run(ledger, p["run_id"])
        except Exception as exc:  # noqa: BLE001
            events.append({"incident_key": key, "outcome": f"ledger_unavailable:{type(exc).__name__}"})
            continue
        st = (row or {}).get("state")
        timeout = float((allowlist.get(p["lane"]) or {}).get("timeout_s") or 300)
        age = now.timestamp() - float(p.get("requested_ts") or now.timestamp())
        ev: dict[str, Any] = {"incident_key": key, "lane": p["lane"], "run_id": p["run_id"], "run_state": st,
                              "signature": p.get("signature")}
        if st == "RUN_DONE":
            phases = list(p.get("phases") or [])
            if "live" in phases and not S.live_rerun_allowed(p["lane"], registry_rows):
                phases = [m for m in phases if m != "live"]     # the stage moved back since the request
                ev["live_phase_dropped"] = f"stage={S.lane_stage(p['lane'], registry_rows) or 'unknown'}"
            idx = int(p.get("phase_idx") or 0)
            if idx + 1 < len(phases):
                mode = phases[idx + 1]
                rid = D.remediation_run_id(key, mode)
                ev["next"] = f"request:{mode}:{rid}"
                if apply:
                    got = handle_request_run(store_factory(), lane=p["lane"], mode=mode, run_id=rid,
                                             allowlist=allowlist, now=now.timestamp(), registry_rows=registry_rows)
                    ev["outcome"] = got["outcome"]
                    if got["ok"]:
                        state["pending"][key] = {**p, "run_id": rid, "phase_idx": idx + 1, "requested_ts": now.timestamp()}
                    else:
                        ev["escalate"] = "P1"
                        state["pending"].pop(key, None)
            else:
                ev["outcome"] = "remediated"
                if apply:
                    state["pending"].pop(key, None)
        elif st in ("RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED", "RUN_SKIPPED_LOCK"):
            ev.update(outcome=f"remediation_failed:{st}", escalate="P1")
            if apply:
                state["pending"].pop(key, None)
        elif row is None or age > 2 * timeout + PENDING_GRACE_S:
            ev.update(outcome="remediation_stuck" if row else "remediation_run_missing", escalate="P1")
            if apply:
                state["pending"].pop(key, None)
        else:
            ev["outcome"] = "waiting"
        ev["siem_id"] = p.get("siem_id")
        events.append(ev)
    return events


def _no_verdict_detail(res_or_ev: dict, reason: str) -> str:
    """What the operator reads when there is no model verdict: why, and whether the next cycle retries.
    (Before 2026-10-15 this printed `conf=None; cause=` — an escalation that looked like a broken diagnosis.)"""
    if res_or_ev.get("run_id"):                 # a remediation event (advance_pending), not a diagnosis
        return f"{reason}; remediation run={res_or_ev.get('run_id')} state={res_or_ev.get('run_state')}"
    if str(reason).startswith("model_refused"):
        why = "model call refused"
    elif res_or_ev.get("model_called"):
        why = "model answered nothing usable"
    elif reason == "deferred_offpeak":
        d = res_or_ev.get("deferral") or {}
        why = f"model not called: off-peak deferral (tier={d.get('tier')}, {d.get('reason')})"
    else:
        why = "model not called"
    retry = "not retried" if str(reason).startswith(D.FINAL_NO_DIAGNOSIS) else "retried next cycle"
    return f"{reason}; no diagnosis yet: {why}; {retry}"


def tried_summary(res_or_ev: dict) -> str:
    """What the self-healing tier already tried, in one short phrase (operator 2026-10-16: a P1 says what was tried)."""
    parts = []
    if res_or_ev.get("deterministic"):
        parts.append(f"auto:{(res_or_ev['deterministic'] or {}).get('outcome')}")
    ar = res_or_ev.get("action_result") or {}
    if ar:
        parts.append(f"rerun:{str(ar.get('outcome'))[:40]}")
    elif res_or_ev.get("run_id"):
        parts.append(f"rerun:{res_or_ev.get('run_id')}={res_or_ev.get('run_state')}")
    if res_or_ev.get("live_heal_gate") and res_or_ev.get("live_heal_gate") != "ok":
        parts.append(f"live_heal:no({str(res_or_ev['live_heal_gate'])[:32]})")
    v = res_or_ev.get("verdict") or {}
    parts.append(f"diag:{v.get('confidence')}" if v else "diag:none")
    return ",".join(parts)


def escalation_key(res_or_ev: dict) -> str:
    """One escalation per (lane, failure signature); an incident without a signature keeps its own key."""
    sig = res_or_ev.get("signature")
    return f"{res_or_ev.get('lane')}|{sig}" if sig else str(res_or_ev.get("incident_key"))


def _escalation(res_or_ev: dict, priority: str, reason: str, now: datetime) -> dict[str, Any]:
    v = res_or_ev.get("verdict") or {}
    tried = tried_summary(res_or_ev)
    if v:
        body = f"{reason}; tried={tried}; conf={v.get('confidence')}; cause={(v.get('cause') or '')[:70]}"
    else:
        body = f"{_no_verdict_detail(res_or_ev, reason)}; tried={tried}"
    detail = f"{body}; siem={res_or_ev.get('siem_id')}"
    return {"key": escalation_key(res_or_ev), "incident_key": res_or_ev.get("incident_key"),
            "signature": res_or_ev.get("signature"), "lane": res_or_ev.get("lane"),
            "event_type": res_or_ev.get("event_type"), "siem_id": res_or_ev.get("siem_id"),
            "siem_ids": [res_or_ev.get("siem_id")], "attached": 0, "priority": priority, "reason": reason,
            "route": "operator_once" if priority == "P1" else P2_ROUTE, "tried": tried, "detail": detail[:150],
            "at": now.isoformat()}


def _put_escalation(state: dict, esc: dict) -> None:
    """Collapse into the signature's one escalation: the worst priority wins, siem ids and counts accumulate."""
    book = state.setdefault("escalations", {})
    prev = book.get(esc["key"])
    if prev:
        esc["siem_ids"] = sorted({*(prev.get("siem_ids") or [prev.get("siem_id")]), *esc["siem_ids"]} - {None})
        esc["attached"] = int(prev.get("attached") or 0)
        if prev.get("priority") == "P1" and esc["priority"] != "P1":
            esc.update(priority="P1", route="operator_once", reason=prev.get("reason"), detail=prev.get("detail"))
    book[esc["key"]] = esc


def apply_results(diag: dict, pending_events: list[dict], state: dict, rows_by_id: dict, *, now: datetime,
                  store_factory, allowlist: dict, root: Path, registry_rows: Optional[list] = None) -> dict[str, Any]:
    """The only function that executes actions or writes a diagnosis. Reached after the dry-run branch returned.
    Writes the diagnoser's own store only — never system_health_events (the SIEM bridge folds the records)."""
    done: dict[str, Any] = {"executed": 0, "diagnoses_appended": 0, "errors": []}
    today = day_bucket(state, now)
    records: list[dict[str, Any]] = []
    for res in diag["results"]:
        if res.get("outcome") == "not_this_cycle":
            continue
        dec = res.get("decision") or {}
        sig = res.get("signature")
        if sig:
            book = today["signatures"].setdefault(sig, {"lead": None, "lane": res["lane"], "attached": 0,
                                                        "event_type": res.get("event_type")})
            if dec.get("kind") == "attach":
                book["attached"] = int(book.get("attached") or 0) + 1
                esc = (state.get("escalations") or {}).get(escalation_key(res))
                if esc is not None:
                    esc["attached"] = int(esc.get("attached") or 0) + 1
                    esc["siem_ids"] = sorted({*(esc.get("siem_ids") or []), res.get("siem_id")} - {None})
            elif not book.get("lead"):
                book["lead"] = res["incident_key"]
        if res.get("model_called"):
            today["calls"] += 1
            today["lane_calls"][res["lane"]] = today["lane_calls"].get(res["lane"], 0) + 1
            if sig:
                today["sig_calls"][sig] = today["sig_calls"].get(sig, 0) + 1
            today["spend_usd"] = round(float(today["spend_usd"]) + float(res.get("cost_usd") or 0.0), 6)
        outcome = res.get("outcome")
        if dec.get("kind") == "execute":
            try:
                got = execute_action(store_factory(), res, allowlist=allowlist, now=now.timestamp(),
                                     registry_rows=registry_rows)
            except Exception as exc:  # noqa: BLE001 — a failed handler is a failed remediation: escalate P1
                got = {"ok": False, "outcome": f"handler_error:{type(exc).__name__}:{str(exc)[:80]}"}
            res["action_result"] = got
            outcome = got["outcome"]
            done["executed"] += 1 if got["ok"] else 0
            if got["ok"]:
                today["lane_remediations"][res["lane"]] = today["lane_remediations"].get(res["lane"], 0) + 1
                state.setdefault("lane_last_remediation", {})[res["lane"]] = now.isoformat()
                action = res.get("_action") or {}
                if action.get("action_id") == H.LIVE_HEAL_ACTION:
                    today["lane_live_heals"][res["lane"]] = today["lane_live_heals"].get(res["lane"], 0) + 1
                if action.get("handler") == "ledger_request_run":
                    phases = res.get("_phases") or ["dry_run"]
                    state.setdefault("pending", {})[res["incident_key"]] = {
                        "lane": res["lane"], "siem_id": res.get("siem_id"), "action_id": action.get("action_id"),
                        "signature": sig,
                        "phases": phases, "phase_idx": 0,
                        "run_id": D.remediation_run_id(res["incident_key"], phases[0]), "requested_ts": now.timestamp()}
            else:
                dec = {"kind": "escalate", "priority": "P1" if not str(outcome).startswith("precondition_unmet") else "P2",
                       "reason": f"remediation_not_done:{outcome}"}
        if dec.get("kind") == "escalate":
            esc = _escalation(res, dec["priority"], dec["reason"], now)
            _put_escalation(state, esc)
            res["escalation"] = f"{dec['priority']}:{dec['reason']}"
        elif dec and dec.get("kind") != "attach":
            # A later cycle reached a decision that needs no human (a catalogue action ran, the failure auto-closed):
            # the escalation an earlier cycle left for this incident / signature is stale and must stop paging.
            (state.get("escalations") or {}).pop(res["incident_key"], None)
            (state.get("escalations") or {}).pop(escalation_key(res), None)
        res["outcome"] = outcome
        retry = outcome == "no_diagnosis" and not str(res.get("reason")).startswith(D.FINAL_NO_DIAGNOSIS)
        if (res.get("model_called") or res.get("decision")) and not retry:
            state.setdefault("diagnosed", {})[res["incident_key"]] = {
                "at": now.isoformat(), "lane": res["lane"], "siem_id": res.get("siem_id"),
                "action_id": (res.get("decision") or {}).get("action_id"), "outcome": outcome,
                "escalation": res.get("escalation")}
        if res.get("model_called") or res.get("decision"):
            rec = D.diagnosis_record(res, rows_by_id.get(res.get("siem_id")) or {}, outcome=outcome, now=now)
            # 2026-10-16 self-healing evidence: the signature, the deterministic verdict, the attach, the gate.
            rec.update({k: res.get(k) for k in ("signature", "deterministic", "attached_to", "failure_class",
                                                "live_heal_gate") if res.get(k) is not None})
            records.append(rec)
    for ev in pending_events:
        if ev.get("escalate"):
            esc = _escalation(ev, ev["escalate"], str(ev.get("outcome")), now)
            _put_escalation(state, esc)
        if ev.get("outcome") not in (None, "waiting"):
            records.append(D.remediation_record(ev, now=now))
    try:
        append_records(root / DIAGNOSES_REL, records)
        done["diagnoses_appended"] = len(records)
    except OSError as exc:
        done["errors"].append(f"diagnoses:{type(exc).__name__}:{str(exc)[:200]}")
    return done


# ---------------------------------------------------------------- main


def _deferral_eval(process_id: str):
    from lib import llm_deferral

    return llm_deferral.evaluate(process_id)


def counts(diag: dict, pending_events: list[dict]) -> dict[str, int]:
    res = diag["results"]
    return {
        "eligible": len(res), "skipped": len(diag["skipped"]),
        "model_called": sum(1 for r in res if r.get("model_called")),
        "diagnosed": sum(1 for r in res if r.get("verdict")),
        "no_diagnosis": sum(1 for r in res if r.get("outcome") == "no_diagnosis"),
        "deferred": sum(1 for r in res if r.get("reason") == "deferred_offpeak"),
        "execute": sum(1 for r in res if (r.get("decision") or {}).get("kind") == "execute"),
        "escalate_p1": sum(1 for r in res if (r.get("decision") or {}).get("priority") == "P1"),
        "escalate_p2": sum(1 for r in res if (r.get("decision") or {}).get("priority") == "P2"),
        "pending_advanced": sum(1 for e in pending_events if e.get("outcome") not in (None, "waiting")),
        "auto_closed": sum(1 for r in res if str(r.get("outcome") or "").startswith("auto_closed:")),
        "attached": sum(1 for r in res if r.get("outcome") == "attached"),
        "deterministic_execute": sum(1 for r in res if str((r.get("decision") or {}).get("reason") or "")
                                     .startswith("deterministic:")),
        "signatures": len({r.get("signature") for r in res if r.get("signature")}),
    }


def _public(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def main(argv: Optional[list[str]] = None, *, conn_factory=None, governed_call=None, now: Optional[datetime] = None,
         catalogue_path: Optional[Path] = None, registry_path: Optional[Path] = None,
         allowlist_path: Optional[Path] = None, deferral=None, store_factory=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--fixture", default=None, help="dry run only: recorded model answer (JSON) used instead of a call")
    ap.add_argument("--max-incidents", type=int, default=5)
    ap.add_argument("--min-severity", default="WARN", choices=["CRITICAL", "URGENT", "WARN", "INFO"])
    args = ap.parse_args(argv)
    if args.fixture and not args.dry_run:
        ap.error("--fixture is a dry-run option")
    now = now or datetime.now(timezone.utc)
    root = state_root()
    ledger = ledger_path(root)
    notes: dict[str, str] = {}
    try:
        catalogue = C.load_catalogue(catalogue_path or CATALOGUE)
        notes["catalogue"] = f"ok:{len(catalogue)}"
    except (OSError, ValueError) as exc:
        catalogue = {}
        notes["catalogue"] = f"invalid:{type(exc).__name__}:{str(exc)[:160]}"
    registry_rows = S.load_stage_rows(Path(registry_path or REGISTRY))     # None = unreadable: no live rerun
    registry = {str(r.get("lane_id")): r for r in registry_rows or []}
    try:
        al_doc = json.loads(Path(allowlist_path or ALLOWLIST).read_text(encoding="utf-8"))
        allowlist = {str(x.get("lane_id")): x for x in al_doc.get("lanes") or []}
    except (OSError, ValueError):
        allowlist = {}
    effect_doc = _load_json(EFFECT_KEYS) or {}
    effect_keys = {str(k): v for k, v in (effect_doc.get("lanes") or {}).items() if isinstance(v, dict)}
    cutover_policy = _load_json(CUTOVER_POLICY)
    try:
        conn = (conn_factory or connect)()
    except Exception as exc:  # noqa: BLE001
        conn = None
        notes["db"] = f"unavailable:{type(exc).__name__}:{str(exc)[:120]}"
    rows: list[dict] = []
    if conn is not None:
        try:
            rows = read_open_rows(conn)
            notes["db"] = f"ok:open_n8n_rows={len(rows)}"
        except Exception as exc:  # noqa: BLE001
            notes["db"] = f"unavailable:{type(exc).__name__}:{str(exc)[:120]}"
            conn = None
    state = _load_json(root / STATE_REL) or empty_state()
    for k, v in empty_state().items():
        state.setdefault(k, v)
    prune_state(state, now, {int(r["id"]) for r in rows if r.get("id") is not None})
    store_factory = store_factory or (lambda: _rw_store(ledger))
    sources_ok = bool(catalogue) and conn is not None
    if args.dry_run:
        pending_events = advance_pending(json.loads(json.dumps(state)), ledger=ledger, store_factory=store_factory,
                                         allowlist=allowlist, now=now, apply=False, registry_rows=registry_rows)
        fixture = DEFAULT_FIXTURE
        if args.fixture:
            fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        call = fixture_call(fixture)
        with tempfile.TemporaryDirectory(prefix="n8n-diag-dry-") as tmp:   # throwaway artifact store, deleted
            diag = diagnose(rows, catalogue=catalogue, registry=registry, state=state, now=now, ledger=ledger,
                            governed_call=call, artifact_root=Path(tmp), min_severity=args.min_severity,
                            max_incidents=args.max_incidents, deferral=deferral or _deferral_eval,
                            effect_keys=effect_keys, cutover_policy=cutover_policy)
        c = counts(diag, pending_events)
        c["fixture_answers"], c["model_called"] = c.pop("model_called"), 0   # a dry run answers from the fixture
        report = {"schema": SCHEMA, "mode": "dry-run", "as_of": now.isoformat(), "source_notes": {**notes, **diag["notes"]},
                  "counts": c, "model_calls": 0, "fixture": bool(args.fixture),
                  "would": [_public(r) for r in diag["results"]], "pending": pending_events,
                  "skipped_reasons": _reasons(diag["skipped"]), "ok": sources_ok}
        print(json.dumps(report, default=str))
        return 0 if sources_ok else 1
    # ---- apply: the only path that calls a model, executes an action or writes
    if not catalogue:
        diag = {"results": [], "skipped": [], "notes": {}}
    else:
        diag = diagnose(rows, catalogue=catalogue, registry=registry, state=state, now=now, ledger=ledger,
                        governed_call=governed_call or _bridge_call, artifact_root=root,
                        min_severity=args.min_severity, max_incidents=args.max_incidents,
                        deferral=deferral or _deferral_eval, effect_keys=effect_keys,
                        cutover_policy=cutover_policy)
    pending_events = advance_pending(state, ledger=ledger, store_factory=store_factory, allowlist=allowlist, now=now,
                                     apply=True, registry_rows=registry_rows)
    rows_by_id = {r.get("id"): r for r in rows}
    done = apply_results(diag, pending_events, state, rows_by_id, now=now, store_factory=store_factory,
                         allowlist=allowlist, root=root, registry_rows=registry_rows)
    c = counts(diag, pending_events)
    ok = sources_ok and not done["errors"]
    prev = _load_json(root / RECEIPT_REL) or {}
    blind = int(prev.get("consecutive_blind") or 0) + 1 if (c["eligible"] and not c["model_called"]
                                                            and not c["deferred"]) else 0
    receipt = {
        "schema": SCHEMA, "lane_id": D.LANE_ID, "authority": "READ_ONLY_ADVISORY", "mode": "apply",
        "as_of": now.isoformat(), "ok": ok, "ok_at": now.isoformat() if ok else prev.get("ok_at"),
        "source_notes": {**notes, **diag["notes"]}, "counts": c, "applied": done,
        "spend_today_usd": day_bucket(state, now)["spend_usd"], "calls_today": day_bucket(state, now)["calls"],
        "caps": {"per_call_usd": D.PER_CALL_CAP_USD, "daily_usd": D.DAILY_CAP_USD,
                 "per_lane_day_calls": D.MAX_CALLS_PER_LANE_DAY},
        "consecutive_blind": blind,
        "results": [_public(r) for r in diag["results"]], "pending": pending_events,
        "pending_open": len(state.get("pending") or {}),
        # 2026-10-16: only P1 rides the fan-in -> notifier -> Telegram path (once per signature); P2 is digest-only.
        "escalations": sorted((e for e in (state.get("escalations") or {}).values() if e.get("priority") == "P1"),
                              key=lambda e: str(e["key"])),
        "digest": sorted((e for e in (state.get("escalations") or {}).values() if e.get("priority") != "P1"),
                         key=lambda e: (str(e.get("lane")), str(e["key"]))),
        "escalation_routes": {"P1": "fan-in -> incident notifier -> Telegram, once per signature",
                              "P2": "receipt digest only (operator digest); never an individual message"},
        "skipped_reasons": _reasons(diag["skipped"]),
    }
    _atomic(root / STATE_REL, state)
    _atomic(root / RECEIPT_REL, receipt)
    print(json.dumps({k: receipt[k] for k in ("mode", "ok", "counts", "applied", "spend_today_usd")}, default=str))
    return 0 if ok else 1


def _reasons(skipped: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in skipped:
        out[s["reason"]] = out.get(s["reason"], 0) + 1
    return out


def _rw_store(ledger: Path):  # pragma: no cover - live ledger only
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

    return LedgerRunStore(CoordinationLedger(ledger))


def _bridge_call(messages, **kw):  # pragma: no cover - live bridge only
    return M.bridge_governed_call(messages, **kw)


if __name__ == "__main__":
    raise SystemExit(main())
