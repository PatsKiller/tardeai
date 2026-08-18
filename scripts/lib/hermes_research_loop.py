"""CIO Hermes research loop orchestrator.

Cycle:
  material gap → enqueue (fingerprint) → worker runs → on_hermes_completed
  → attach evidence → re-synth once → Telegram only if material change

Worker does not call Telegram. This module owns CIO side-effects.
READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _import_store():
    try:
        from lib import cio_hermes_research as hr
    except Exception:
        from scripts.lib import cio_hermes_research as hr  # type: ignore
    return hr


def _import_plans():
    try:
        from lib.cio_plans import CIOPlanStore
    except Exception:
        from scripts.lib.cio_plans import CIOPlanStore  # type: ignore
    return CIOPlanStore


def should_enqueue_for_plan(plan: dict[str, Any]) -> tuple[bool, str, str]:
    """
    Returns (should, priority, reason).
    Escalation aligned with thesis: S1 DD, S6 fire, S8 high; S5 lower.
    """
    st = str(plan.get("situation_type") or "")
    fire = " ".join(str(x) for x in (plan.get("fire_reasons") or (plan.get("extra") or {}).get("fire_reasons") or []))
    fire_l = fire.lower()

    if st.startswith("S8"):
        return True, "high", "s8_defensive_regime"
    if st.startswith("S1"):
        if "deep_drawdown" in fire_l or "calendar_catalyst" in fire_l or "major_catalyst" in fire_l:
            return True, "high", "s1_material_lifecycle"
        return True, "normal", "s1_lifecycle"
    if st.startswith("S6"):
        return True, "high", "s6_concentration"
    if st.startswith("S5"):
        return True, "normal", "s5_cash_narrative"
    if st.startswith("S2"):
        return True, "normal", "s2_stop_gap_context"
    # Operator-marked
    if plan.get("hermes_requested") or plan.get("operator_forced"):
        return True, "high", "operator_requested"
    return False, "low", "no_trigger"


def emit_research_for_plan(
    plan: dict[str, Any],
    *,
    reason: str = "",
    priority: Optional[str] = None,
    operator_forced: bool = False,
    force_refresh: bool = False,
    questions: Optional[list[dict[str, str]]] = None,
    actor_id: str = "hermes_research_loop",
) -> dict[str, Any]:
    """Single entry: enqueue via fingerprint path. Never raw JSONL append."""
    hr = _import_store()
    should, pri_default, auto_reason = should_enqueue_for_plan(plan)
    if not should and not operator_forced and not plan.get("hermes_requested"):
        return {"ok": False, "skipped": True, "reason": auto_reason}
    pri = priority or pri_default
    rr = hr.enqueue_research_request(
        plan,
        reason=reason or auto_reason,
        priority=pri,
        questions=questions,
        operator_forced=operator_forced,
        force_refresh=force_refresh or operator_forced,
        actor_id=actor_id,
    )
    # Attach in-flight stub so synthesis can say "research in flight"
    if rr.get("ok") and rr.get("research_id") and not rr.get("reused"):
        try:
            _attach_stub_to_plan(plan, rr["research_id"], status=rr.get("status") or "queued")
        except Exception:
            pass
    if rr.get("ok") and rr.get("reused") and rr.get("existing"):
        try:
            on_hermes_reused(plan, rr)
        except Exception:
            pass
    return rr


def _attach_stub_to_plan(plan: dict[str, Any], research_id: str, *, status: str) -> None:
    try:
        from lib.hermes_research_schema import evidence_stub_in_flight
    except Exception:
        from scripts.lib.hermes_research_schema import evidence_stub_in_flight  # type: ignore
    stub = evidence_stub_in_flight(
        research_id, plan_id=str(plan.get("plan_id") or ""), status=status,
    )
    _merge_evidence_on_plan_id(str(plan.get("plan_id") or ""), stub, research_id=research_id)


def _merge_evidence_on_plan_id(
    plan_id: str,
    domain_ref: dict[str, Any],
    *,
    research_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if not plan_id:
        return None
    CIOPlanStore = _import_plans()
    store = CIOPlanStore()
    plan = store.get_plan(plan_id)
    if not plan:
        return None
    refs = list(plan.get("evidence_refs") or [])
    # replace existing hermes_research / hermes_research_findings for same research
    new_refs = []
    for r in refs:
        if not isinstance(r, dict):
            continue
        dom = r.get("domain")
        if dom in ("hermes_research", "hermes_research_findings"):
            if research_id and r.get("research_id") and r.get("research_id") != research_id:
                # keep other open stubs briefly
                if r.get("status") in ("queued", "running", "started"):
                    new_refs.append(r)
                continue
            continue  # drop old same-domain primary
        new_refs.append(r)
    new_refs.append(domain_ref)
    # also dual-write findings domain for older consumers
    findings_ref = dict(domain_ref)
    findings_ref["domain"] = "hermes_research_findings"
    new_refs.append(findings_ref)
    patch: dict[str, Any] = {"evidence_refs": new_refs}
    rid = domain_ref.get("research_id") or research_id
    if rid:
        patch["hermes_research_id"] = rid
    updated = store.update_plan(plan_id, **patch)
    return updated


def _material_fingerprint(plan: dict[str, Any]) -> str:
    blob = {
        "rec": (plan.get("recommendation") or "")[:400],
        "summary": (plan.get("summary") or "")[:400],
        "fire": plan.get("fire_reasons") or (plan.get("extra") or {}).get("fire_reasons"),
        "material": plan.get("material"),
        "result_id": plan.get("hermes_result_id"),
    }
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()[:16]


def on_hermes_completed(
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    resynth: bool = True,
    notify: bool = True,
) -> dict[str, Any]:
    """
    CIO completion hook (injected into worker):
      1. Attach hermes_research evidence
      2. enrich_plan once
      3. maybe_notify only if material fingerprint changed
      4. optional desk memo regenerate (fail-soft)
    """
    out: dict[str, Any] = {
        "ok": True,
        "plan_id": request.get("plan_id") or result.get("plan_id"),
        "research_id": result.get("research_id"),
        "result_id": result.get("result_id"),
        "attached": False,
        "enriched": False,
        "notified": False,
        "memo": False,
        "critique": None,
        "memory": None,
    }
    try:
        from lib.research_quality import critique as _critique
        from lib.research_memory_bridge import admit_from_research
        from lib.research_circuit import record_success
    except Exception:
        from scripts.lib.research_quality import critique as _critique  # type: ignore
        from scripts.lib.research_memory_bridge import admit_from_research  # type: ignore
        from scripts.lib.research_circuit import record_success  # type: ignore
    try:
        merged = dict(result)
        if not merged.get("symbol"):
            merged["symbol"] = request.get("symbol") or (request.get("metadata") or {}).get("symbol")
        if not merged.get("research_id"):
            merged["research_id"] = request.get("research_id")
        if not merged.get("summary"):
            merged["summary"] = merged.get("thesis") or merged.get("content") or merged.get("findings") or ""
        crit = _critique(merged)
        out["critique"] = crit
        out["memory"] = admit_from_research(merged, critique=crit)
        record_success()
    except Exception as e:
        out["memory_error"] = f"{type(e).__name__}:{e}"
    plan_id = str(out["plan_id"] or "")
    if not plan_id:
        out["ok"] = False
        out["error"] = "plan_id_missing"
        return out

    try:
        try:
            from lib.hermes_research_schema import evidence_domain_from_result
        except Exception:
            from scripts.lib.hermes_research_schema import evidence_domain_from_result  # type: ignore
        domain = evidence_domain_from_result(result, reused=bool(result.get("reused")))
        plan = _merge_evidence_on_plan_id(
            plan_id, domain, research_id=str(result.get("research_id") or ""),
        )
        out["attached"] = plan is not None
    except Exception as e:
        out["attach_error"] = f"{type(e).__name__}:{e}"
        plan = None

    CIOPlanStore = _import_plans()
    store = CIOPlanStore()
    plan = plan or store.get_plan(plan_id)
    if not plan:
        out["ok"] = False
        out["error"] = "plan_not_found"
        return out

    before_fp = _material_fingerprint(plan)

    if resynth:
        try:
            try:
                from lib.cio_plan_enrichment import enrich_plan, maybe_notify_plan, is_material_plan
            except Exception:
                from scripts.lib.cio_plan_enrichment import (  # type: ignore
                    enrich_plan,
                    maybe_notify_plan,
                    is_material_plan,
                )
            enr = enrich_plan(plan, source="hermes_result", force_template=False)
            if isinstance(enr, dict) and enr.get("plan"):
                plan = enr["plan"]
                out["enriched"] = True
            elif isinstance(enr, dict) and enr.get("ok") is not False:
                # enrich_plan may return plan dict directly
                if enr.get("plan_id"):
                    plan = enr
                    out["enriched"] = True
            # reload after enrich writes
            plan = store.get_plan(plan_id) or plan
            after_fp = _material_fingerprint(plan)
            material_changed = after_fp != before_fp
            out["material_changed"] = material_changed
            if notify and material_changed and is_material_plan(plan):
                try:
                    notified = maybe_notify_plan(plan, force=False)
                    out["notified"] = bool(notified)
                except Exception as e:
                    out["notify_error"] = f"{type(e).__name__}:{e}"
        except Exception as e:
            out["enrich_error"] = f"{type(e).__name__}:{e}"

    # Desk memo once (fail-soft; do not block)
    try:
        try:
            from lib.cio_desk_synthesis import generate_desk_synthesis_v1
        except Exception:
            from scripts.lib.cio_desk_synthesis import generate_desk_synthesis_v1  # type: ignore
        gen = generate_desk_synthesis_v1()
        note = gen.get("note") or ""
        if note:
            root = Path("data/cio")
            root.mkdir(parents=True, exist_ok=True)
            (root / "cio_desk_note_latest.md").write_text(note + "\n", encoding="utf-8")
            out["memo"] = True
    except Exception as e:
        out["memo_error"] = f"{type(e).__name__}:{e}"

    # Audit line
    try:
        Path("data/cio").mkdir(parents=True, exist_ok=True)
        with open("data/cio/hermes_research_requests.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "event": "HERMES_LOOP_COMPLETED",
                "ts": _now(),
                "plan_id": plan_id,
                "research_id": result.get("research_id"),
                "result_id": result.get("result_id"),
                "enriched": out.get("enriched"),
                "notified": out.get("notified"),
                "material_changed": out.get("material_changed"),
            }, sort_keys=True) + "\n")
    except Exception:
        pass

    return out


def on_hermes_reused(plan: dict[str, Any], enqueue_result: dict[str, Any]) -> dict[str, Any]:
    """TTL reuse: attach existing result evidence without re-running Hermes."""
    existing = enqueue_result.get("existing") or {}
    result = {
        "result_id": existing.get("result_id") or enqueue_result.get("result_id"),
        "research_id": enqueue_result.get("research_id"),
        "plan_id": plan.get("plan_id"),
        "as_of": existing.get("as_of") or existing.get("completed_ts"),
        "status": "completed",
        "summary": existing.get("summary") or "",
        "findings": existing.get("findings") or [],
        "answers": existing.get("answers") or [],
        "desk_implications": existing.get("desk_implications") or {},
        "reused": True,
    }
    # Prefer full result from store when only ids present
    if result.get("result_id") and not result.get("findings") and not result.get("summary"):
        hr = _import_store()
        info = hr.latest_research_for_plan(str(plan.get("plan_id") or ""))
        full = info.get("latest_result")
        if isinstance(full, dict):
            result = {**full, "reused": True}
    return on_hermes_completed(
        {"plan_id": plan.get("plan_id"), "research_id": result.get("research_id")},
        result,
        resynth=True,
        notify=False,  # pure reuse: no Telegram
    )


def on_hermes_failed(request: dict[str, Any], error: str) -> dict[str, Any]:
    """Attach explicit gap stub; do not crash desk."""
    plan_id = str(request.get("plan_id") or "")
    rid = str(request.get("research_id") or "")
    stub = {
        "domain": "hermes_research",
        "as_of": _now()[:19],
        "research_id": rid,
        "plan_id": plan_id,
        "status": "failed",
        "quality_state": "DATA_UNAVAILABLE",
        "gap_reason": f"research_failed:{error[:120]}",
        "findings_summary": [],
        "fields_used": [],
        "authority": "READ_ONLY_ADVISORY",
    }
    plan = _merge_evidence_on_plan_id(plan_id, stub, research_id=rid)
    return {"ok": True, "attached": plan is not None, "status": "failed", "error": error[:200]}


def process_queue_once(
    *,
    worker_id: str = "cio-hermes-loop",
    limit: int = 1,
    backend_name: str | None = None,
) -> dict[str, Any]:
    """Convenience: run worker once with factory backend + completion hook."""
    try:
        from lib.hermes_worker import HermesWorker
        from lib.hermes_research_backend import build_hermes_backend
    except Exception:
        from scripts.lib.hermes_worker import HermesWorker  # type: ignore
        from scripts.lib.hermes_research_backend import build_hermes_backend  # type: ignore
    hr = _import_store()
    # Default stub unless HERMES_BACKEND or explicit name
    name = backend_name
    if name is None:
        name = "stub"
    backend = build_hermes_backend(name)
    worker = HermesWorker(
        store=hr,
        backend=backend,
        worker_id=worker_id,
        on_completed=on_hermes_completed,
        on_failed=on_hermes_failed,
    )
    return worker.run_once(limit=limit)
