"""GET-only Command Center APIs for the maturity control plane.

Control mutations live on /api/v3/maturity-control/* and require
MATURITY_CONTROL_ENABLED=1 plus the Phase 11 ack. They never grant
financial_action and never use the agent-runtime read role.
"""
from __future__ import annotations

import json
import os
from typing import Any

from scripts.lib.maturity_control import lessons as L
from scripts.lib.maturity_control import promotion as P
from scripts.lib.maturity_control import store
from scripts.lib.maturity_control.autonomy_health import collect_autonomy_health
from scripts.lib.maturity_control.evidence import lesson_evidence
from scripts.lib.maturity_control.notification_view import collect_notification_gate
from scripts.lib.maturity_control.redaction import redact
from scripts.lib.maturity_control.schema import ACK_TOKEN
from scripts.lib.maturity_control.telegram_receipts import collect_telegram_receipts

AUTHORITY = {
    "authority": "READ_ONLY_ADVISORY",
    "mutation": False,
    "financial_action": False,
    "service_control": False,
    "provider_call": False,
    "auto_promotion_to_trading": False,
}


def _q(query: dict | None, key: str, default: str = "") -> str:
    if not query:
        return default
    v = query.get(key)
    if isinstance(v, list):
        return str(v[0]) if v else default
    return str(v) if v is not None else default


def handle_get(path: str, query: dict | None = None) -> tuple[int, dict[str, Any]]:
    p = path.strip("/")
    if p in ("", "authority"):
        return 200, {"ok": True, **AUTHORITY, "contract": "maturity-control-plane-v1"}
    if p == "learning":
        return 200, {"ok": True, **AUTHORITY, **L.collect_lessons()}
    if p == "lessons":
        data = L.collect_lessons()
        return 200, {"ok": True, **AUTHORITY, "lessons": data["lessons"], "counts": data["counts"]}
    if p == "senses":
        return 200, {"ok": True, **AUTHORITY, **lesson_evidence("_")}
    if p.startswith("lessons/"):
        lid = p.split("/", 1)[1]
        return 200, {"ok": True, **AUTHORITY, **lesson_evidence(lid)}
    if p == "cases":
        return 200, {"ok": True, **AUTHORITY, **L.collect_cases()}
    if p == "promotions":
        snap = store.load_snapshot()
        return 200, {"ok": True, **AUTHORITY, "promotions": list((snap.get("promotions") or {}).values())}
    if p.startswith("promotions/"):
        pid = p.split("/", 1)[1]
        return 200, {"ok": True, **P.inspect(pid)}
    if p in ("notification-gate", "notifications"):
        return 200, {"ok": True, **AUTHORITY, **collect_notification_gate()}
    if p in ("telegram-receipts", "telegram"):
        return 200, {"ok": True, **AUTHORITY, **collect_telegram_receipts()}
    if p in ("autonomy-health", "autonomy"):
        return 200, {"ok": True, **AUTHORITY, **collect_autonomy_health()}
    if p == "memory":
        from scripts.lib.agent_durable_memory import get_durable_provider, display_status
        from scripts.lib.agent_memory_shadow import shadow_metrics
        from scripts.lib.maturity_control.redaction import redact
        import json as _json
        from pathlib import Path as _Path
        prov = get_durable_provider()
        recs = []
        contradictions = []
        for r in prov._store.values():
            item = {
                "memory_id": r.get("memory_id"),
                "status": display_status(r.get("status")),
                "raw_status": r.get("status"),
                "authority_class": r.get("authority_class"),
                "subject": r.get("subject"),
                "content": r.get("content"),
                "memory_type": r.get("memory_type"),
                "symbols": r.get("symbols"),
                "confidence": r.get("confidence"),
                "created_at": r.get("created_at"),
                "as_of": r.get("as_of") or r.get("valid_from") or r.get("created_at"),
                "expires_at": r.get("expires_at"),
                "source_refs": r.get("source_refs") or r.get("source_event_ids"),
                "provenance": r.get("source_kind"),
                "content_hash": r.get("content_hash") or r.get("content_digest"),
                "contradicts": r.get("contradicts"),
                "supersedes": r.get("supersedes"),
                "superseded_by": r.get("superseded_by"),
                "admission_reason": r.get("admission_reason"),
            }
            recs.append(item)
            if r.get("contradicts") or r.get("status") == "DISPUTED":
                contradictions.append({
                    "memory_id": r.get("memory_id"),
                    "status": display_status(r.get("status")),
                    "contradicts": r.get("contradicts"),
                    "dispute_reason": r.get("dispute_reason"),
                })
        shadow_runs = []
        shadow_path = _Path(prov.path).with_name("memory_shadow_runs.jsonl")
        if shadow_path.is_file():
            for line in shadow_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]:
                if not line.strip():
                    continue
                try:
                    shadow_runs.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
        health = prov.health()
        return 200, redact({
            "ok": True, **AUTHORITY,
            "backend": health,
            "influence_mode": os.environ.get("GOVERNED_MEMORY_ADVISORY_INFLUENCE", "OFF"),
            "memory_behavior_influence": os.environ.get("MEMORY_BEHAVIOR_INFLUENCE", "0"),
            "counts": prov.counts(),
            "records": recs,
            "contradictions": contradictions,
            "admission_receipts": prov.tail_jsonl(prov.receipts_path, 20),
            "retrieval_receipts": prov.tail_jsonl(prov.retrievals_path, 20),
            "shadow": shadow_metrics(shadow_runs),
            "shadow_runs": shadow_runs[-10:],
            "operator_actions": ["dispute", "retract", "expire"],
            "control_path": "/api/v3/maturity-control/memory/{dispute|retract|expire}",
        })
    if p in ("influence", "comparator"):
        from scripts.lib.advisory_influence.gates import current_gates
        from scripts.lib.advisory_influence.comparator import metrics
        from scripts.lib.maturity_control.store import resolve_root
        import json
        from pathlib import Path
        runs_path = resolve_root() / "data" / "cio" / "advisory_influence_runs.jsonl"
        runs = []
        if runs_path.is_file():
            for line in runs_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        runs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return 200, {
            "ok": True, **AUTHORITY,
            "gates": current_gates(),
            "metrics": metrics(runs),
            "runs": runs[-20:],
            "badge": "LEARNING-INFLUENCED ADVISORY" if current_gates().get("lesson_mode") in {"CANARY", "ACTIVE_ADVISORY"} else "BASELINE",
        }
    return 404, {"ok": False, "error": f"unknown_maturity_get:{p}"}


def handle_control_post(path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    """Governed control API — not the dashboard read API."""
    enabled = os.environ.get("MATURITY_CONTROL_ENABLED", "").strip() in {"1", "true", "yes"}
    if not enabled:
        return 403, {"ok": False, "error": "control_disabled", "message": "MATURITY_CONTROL_ENABLED is not set"}
    body = dict(body or {})
    p = path.strip("/")
    try:
        if p == "draft":
            rec = P.new_promotion(
                capability_type=str(body.get("capability_type") or ""),
                from_state=str(body.get("from_state") or ""),
                requested_state=str(body.get("requested_state") or ""),
                exact_source_sha=str(body.get("exact_source_sha") or ""),
                requested_by=str(body.get("requested_by") or "operator"),
                agent_id=body.get("agent_id"),
                lesson_id=body.get("lesson_id"),
                evidence_bundle=body.get("evidence_bundle") or {},
                shadow_sample_size=int(body.get("shadow_sample_size") or 0),
                matured_outcome_count=int(body.get("matured_outcome_count") or 0),
                quality_metrics=body.get("quality_metrics") or {},
                safety_metrics=body.get("safety_metrics") or {},
                rollback_target=body.get("rollback_target"),
            )
            rec = P.preflight(
                rec,
                live_sha=str(body.get("live_sha") or rec.get("exact_source_sha")),
                has_review=bool(body.get("has_review")),
                has_score=bool(body.get("has_score")),
            )
            return 200, {"ok": True, "financial_action": False, "promotion": rec}
        if p.startswith("memory/"):
            from scripts.lib.agent_durable_memory import get_durable_provider
            action = p.split("/", 1)[1]
            mid = str(body.get("memory_id") or "")
            prov = get_durable_provider()
            if action == "dispute":
                ok = prov.dispute(mid, str(body.get("reason") or "operator"))
            elif action == "retract":
                ok = prov.retract(mid, str(body.get("reason") or "operator"))
            elif action == "expire":
                ok = prov.expire(mid)
            else:
                return 404, {"ok": False, "error": f"unknown_memory_control:{action}"}
            return 200, {"ok": ok, "financial_action": False, "memory_id": mid, "action": action}
        pid = str(body.get("promotion_id") or "")
        rec = P.load_or_raise(pid)
        if p == "preflight":
            out = P.preflight(
                rec,
                live_sha=str(body.get("live_sha") or rec.get("exact_source_sha")),
                has_review=bool(body.get("has_review")),
                has_score=bool(body.get("has_score")),
            )
        elif p == "sign":
            out = P.sign(
                rec,
                operator=str(body.get("operator") or ""),
                ack=str(body.get("ack") or ""),
                live_sha=str(body.get("live_sha") or ""),
            )
        elif p == "activate-canary":
            out = P.activate_canary(rec)
        elif p == "restrict":
            out = P.restrict(rec, reason=str(body.get("reason") or "operator"))
        elif p == "rollback":
            out = P.rollback(rec, reason=str(body.get("reason") or "operator"))
        else:
            return 404, {"ok": False, "error": f"unknown_control_post:{p}"}
        return 200, {"ok": True, "financial_action": False, "promotion": out}
    except P.PromotionError as e:
        return 400, e.as_dict()
    except Exception as e:
        return 500, {"ok": False, "error": type(e).__name__, "detail": str(e)[:200]}
