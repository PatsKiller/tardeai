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
  GET /api/v3/cio/universe-theses — UNIVERSE & THESES projection (read-only)
  GET /api/v3/cio/agent-research-ops — queue/provider/spend ops strip (no secrets)
  GET /api/v3/cio/symbol-thesis/{SYM} — per-symbol thesis card + history
  GET /api/v3/cio/intelligence/{SYM} — SymbolIntelligence + feedback journal
  POST /api/v3/cio/intelligence/{SYM}/feedback — OperatorTickerFeedback@v1
  GET /api/v3/cio/thesis-research-proposal — dry prioritized research set (RI plane)
  GET /api/v3/cio/thesis-ri-pipeline/{SYM} — RAG-first + acquisition plan (dry)
  GET /api/v3/cio/thesis-research-context/{SYM} — ThesisResearchContext@v1 + supply plane
  GET /api/v3/cio/r71-fabric-map — Cursor dependency + integration map
  GET /api/v3/cio/ask-thesis/{SYM} — Ask CIO symbol-thesis context
  POST /api/v3/cio/plans/{id}/disposition — ack/defer/done/reject (status only)
  GET  /api/v3/cio/dispositions — latest operator dispositions (decision_id key)
  POST /api/v3/cio/decision/{decision_id}/disposition — ACK/DEFER/DONE/REJECT
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Operator-facing label normalization ───────────────────────────────────────
# Internal sprint/situation codes (S0–S6) mean nothing to an operator; map them
# to plain language. Fire reasons are telemetry strings; render them as English.

SITUATION_LABELS: dict[str, str] = {
    "S0_OPERATOR_CONVERSE": "Operator conversation",
    "S1_POSITION_LIFECYCLE": "Position lifecycle",
    "S2_STOP_GAP": "Stop gap",
    "S4_SECTOR_ROTATION": "Sector rotation",
    "S5_CASH_DEPLOYMENT": "Cash deployment",
    "S6_CONCENTRATION_OR_DISPOSITION": "Concentration / disposition",
}

_STANCE_TITLE: dict[str, str] = {
    "defensive_observe": "Defensive · observe",
    "defensive_trim": "Defensive · trim",
    "neutral_hold": "Neutral · hold",
    "offensive_add": "Offensive · add",
}

_FIRE_REASON_OVERRIDES: dict[str, str] = {
    "cash_pct_above_band": "Cash above policy band",
    "no_stop": "No stop in place",
    "no_stop_above_be_after_reclaim_path": "No stop above break-even after reclaim",
    "no_stop_while_materially_underwater": "No stop while materially underwater",
    "major_catalyst_while_held": "Major catalyst while held",
    "basis_reclaim_zone": "Basis reclaim zone",
    "rotation_material_change": "Material rotation change",
    "probe": "Probe",
}


def _human_stance(raw: str | None) -> str:
    if not raw:
        return ""
    return _STANCE_TITLE.get(raw) or raw.replace("_", " ").title()


def _human_fire_reason(code: str) -> str:
    """Render an internal fire-reason code as a plain-English phrase."""
    c = str(code or "")
    if c in _FIRE_REASON_OVERRIDES:
        return _FIRE_REASON_OVERRIDES[c]
    m = re.match(r"^weight_(\d+(?:\.\d+)?)pct$", c)
    if m:
        return f"Single-name weight {float(m.group(1)):.1f}%"
    m = re.match(r"^deep_drawdown_from_basis_(\d+(?:\.\d+)?)pct$", c)
    if m:
        return f"Deep drawdown {float(m.group(1)):.1f}% from basis"
    m = re.match(r"^disposition_loss_(\d+(?:\.\d+)?)pct_hold_(\d+(?:\.\d+)?)m$", c)
    if m:
        return f"Disposition loss {float(m.group(1)):.1f}% / {float(m.group(2)):.0f}mo hold"
    m = re.match(r"^partial_recovery_from_trough_(\d+(?:\.\d+)?)pct_of_span$", c)
    if m:
        return f"Partial recovery from trough ({float(m.group(1)):.1f}% of span)"
    m = re.match(r"^calendar_catalyst_(\w+)_(\w+)_h(\d+)$", c)
    if m:
        sev = m.group(1).replace("_", " ").title()
        kind = m.group(2).replace("_", " ").title()
        horizon = "today" if m.group(3) == "0" else f"h{m.group(3)}"
        return f"Calendar catalyst: {sev} {kind} ({horizon})"
    m = re.match(r"^quality_(\w+)$", c)
    if m:
        return f"Data quality: {m.group(1).title()}"
    return c.replace("_", " ").replace("  ", " ").strip().capitalize()


def _clean_summary(raw: str | None) -> str:
    """Strip internal telemetry from an LLM summary for operator display.

    Removes ``Fire=<...>`` token lists, an inline ``Thesis alignment:`` clause
    (surfaced separately), and a leading ``Under desk@vN (stance):`` prefix.
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    s = re.split(r"\s+Thesis alignment\s*:", s, maxsplit=1)[0]
    s = re.sub(r"Fire=[A-Za-z0-9_.]+(?:\s*,\s*[A-Za-z0-9_.]+)*\s*\.?", "", s)
    s = re.sub(r"^Under\s+desk@v?\d+\s*\([^)]*\)\s*:\s*", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" .,;:-")
    return s


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
    except Exception as e:
        return {"error": "Data Broker unavailable", "detail": str(e)[:200], "domains": {}, "health": {}}


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

    try:
        from lib.intelligence_lineage import challenge_latest, challenge_pending
    except ImportError:
        from scripts.lib.intelligence_lineage import challenge_latest, challenge_pending  # type: ignore

    latest_by_stream = challenge_latest(challenges)
    pending = challenge_pending(latest_by_stream)
    challenge_statuses: dict[str, int] = {}
    for c in latest_by_stream.values():
        et = str(c.get("event_type") or "")
        if et == "HERMES_CHALLENGE_GENESIS":
            continue
        key = et.replace("HERMES_CHALLENGE_", "") or "UNKNOWN"
        challenge_statuses[key] = challenge_statuses.get(key, 0) + 1
    challenge_statuses["PENDING"] = len(pending)

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
            "pending": len(pending),
            "unique_streams": len([k for k in latest_by_stream if k != "hermes_challenge_queue"]),
            "total_events": len([c for c in challenges if c.get("event_type") != "HERMES_CHALLENGE_GENESIS"]),
            "total": len(pending),
            "latest": {
                "event_type": latest_challenge.get("event_type"),
                "stream_id": latest_challenge.get("stream_id"),
                "challenge_type": (latest_challenge.get("payload") or {}).get("challenge_type") if latest_challenge else None,
                "timestamp": latest_challenge.get("timestamp") or latest_challenge.get("occurred_at"),
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
        "prompt_version", "prompt_content_hash", "prompt_alias",
        "eval_structural_score", "eval_quality_total", "eval_judge_total", "eval_judge_scores", "judge_prompt_version",
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
    # Operator-facing normalization (deterministic, no narrative invention)
    st = out.get("situation_type")
    out["situation_label"] = SITUATION_LABELS.get(st, (st or "").replace("_", " ").strip())
    out["fire_reasons_human"] = [_human_fire_reason(f) for f in (out.get("fire_reasons") or [])]
    out["stance_label"] = _human_stance(plan.get("stance"))
    out["summary_clean"] = _clean_summary(out.get("summary"))
    out["recommendation_clean"] = _clean_summary(out.get("recommendation"))
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


def _count_cell(row: Any) -> int:
    if row is None:
        return 0
    if isinstance(row, dict):
        for v in row.values():
            try:
                return int(v or 0)
            except (TypeError, ValueError):
                continue
        return 0
    try:
        return int(row[0] or 0)
    except Exception:
        return 0


def classify_research_failure_message(message: str | None) -> str:
    """Map a watchlist_events failure message to a stable failure class.

    Pure helper — unit-tested. Never invents a success.
    """
    msg = str(message or "").strip()
    low = msg.lower()
    if not msg:
        return "UNKNOWN"
    # Circuit-open is the cascading class even when the last error mentions the cap.
    if "circuit_open" in low or "circuit breaker open" in low:
        return "AGENT_FLASH_CIRCUIT_OPEN"
    if "cost_configuration_invalid" in low or "global daily usd cap required" in low:
        return "LLM_GLOBAL_DAILY_USD_CAP_MISSING"
    if "budget_exhausted" in low or ("global_cap" in low and "exhaust" in low):
        return "LLM_GLOBAL_DAILY_USD_CAP_EXHAUSTED"
    if "cost_cap_exceeded" in low:
        return "COST_CAP_EXCEEDED"
    if "invalid_symbol" in low or "skipped: not found" in low:
        return "INVALID_SYMBOL"
    if "data gap" in low or "data_gap" in low:
        return "DATA_GAP_SKIP"
    if "llm error" in low:
        return "LLM_ERROR"
    return "OTHER"


def _bump(counter: dict[str, int], key: str | None, n: int = 1) -> None:
    k = str(key or "unknown").strip() or "unknown"
    counter[k] = int(counter.get(k) or 0) + n


def summarize_flash_first_attempts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate provider-attempted / actual / fallback from result full_result blobs."""
    attempted: dict[str, int] = {}
    actual: dict[str, int] = {}
    fallback_reasons: dict[str, int] = {}
    policies: dict[str, int] = {}
    for row in rows:
        fr = row.get("full_result") if isinstance(row, dict) else None
        if isinstance(fr, str):
            try:
                fr = json.loads(fr)
            except Exception:
                fr = None
        if not isinstance(fr, dict):
            # Fall back to model_used column only
            _bump(actual, (row or {}).get("model_used") if isinstance(row, dict) else None)
            continue
        _bump(attempted, fr.get("first_provider_attempted") or fr.get("requested_provider_policy"))
        _bump(actual, fr.get("actual_provider") or fr.get("provider") or fr.get("model") or (row or {}).get("model_used"))
        if fr.get("fallback_reason"):
            _bump(fallback_reasons, fr.get("fallback_reason"))
        if fr.get("requested_provider_policy"):
            _bump(policies, fr.get("requested_provider_policy"))
    return {
        "provider_attempted_today": attempted,
        "provider_actual_today": actual,
        "fallback_reason_today": fallback_reasons,
        "requested_provider_policy_today": policies,
        "flash_attempted": any(
            "flash" in k.lower() or "deepseek" in k.lower() for k in attempted
        ),
        "sample_count": len(rows),
    }


def get_agent_research_ops() -> dict[str, Any]:
    """GET /api/v3/cio/agent-research-ops — operator-visible intelligence engine health.

    Never returns cap values, tokens, or credentials. Cap status is CONFIGURED/MISSING/EXHAUSTED only.
    Surfaces Flash-first attempt/actual/fallback and dominant failure class when present.
    Does not silently re-queue failed jobs.
    """
    cap_raw = str(os.environ.get("LLM_GLOBAL_DAILY_USD_CAP") or "").strip()
    cap_status = "CONFIGURED" if cap_raw else "MISSING"
    out: dict[str, Any] = {
        "ok": True,
        "as_of": _now_iso(),
        "authority": "READ_ONLY_ADVISORY",
        "global_cap_status": cap_status,
        "queue": {},
        "provider_mix_today": {},
        "failure_classes_today": {},
        "flash_first": {},
        "dominant_failure_class": None,
        "operator_finding": None,
        "notification": {},
        "requeue_suppressed": True,
        "requeue_note": "Failed jobs are not auto-requeued; fix config/cap then enqueue deliberately.",
    }
    try:
        from db_adapter import USE_DB, _execute
        if not USE_DB:
            out["queue"] = {"error": "db_unavailable"}
            return out
        rows = _execute("SELECT status, COUNT(*) FROM watchlist_agent_jobs GROUP BY status", fetch="all") or []
        by_status: dict[str, int] = {}
        for row in rows:
            if isinstance(row, dict):
                st = str(row.get("status") or "")
                cnt = int(list(row.values())[1] or 0)
            else:
                st, cnt = str(row[0]), int(row[1] or 0)
            by_status[st] = cnt
        queued = int(by_status.get("queued") or 0)
        oldest = _execute(
            "SELECT MIN(created_at) FROM watchlist_agent_jobs WHERE status='queued'",
            fetch="one",
        )
        oldest_at = None
        if oldest:
            oldest_at = str(oldest[0] if not isinstance(oldest, dict) else list(oldest.values())[0])
        agents = _execute(
            """SELECT requested_agent, COUNT(*) FROM watchlist_agent_jobs
               WHERE status='queued' GROUP BY requested_agent""",
            fetch="all",
        ) or []
        by_agent: dict[str, int] = {}
        for row in agents:
            if isinstance(row, dict):
                by_agent[str(list(row.values())[0])] = int(list(row.values())[1] or 0)
            else:
                by_agent[str(row[0])] = int(row[1] or 0)
        created = _execute(
            "SELECT COUNT(*) FROM watchlist_agent_jobs WHERE created_at >= CURRENT_DATE",
            fetch="one",
        )
        completed = _execute(
            "SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status='completed' AND COALESCE(completed_at, created_at) >= CURRENT_DATE",
            fetch="one",
        )
        failed = _execute(
            "SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status='failed' AND COALESCE(completed_at, created_at) >= CURRENT_DATE",
            fetch="one",
        )
        mix = _execute(
            """SELECT COALESCE(model_used,'unknown'), COUNT(*)
               FROM watchlist_agent_results
               WHERE created_at >= CURRENT_DATE
               GROUP BY 1""",
            fetch="all",
        ) or []
        provider_mix: dict[str, int] = {}
        for row in mix:
            if isinstance(row, dict):
                provider_mix[str(list(row.values())[0])] = int(list(row.values())[1] or 0)
            else:
                provider_mix[str(row[0])] = int(row[1] or 0)

        # Failure class honesty from today's events (Flash-first fail-closed)
        fail_events = _execute(
            """SELECT message, COUNT(*) AS c FROM watchlist_events
               WHERE created_at >= CURRENT_DATE
                 AND status IN ('failed', 'skipped')
               GROUP BY message
               ORDER BY c DESC
               LIMIT 40""",
            fetch="all",
        ) or []
        failure_classes: dict[str, int] = {}
        for row in fail_events:
            if isinstance(row, dict):
                msg = row.get("message")
                cnt = int(row.get("c") or list(row.values())[1] or 0)
            else:
                msg, cnt = row[0], int(row[1] or 0)
            _bump(failure_classes, classify_research_failure_message(str(msg or "")), cnt)

        # Per-cycle Flash-first visibility from completed result provenance
        attempt_rows = _execute(
            """SELECT model_used, full_result FROM watchlist_agent_results
               WHERE created_at >= CURRENT_DATE
               ORDER BY created_at DESC
               LIMIT 200""",
            fetch="all",
        ) or []
        flash = summarize_flash_first_attempts([dict(r) if not isinstance(r, dict) else r for r in attempt_rows])

        dominant = None
        if failure_classes:
            dominant = max(failure_classes.items(), key=lambda kv: kv[1])[0]

        # Cap status refinement from observed failures (env may be set in CC but not in worker)
        if dominant == "LLM_GLOBAL_DAILY_USD_CAP_MISSING":
            cap_status = "MISSING"
            out["operator_finding"] = (
                "docs/ops/RESEARCH_ENGINE_FLASH_FIRST_FAILURE_2026-08-20.md — "
                "worker lacks LLM_GLOBAL_DAILY_USD_CAP; Flash fail-closed then circuit-open. "
                "Do not silently re-queue."
            )
        elif dominant == "LLM_GLOBAL_DAILY_USD_CAP_EXHAUSTED":
            cap_status = "EXHAUSTED"
        elif dominant == "AGENT_FLASH_CIRCUIT_OPEN" and cap_status == "MISSING":
            out["operator_finding"] = (
                "docs/ops/RESEARCH_ENGINE_FLASH_FIRST_FAILURE_2026-08-20.md — "
                "agent_flash circuit open after cap-config failures."
            )

        out["global_cap_status"] = cap_status
        out["queue"] = {
            "queued": queued,
            "by_status": by_status,
            "by_agent": by_agent,
            "oldest_queued": oldest_at,
            "created_today": _count_cell(created),
            "completed_today": _count_cell(completed),
            "failed_today": _count_cell(failed),
            "actionable_queue": queued,
            "stale_or_superseded": int(by_status.get("deferred") or 0) + int(by_status.get("superseded") or 0),
        }
        out["provider_mix_today"] = provider_mix
        out["failure_classes_today"] = failure_classes
        out["dominant_failure_class"] = dominant
        out["flash_first"] = flash
    except Exception as e:
        out["ok"] = False
        out["error"] = type(e).__name__
        out["detail"] = str(e)[:200]
    return out


def get_universe_theses() -> dict[str, Any]:
    """GET /api/v3/cio/universe-theses — UNIVERSE & THESES operator projection."""
    try:
        from scripts.lib.symbol_thesis_cc import build_universe_theses_projection
        payload = build_universe_theses_projection(include_proposed_research=True)
        return {"ok": True, **payload}
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:240],
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _now_iso(),
        }


def get_symbol_thesis_card(symbol: str) -> dict[str, Any]:
    """GET /api/v3/cio/symbol-thesis/{SYM} — drill-down card + history."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "symbol_required", "authority": "READ_ONLY_ADVISORY"}
    try:
        from scripts.lib.symbol_thesis_cc import build_symbol_thesis_card
        card = build_symbol_thesis_card(sym)
        return {"ok": True, **card}
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:240],
            "symbol": sym,
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _now_iso(),
        }


def get_symbol_intelligence(symbol: str) -> dict[str, Any]:
    """GET /api/v3/cio/intelligence/{SYM} — SIO + feedback journal (Phase B).

    Assembles SymbolIntelligenceObject without a change_item when cheap, and
    always returns ``journal`` + ``latest_feedback`` from the operator ticker
    feedback store. READ_ONLY_ADVISORY.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "symbol_required", "authority": "READ_ONLY_ADVISORY"}
    latest = None
    journal: list[dict[str, Any]] = []
    try:
        from scripts.lib.cio_operator_ticker_feedback import (
            journal_for_symbol,
            latest_feedback,
        )

        latest = latest_feedback(sym)
        journal = journal_for_symbol(sym, limit=20)
    except Exception:
        latest = None
        journal = []

    intelligence: dict[str, Any] | None = None
    intel_err: str | None = None
    try:
        from scripts.lib.cio_symbol_intelligence import assemble_symbol_intelligence

        intelligence = assemble_symbol_intelligence(
            sym,
            change_item=None,
            prior_feedback=latest,
        )
    except Exception as e:
        intel_err = f"{type(e).__name__}:{e}"[:240]

    research_queue: dict[str, Any]
    try:
        from scripts.lib.symbol_thesis_queue import load_symbol_research_queue

        rq = load_symbol_research_queue(sym)
        research_queue = {
            "open_count": int(rq.get("open_count") or 0),
            "oldest_wait_seconds": rq.get("oldest_wait_seconds"),
            "oldest_wait_human": rq.get("oldest_wait_human"),
            "active_research": rq.get("active_research") or [],
            "recent_completed_research": rq.get("recent_completed_research") or [],
            "source": rq.get("source"),
            "ok": bool(rq.get("ok")),
        }
    except Exception:
        research_queue = {
            "open_count": 0,
            "oldest_wait_seconds": None,
            "oldest_wait_human": None,
            "active_research": [],
            "recent_completed_research": [],
            "source": "unavailable",
            "ok": False,
        }

    return {
        "ok": True,
        "as_of": _now_iso(),
        "symbol": sym,
        "intelligence": intelligence,
        "intelligence_error": intel_err,
        "journal": journal,
        "latest_feedback": latest,
        "research_queue": research_queue,
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }


def post_symbol_intelligence_feedback(
    symbol: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST /api/v3/cio/intelligence/{SYM}/feedback — append OperatorTickerFeedback@v1.

    body.intent (required): AGREE|DISAGREE|INTERESTED|DEFER|NEED_DATA|DISMISS|ACK
    body.free_text / object_id / channel optional.
    NEED_DATA triggers best-effort held-coverage dry / Hermes enqueue (fail-soft).
    """
    body = body if isinstance(body, dict) else {}
    sym = str(symbol or body.get("symbol") or "").strip().upper()
    if not sym:
        return {
            "ok": False,
            "error": "symbol_required",
            "as_of": _now_iso(),
            "authority": "READ_ONLY_ADVISORY",
        }
    intent_raw = body.get("intent")
    if not intent_raw:
        return {
            "ok": False,
            "error": "intent_required",
            "as_of": _now_iso(),
            "authority": "READ_ONLY_ADVISORY",
        }
    try:
        from scripts.lib.cio_operator_ticker_feedback import (
            VALID_INTENTS,
            append_feedback,
            maybe_enqueue_need_data,
            normalize_intent,
            stance_from_intent,
        )

        intent = normalize_intent(intent_raw)
        if intent not in VALID_INTENTS:
            return {
                "ok": False,
                "error": "invalid_intent",
                "detail": f"expected one of {sorted(VALID_INTENTS)}",
                "as_of": _now_iso(),
                "authority": "READ_ONLY_ADVISORY",
            }
        row = append_feedback({
            "symbol": sym,
            "intent": intent,
            "stance": stance_from_intent(intent),
            "free_text": body.get("free_text") or body.get("note"),
            "object_id": body.get("object_id"),
            "channel": body.get("channel") or "api",
            "operator_actor_id": body.get("operator_actor_id"),
        })
    except ValueError as e:
        return {
            "ok": False,
            "error": "invalid_feedback",
            "detail": str(e)[:200],
            "as_of": _now_iso(),
            "authority": "READ_ONLY_ADVISORY",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:240],
            "as_of": _now_iso(),
            "authority": "READ_ONLY_ADVISORY",
        }

    need_data: dict[str, Any] | None = None
    if row.get("intent") == "NEED_DATA":
        try:
            need_data = maybe_enqueue_need_data(sym, apply=False)
        except Exception as e:
            need_data = {"ok": False, "error": f"{type(e).__name__}:{e}"[:200]}

    return {
        "ok": True,
        "as_of": row.get("ts") or _now_iso(),
        "feedback": row,
        "need_data": need_data,
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }


def get_thesis_research_proposal() -> dict[str, Any]:
    """GET /api/v3/cio/thesis-research-proposal — DRY prioritized research set (RI plane)."""
    try:
        from scripts.lib.symbol_thesis_research import propose_prioritized_research
        prop = propose_prioritized_research(limit=40, run_pipeline_preview=0)
        return {"ok": True, **prop}
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:240],
            "authority": "READ_ONLY_ADVISORY",
            "enqueued": False,
            "hermes_is_acquisition_source": False,
            "as_of": _now_iso(),
        }


def get_thesis_ri_pipeline(symbol: str) -> dict[str, Any]:
    """GET /api/v3/cio/thesis-ri-pipeline/{SYM} — RAG-first + budgeted acquisition plan.

    Hermes/Flash are synthesis-only. Default dry: no acquire/embed/LLM.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "symbol_required", "authority": "READ_ONLY_ADVISORY"}
    try:
        from scripts.lib.symbol_thesis_research import run_ri_pipeline_for_gap
        out = run_ri_pipeline_for_gap(
            sym,
            retrieve=True,
            apply_acquire=False,
            apply_embed=False,
            call_llm=False,
        )
        return {"ok": True, **out}
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:240],
            "symbol": sym,
            "hermes_is_acquisition_source": False,
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _now_iso(),
        }


def get_ask_thesis_context(symbol: str) -> dict[str, Any]:
    """GET /api/v3/cio/ask-thesis/{SYM} — Ask CIO symbol-thesis context."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "symbol_required", "authority": "READ_ONLY_ADVISORY"}
    try:
        from scripts.lib.symbol_thesis_cc import ask_cio_symbol_context
        ctx = ask_cio_symbol_context(sym)
        return {"ok": True, **ctx}
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:240],
            "symbol": sym,
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _now_iso(),
        }


def get_thesis_research_context(symbol: str) -> dict[str, Any]:
    """GET /api/v3/cio/thesis-research-context/{SYM} — supply plane + RAG + materiality."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "symbol_required", "authority": "READ_ONLY_ADVISORY"}
    try:
        from scripts.lib.r71_cursor_fabric_map import load_dependency
        from scripts.lib.thesis_research_context import build_thesis_research_context
        ctx = build_thesis_research_context(sym, run_rag_pipeline=True)
        dep = load_dependency()
        ctx["cursor_dependency_sha"] = dep.get("cursor_head")
        return {"ok": True, **ctx}
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:240],
            "symbol": sym,
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _now_iso(),
        }


def get_r71_fabric_map() -> dict[str, Any]:
    """GET /api/v3/cio/r71-fabric-map — Cursor Gap A–F integration map + dependency SHA."""
    try:
        from scripts.lib.r71_cursor_fabric_map import fabric_map_report
        return {"ok": True, **fabric_map_report()}
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:240],
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _now_iso(),
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


def get_investment_product() -> dict[str, Any]:
    """GET /api/v3/cio/investment-product — four canonical CIO books."""
    try:
        from scripts.lib.cio_investment_product import (
            build_product, load_brief, load_current_production_product, persist_product,
        )
        brief = load_brief()
        if not brief:
            brief = persist_product(build_product())
        current = load_current_production_product()
        return {"ok": True, "authority": "READ_ONLY_ADVISORY", "mutation": False,
                "financial_action": False, "product": current or brief}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)[:200],
                "authority": "READ_ONLY_ADVISORY", "financial_action": False}


def get_cio_home() -> dict[str, Any]:
    """GET /api/v3/cio/home — Phase 8 office-home payload (6 sections, decision-first).

    Composes CIO NOW / CAPITAL PLAN / PORTFOLIO POSTURE / OPPORTUNITIES /
    REPORT / EVIDENCE from the canonical Phases 5–7 surfaces. READ_ONLY_ADVISORY.
    """
    try:
        from scripts.lib.cio_command_center import build_office_home
        import api_v2 as _v2
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)[:200],
                "authority": "READ_ONLY_ADVISORY", "as_of": _now_iso()}

    capital_plan = None
    sector_opportunities = None
    opportunity_queue = None
    report = None
    attribution = None
    income = None

    # Fail-soft per domain — a missing surface must not blank the whole home.
    try:
        capital_plan = _v2._cio_capital_plan()
        capital_plan = capital_plan if capital_plan and capital_plan.get("ok") is not False else None
    except Exception:
        capital_plan = None
    try:
        sector_opportunities = _v2._cio_sector_opportunities()
        sector_opportunities = sector_opportunities if sector_opportunities and sector_opportunities.get("ok") is not False else None
    except Exception:
        sector_opportunities = None
    try:
        from scripts.lib.cio_opportunity_queue import build_queue_from_executor
        opportunity_queue = build_queue_from_executor(_v2._db_query)
    except Exception:
        opportunity_queue = None
    try:
        report = _v2._cio_report_v2()
        report = report if report and report.get("ok") is not False else None
    except Exception:
        report = None
    try:
        attribution = _v2._load_json(
            PROJECT_ROOT / "data" / "portfolios" / "state" / "performance_attribution.json"
        ) or {}
    except Exception:
        attribution = None
    try:
        income = _v2._load_json(
            PROJECT_ROOT / "data" / "portfolios" / "state" / "income_ledger.json"
        ) or {}
    except Exception:
        income = None

    thesis = (get_cio_thesis() or {}).get("thesis") or None
    actions = _cio_actions_data(20)
    plans = (get_cio_plans(limit=12) or {}).get("plans") or []

    # Evidence / audit block.
    source_refs = [
        {"name": name, "sha256": h}
        for name, h in sorted((((report or {}).get("manifest") or {}).get("input_hashes") or {}).items())
    ]
    validator_states = []
    for rev in _read_jsonl(PROJECT_ROOT / "data" / "cio" / "sentinel_reviews.jsonl")[-3:]:
        validator_states.append({
            "reviewer": rev.get("reviewer"),
            "status": rev.get("status"),
            "contradictions": rev.get("contradictions"),
            "ts": rev.get("timestamp"),
        })
    for sc in _read_jsonl(PROJECT_ROOT / "data" / "cio" / "darwin_scorecards.jsonl")[-2:]:
        validator_states.append({
            "reviewer": sc.get("scorer"),
            "status": sc.get("event_type"),
            "ts": sc.get("timestamp"),
        })
    run_ids = []
    for w in _read_jsonl(PROJECT_ROOT / "data" / "cio" / "cio_wake_jobs.jsonl")[-4:]:
        run_ids.append({
            "id": w.get("wake_id") or w.get("event_id"),
            "state": w.get("state") or w.get("event_type"),
            "ts": w.get("ts") or w.get("timestamp"),
        })
    handoff = _delegation_data().get("handoffs") or {}
    if handoff.get("latest"):
        run_ids.append({
            "id": handoff["latest"].get("stream_id"),
            "state": handoff["latest"].get("event_type"),
            "ts": handoff["latest"].get("timestamp"),
        })

    home = build_office_home(
        capital_plan=capital_plan,
        sector_opportunities=sector_opportunities,
        opportunity_queue=opportunity_queue,
        report=report,
        thesis=thesis,
        attribution=attribution,
        income=income,
        actions=actions,
        plans=plans,
        source_refs=source_refs,
        validator_states=validator_states,
        run_ids=run_ids,
    )
    home["ok"] = True
    stamp_decision_identity(home, capital_plan)
    return home


# ─────────────────────────────────────────────────────────────────────────────
# Decision dispositions (Phase 8 + P0-11 identity): durable advisory actions
# ─────────────────────────────────────────────────────────────────────────────
# ACK / DEFER / DONE / REJECT / RATE are appended to an event ledger, never to
# broker/order/stop state. Canonical key is decision_id. Legacy
# position:symbol:account events remain readable as LEGACY_UNVERSIONED and
# must never auto-apply to a newer decision.

_DISPOSITION_PATH = PROJECT_ROOT / "data" / "cio" / "decision_dispositions.jsonl"
_VALID_DISPOSITIONS = {"ack", "defer", "done", "reject", "rate"}
AUTHORITY_ADVISORY = "READ_ONLY_ADVISORY"
IDENTITY_DECISION_ID = "DECISION_ID"
IDENTITY_LEGACY = "LEGACY_UNVERSIONED"
IDENTITY_ARCHIVED = "ARCHIVED_FEEDBACK"
IDENTITY_DIGEST_CAPABLE = "DIGEST_CAPABLE"
IDENTITY_LEGACY_DECISION_ID_ONLY = "LEGACY_DECISION_ID_ONLY"
_LEGACY_PREFIXES = ("position:", "action:")
_DECISION_ID_RE = re.compile(r"^(dec_[A-Za-z0-9._:-]{8,80}|[0-9a-fA-F]{32,64})$")


def is_legacy_disposition_key(key: str) -> bool:
    s = str(key or "").strip()
    return any(s.startswith(p) for p in _LEGACY_PREFIXES)


def is_decision_id(key: str) -> bool:
    s = str(key or "").strip()
    if not s or is_legacy_disposition_key(s) or len(s) > 160:
        return False
    return bool(_DECISION_ID_RE.match(s))


def classify_disposition_identity(entry: dict[str, Any]) -> str:
    """Classify a stored event. Legacy keys never become current decisions."""
    if not isinstance(entry, dict):
        return IDENTITY_LEGACY
    tagged = str(entry.get("identity_class") or "").strip().upper()
    if tagged == IDENTITY_ARCHIVED:
        return IDENTITY_ARCHIVED
    if tagged == IDENTITY_LEGACY:
        return IDENTITY_LEGACY
    did = str(entry.get("decision_id") or "").strip()
    key = str(entry.get("decision_key") or "").strip()
    if is_legacy_disposition_key(key) or is_legacy_disposition_key(did):
        return IDENTITY_LEGACY
    if is_decision_id(did) or (not did and is_decision_id(key)):
        return IDENTITY_DECISION_ID
    return IDENTITY_LEGACY


def classify_decision_identity(known: Any) -> str:
    """Classify a catalog row: digest-capable vs decision_id-only legacy.

    DIGEST_CAPABLE — both input and evidence digests are non-empty.
    LEGACY_DECISION_ID_ONLY — missing/empty catalog digests (compat).
    Does not invent or strip digest fields.
    """
    if not isinstance(known, dict):
        return IDENTITY_LEGACY_DECISION_ID_ONLY
    inp = _norm_digest(known.get("decision_input_digest"))
    ev = _norm_digest(known.get("decision_evidence_digest"))
    if inp and ev:
        return IDENTITY_DIGEST_CAPABLE
    return IDENTITY_LEGACY_DECISION_ID_ONLY


def new_decision_digestless_rejected(known: Any) -> bool:
    """True when a row is not digest-capable (legacy / digestless).

    Does not mutate. New aggregated decisions must be DIGEST_CAPABLE;
    this helper only classifies — it does not strip catalog fields.
    """
    return classify_decision_identity(known) != IDENTITY_DIGEST_CAPABLE


def catalog_from_position_decisions(rows: Any) -> dict[str, dict[str, Any]]:
    """Map decision_id → identity fields from capital-plan / CIO NOW rows.

    Does not strip empty digests; classifies each row instead.
    """
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for d in rows:
        if not isinstance(d, dict):
            continue
        did = str(d.get("decision_id") or "").strip()
        if not is_decision_id(did):
            continue
        acct = d.get("account")
        if not acct and isinstance(d.get("accounts"), list) and d.get("accounts"):
            acct = d["accounts"][0]
        rec = {
            "decision_id": did,
            "decision_input_digest": str(d.get("decision_input_digest") or ""),
            "decision_evidence_digest": str(d.get("decision_evidence_digest") or ""),
            "symbol": d.get("symbol"),
            "account": acct,
            "action": d.get("action") or d.get("stance") or d.get("stance_code"),
        }
        rec["decision_identity"] = classify_decision_identity(rec)
        out[did] = rec
    return out


def load_known_decision_catalog() -> dict[str, dict[str, Any]]:
    """Current decision catalog. Fail-closed to empty on load error."""
    try:
        import api_v2 as _v2
        plan = _v2._cio_capital_plan()
        if not plan or plan.get("ok") is False:
            return {}
        return catalog_from_position_decisions(plan.get("position_decisions") or [])
    except Exception:
        return {}


def stamp_decision_identity(
    home: dict[str, Any] | None,
    capital_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach digests from the capital-plan catalog onto CIO NOW cards."""
    home = home if isinstance(home, dict) else {}
    catalog = catalog_from_position_decisions(
        (capital_plan or {}).get("position_decisions") if isinstance(capital_plan, dict) else []
    )
    cards = ((home.get("cio_now") or {}).get("decisions") or [])
    if not isinstance(cards, list):
        return home
    for card in cards:
        if not isinstance(card, dict):
            continue
        did = str(card.get("decision_id") or "").strip()
        known = catalog.get(did) or {}
        for fld in ("decision_input_digest", "decision_evidence_digest"):
            if not card.get(fld) and known.get(fld):
                card[fld] = known[fld]
    return home


def _truthy(val: Any) -> bool:
    if val is True:
        return True
    s = str(val or "").strip().lower()
    return s in {"1", "true", "yes", "on", "archived-feedback", "archived_feedback"}


def _archived_feedback_requested(body: dict[str, Any]) -> bool:
    if _truthy(body.get("archived_feedback")):
        return True
    mode = str(body.get("mode") or "").strip().lower().replace("_", "-")
    return mode == "archived-feedback"


def _norm_digest(val: Any) -> str:
    return str(val or "").strip().lower()


def _digests_match(
    supplied: str,
    known: str,
    *,
    identity_class: str | None = None,
) -> bool:
    """Match policy depends on catalog identity class.

    DIGEST_CAPABLE: a presented (non-empty) digest must equal the catalog.
    Wrong hash → False (caller returns digest_mismatch 409).
    LEGACY_DECISION_ID_ONLY: empty or any supplied hash is accepted.
    Two-arg callers without identity_class keep the prior inference:
    empty catalog digest ⇒ legacy; otherwise require a match when supplied.
    """
    s = _norm_digest(supplied)
    k = _norm_digest(known)
    cls = str(identity_class or "").strip().upper()
    if not cls:
        cls = IDENTITY_DIGEST_CAPABLE if k else IDENTITY_LEGACY_DECISION_ID_ONLY
    if cls == IDENTITY_LEGACY_DECISION_ID_ONLY:
        return True
    # DIGEST_CAPABLE — exact match REQUIRED. Missing or wrong digest fails closed
    # (caller returns digest_mismatch 409). Only LEGACY_DECISION_ID_ONLY keeps
    # decision-id-only binding for pre-existing cards.
    if not s:
        return False
    return s == k


def get_decision_dispositions() -> dict[str, Any]:
    """Latest disposition per identity class (read-only).

    ``dispositions`` is keyed by decision_id and contains only versioned
    current-applicable events. Legacy ``position:symbol:account`` rows are
    returned under ``legacy_unversioned`` and are never folded into a new
    decision_id.
    """
    current: dict[str, dict[str, Any]] = {}
    legacy: dict[str, dict[str, Any]] = {}
    archived: dict[str, dict[str, Any]] = {}
    for entry in _read_jsonl(_DISPOSITION_PATH):
        if not isinstance(entry, dict):
            continue
        cls = classify_disposition_identity(entry)
        view = dict(entry)
        view["identity_class"] = cls
        if cls == IDENTITY_ARCHIVED:
            key = str(entry.get("decision_id") or entry.get("decision_key") or "").strip()
            if key:
                archived[key] = view
            continue
        if cls == IDENTITY_DECISION_ID:
            key = str(entry.get("decision_id") or entry.get("decision_key") or "").strip()
            if key and not is_legacy_disposition_key(key):
                current[key] = view
            continue
        key = str(entry.get("decision_key") or entry.get("decision_id") or "").strip()
        if key:
            view.setdefault("decision_id", None)
            legacy[key] = view
    return {
        "ok": True,
        "as_of": _now_iso(),
        "dispositions": current,
        "legacy_unversioned": legacy,
        "archived_feedback": archived,
        "canonical_key": "decision_id",
        "authority": AUTHORITY_ADVISORY,
    }


def post_decision_disposition(decision_key: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record an operator disposition on a versioned decision.

    Canonical key is ``decision_id``. Rejects missing IDs, digest mismatch,
    stale/unknown IDs (unless archived-feedback), and legacy position keys.
    No broker/order/stop authority.

    body.disposition: ack | defer | done | reject (required)
    body.rating:       1..5 usefulness rating (optional)
    body.note:         free-text advisory note (optional)
    body.decision_id / decision_input_digest / decision_evidence_digest
    body.symbol / account / action
    body.mode=archived-feedback | archived_feedback=true — allow stale IDs
    """
    body = body or {}
    path_key = str(decision_key or "").strip()
    body_id = str(body.get("decision_id") or "").strip()

    if is_legacy_disposition_key(path_key):
        return {
            "ok": False,
            "error": "legacy_unversioned_key_not_applicable",
            "detail": "POST requires decision_id; position:symbol:account is not applied to a new decision",
            "identity_class": IDENTITY_LEGACY,
            "as_of": _now_iso(),
            "authority": AUTHORITY_ADVISORY,
        }

    did = body_id or path_key
    if not did:
        return {
            "ok": False,
            "error": "missing_decision_id",
            "as_of": _now_iso(),
            "authority": AUTHORITY_ADVISORY,
        }
    if body_id and path_key and body_id != path_key:
        return {
            "ok": False,
            "error": "decision_id_mismatch",
            "as_of": _now_iso(),
            "authority": AUTHORITY_ADVISORY,
        }
    if not is_decision_id(did):
        return {
            "ok": False,
            "error": "invalid_decision_id",
            "as_of": _now_iso(),
            "authority": AUTHORITY_ADVISORY,
        }

    disp = str(body.get("disposition") or "").strip().lower()
    if disp not in _VALID_DISPOSITIONS:
        return {"ok": False, "error": "invalid_disposition",
                "allowed": sorted(_VALID_DISPOSITIONS), "as_of": _now_iso(),
                "authority": AUTHORITY_ADVISORY}

    rating = body.get("rating")
    if rating is not None:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            rating = None
        if rating is not None and not (1 <= rating <= 5):
            return {"ok": False, "error": "invalid_rating", "as_of": _now_iso(),
                    "authority": AUTHORITY_ADVISORY}

    archived = _archived_feedback_requested(body)
    catalog = load_known_decision_catalog()
    known = catalog.get(did)
    if known is None and not archived:
        return {
            "ok": False,
            "error": "unknown_or_stale_decision_id",
            "detail": "decision_id is not in the current catalog; use archived-feedback mode for historical notes",
            "as_of": _now_iso(),
            "authority": AUTHORITY_ADVISORY,
        }
    known = known or {}
    in_catalog = bool(catalog.get(did))
    decision_identity = (
        classify_decision_identity(known) if in_catalog
        else IDENTITY_LEGACY_DECISION_ID_ONLY
    )

    supplied_in = body.get("decision_input_digest")
    supplied_ev = body.get("decision_evidence_digest")
    # Digest binding applies to current catalog entries only. Archived-feedback
    # on an unknown ID records whatever the operator supplied.
    # DIGEST_CAPABLE requires exact match (wrong hash → digest_mismatch 409).
    # LEGACY_DECISION_ID_ONLY accepts empty or any supplied digest.
    if in_catalog and not _digests_match(
        supplied_in, known.get("decision_input_digest"),
        identity_class=decision_identity,
    ):
        return {
            "ok": False,
            "error": "digest_mismatch",
            "field": "decision_input_digest",
            "decision_identity": decision_identity,
            "as_of": _now_iso(),
            "authority": AUTHORITY_ADVISORY,
        }
    if in_catalog and not _digests_match(
        supplied_ev, known.get("decision_evidence_digest"),
        identity_class=decision_identity,
    ):
        return {
            "ok": False,
            "error": "digest_mismatch",
            "field": "decision_evidence_digest",
            "decision_identity": decision_identity,
            "as_of": _now_iso(),
            "authority": AUTHORITY_ADVISORY,
        }

    # Archived-feedback is only for IDs absent from the current catalog.
    if archived and not catalog.get(did):
        identity_class = IDENTITY_ARCHIVED
    elif in_catalog and decision_identity == IDENTITY_LEGACY_DECISION_ID_ONLY:
        identity_class = IDENTITY_LEGACY_DECISION_ID_ONLY
    else:
        identity_class = IDENTITY_DECISION_ID

    input_digest = _norm_digest(supplied_in) or _norm_digest(known.get("decision_input_digest"))
    evidence_digest = _norm_digest(supplied_ev) or _norm_digest(known.get("decision_evidence_digest"))
    symbol = body.get("symbol") if body.get("symbol") is not None else known.get("symbol")
    account = body.get("account") if body.get("account") is not None else known.get("account")
    action = body.get("action") if body.get("action") is not None else known.get("action")
    note = str(body.get("note") or "").strip()[:500]

    entry = {
        "decision_id": did,
        "decision_key": did,
        "decision_input_digest": input_digest,
        "decision_evidence_digest": evidence_digest,
        "symbol": symbol,
        "account": account,
        "action": action,
        "disposition": disp,
        "rating": rating,
        "note": note,
        "occurred_at": _now_iso(),
        "authority": AUTHORITY_ADVISORY,
        "identity_class": identity_class,
        "decision_identity": (
            IDENTITY_ARCHIVED if identity_class == IDENTITY_ARCHIVED
            else decision_identity
        ),
    }
    try:
        _DISPOSITION_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DISPOSITION_PATH, "a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)[:200],
                "as_of": _now_iso(), "authority": AUTHORITY_ADVISORY}

    outcome = None
    try:
        from scripts.lib.cio_outcome_observer import record_disposition_outcome
        outcome = record_disposition_outcome(
            decision_or_plan_id=did,
            disposition=disp,
            lineage_id=str(body.get("lineage_id") or "") or None,
            rating=rating,
            note=note,
            symbol=str(symbol or "") or None,
        )
    except Exception as e:
        outcome = {"ok": False, "error": f"{type(e).__name__}:{e}"}

    return {
        "ok": True,
        "as_of": entry["occurred_at"],
        "disposition": entry,
        "outcome": outcome,
        "authority": AUTHORITY_ADVISORY,
    }


def get_maturity_learning() -> dict[str, Any]:
    """GET /api/v3/maturity/learning — disposition outcome maturity (fail-soft)."""
    try:
        from scripts.lib.cio_outcome_observer import learning_summary
        return learning_summary()
    except Exception as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:200],
            "matured_count": 0,
            "eligible_runs": 0,
            "memory_behavior_influence": 0,
            "authority": AUTHORITY_ADVISORY,
            "as_of": _now_iso(),
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
        "fallback": "none — fail-closed (VISIBLE_FAILURE_NO_SILENT_FALLBACK)",
        "authority": "READ_ONLY_ADVISORY",
    }


def get_cio_snapshot() -> dict[str, Any]:
    return {"ok": True, "as_of": _now_iso(), "snapshot": _cio_snapshot_data()}


def get_cio_actions() -> dict[str, Any]:
    actions = _cio_actions_data(30)
    return {"ok": True, "as_of": _now_iso(), "actions": actions, "count": len(actions)}


def get_cio_delegation() -> dict[str, Any]:
    return {"ok": True, "as_of": _now_iso(), "delegation": _delegation_data()}
