"""Wire thesis coverage checks onto EXISTING CIO event/wake types.

Uses existing event types only (no new bus / no new scheduler):
  watch.new_signal
  hermes.research_promoted
  hermes.contradiction_found
  market.regime_change
  portfolio.material_change

Discovery events may trigger coverage/materiality/RAG checks.
They must NOT automatically publish a thesis version.
Replay-safe / idempotent by semantic identity.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolThesisEventWake@v1"
CONSUMER = "symbol_thesis_r71"

# Existing CIO bus types we map onto
WAKE_MAP = {
    "candidate_discovery": "watch.new_signal",
    "research_discovery": "watch.new_signal",
    "social_material_transition": "watch.new_signal",
    "research_completion": "hermes.research_promoted",
    "contradiction": "hermes.contradiction_found",
    "regime_change": "market.regime_change",
    "holding_change": "portfolio.material_change",
    "reentry_transition": "watch.new_signal",
    "scheduled_review": "system.heartbeat_ok",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def semantic_wake_id(*, kind: str, symbol: str, source_id: str, day: str | None = None) -> str:
    day = day or datetime.now(timezone.utc).strftime("%Y%m%d")
    return "stw_" + hashlib.sha256(f"{kind}|{symbol}|{source_id}|{day}".encode()).hexdigest()[:20]


def _seen_path(root: Path) -> Path:
    return root / "data" / "cio" / "symbol_thesis_wake_dedupe.json"


def _load_seen(root: Path) -> dict[str, Any]:
    p = _seen_path(root)
    if not p.is_file():
        return {"seen": {}, "updated_at": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"seen": {}, "updated_at": None}


def _save_seen(root: Path, obj: dict[str, Any]) -> None:
    p = _seen_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def plan_wake_from_discovery(
    *,
    symbol: str,
    event_id: str,
    source_key: str = "candidate_discovery",
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Plan a coverage/materiality/RAG wake — never a thesis version publish."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    wid = semantic_wake_id(kind="candidate_discovery", symbol=symbol, source_id=event_id)
    seen = _load_seen(root)
    if wid in (seen.get("seen") or {}):
        return {
            "schema": SCHEMA,
            "duplicate": True,
            "wake_id": wid,
            "action": "SUPPRESS",
            "reason": "semantic_dedupe",
            "authority": AUTHORITY,
        }
    bus_type = WAKE_MAP["candidate_discovery"]
    return {
        "schema": SCHEMA,
        "duplicate": False,
        "wake_id": wid,
        "symbol": symbol.upper(),
        "cio_event_type": bus_type,
        "actions_allowed": ["coverage_check", "materiality_check", "rag_check"],
        "actions_forbidden": ["auto_thesis_version", "auto_ADD", "auto_RE_ENTER", "paid_deep_research"],
        "source_key": source_key,
        "source_event_id": event_id,
        "membership_is_not_evidence": True,
        "emit": False,  # dry default — caller opts in
        "authority": AUTHORITY,
        "as_of": _now(),
    }


def execute_wake_checks(
    symbol: str,
    *,
    root: Path | str | None = None,
    wake_plan: Optional[dict[str, Any]] = None,
    persist_dedupe: bool = False,
) -> dict[str, Any]:
    """Run coverage + materiality + RAG checks for a wake (idempotent)."""
    from scripts.lib.thesis_research_context import build_thesis_research_context

    root = Path(root) if root else Path(__file__).resolve().parents[2]
    if wake_plan and wake_plan.get("duplicate"):
        return {**wake_plan, "checks": None, "replay_quiet": True}

    ctx = build_thesis_research_context(symbol, root=root, run_rag_pipeline=True)
    out = {
        "schema": SCHEMA,
        "wake_id": (wake_plan or {}).get("wake_id"),
        "symbol": symbol.upper(),
        "checks": {
            "coverage_state": ctx.get("thesis_state"),
            "materiality_tier": (ctx.get("materiality") or {}).get("materiality_tier"),
            "expensive_allowed": (ctx.get("materiality") or {}).get("expensive_thesis_work_allowed"),
            "thesis_evidence_state": ctx.get("thesis_evidence_state"),
            "rag_sufficiency": ((ctx.get("rag_refs") or {}).get("sufficiency") or {}),
            "acquisition_status": ((ctx.get("new_acquisition_refs") or {}).get("plan_status")),
            "synthesis_gate": ((ctx.get("hermes_result") or {}).get("gate")),
        },
        "thesis_version_published": False,
        "replay_safe": True,
        "authority": AUTHORITY,
        "as_of": _now(),
    }
    if persist_dedupe and wake_plan and wake_plan.get("wake_id"):
        seen = _load_seen(root)
        bucket = dict(seen.get("seen") or {})
        bucket[wake_plan["wake_id"]] = {"as_of": _now(), "symbol": symbol.upper()}
        # keep last 2000
        if len(bucket) > 2000:
            for k in list(bucket.keys())[: len(bucket) - 2000]:
                bucket.pop(k, None)
        seen["seen"] = bucket
        seen["updated_at"] = _now()
        _save_seen(root, seen)
    return out


def emit_cio_wake_if_enabled(
    wake_plan: dict[str, Any],
    *,
    enable_emit: bool = False,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Optionally emit onto existing CIO event bus. Default dry."""
    if wake_plan.get("duplicate"):
        return {**wake_plan, "emitted": False, "reason": "duplicate"}
    if not enable_emit:
        return {**wake_plan, "emitted": False, "reason": "dry_default"}
    try:
        from scripts.lib.cio_event_bus import CIOEventBus
        bus = CIOEventBus()
        evt = bus.emit(
            wake_plan["cio_event_type"],
            payload={
                "symbol": wake_plan.get("symbol"),
                "wake_id": wake_plan.get("wake_id"),
                "r71": True,
                "actions_allowed": wake_plan.get("actions_allowed"),
                "actions_forbidden": wake_plan.get("actions_forbidden"),
                "source_event_id": wake_plan.get("source_event_id"),
            },
            source="symbol_thesis_event_wake",
            source_event_id=str(wake_plan.get("source_event_id") or ""),
            semantic_event_key=str(wake_plan.get("wake_id") or ""),
        )
        return {
            **wake_plan,
            "emitted": True,
            "event_id": getattr(evt, "event_id", None),
        }
    except Exception as exc:
        return {**wake_plan, "emitted": False, "error": f"{type(exc).__name__}:{exc}"}
