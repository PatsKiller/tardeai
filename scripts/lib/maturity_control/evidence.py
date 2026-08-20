"""Evidence drill-down for a lesson or case. Structured lineage only — no CoT."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from scripts.lib.maturity_control.lessons import collect_lessons
from scripts.lib.maturity_control.store import resolve_root


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def collect_fs_provider_status(*, env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Honest FS provider surface for SENSES EVIDENCE (shadow / unconfigured / DENIED).

    Prefer backend fields the UI can show. Never invent credentials or live calls.
    """
    env_map = env if env is not None else os.environ
    try:
        from scripts.lib.financial_senses_aif import (
            FLAG_AIF_FINANCIAL_SENSES_SHADOW,
            build_live_providers,
            shadow_enabled,
        )
        from scripts.lib.financial_senses.result import STATUS_NOT_CONFIGURED
    except Exception as exc:
        return {
            "providers": [],
            "shadow_flag": "AIF_FINANCIAL_SENSES_SHADOW",
            "shadow_enabled": False,
            "error": f"{type(exc).__name__}:{exc}",
            "note": "provider status unavailable",
        }

    shadow_on = shadow_enabled(env_map)
    providers_out: list[dict[str, Any]] = []
    try:
        live = build_live_providers()
    except Exception as exc:
        live = {}
        build_err = f"{type(exc).__name__}:{exc}"
    else:
        build_err = None

    for name, prov in sorted((live or {}).items()):
        status = "UNKNOWN"
        detail = ""
        configured = None
        try:
            health = prov.health() if hasattr(prov, "health") else None
            if health is not None:
                status = str(
                    getattr(health, "status", None)
                    or (health.get("status") if isinstance(health, dict) else "UNKNOWN")
                )
                details = (
                    getattr(health, "details", None)
                    or (health.get("details") if isinstance(health, dict) else {})
                    or {}
                )
                configured = details.get("configured")
                detail = str(details.get("detail") or "")
            elif hasattr(prov, "_configured"):
                configured = bool(prov._configured)
                status = "OK" if configured else STATUS_NOT_CONFIGURED
                detail = str(getattr(prov, "_config_detail", "") or "")
        except Exception as exc:
            status = "ERROR"
            detail = f"{type(exc).__name__}:{exc}"

        # Operator-facing label: shadow/unconfigured when not live-ready.
        if not shadow_on:
            label = "DENIED"
            reason = f"{FLAG_AIF_FINANCIAL_SENSES_SHADOW}!=1 (gateway shadow off)"
        elif str(status).upper() in {STATUS_NOT_CONFIGURED, "NOT_CONFIGURED"} or configured is False:
            label = "shadow/unconfigured"
            reason = detail or "provider not configured"
        elif str(status).upper() in {"DENIED", "ERROR", "UNAVAILABLE", "FAILED"}:
            label = str(status).upper()
            reason = detail or status
        else:
            label = "shadow"
            reason = "shadow-only; no execution influence"

        providers_out.append({
            "provider": name,
            "status": status,
            "configured": configured,
            "label": label,
            "reason": reason,
            "shadow_only": True,
            "behavior_influence": False,
        })

    unconfigured = [p for p in providers_out if p["label"] in {"shadow/unconfigured", "DENIED"}]
    return {
        "providers": providers_out,
        "unconfigured_or_denied": unconfigured,
        "shadow_flag": FLAG_AIF_FINANCIAL_SENSES_SHADOW,
        "shadow_enabled": shadow_on,
        "build_error": build_err,
        "note": (
            "Honest provider surface for SENSES EVIDENCE. "
            "shadow/unconfigured = missing keys or shadow-only; "
            "DENIED = AIF financial senses shadow flag off."
        ),
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }


def lesson_evidence(lesson_id: str, *, root: Path | str | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    view = collect_lessons(root=base)
    lesson = next((l for l in view["lessons"] if l["lesson_id"] == lesson_id), None)
    refs = list((lesson or {}).get("evidence_refs") or [])
    cases_path = base / "data" / "cio" / "cio_production_cases.jsonl"
    cases = []
    if cases_path.is_file():
        from scripts.lib import cio_production_case as cs
        all_cases = cs.materialize_cases(path=cases_path)
        want = set(refs) | {lesson_id}
        for c in all_cases:
            if c.get("case_id") in want or c.get("decision_id") in want:
                cases.append({
                    "case_id": c.get("case_id"),
                    "decision_id": c.get("decision_id"),
                    "status": c.get("status"),
                    "operator_disposition": c.get("operator_disposition"),
                    "note": c.get("note"),
                    "outcome": c.get("outcome"),
                    "darwin": c.get("darwin"),
                })
    traces = []
    for row in _jsonl(base / "data" / "cio" / "agent_run_traces.jsonl")[-20:]:
        traces.append({
            "trace_id": row.get("trace_id"),
            "agent": row.get("agent"),
            "started_at": row.get("started_at"),
            "ended_at": row.get("ended_at"),
            "status": row.get("status"),
        })
    receipts = []
    for row in _jsonl(base / "data" / "cio" / "agent_tool_traces.jsonl")[-20:]:
        if row.get("provider") or row.get("fs_provider") or row.get("shadow_only") is not None:
            receipts.append({
                "provider": row.get("fs_provider") or row.get("provider"),
                "capability": row.get("fs_capability") or row.get("tool_name"),
                "request_id": row.get("request_id"),
                "status": row.get("status"),
                "shadow_only": row.get("shadow_only"),
                "behavior_influence": row.get("behavior_influence"),
                "source_asof": row.get("source_asof"),
                "quality_summary": row.get("quality_summary"),
                "fact_count": row.get("fact_count"),
                "estimate_count": row.get("estimate_count"),
            })
    snap = {}
    sp = base / "data" / "cio" / "cio_reflection_candidates.json"
    if sp.is_file():
        try:
            snap = json.loads(sp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            snap = {}
    provider_status = collect_fs_provider_status()
    return {
        "authority": "READ_ONLY_ADVISORY",
        "lesson": lesson,
        "originating_cases": cases,
        "reflection": {
            "at": snap.get("at"),
            "cases_seen": snap.get("cases_seen"),
            "scored": snap.get("scored"),
            "auto_promotions": snap.get("auto_promotions"),
            "mutates_production": snap.get("mutates_production"),
        },
        "agent_runs": traces,
        "financial_senses_receipts": receipts,
        "fs_providers": provider_status.get("providers") or [],
        "fs_providers_unconfigured_or_denied": provider_status.get("unconfigured_or_denied") or [],
        "fs_provider_status": provider_status,
        "hidden_chain_of_thought": False,
    }
