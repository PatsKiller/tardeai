"""Pilot observations built from the REAL producers (plan tranche B, 2026-10-07).

The five contracts in n8n_pilot_contracts.py were proven only against fixtures whose field names
(``period``, ``amount_usd``, ``hermes_run_id``) do not exist in the served stores (``cadence``,
``usd``, ``run_id``). Each builder here reads the producer's own artifact, maps it onto the
contract's vocabulary, and says NOT_MEASURED where the producer carries no such fact. Nothing here
sends, charges, or writes; a missing store yields an observation the contract will refuse.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Callable, Optional

NO_CONSUMER_REASON = "library for the n8n pilot shadow runs; called by tests and the (unscheduled) pilot runner"
OBSERVATION_SCHEMA = "N8nPilotObservation@v1"


def state_root(env: Optional[dict] = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def served_sha(env: Optional[dict] = None) -> Optional[str]:
    env = os.environ if env is None else env
    explicit = env.get("TRADEAI_SERVED_SHA")
    if explicit:
        return explicit.strip()
    try:
        return (Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "GIT_SHA").read_text().strip()
    except OSError:
        return None


def _json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _tail_jsonl(path: Path, *, max_bytes: int = 4_000_000) -> list[dict]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    for line in chunk.splitlines()[1 if size > max_bytes else 0:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _base(lane_id: str, source: str, root: Path) -> dict[str, Any]:
    return {"schema": OBSERVATION_SCHEMA, "lane_id": lane_id, "source": source, "state_root": str(root),
            "send": False, "provider_charge_requested": False, "consumer_receipt": None}


# ── morning-brief-0730 ───────────────────────────────────────────────────────────────────────
def morning_brief(root: Optional[Path] = None, *, session_date: Optional[str] = None) -> dict[str, Any]:
    """From data/cio/morning_brief_semantic_state.json (publish CLAIMS made before the send). The
    claim is not a send receipt and not a consumer receipt: the contract will answer ARTIFACT_WRITTEN."""
    root = root or state_root()
    p = root / "data" / "cio" / "morning_brief_semantic_state.json"
    obs = _base("morning-brief-0730", str(p), root)
    doc = _json(p) or {}
    published = doc.get("published") or {}
    day = session_date or _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    todays = [v for k, v in published.items() if str(v.get("session_date")) == day]
    obs.update({"session_date": day, "publish_claims": len(todays),
                "claimed_at": max((v.get("claimed_at") or "" for v in todays), default=None),
                "signal_kind": "publish_claim", "artifact_status": "OBSERVED" if todays else "ABSENT",
                "send_receipt": ("OBSERVED" if any(isinstance(e, dict) and "sent" in e for e in todays) else "NOT_MEASURED (no sent flag persisted for this session)"), "sent": any(bool(e.get("sent")) for e in todays if isinstance(e, dict)), "sent_at": max((str(e.get("sent_at") or "") for e in todays if isinstance(e, dict)), default=None) or None})
    return obs


# ── research-scheduler-holdings ──────────────────────────────────────────────────────────────
def holdings_research(root: Optional[Path] = None, *, since_hours: float = 24.0, now: Optional[_dt.datetime] = None) -> dict[str, Any]:
    """From data/cio/research_call_accounting.jsonl: the scheduler's own run_id and trigger/mode.
    Only a research_scheduler row whose trigger is ``holdings`` proves the mode; a SKIP_GATED row
    becomes the typed refusal; no row in the window is a typed refusal too."""
    root = root or state_root()
    now = now or _dt.datetime.now(_dt.timezone.utc)
    p = root / "data" / "cio" / "research_call_accounting.jsonl"
    obs = _base("research-scheduler-holdings", str(p), root)
    since = now - _dt.timedelta(hours=since_hours)
    rows = []
    for r in _tail_jsonl(p):
        if r.get("producer") != "research_scheduler":
            continue
        try:
            ts = _dt.datetime.fromisoformat(str(r.get("timestamp")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= since:
            rows.append(r)
    modes = sorted({str((r.get("metadata") or {}).get("mode") or r.get("trigger") or "") for r in rows})
    holdings = [r for r in rows if "holdings" in str((r.get("metadata") or {}).get("mode") or r.get("trigger") or "")]
    obs.update({"window_hours": since_hours, "scheduler_rows": len(rows), "modes_seen": modes})
    if not holdings:
        obs.update({"mode": None, "typed_refusal": {"code": "no_holdings_run_in_window",
                                                     "reason": f"research_scheduler wrote {len(rows)} rows in {since_hours:g} h, modes {modes or ['none']}, none in holdings mode"}})
        return obs
    latest = holdings[-1]
    obs["mode"] = "holdings"
    if latest.get("event") == "SCHEDULED":
        obs["hermes_run_id"] = latest.get("run_id")
        obs["call_id"] = latest.get("call_id")
    else:
        obs["typed_refusal"] = {"code": str(latest.get("event") or "unknown_event").lower(),
                                "reason": str(latest.get("reason") or "scheduler refused the run")}
    return obs


# ── material-change-digest ───────────────────────────────────────────────────────────────────
def material_digest(db_query: Optional[Callable[..., list[dict]]] = None, *, since_hours: float = 24.0,
                    root: Optional[Path] = None) -> dict[str, Any]:
    """From Postgres material_changes (read-only): the newest detector event and its notify_outcome.
    ``muted`` is never asserted here — the live notifier owns delivery — so the contract refuses
    with live_notifier_stays_in_code until a muted digest path exists. That refusal is the finding."""
    root = root or state_root()
    obs = _base("material-change-digest", "postgres:material_changes", root)
    obs["muted"] = False
    if db_query is None:
        obs.update({"detector_event_id": None, "detector_status": "NOT_MEASURED (no read-only query supplied)"})
        return obs
    try:
        rows = db_query("SELECT change_guid, symbol, kind, notify_outcome, notified_at, created_at FROM material_changes "
                        "WHERE created_at > now() - (%s * interval '1 hour') ORDER BY created_at DESC LIMIT 1", (since_hours,)) or []
    except Exception as exc:  # noqa: BLE001
        obs.update({"detector_event_id": None, "detector_status": f"UNREADABLE:{type(exc).__name__}"})
        return obs
    if not rows:
        obs.update({"detector_event_id": None, "detector_status": "no detector event in window"})
        return obs
    r = rows[0]
    obs.update({"detector_event_id": str(r.get("change_guid")), "symbol": r.get("symbol"), "kind": r.get("kind"),
                "suppression": r.get("notify_outcome"), "notified_at": str(r.get("notified_at")) if r.get("notified_at") else None,
                "detector_status": "OBSERVED"})
    return obs


# ── llm-spend-report-daily ───────────────────────────────────────────────────────────────────
def llm_spend_daily(root: Optional[Path] = None) -> dict[str, Any]:
    """From data/runtime/llm_spend_report_last_daily.json (LlmSpendReportRun@v1): cadence -> period,
    usd -> amount_usd. ``sent`` is the adapter return, not a consumer receipt."""
    root = root or state_root()
    p = root / "data" / "runtime" / "llm_spend_report_last_daily.json"
    obs = _base("llm-spend-report-daily", str(p), root)
    doc = _json(p)
    if not doc:
        obs.update({"period": None, "amount_usd": None, "artifact_status": "ABSENT"})
        return obs
    usd = doc.get("usd")
    obs.update({"period": doc.get("cadence"), "amount_usd": float(usd) if isinstance(usd, (int, float)) and not isinstance(usd, bool) else None,
                "report_key": doc.get("key"), "ran_at": doc.get("ran_at"), "adapter_sent": bool(doc.get("sent")),
                "artifact_status": "OBSERVED"})
    return obs


# ── approval-package-reminder ────────────────────────────────────────────────────────────────
def approval_reminder(root: Optional[Path] = None) -> dict[str, Any]:
    """From the run receipt (ApprovalReminderReceipt@v1) and, when the reconciler has written one,
    its reconcile receipt. A reconciled DELIVERY_OBSERVED becomes the contract's consumer receipt."""
    root = root or state_root()
    p = root / "data" / "runtime" / "approval_package_reminder_last.json"
    q = root / "data" / "runtime" / "approval_reminder_reconcile_last.json"
    obs = _base("approval-package-reminder", str(p), root)
    receipt = _json(p)
    obs["signal"] = str(p)
    obs["signal_kind"] = "run_receipt"
    if not receipt:
        obs["run_receipt"] = None
        obs["artifact_status"] = "ABSENT"
        return obs
    obs["run_receipt"] = {k: receipt.get(k) for k in ("run_id", "served_sha", "planner_status", "outcome", "action_count",
                                                        "delivery_status", "delivery_receipt_count", "started_at", "ended_at")}
    obs["artifact_status"] = "OBSERVED"
    rec = _json(q)
    if rec and rec.get("run_id") == receipt.get("run_id") and receipt.get("delivery_status") == "DELIVERY_OBSERVED":
        obs["consumer_receipt"] = {"consumer": "approval-reminder-reconcile", "receipt_id": str(rec.get("run_id"))}
    return obs


BUILDERS: dict[str, Callable[..., dict[str, Any]]] = {
    "morning-brief-0730": morning_brief,
    "research-scheduler-holdings": holdings_research,
    "material-change-digest": material_digest,
    "llm-spend-report-daily": llm_spend_daily,
    "approval-package-reminder": approval_reminder,
}


def event_reference(lane_id: str, *, idempotency_key: str, subject_key: str, artifact_ref: str,
                    now: Optional[_dt.datetime] = None, deadline_hours: float = 1.0,
                    origin_sha: Optional[str] = None, correlation_id: Optional[str] = None) -> dict[str, Any]:
    """A gateway event reference (event-reference/v0) for a pilot lane, stamped with the served SHA."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    sha = origin_sha or served_sha() or ""
    return {"event_id": f"evt-{lane_id}-{idempotency_key}", "source_project": "trade-ai", "lane_id": lane_id,
            "schema_version": "event-reference/v0", "origin_sha": sha, "subject_key": subject_key,
            "source_timestamp": now.isoformat(), "deadline": (now + _dt.timedelta(hours=deadline_hours)).isoformat(),
            "artifact_ref": artifact_ref, "authority_class": "coordination_read",
            "correlation_id": correlation_id or f"corr-{idempotency_key}", "idempotency_key": idempotency_key}
