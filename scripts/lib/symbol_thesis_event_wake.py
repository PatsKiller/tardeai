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


# ── Consumer: cio_wake_dispatch_entrypoint (SHADOW until the operator flips it) ──
# Governance: ACTIVE needs BOTH the existing persistent-wake flag
# (PERSISTENT_WAKE_ENABLED=1) AND an explicit SYMBOL_THESIS_EVENT_WAKE_MODE=active.
# Anything else is SHADOW: plan the wake (pure; reads the dedupe file only) and
# append a receipt. SHADOW never runs execute_wake_checks (RAG / paid work),
# never writes the dedupe file and never emits onto the CIO bus.

MODE_ENV = "SYMBOL_THESIS_EVENT_WAKE_MODE"
GOVERNANCE_FLAG = "PERSISTENT_WAKE_ENABLED"
RECEIPT_SCHEMA = "SymbolThesisEventWakeReceipt@v1"
RECEIPTS_RELATIVE = Path("data") / "cio" / "symbol_thesis_event_wake_receipts.jsonl"
EVENTS_RELATIVE = Path("data") / "cio" / "cio_events.jsonl"

# Bus event type -> the wake kind this module plans for it.
EVENT_KIND = {
    "watch.new_signal": "candidate_discovery",
    "hermes.research_promoted": "research_completion",
    "hermes.contradiction_found": "contradiction",
    "market.regime_change": "regime_change",
    "portfolio.material_change": "holding_change",
}


def wake_mode(env: Optional[dict[str, str]] = None) -> str:
    """'active' only when BOTH governance flags say so; otherwise 'shadow'."""
    import os

    e = os.environ if env is None else env
    explicit = str(e.get(MODE_ENV) or "").strip().lower() == "active"
    governed = str(e.get(GOVERNANCE_FLAG) or "").strip() == "1"
    return "active" if (explicit and governed) else "shadow"


def plan_wake_for_event(
    *, event_type: str, symbol: str, event_id: str, root: Path | str | None = None,
) -> Optional[dict[str, Any]]:
    """Plan a coverage/materiality/RAG wake for one bus event; None if not a mapped type."""
    kind = EVENT_KIND.get(str(event_type or ""))
    sym = str(symbol or "").strip().upper()
    if not kind or not sym or not event_id:
        return None
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    wid = semantic_wake_id(kind=kind, symbol=sym, source_id=str(event_id))
    if wid in (_load_seen(root).get("seen") or {}):
        return {"schema": SCHEMA, "duplicate": True, "wake_id": wid, "action": "SUPPRESS",
                "reason": "semantic_dedupe", "authority": AUTHORITY}
    return {
        "schema": SCHEMA,
        "duplicate": False,
        "wake_id": wid,
        "symbol": sym,
        "kind": kind,
        "cio_event_type": event_type,
        "actions_allowed": ["coverage_check", "materiality_check", "rag_check"],
        "actions_forbidden": ["auto_thesis_version", "auto_ADD", "auto_RE_ENTER", "paid_deep_research"],
        "source_event_id": str(event_id),
        "membership_is_not_evidence": True,
        "emit": False,
        "authority": AUTHORITY,
        "as_of": _now(),
    }


def _events_by_id(path: Path, wanted: set[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    if not wanted or not path.is_file():
        return found
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not any(w in line for w in wanted):
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            eid = str(ev.get("event_id") or "")
            if eid in wanted:
                found[eid] = ev
                if len(found) == len(wanted):
                    break
    return found


def _append_receipts(path: Path, rows: list[dict[str, Any]]) -> None:
    import fcntl
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def consume_dispatched_wakes(
    dispatched: list[dict[str, Any]] | None,
    *,
    root: Path | str | None = None,
    env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Consume EVENT_BUS wakes the CIO dispatcher just dispatched. Fail-soft; SHADOW by default."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    mode = wake_mode(env)
    summary = {"schema": RECEIPT_SCHEMA, "mode": mode, "considered": 0, "planned": 0,
               "duplicates": 0, "unmapped": 0, "checks_run": 0, "receipts": 0}
    try:
        wakes = [
            w for w in (dispatched or [])
            if isinstance(w, dict) and (
                str(w.get("trigger_type") or "") == "EVENT_BUS"
                or str(w.get("trigger_ref") or "").startswith("evt-")
            ) and str(w.get("trigger_ref") or "")
        ]
        summary["considered"] = len(wakes)
        if not wakes:
            return summary
        events = _events_by_id(root / EVENTS_RELATIVE, {str(w["trigger_ref"]) for w in wakes})
        receipts: list[dict[str, Any]] = []
        for w in wakes:
            eid = str(w["trigger_ref"])
            ev = events.get(eid) or {}
            etype = str(ev.get("event_type") or "")
            symbol = str((ev.get("payload") or {}).get("symbol") or "")
            plan = plan_wake_for_event(event_type=etype, symbol=symbol, event_id=eid, root=root)
            receipt = {
                "schema": RECEIPT_SCHEMA, "mode": mode, "wake_job_id": w.get("wake_job_id"),
                "run_id": w.get("run_id"), "event_id": eid, "event_type": etype or None,
                "symbol": symbol.upper() or None, "authority": AUTHORITY, "as_of": _now(),
                "checks_run": False, "emitted": False, "thesis_version_published": False,
            }
            if plan is None:
                summary["unmapped"] += 1
                receipt["action"] = "NOT_A_THESIS_WAKE_EVENT"
            elif plan.get("duplicate"):
                summary["duplicates"] += 1
                receipt.update({"action": "SUPPRESS_DUPLICATE", "wake_id": plan.get("wake_id")})
            else:
                summary["planned"] += 1
                receipt.update({"action": "SHADOW_PLANNED" if mode == "shadow" else "CHECKS_RUN",
                                "wake_id": plan.get("wake_id"), "kind": plan.get("kind")})
                if mode == "active":
                    checks = execute_wake_checks(plan["symbol"], root=root, wake_plan=plan, persist_dedupe=True)
                    receipt["checks_run"] = True
                    receipt["checks"] = checks.get("checks")
                    summary["checks_run"] += 1
            receipts.append(receipt)
        _append_receipts(root / RECEIPTS_RELATIVE, receipts)
        summary["receipts"] = len(receipts)
    except Exception as exc:  # noqa: BLE001 — never fails the dispatch cycle
        summary["error"] = f"{type(exc).__name__}"
    return summary
