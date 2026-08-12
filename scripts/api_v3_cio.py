"""api_v3_cio.py — /v3/cio Command Center API: CIO dashboard data.

Serves the CIO Data Broker projection, action ledger, delegation status,
Hermes research, and advisory plans — all READ_ONLY_ADVISORY (no broker/order).

Routes:
  GET /api/v3/cio              — Full CIO dashboard (snapshot + actions + delegation)
  GET /api/v3/cio/snapshot      — CIO Data Broker snapshot only
  GET /api/v3/cio/actions       — Open action items from the JSONL ledger
  GET /api/v3/cio/delegation    — Delegation + Hermes challenge status
  GET /api/v3/cio/hermes        — Hermes research intelligence summary
  GET /api/v3/cio/plans         — Open advisory plans (optional ?limit=)
  GET /api/v3/cio/plans/{id}    — Single plan detail for deep links ?plan=
  GET /api/v3/cio/thesis        — Active desk@vN thesis
  POST /api/v3/cio/plans/{id}/disposition — ack/defer/done/reject (status only)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _cio_snapshot_data() -> dict[str, Any]:
    """Get the CIO Data Broker snapshot."""
    try:
        from lib.data_broker.cio_portfolio import get_cio_snapshot
        return get_cio_snapshot(max_age_s=30)
    except Exception:
        return {"error": "Data Broker unavailable", "domains": {}, "health": {}}


def _cio_actions_data(limit: int = 20) -> list[dict[str, Any]]:
    """Get CIO actions from the event-sourced JSONL ledger."""
    ledger_path = PROJECT_ROOT / "data" / "cio" / "cio_action_ledger.jsonl"
    events = _read_jsonl(ledger_path)
    actions: dict[str, dict[str, Any]] = {}

    for event in events:
        payload = event.get("payload", {})
        aid = payload.get("cio_action_id")
        if not aid:
            continue
        event_type = event.get("event_type", "")
        if event_type == "CIO_ACTION_CREATED":
            actions[aid] = payload
        elif event_type == "CIO_ACTION_UPDATED":
            if aid in actions:
                actions[aid].update(payload)

    open_actions = [
        a for a in actions.values()
        if a.get("status") in ("OPEN", "ACKNOWLEDGED")
    ]
    return sorted(open_actions, key=lambda a: a.get("created_at", ""), reverse=True)[:limit]


def _delegation_data() -> dict[str, Any]:
    """Get delegation and Hermes challenge status."""
    handoff_path = PROJECT_ROOT / "data" / "cio" / "agent_handoff_queue.jsonl"
    challenge_path = PROJECT_ROOT / "data" / "cio" / "hermes_challenge_queue.jsonl"

    handoffs = _read_jsonl(handoff_path)
    challenges = _read_jsonl(challenge_path)

    # Count by status
    handoff_statuses: dict[str, int] = {}
    for h in handoffs:
        et = h.get("event_type", "")
        if "ENQUEUED" in et:
            handoff_statuses["ENQUEUED"] = handoff_statuses.get("ENQUEUED", 0) + 1
        elif "BLOCKED" in et:
            handoff_statuses["BLOCKED"] = handoff_statuses.get("BLOCKED", 0) + 1
        elif "COMPLETED" in et:
            handoff_statuses["COMPLETED"] = handoff_statuses.get("COMPLETED", 0) + 1

    challenge_statuses: dict[str, int] = {}
    for c in challenges:
        et = c.get("event_type", "")
        if "ENQUEUED" in et:
            challenge_statuses["ENQUEUED"] = challenge_statuses.get("ENQUEUED", 0) + 1
        elif "RESOLVED" in et:
            challenge_statuses["RESOLVED"] = challenge_statuses.get("RESOLVED", 0) + 1

    # Latest events
    latest_handoff = handoffs[-1] if handoffs else None
    latest_challenge = challenges[-1] if challenges else None

    return {
        "handoffs": {
            "statuses": handoff_statuses,
            "total": len([h for h in handoffs if h.get("event_type") != "HANDOFF_QUEUE_GENESIS"]),
            "latest": {
                "event_type": latest_handoff.get("event_type"),
                "stream_id": latest_handoff.get("stream_id"),
                "timestamp": latest_handoff.get("timestamp"),
            } if latest_handoff else None,
        },
        "challenges": {
            "statuses": challenge_statuses,
            "total": len([c for c in challenges if c.get("event_type") != "HERMES_CHALLENGE_GENESIS"]),
            "latest": {
                "event_type": latest_challenge.get("event_type"),
                "stream_id": latest_challenge.get("stream_id"),
                "challenge_type": (latest_challenge.get("payload") or {}).get("challenge_type") if latest_challenge else None,
                "timestamp": latest_challenge.get("timestamp"),
            } if latest_challenge else None,
        },
    }


def _plan_store():
    try:
        from lib.cio_plans import CIOPlanStore
        return CIOPlanStore()
    except Exception:
        from scripts.lib.cio_plans import CIOPlanStore  # type: ignore
        return CIOPlanStore()


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Operator-facing plan projection (no internal event noise)."""
    keys = (
        "plan_id", "situation_type", "symbols", "status", "title", "summary",
        "options", "recommendation", "risks", "evidence_refs", "fire_reasons",
        "owner_agent", "thesis_version", "thesis_alignment", "multi_domain_summary",
        "narrative_source", "llm_model", "llm_status", "revisit_at",
        "cc_deep_links", "linked_goal_ids",
        "created_ts", "updated_ts", "narrative_enriched_at", "authority",
    )
    out = {k: plan.get(k) for k in keys if plan.get(k) is not None}
    # promote fire_reasons from extra when needed
    if not out.get("fire_reasons"):
        extra = plan.get("extra") or {}
        if isinstance(extra, dict) and extra.get("fire_reasons"):
            out["fire_reasons"] = extra["fire_reasons"]
    out.setdefault("authority", "READ_ONLY_ADVISORY")
    return out


def get_cio_plans(*, limit: int = 30, situation_type: Optional[str] = None) -> dict[str, Any]:
    store = _plan_store()
    rows = store.list_open_plans(situation_type=situation_type, limit=limit)
    return {
        "ok": True,
        "as_of": _now_iso(),
        "plans": [_public_plan(p) for p in rows],
        "count": len(rows),
        "authority": "READ_ONLY_ADVISORY",
    }


def get_cio_plan(plan_id: str) -> dict[str, Any]:
    store = _plan_store()
    plan = store.get_plan(str(plan_id).strip())
    if not plan:
        return {"ok": False, "error": "plan_not_found", "plan_id": plan_id, "as_of": _now_iso()}
    thesis = None
    pin = plan.get("thesis_version")
    if pin:
        try:
            from lib.cio_theses import CIOThesisStore
            thesis = CIOThesisStore().get_by_pin(str(pin))
        except Exception:
            try:
                from scripts.lib.cio_theses import CIOThesisStore  # type: ignore
                thesis = CIOThesisStore().get_by_pin(str(pin))
            except Exception:
                thesis = None
    return {
        "ok": True,
        "as_of": _now_iso(),
        "plan": _public_plan(plan),
        "thesis": thesis,
        "authority": "READ_ONLY_ADVISORY",
    }


def get_cio_thesis() -> dict[str, Any]:
    try:
        from lib.cio_theses import safe_context_block, safe_current_pin
        pin = safe_current_pin("desk")
        block = safe_context_block("desk", full=True)
    except Exception:
        try:
            from scripts.lib.cio_theses import safe_context_block, safe_current_pin  # type: ignore
            pin = safe_current_pin("desk")
            block = safe_context_block("desk", full=True)
        except Exception:
            pin, block = None, None
    return {
        "ok": True,
        "as_of": _now_iso(),
        "thesis_version": pin,
        "thesis": block,
        "authority": "READ_ONLY_ADVISORY",
    }


def get_cio_desk_note() -> dict[str, Any]:
    """Portfolio-grade desk synthesis note under live desk@vN."""
    try:
        try:
            from lib.cio_desk_synthesis import generate_desk_synthesis_v1
        except Exception:
            from scripts.lib.cio_desk_synthesis import generate_desk_synthesis_v1  # type: ignore
        return generate_desk_synthesis_v1()
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:200],
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _now_iso(),
        }


def post_plan_disposition(plan_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Operator disposition on a plan — status only. No broker/order/stop authority.

    body.disposition: ack|accept|accepted|defer|done|reject|cancel
    Maps to plan status: accepted / proposed / cancelled.
    """
    body = body or {}
    disp = str(body.get("disposition") or body.get("status") or "").strip().lower()
    note = str(body.get("note") or "")[:400]
    mapping = {
        "ack": "accepted",
        "accept": "accepted",
        "accepted": "accepted",
        "done": "accepted",
        "defer": "proposed",
        "reject": "cancelled",
        "cancel": "cancelled",
        "cancelled": "cancelled",
    }
    if disp not in mapping:
        return {
            "ok": False,
            "error": "invalid_disposition",
            "allowed": sorted(mapping.keys()),
            "authority": "READ_ONLY_ADVISORY",
        }
    status = mapping[disp]
    store = _plan_store()
    plan = store.get_plan(str(plan_id).strip())
    if not plan:
        return {"ok": False, "error": "plan_not_found", "plan_id": plan_id}
    try:
        updated = store.update_plan(
            plan_id,
            status=status,
            actor_id="cc_v3_operator",
            **({"recommendation": f"{plan.get('recommendation') or ''} [{disp}: {note}]".strip()} if note else {}),
        )
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)[:200]}
    # Learning loop → desk thesis learning_log + durable JSONL
    try:
        try:
            from lib.cio_theses import record_plan_disposition_learning
        except Exception:
            from scripts.lib.cio_theses import record_plan_disposition_learning  # type: ignore
        record_plan_disposition_learning(
            updated or plan, disp, note=note, actor_id="cc_v3_operator",
        )
    except Exception:
        pass
    return {
        "ok": True,
        "plan_id": plan_id,
        "disposition": disp,
        "status": status,
        "plan": _public_plan(updated),
        "authority": "READ_ONLY_ADVISORY",
        "note": "Status only — no orders/stops placed",
    }


def get_cio_dashboard() -> dict[str, Any]:
    """Full CIO dashboard payload for /v3/cio."""
    snapshot = _cio_snapshot_data()
    actions = _cio_actions_data(15)
    delegation = _delegation_data()
    plans_payload = get_cio_plans(limit=12)
    thesis_payload = get_cio_thesis()

    return {
        "ok": True,
        "as_of": _now_iso(),
        "snapshot": snapshot,
        "actions": actions,
        "delegation": delegation,
        "plans": plans_payload.get("plans") or [],
        "thesis": thesis_payload.get("thesis"),
        "thesis_version": thesis_payload.get("thesis_version"),
        "model_provider": "deepseek-v4-pro",
        "fallback": "deepseek-v4-flash → free-oauth (grok/chatgpt)",
        "authority": "READ_ONLY_ADVISORY",
    }


def get_cio_snapshot() -> dict[str, Any]:
    return {"ok": True, "as_of": _now_iso(), "snapshot": _cio_snapshot_data()}


def get_cio_actions() -> dict[str, Any]:
    actions = _cio_actions_data(30)
    return {"ok": True, "as_of": _now_iso(), "actions": actions, "count": len(actions)}


def get_cio_delegation() -> dict[str, Any]:
    return {"ok": True, "as_of": _now_iso(), "delegation": _delegation_data()}
