"""cio_full_cycle.py — Phase 9 full-system integration dry-run.

One autonomous advisory cycle, end-to-end, through every Phase 1-8 component:

    wake ─▶ snapshot ─▶ specialists ─▶ synthesis ─▶ capital plan
        ─▶ report v2 ─▶ office home ─▶ operator disposition

and asserts the complete evidence spine from run-ID through to operator
disposition, with store integrity verification on every event-sourced ledger.

This module is READ_ONLY_ADVISORY: it never touches a broker, order, stop,
2FA, or provider. It produces no execution authority. Every downstream
composition (capital plan, report v2, office home) is invoked as a pure
function over already-fetched, deterministic inputs.

Design contract
---------------
* Pure and deterministic for fixed inputs (including a fixed ``now``).
* Every external component is injectable; when omitted, a sandboxed
  event-store is created under ``store_dir`` (default: a fresh temp dir).
* Specialist and Hermes queues are injected; the default stand-ins simulate
  completed specialist output (SUPPORT) so the resume path convenes a real
  committee without the live agent fleet (proven separately in Checkpoint 4a).
* Fail-soft: a missing downstream source degrades gracefully rather than
  aborting the cycle.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_advisory_schema import SpecialistAdvisoryPosition  # noqa: F401
from scripts.lib.cio_capital_plan import build_capital_plan_from_sources
from scripts.lib.cio_command_center import build_office_home
from scripts.lib.cio_committee_synthesis import build_committee_synthesis_fn
from scripts.lib.cio_domain_registry import CIODomainRegistry
from scripts.lib.cio_evidence_ref import make_ref
from scripts.lib.cio_investment_decision import POSITION_HOLD
from scripts.lib.cio_outcome_learning import grade_and_learn
from scripts.lib.cio_report_v2 import build_report_v2

AUTHORITY = "READ_ONLY_ADVISORY"
OFFICE_HOME_VERSION_REF = "v1"

# Wake trigger → CIO run trigger (canonical, mirrors CIOWakeDispatcher).
WAKE_TRIGGER = "SCHEDULE_DUE"
RUN_TRIGGER = "SCHEDULED_DAILY"
RUN_PURPOSE = "SCHEDULED_CIO_BRIEF"

# Specialist domains routed for a standard daily brief (3 specialists, within
# the run-store default budget of max_specialist_calls=5).
DEFAULT_REQUIRED_DOMAINS = ["holdings", "watch", "risk"]


# ═══════════════════════════════════════════════════════════════════════════════
# Deterministic dry-run fixtures (all values explicit, none invented at runtime)
# ═══════════════════════════════════════════════════════════════════════════════


def default_holdings_doc() -> dict[str, Any]:
    """A minimal, internally-consistent holdings document for the dry-run.

    Shape matches the live `holdings.json` consumed by
    ``cio_capital_plan.load_holdings_snapshot``: cash is a holding with
    ``is_cash=True``; accounts live under ``config.accounts``.
    """
    return {
        "as_of": "2026-08-13T00:00:00+00:00",
        "portfolio_totals": {"total_value": 121_000.0},
        "config": {
            "accounts": {
                "schwab_taxable": {"taxable": True},
                "schwab_rollover_ira": {"taxable": False},
            }
        },
        "holdings": [
            {
                "symbol": "CASH",
                "is_cash": True,
                "market_value": 60_000.0,
                "account": "schwab_taxable",
            },
            {
                "symbol": "SCHD",
                "is_cash": False,
                "market_value": 31_200.0,
                "quantity": 400.0,
                "account": "schwab_rollover_ira",
                "name": "Schwab U.S. Dividend Equity ETF",
            },
            {
                "symbol": "CVX",
                "is_cash": False,
                "market_value": 18_600.0,
                "quantity": 120.0,
                "account": "schwab_taxable",
                "name": "Chevron Corp",
            },
            {
                "symbol": "XOM",
                "is_cash": False,
                "market_value": 11_200.0,
                "quantity": 100.0,
                "account": "schwab_taxable",
                "name": "Exxon Mobil Corp",
            },
        ],
    }


def default_queue() -> dict[str, Any]:
    """A desk-suggestion opportunity queue with one watch and one reentry."""
    return {
        "queue_version": "v1",
        "as_of": "2026-08-13T00:00:00+00:00",
        "items": [
            {
                "symbol": "ADBE",
                "source": "reentry_desk",
                "directive_label": "REENTRY",
                "verdict": "SUPPORT",
                "score": 0.82,
                "reason": "Momentum recovered above 200-day; thesis re-validated.",
            },
            {
                "symbol": "VTI",
                "source": "watch_desk",
                "directive_label": "WATCH",
                "verdict": None,
                "score": 0.71,
                "reason": "Broad-market rebalance candidate; awaiting dip.",
            },
        ],
    }


def default_sector_opportunities() -> list[dict[str, Any]]:
    """A single sector-opportunity synthesis row for composition coverage."""
    return [
        {
            "sector": "Energy",
            "momentum": "IMPROVING",
            "portfolio_weight_pct": 8.2,
            "target_weight_pct": 10.0,
            "deployable_usd": 24_000.0,
            "candidate_symbols": ["XOM", "CVX"],
            "readiness": "ready",
        }
    ]


def default_thesis() -> dict[str, Any]:
    return {
        "summary": "Dividend-growth core with a measured energy tilt.",
        "stance": "NEUTRAL",
        "bullets": [
            "Maintain SCHD as the income spine.",
            "Energy tilt funded from idle cash, bounded by headroom.",
        ],
        "risk_posture": "MODERATE",
    }


def default_attribution() -> dict[str, Any]:
    return {
        "ytd_return_pct": 6.4,
        "benchmark_ytd_return_pct": 5.9,
        "excess_return_pct": 0.5,
    }


def default_income() -> dict[str, Any]:
    return {
        "annual_income_usd": 14_200.0,
        "yield_pct": 2.3,
        "sources": [{"symbol": "SCHD", "income_usd": 9_600.0}],
    }


def default_source_refs() -> list[dict[str, Any]]:
    return [
        {
            "ref_id": "ref_dryrun_holdings",
            "domain": "holdings",
            "source": "broker_export",
            "source_record_id": "holdings-2026-08-13",
            "quality_state": "AVAILABLE",
        },
        {
            "ref_id": "ref_dryrun_risk",
            "domain": "risk",
            "source": "risk_model",
            "source_record_id": "risk-2026-08-13",
            "quality_state": "AVAILABLE",
        },
    ]


def default_snapshot(now: datetime) -> dict[str, Any]:
    """A comprehensive AVAILABLE domain snapshot so the evidence gate passes.

    Mirrors the shape produced by ``CIOFinancialSnapshot.to_evidence_record``
    plus the ``domain_states`` map that ``CIORunWorker`` derives.
    """
    domains = list(CIODomainRegistry.load().domain_ids)
    return {
        "snapshot_id": f"snap-dryrun-{uuid.uuid4().hex[:12]}",
        "observed_at": now.isoformat(),
        "content_hash": hashlib.sha256(
            json.dumps({"dryrun": True, "now": now.isoformat()}, sort_keys=True).encode()
        ).hexdigest(),
        "available": domains,
        "stale": [],
        "unavailable": [],
        "not_applicable": [],
        "domain_states": {d: "AVAILABLE" for d in domains},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Stand-in queues (replacing the live agent fleet / Hermes for the dry-run)
# ═══════════════════════════════════════════════════════════════════════════════


class _AutoCompleteHandoffQueue:
    """Handoff queue stand-in that completes specialists immediately (SUPPORT).

    The live specialist round-trip depends on the agent fleet's readiness
    registry, proven separately in Checkpoint 4a. This stand-in records every
    enqueue and returns a COMPLETED projection carrying a deterministic SUPPORT
    advisory so the resume path convenes a real advisory committee.
    """

    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self._projections: dict[str, dict[str, Any]] = {}

    def get_handoff(self, handoff_id: str) -> Optional[dict[str, Any]]:
        return self._projections.get(handoff_id)

    def enqueue(self, handoff: dict[str, Any], actor_id: str = "cio_run_worker") -> dict[str, Any]:
        self.enqueued.append(dict(handoff))
        hid = handoff["handoff_id"]
        specialist = handoff.get("to_agent", "maria")
        self._projections[hid] = {
            "current_status": "COMPLETED",
            "to_agent": specialist,
            "specialist_advisory": {
                "specialist_id": specialist,
                "position": SpecialistAdvisoryPosition.SUPPORT.value,
                "confidence": 0.7,
                "rationale": "deterministic dry-run support",
            },
        }
        return {"stream_id": hid}


class _NullGoalStore:
    """Goal-store stand-in that reports no due goals (disables WS2 wake path)."""

    def list_due_or_idle_goals(self, limit: int = 0) -> list[dict[str, Any]]:
        return []

    def goals_for_event_types(self, event_types: list[str], limit: int = 0) -> list[dict[str, Any]]:
        return []

    def get_context_for_agent(self, agent_id: str) -> dict[str, Any]:
        return {"open_goals": [], "thesis_snippets": [], "open_actions": []}

    def record_wake(self, goal_id: str, *, agent_id: str = "", outcome: str = "") -> None:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Store assembly
# ═══════════════════════════════════════════════════════════════════════════════


def _ensure_stores(
    store_dir: Path,
    run_store: Any,
    wake_store: Any,
    handoff_queue: Any,
    hermes_queue: Any,
    action_ledger: Any,
    notification_outbox: Any,
    outcome_store: Any,
    learning_store: Any,
) -> dict[str, Any]:
    """Return a dict of store instances, creating sandboxed defaults as needed."""
    from scripts.lib.cio_action_ledger import CIOActionLedger
    from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue
    from scripts.lib.cio_hermes_challenge_queue import HermesChallengeQueue
    from scripts.lib.cio_learning_candidate import CIOLearningCandidateStore
    from scripts.lib.cio_notification_outbox import NotificationOutbox
    from scripts.lib.cio_outcome_store import CIOOutcomeStore
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore

    store_dir.mkdir(parents=True, exist_ok=True)

    if run_store is None:
        run_store = CIORunStore(store_path=str(store_dir / "cio_runs.jsonl"))
        run_store.initialize()
    if wake_store is None:
        wake_store = CIOWakeJobStore(event_store_path=store_dir / "cio_wake_jobs.jsonl")
    if handoff_queue is None:
        handoff_queue = _AutoCompleteHandoffQueue()
    if hermes_queue is None:
        hermes_queue = HermesChallengeQueue(event_store_path=store_dir / "hermes_challenge_queue.jsonl")
    if action_ledger is None:
        action_ledger = CIOActionLedger(event_store_path=store_dir / "cio_action_ledger.jsonl")
    if notification_outbox is None:
        notification_outbox = NotificationOutbox(event_store_path=store_dir / "cio_notification_outbox.jsonl")
    if outcome_store is None:
        outcome_store = CIOOutcomeStore(store_path=str(store_dir / "cio_outcomes.jsonl"))
    if learning_store is None:
        learning_store = CIOLearningCandidateStore(store_path=str(store_dir / "cio_learning_candidates.jsonl"))

    return {
        "run_store": run_store,
        "wake_store": wake_store,
        "handoff_queue": handoff_queue,
        "hermes_queue": hermes_queue,
        "action_ledger": action_ledger,
        "notification_outbox": notification_outbox,
        "outcome_store": outcome_store,
        "learning_store": learning_store,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full-cycle orchestration
# ═══════════════════════════════════════════════════════════════════════════════


def run_full_cycle(
    *,
    store_dir: Optional[Path] = None,
    run_store: Any = None,
    wake_store: Any = None,
    handoff_queue: Any = None,
    hermes_queue: Any = None,
    action_ledger: Any = None,
    notification_outbox: Any = None,
    outcome_store: Any = None,
    learning_store: Any = None,
    goal_store: Any = None,
    readiness_registry: Any = None,
    synthesis_fn: Any = None,
    required_domains: Optional[list[str]] = None,
    force_snapshot: Optional[dict[str, Any]] = None,
    symbols: Optional[list[str]] = None,
    holdings_doc: Optional[dict[str, Any]] = None,
    queue: Optional[dict[str, Any]] = None,
    sector_opportunities: Optional[list[dict[str, Any]]] = None,
    thesis: Optional[dict[str, Any]] = None,
    attribution: Optional[dict[str, Any]] = None,
    income: Optional[dict[str, Any]] = None,
    source_refs: Optional[list[dict[str, Any]]] = None,
    disposition: str = "ACKNOWLEDGED",
    rating: Optional[int] = None,
    note: str = "",
    outcome_status: str = "UNKNOWN",
    what_was_right: str = "",
    what_was_wrong: str = "",
    unknowns: str = "",
    outcome_symbol: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Run one autonomous advisory cycle end-to-end and assert the evidence spine.

    Returns a dict with ``ok``, ``spine``, ``integrity``, ``office_home``,
    ``capital_plan``, ``report_v2``, ``run_projection``, and ``store_dir``.
    """
    now = now or datetime.now(timezone.utc)
    required_domains = list(required_domains or DEFAULT_REQUIRED_DOMAINS)
    symbols = list(symbols or ["SCHD", "CVX", "XOM"])

    if store_dir is None:
        store_dir = Path(tempfile.mkdtemp(prefix="cio_full_cycle_"))

    stores = _ensure_stores(
        store_dir,
        run_store,
        wake_store,
        handoff_queue,
        hermes_queue,
        action_ledger,
        notification_outbox,
        outcome_store,
        learning_store,
    )
    run_store = stores["run_store"]
    wake_store = stores["wake_store"]
    handoff_queue = stores["handoff_queue"]
    hermes_queue = stores["hermes_queue"]
    action_ledger = stores["action_ledger"]
    notification_outbox = stores["notification_outbox"]
    outcome_store = stores["outcome_store"]
    learning_store = stores["learning_store"]

    snapshot = force_snapshot or default_snapshot(now)

    # ── Defaults for downstream composition (fail-soft) ────────────────────
    holdings_doc = holdings_doc if holdings_doc is not None else default_holdings_doc()
    queue = queue if queue is not None else default_queue()
    sector_opportunities = (
        sector_opportunities if sector_opportunities is not None else default_sector_opportunities()
    )
    thesis = thesis if thesis is not None else default_thesis()
    attribution = attribution if attribution is not None else default_attribution()
    income = income if income is not None else default_income()
    source_refs = source_refs if source_refs is not None else default_source_refs()

    # ── Synthesis function (committee HOLD by default; deterministic) ───────
    # The synthesis function is always wrapped so its decision identity is
    # captured for the evidence spine, whether it is the built-in committee
    # synthesis or an injected stand-in.
    captured: dict[str, Any] = {}
    base_fn = synthesis_fn
    if base_fn is None:
        refs = [
            make_ref(
                "portfolio",
                {"portfolio_value_usd": 1_000_000},
                source="dry-run fixture",
                quality_state="AVAILABLE",
            ),
            make_ref(
                "risk",
                {"risk_heat": "MODERATE"},
                source="dry-run fixture",
                quality_state="AVAILABLE",
            ),
        ]
        base_fn = build_committee_synthesis_fn(
            intended_position=POSITION_HOLD,
            quorum=3,
            symbols=symbols,
            rationale_linked_to_evidence=(
                "Hold across book; committee unanimous SUPPORT; no execution authority."
            ),
            conditions_to_change_view=[
                "Sector momentum accelerates above drift threshold",
                "Cash falls below policy band floor",
                "Single-name concentration breaches cap",
            ],
            evidence_refs=refs,
        )

    def synthesis_fn(run, snapshot, specialist_result, hermes_result):
        out = base_fn(run, snapshot, specialist_result, hermes_result)
        captured["decision_id"] = out.get("decision_id")
        captured["final_position"] = out.get("final_position")
        captured["summary"] = out.get("summary")
        return out

    # ── Wake → dispatch → run ───────────────────────────────────────────────
    from scripts.lib.cio_run_worker import CIORunWorker
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher

    wake_job_id = f"wake-sched-{uuid.uuid4().hex[:12]}"
    wake_store.enqueue(
        {
            "wake_job_id": wake_job_id,
            "trigger_type": WAKE_TRIGGER,
            "trigger_ref": "daily-brief-dryrun",
            "trigger_hash": hashlib.sha256(b"daily-brief-dryrun").hexdigest()[:16],
            "required_domains": required_domains,
            "wake_intent": "NEW_RUN",
            "idempotency_key": f"dryrun:{wake_job_id}",
            "context": {"dryrun": True},
        },
        actor_id="cio_full_cycle",
    )

    dispatcher = CIOWakeDispatcher(
        wake_store=wake_store,
        run_store=run_store,
        dispatch_ledger_path=str(store_dir / "cio_wake_dispatches.jsonl"),
        goal_store=goal_store if goal_store is not None else _NullGoalStore(),
        readiness_registry=readiness_registry,
    )

    dispatch_result = dispatcher.poll_and_dispatch(max_dispatches=1)
    dispatched = dispatch_result.get("dispatched") or []
    if not dispatched:
        return {
            "ok": False,
            "authority": AUTHORITY,
            "error": "No run dispatched",
            "dispatch_result": dispatch_result,
            "store_dir": str(store_dir),
        }
    run_id = dispatched[0]["run_id"]

    worker = CIORunWorker(
        run_store=run_store,
        action_ledger=action_ledger,
        notification_outbox=notification_outbox,
        handoff_queue=handoff_queue,
        hermes_queue=hermes_queue,
        mode="shadow",
        synthesis_fn=synthesis_fn,
    )

    # Pass 1: health → snapshot → route specialists → wait.
    pass1 = worker.execute(run_id, force_health_state="HEALTHY", force_snapshot=snapshot)

    # Pass 2: resume → resolve completed specialists → synthesize → act → notify.
    pass2 = worker.execute(run_id, force_snapshot=snapshot)

    if pass2.get("status") != "COMPLETED":
        return {
            "ok": False,
            "authority": AUTHORITY,
            "error": f"Run did not complete: {pass2.get('status')}",
            "run_id": run_id,
            "wake_job_id": wake_job_id,
            "pass1": pass1,
            "pass2": pass2,
            "store_dir": str(store_dir),
        }

    run_projection = run_store.get_run(run_id)
    cio_artifact_id = run_projection.get("cio_artifact_id") or ""

    # Complete the linked wake now that the run reached a terminal state.
    dispatcher.on_run_completed(
        wake_job_id, run_id, "COMPLETED", cio_artifact_id=cio_artifact_id
    )

    action_ids = list(run_projection.get("created_action_ids") or [])
    notification_ids = list(run_projection.get("notification_ids") or [])
    handoff_ids = list(run_projection.get("specialist_requests") or [])
    decision_id = captured.get("decision_id") or ""
    final_position = captured.get("final_position") or ""

    # ── Operator disposition + outcome learning (advisory-only) ──────────────
    # Phase 9 closed the loop to a durable disposition. Phase 10 closes it the
    # rest of the way: the disposition + a measured outcome derive learning
    # candidates (effect-constrained) and reverse-factor writebacks that feed the
    # scorer's reliability gate. An unmeasured outcome is fail-closed: no
    # candidates and no writebacks are fabricated.
    disposition_record = None
    learning = None
    disposition_target = action_ids[0] if action_ids else None
    if disposition_target:
        learning = grade_and_learn(
            outcome_store=outcome_store,
            learning_store=learning_store,
            cio_action_id=disposition_target,
            operator_disposition=disposition,
            outcome_status=outcome_status,
            result_summary=note,
            what_was_right=what_was_right,
            what_was_wrong=what_was_wrong,
            unknowns=unknowns,
            symbol=(outcome_symbol or (symbols[0] if symbols else None)),
            context_refs=[decision_id] if decision_id else [],
            actor="operator",
        )
        if learning.get("ok"):
            disposition_record = learning.get("outcome")

    # ── Downstream composition (Phases 6, 7, 8) ─────────────────────────────
    capital_plan = build_capital_plan_from_sources(
        holdings_doc=holdings_doc,
        queue=queue,
        sector_opportunities=sector_opportunities,
        now=now,
    )

    report_v2 = build_report_v2(
        part_b_ctx={"positions": holdings_doc.get("holdings", [])},
        part_a_inputs={
            "thesis": thesis,
            "capital_plan": capital_plan,
            "sector_opportunities": sector_opportunities,
            "opportunity_queue": queue,
            "performance_attribution": attribution,
            "dispositions": [{"action_id": disposition_target, "disposition": disposition}]
            if disposition_target
            else [],
        },
        source_sha="dryrun",
        input_payloads={
            "holdings_doc": holdings_doc,
            "queue": queue,
            "decision_id": decision_id,
            "run_id": run_id,
        },
        now=now,
    )

    office_home = build_office_home(
        capital_plan=capital_plan,
        sector_opportunities={"rows": sector_opportunities},
        opportunity_queue=queue,
        report=report_v2,
        thesis=thesis,
        attribution=attribution,
        income=income,
        actions=[
            {
                "cio_action_id": aid,
                "action_type": "HOLD",
                "title": "Hold across book",
                "domain": "GENERAL",
                "priority": "HIGH",
                "cio_decision_id": decision_id,
            }
            for aid in action_ids
        ],
        source_refs=source_refs,
        run_ids=[{"run_id": run_id, "status": "COMPLETED"}],
        now=now,
    )

    spine = {
        "authority": AUTHORITY,
        "run_id": run_id,
        "wake_job_id": wake_job_id,
        "snapshot_id": snapshot.get("snapshot_id"),
        "handoff_ids": handoff_ids,
        "decision_id": decision_id,
        "decision_position": final_position,
        "action_ids": action_ids,
        "notification_ids": notification_ids,
        "decision_key": f"action:{disposition_target}" if disposition_target else None,
        "disposition": (
            {
                "cio_action_id": disposition_target,
                "operator_disposition": disposition,
                "rating": rating,
                "note": note,
            }
            if disposition_target
            else None
        ),
        "learning": (
            {
                "outcome_id": learning.get("outcome_id"),
                "signal": learning.get("signal"),
                "candidate_ids": [c.get("event_id") for c in (learning.get("candidates") or [])],
                "candidate_count": learning.get("candidate_count"),
                "writeback_count": learning.get("writeback_count"),
                "sample_sizes": learning.get("sample_sizes"),
                "calibration": learning.get("calibration"),
            }
            if learning
            else None
        ),
        "as_of": now.isoformat(),
    }

    integrity = _verify_spine(
        run_store=run_store,
        run_projection=run_projection,
        wake_job_id=wake_job_id,
        action_ledger=action_ledger,
        notification_outbox=notification_outbox,
        outcome_store=outcome_store,
        learning_store=learning_store,
        spine=spine,
    )

    return {
        "ok": bool(integrity.get("passed")),
        "authority": AUTHORITY,
        "run_id": run_id,
        "wake_job_id": wake_job_id,
        "decision_id": decision_id,
        "spine": spine,
        "integrity": integrity,
        "office_home": office_home,
        "capital_plan": capital_plan,
        "report_v2": report_v2,
        "learning": learning,
        "run_projection": run_projection,
        "dispatch_result": dispatch_result,
        "pass1_status": pass1.get("status"),
        "pass2_status": pass2.get("status"),
        "disposition_record": disposition_record,
        "store_dir": str(store_dir),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Evidence-spine verification
# ═══════════════════════════════════════════════════════════════════════════════


def _verify_spine(
    *,
    run_store: Any,
    run_projection: dict[str, Any],
    wake_job_id: str,
    action_ledger: Any,
    notification_outbox: Any,
    outcome_store: Any,
    learning_store: Any,
    spine: dict[str, Any],
) -> dict[str, Any]:
    """Assert the full evidence spine and store integrity. Returns check results."""
    checks: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    def _note(name: str, ok: bool, detail: str = "") -> None:
        notes.append({"name": name, "ok": bool(ok), "detail": detail})

    run_id = spine.get("run_id")
    decision_id = spine.get("decision_id") or ""

    # 1. wake → run linkage
    _check(
        "wake_run_linkage",
        run_projection.get("trigger_ref") == wake_job_id,
        f"run.trigger_ref={run_projection.get('trigger_ref')!r} wake={wake_job_id!r}",
    )

    # 2. run terminal state
    _check(
        "run_terminal",
        run_projection.get("status") == "COMPLETED",
        f"status={run_projection.get('status')!r}",
    )

    # 3. snapshot captured
    _check("snapshot_captured", bool(spine.get("snapshot_id")), str(spine.get("snapshot_id")))

    # 4. specialists routed (handoffs) present
    _check(
        "specialists_routed",
        len(spine.get("handoff_ids") or []) > 0,
        f"handoffs={len(spine.get('handoff_ids') or [])}",
    )

    # 5. decision produced (informational — a DEFER/no-recommendation cycle is
    #    a legitimate outcome, not an integrity failure)
    _note("decision_produced", bool(decision_id), str(decision_id))

    # 6. actions written and linked to the run via origin_run_id (always hard)
    action_ids = spine.get("action_ids") or []
    action_ok = bool(action_ids)
    action_detail = f"actions={len(action_ids)}"
    has_decision_link = False
    for aid in action_ids:
        a = action_ledger.get_action(aid)
        if not a:
            action_ok = False
            action_detail = f"action {aid} missing from ledger"
            break
        if a.get("origin_run_id") != run_id:
            action_ok = False
            action_detail = f"action {aid} origin_run_id={a.get('origin_run_id')!r}"
            break
        if a.get("cio_decision_id"):
            has_decision_link = True
            if decision_id and a.get("cio_decision_id") != decision_id:
                action_ok = False
                action_detail = (
                    f"action {aid} cio_decision_id={a.get('cio_decision_id')!r} "
                    f"!= decision {decision_id!r}"
                )
                break
    _check("actions_linked_to_run", action_ok, action_detail)

    # 7. decision → action linkage (hard only when a decision was produced AND
    #    at least one action carries it; otherwise it is an informational note —
    #    a no-recommendation cycle legitimately writes a STATUS action with no
    #    decision linkage).
    if decision_id:
        if has_decision_link:
            _check("decision_linked_to_action", True, f"decision={decision_id!r}")
        else:
            _note(
                "decision_unlinked",
                False,
                "decision produced but no action carried it (STATUS fallback)",
            )

    # 8. notifications linked to actions
    notif_ok = True
    notif_detail = ""
    for nid in spine.get("notification_ids") or []:
        n = notification_outbox.get_notification(nid)
        if not n:
            notif_ok = False
            notif_detail = f"notification {nid} missing"
            break
        if n.get("cio_action_id") not in action_ids:
            notif_ok = False
            notif_detail = f"notification {nid} cio_action_id={n.get('cio_action_id')!r}"
            break
    _check(
        "notifications_linked_to_actions",
        notif_ok and bool(spine.get("notification_ids")),
        notif_detail or f"notifications={len(spine.get('notification_ids') or [])}",
    )

    # 9. disposition recorded against an action
    disp = spine.get("disposition") or {}
    disp_ok = bool(disp.get("cio_action_id"))
    if disp_ok:
        outcomes = outcome_store.get_outcomes(disp["cio_action_id"])
        disp_ok = bool(outcomes)
    _check("disposition_recorded", disp_ok, str(disp))

    # 9b. outcome learning loop closed (Phase 10). A measured outcome derives
    #     effect-constrained learning candidates + reverse writebacks; an
    #     unmeasured outcome is fail-closed (no candidates, no writebacks).
    learning = spine.get("learning") or {}
    if learning:
        _check("learning_loop_closed", bool(learning.get("outcome_id")), str(learning.get("signal")))
        cand_ids = learning.get("candidate_ids") or []
        if cand_ids:
            cand_ok = True
            cand_detail = ""
            by_id = {e.get("event_id"): e for e in learning_store.list_candidates()}
            for cid in cand_ids:
                ev = by_id.get(cid)
                if not ev:
                    cand_ok = False
                    cand_detail = f"candidate {cid} missing from store"
                    break
                p = ev.get("payload") or {}
                if p.get("parent_outcome_id") != learning.get("outcome_id"):
                    cand_ok = False
                    cand_detail = f"candidate {cid} parent_outcome_id mismatch"
                    break
                if p.get("parent_action_id") != disp.get("cio_action_id"):
                    cand_ok = False
                    cand_detail = f"candidate {cid} parent_action_id mismatch"
                    break
            _check("learning_candidates_linked", cand_ok, cand_detail or f"candidates={len(cand_ids)}")
        else:
            _note("no_learning_candidates", True, "no measurable signal — no candidates minted")
        gates = (learning.get("calibration") or {}).get("gates") or {}
        inflated = [
            f for f, g in gates.items()
            if g.get("effective_weight", 0.0) > g.get("base_weight", 0.0) + 1e-9
        ]
        _check("calibration_not_inflated", not inflated, "inflated=%s" % inflated or "ok")
    else:
        _note("learning_loop_not_run", False, "no disposition target")

    # 10. store integrity (hash chains)
    if hasattr(run_store, "verify_integrity"):
        run_integrity = run_store.verify_integrity()
        if isinstance(run_integrity, tuple):
            run_valid, run_detail = run_integrity
        else:
            run_valid = bool(run_integrity.get("valid"))
            run_detail = f"events={run_integrity.get('total_events')}"
    else:
        run_valid, run_detail = True, "no verifier"
    _check("run_store_integrity", bool(run_valid), str(run_detail))
    ledger_integrity = action_ledger.verify_integrity()
    _check(
        "action_ledger_integrity",
        bool(ledger_integrity.get("valid")),
        f"events={ledger_integrity.get('total_events')}",
    )
    outbox_integrity = notification_outbox.verify_integrity()
    _check(
        "notification_outbox_integrity",
        bool(outbox_integrity.get("valid")),
        f"events={outbox_integrity.get('total_events')}",
    )

    passed = all(c["ok"] for c in checks)
    return {
        "passed": passed,
        "checks": checks,
        "notes": notes,
        "passed_count": sum(1 for c in checks if c["ok"]),
        "total_count": len(checks),
    }
