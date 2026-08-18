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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_PLAN_ID_RE = re.compile(r"plan_[0-9a-f]{8,}", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def plan_id_from_challenge(rec: dict[str, Any]) -> str:
    """Extract plan_id from overlay metadata, payload.source, or description."""
    md = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
    if md.get("plan_id"):
        return str(md["plan_id"])
    pl = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    if pl.get("plan_id"):
        return str(pl["plan_id"])
    for blob in (pl.get("source"), pl.get("description"), rec.get("stream_id"), rec.get("challenge_id")):
        m = _PLAN_ID_RE.search(str(blob or ""))
        if m:
            return m.group(0)
    return ""


def expire_overlay_for_plan(
    plan_id: str,
    *,
    result_id: str = "",
    research_id: str = "",
    apply: bool = True,
) -> dict[str, Any]:
    """Expire pending overlay streams whose payload points at this plan.

    Append-only. Never deletes history. No-op when plan_id is empty.
    """
    out: dict[str, Any] = {
        "ok": True,
        "plan_id": plan_id,
        "result_id": result_id,
        "research_id": research_id,
        "matched": 0,
        "expired": 0,
        "errors": [],
        "stream_ids": [],
        "applied": apply,
        "authority": "READ_ONLY_ADVISORY",
    }
    if not plan_id:
        out["ok"] = False
        out["error"] = "plan_id_required"
        return out
    try:
        from lib.intelligence_lineage import (
            _read_jsonl,
            challenge_latest,
            challenge_pending,
            cio_dir,
        )
        from lib.cio_hermes_challenge_queue import HermesChallengeQueue
    except Exception:
        from scripts.lib.intelligence_lineage import (  # type: ignore
            _read_jsonl,
            challenge_latest,
            challenge_pending,
            cio_dir,
        )
        from scripts.lib.cio_hermes_challenge_queue import HermesChallengeQueue  # type: ignore
    path = cio_dir() / "hermes_challenge_queue.jsonl"
    pending = challenge_pending(challenge_latest(_read_jsonl(path)))
    reason = f"satisfied_by_structured_result:{result_id or research_id or plan_id}"
    matches = []
    for rec in pending:
        if plan_id_from_challenge(rec) == plan_id:
            sid = str(rec.get("stream_id") or "")
            if sid:
                matches.append(sid)
    out["matched"] = len(matches)
    out["stream_ids"] = matches
    if not apply or not matches:
        return out
    q = HermesChallengeQueue(event_store_path=path)
    for sid in matches:
        try:
            q.expire(sid, actor_id="hermes_research_loop", reason=reason)
            out["expired"] += 1
        except Exception as exc:
            out["errors"].append(f"{sid}:{type(exc).__name__}:{exc}")
    if out["errors"] and out["expired"] == 0:
        out["ok"] = False
    return out


def expire_satisfied_overlays(*, apply: bool = True) -> dict[str, Any]:
    """Expire overlay streams whose plan already has a completed structured result."""
    try:
        from lib.intelligence_lineage import (
            _read_jsonl,
            challenge_latest,
            challenge_pending,
            cio_dir,
        )
        from lib import cio_hermes_research as hr
    except Exception:
        from scripts.lib.intelligence_lineage import (  # type: ignore
            _read_jsonl,
            challenge_latest,
            challenge_pending,
            cio_dir,
        )
        from scripts.lib import cio_hermes_research as hr  # type: ignore
    path = cio_dir() / "hermes_challenge_queue.jsonl"
    pending = challenge_pending(challenge_latest(_read_jsonl(path)))
    proj = hr._load_projection()
    by_plan: dict[str, list[dict[str, Any]]] = {}
    for rec in (proj.get("by_research_id") or {}).values():
        if not isinstance(rec, dict):
            continue
        pid = str(rec.get("plan_id") or "")
        if pid:
            by_plan.setdefault(pid, []).append(rec)
    report = {
        "ok": True,
        "before_pending": len(pending),
        "expired": 0,
        "skipped_open": 0,
        "no_plan": 0,
        "applied": apply,
        "authority": "READ_ONLY_ADVISORY",
        "deleted": 0,
    }
    seen: set[str] = set()
    for rec in pending:
        pid = plan_id_from_challenge(rec)
        if not pid:
            report["no_plan"] += 1
            continue
        done = next((r for r in by_plan.get(pid) or [] if r.get("status") == "completed"), None)
        if not done:
            report["skipped_open"] += 1
            continue
        if pid in seen:
            continue
        seen.add(pid)
        exp = expire_overlay_for_plan(
            pid,
            result_id=str(done.get("latest_result_id") or ""),
            research_id=str(done.get("research_id") or ""),
            apply=apply,
        )
        report["expired"] += int(exp.get("expired") or 0)
    return report


def classify_overlay_pending(*, apply_satisfied: bool = False) -> dict[str, Any]:
    """Classify remaining overlay streams. Never deletes history."""
    try:
        from lib.intelligence_lineage import (
            _read_jsonl,
            challenge_latest,
            challenge_pending,
            cio_dir,
        )
        from lib import cio_hermes_research as hr
    except Exception:
        from scripts.lib.intelligence_lineage import (  # type: ignore
            _read_jsonl,
            challenge_latest,
            challenge_pending,
            cio_dir,
        )
        from scripts.lib import cio_hermes_research as hr  # type: ignore
    path = cio_dir() / "hermes_challenge_queue.jsonl"
    latest = challenge_latest(_read_jsonl(path))
    pending = challenge_pending(latest)
    proj = hr._load_projection()
    by_plan: dict[str, list[dict[str, Any]]] = {}
    for rec in (proj.get("by_research_id") or {}).values():
        if isinstance(rec, dict) and rec.get("plan_id"):
            by_plan.setdefault(str(rec["plan_id"]), []).append(rec)
    buckets = {
        "ACTIVE_VALID": 0,
        "WAITING_RESEARCH": 0,
        "SATISFIED_BY_RESULT": 0,
        "ORPHANED_LEGACY": 0,
        "DUPLICATE": 0,
        "STALE_EXPIRED": 0,
        "INVALID": 0,
    }
    seen_plan: set[str] = set()
    satisfied_plans: list[str] = []
    for rec in pending:
        if not isinstance(rec, dict):
            buckets["INVALID"] += 1
            continue
        pid = plan_id_from_challenge(rec)
        if not pid:
            buckets["ORPHANED_LEGACY"] += 1
            continue
        if pid in seen_plan:
            buckets["DUPLICATE"] += 1
            continue
        seen_plan.add(pid)
        done = next((r for r in by_plan.get(pid) or [] if r.get("status") == "completed"), None)
        if done:
            buckets["SATISFIED_BY_RESULT"] += 1
            satisfied_plans.append(pid)
            continue
        ev = str(rec.get("event") or rec.get("status") or "").upper()
        if ev in {"EXPIRED", "CANCELLED"}:
            buckets["STALE_EXPIRED"] += 1
        elif by_plan.get(pid):
            buckets["WAITING_RESEARCH"] += 1
        else:
            buckets["ACTIVE_VALID"] += 1
    expired = 0
    if apply_satisfied:
        for pid in satisfied_plans:
            exp = expire_overlay_for_plan(pid, apply=True)
            expired += int(exp.get("expired") or 0)
    return {
        "ok": True,
        "pending": len(pending),
        "buckets": buckets,
        "satisfied_closed": expired,
        "applied": apply_satisfied,
        "authority": "READ_ONLY_ADVISORY",
        "deleted": 0,
    }


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
        "overlay": None,
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
        try:
            from lib.hermes_research_schema import collect_sources, synthesize_summary
        except Exception:
            from scripts.lib.hermes_research_schema import (  # type: ignore
                collect_sources,
                synthesize_summary,
            )
        if not str(merged.get("summary") or "").strip():
            merged["summary"] = synthesize_summary(merged, request)
        if not (merged.get("sources") or merged.get("source_urls")):
            merged["sources"] = collect_sources(merged, request)
        crit = _critique(merged)
        out["critique"] = crit
        mem = admit_from_research(merged, critique=crit)
        out["memory"] = mem
        record_success()
    except Exception as e:
        out["memory_error"] = f"{type(e).__name__}:{e}"
    plan_id = str(out["plan_id"] or "")
    # Plan attach/enrich needs a plan. Product reassessment does not —
    # overnight Flash jobs often have no plan_id (ORPHANED_LEGACY parent).

    plan = None
    store = None
    if plan_id:
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

    before_fp = _material_fingerprint(plan) if plan else ""

    if resynth and plan and store:
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

    if plan_id:
        try:
            out["overlay"] = expire_overlay_for_plan(
                plan_id,
                result_id=str(result.get("result_id") or ""),
                research_id=str(result.get("research_id") or ""),
                apply=True,
            )
        except Exception as e:
            out["overlay_error"] = f"{type(e).__name__}:{e}"

    # Missing R6.8 link: persist a new investment product + what_changed + notify.
    # Fail-soft. Never reruns paid research. Never grants RE_ENTER.
    try:
        try:
            from lib.cio_product_reassessment import reassess_on_research_completed
        except Exception:
            from scripts.lib.cio_product_reassessment import (  # type: ignore
                reassess_on_research_completed,
            )
        out["reassessment"] = reassess_on_research_completed(
            request, result, critique=out.get("critique") if isinstance(out.get("critique"), dict) else None,
        )
    except Exception as e:
        out["reassessment_error"] = f"{type(e).__name__}:{e}"

    # Audit line — include critique/memory/overlay so a missing receipt is visible
    try:
        Path("data/cio").mkdir(parents=True, exist_ok=True)
        mem = out.get("memory") if isinstance(out.get("memory"), dict) else {}
        admission = mem.get("admission") if isinstance(mem.get("admission"), dict) else {}
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
                "critique_verdict": (out.get("critique") or {}).get("verdict")
                if isinstance(out.get("critique"), dict) else None,
                "memory_ok": mem.get("ok"),
                "memory_accepted": admission.get("accepted"),
                "memory_id": admission.get("memory_id") or mem.get("memory_id"),
                "memory_reason": admission.get("reason") or mem.get("reason") or mem.get("error"),
                "memory_error": out.get("memory_error"),
                "overlay_expired": (out.get("overlay") or {}).get("expired")
                if isinstance(out.get("overlay"), dict) else None,
                "reassessment_ok": (out.get("reassessment") or {}).get("ok")
                if isinstance(out.get("reassessment"), dict) else None,
                "reassessment_id": (out.get("reassessment") or {}).get("reassessment_id")
                if isinstance(out.get("reassessment"), dict) else None,
                "reassessment_duplicate": (out.get("reassessment") or {}).get("duplicate")
                if isinstance(out.get("reassessment"), dict) else None,
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
