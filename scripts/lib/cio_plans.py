"""CIO Action Plan store — durable JSONL beside goals/action ledger.

READ_ONLY_ADVISORY. No broker/order/stop/2FA authority.

Storage:
  data/cio/cio_plans.jsonl            — append-only events
  data/cio/cio_plans_projection.json  — rebuildable snapshot
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_EVENT_PATH = Path("data/cio/cio_plans.jsonl")
DEFAULT_PROJECTION_PATH = Path("data/cio/cio_plans_projection.json")

DETECTOR_VERSION_DEFAULT = "situation-catalog-v1.0.0"

VALID_STATUSES = frozenset({
    "draft", "proposed", "accepted", "superseded", "cancelled",
})
OPENISH = frozenset({"draft", "proposed", "accepted"})

VALID_SITUATION_TYPES = frozenset({
    "S1_POSITION_LIFECYCLE",
    "S2_STOP_GAP",
    "S3_REENTRY_CANDIDATE",
    "S4_SECTOR_ROTATION",
    "S5_CASH_DEPLOYMENT",
    "S6_CONCENTRATION_OR_DISPOSITION",
    "S7_WATCH_PROMOTION",
    "S8_DEFENSIVE_REGIME",
    "S0_OPERATOR_CONVERSE",  # Telegram CIO free-text continuity plans
})

VALID_EVENT_TYPES = frozenset({
    "PLAN_CREATED",
    "PLAN_UPDATED",
    "PLAN_STATUS_CHANGED",
    "PLAN_SUPERSEDED",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_id() -> str:
    return f"plan_{uuid.uuid4().hex[:12]}"


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def validate_plan_payload(p: dict[str, Any], *, partial: bool = False) -> list[str]:
    """Return list of validation errors (empty = ok)."""
    errs: list[str] = []
    if not partial:
        for req in ("plan_id", "situation_type", "symbols", "status", "title",
                    "options", "recommendation", "evidence_refs", "revisit_at",
                    "owner_agent", "authority"):
            if req not in p:
                errs.append(f"missing:{req}")
    st = p.get("situation_type")
    if st is not None and st not in VALID_SITUATION_TYPES:
        errs.append(f"invalid_situation_type:{st}")
    status = p.get("status")
    if status is not None and status not in VALID_STATUSES:
        errs.append(f"invalid_status:{status}")
    if p.get("authority") not in (None, "READ_ONLY_ADVISORY"):
        errs.append("authority_must_be_READ_ONLY_ADVISORY")
    opts = p.get("options")
    if opts is not None:
        if not isinstance(opts, list) or not opts:
            errs.append("options_must_be_nonempty_list")
        else:
            for i, o in enumerate(opts):
                if not isinstance(o, dict) or "id" not in o or "label" not in o:
                    errs.append(f"option[{i}]_missing_id_or_label")
    refs = p.get("evidence_refs")
    if refs is not None:
        if not isinstance(refs, list):
            errs.append("evidence_refs_must_be_list")
        else:
            for i, r in enumerate(refs):
                if not isinstance(r, dict) or "domain" not in r:
                    errs.append(f"evidence_refs[{i}]_missing_domain")
    return errs


class CIOPlanStore:
    """First-class action plan store."""

    def __init__(
        self,
        event_path: Path | str = DEFAULT_EVENT_PATH,
        projection_path: Path | str = DEFAULT_PROJECTION_PATH,
    ):
        self.event_path = Path(event_path)
        self.projection_path = Path(projection_path)
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        self._plans: dict[str, dict[str, Any]] = {}
        self._load_or_rebuild()

    def _load_or_rebuild(self) -> None:
        if self.projection_path.exists():
            try:
                data = json.loads(self.projection_path.read_text())
                plans = data.get("plans") or {}
                if isinstance(plans, dict):
                    self._plans = plans
                    return
            except Exception:
                pass
        self.rebuild_projection()

    def rebuild_projection(self) -> dict[str, Any]:
        plans: dict[str, dict[str, Any]] = {}
        if self.event_path.exists():
            with open(self.event_path, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._apply_event(plans, ev)
        self._plans = plans
        self._write_projection()
        return {"plan_count": len(plans)}

    def _write_projection(self) -> None:
        payload = {
            "updated_ts": _now(),
            "plan_count": len(self._plans),
            "plans": self._plans,
        }
        tmp = self.projection_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
        os.replace(tmp, self.projection_path)

    def _append_event(
        self, event_type: str, plan_id: str, payload: dict[str, Any], actor_id: str,
    ) -> dict[str, Any]:
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"invalid event_type: {event_type}")
        envelope = {
            "event_id": f"{int(time.time() * 1_000_000):020d}-{uuid.uuid4().hex[:8]}",
            "event_type": event_type,
            "plan_id": plan_id,
            "occurred_at": _now(),
            "actor_id": actor_id,
            "authority": "READ_ONLY_ADVISORY",
            "payload": payload,
        }
        lock = _lock_path(self.event_path)
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                with open(self.event_path, "a") as fh:
                    fh.write(json.dumps(envelope, sort_keys=True, default=str) + "\n")
                    fh.flush()
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        self._apply_event(self._plans, envelope)
        self._write_projection()
        return envelope

    def _apply_event(self, plans: dict[str, dict[str, Any]], ev: dict[str, Any]) -> None:
        et = ev.get("event_type")
        pid = ev.get("plan_id")
        if not pid:
            return
        p = ev.get("payload") or {}
        if et == "PLAN_CREATED":
            plans[pid] = dict(p)
            plans[pid]["plan_id"] = pid
            return
        g = plans.get(pid)
        if g is None:
            return
        if et == "PLAN_UPDATED":
            for k, v in p.items():
                if k in ("plan_id", "created_ts", "version"):
                    continue
                g[k] = v
            g["version"] = int(g.get("version") or 1) + 1
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
        elif et == "PLAN_STATUS_CHANGED":
            g["status"] = p.get("status", g.get("status"))
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            g["version"] = int(g.get("version") or 1) + 1
            if p.get("reason"):
                g["status_reason"] = p["reason"]
        elif et == "PLAN_SUPERSEDED":
            g["status"] = "superseded"
            g["superseded_by"] = p.get("superseded_by")
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            g["version"] = int(g.get("version") or 1) + 1

    # ── Public API ───────────────────────────────────────────────────────

    def create_plan(
        self,
        *,
        situation_type: str,
        symbols: list[str],
        title: str,
        summary: str = "",
        options: list[dict[str, Any]],
        recommendation: str,
        risks: Optional[list[str]] = None,
        evidence_refs: Optional[list[dict[str, Any]]] = None,
        linked_goal_ids: Optional[list[str]] = None,
        linked_action_ids: Optional[list[str]] = None,
        revisit_at: str,
        owner_agent: str,
        cc_deep_links: Optional[list[str]] = None,
        status: str = "draft",
        detector_version: str = DETECTOR_VERSION_DEFAULT,
        actor_id: str = "cio_situation_detector",
        plan_id: Optional[str] = None,
        thesis_version: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if situation_type not in VALID_SITUATION_TYPES:
            raise ValueError(f"invalid situation_type: {situation_type}")
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        pid = plan_id or _plan_id()
        ts = _now()
        # P3: pin current desk thesis when not provided (fail-soft)
        pin = thesis_version
        if not pin:
            try:
                from scripts.lib.cio_theses import safe_current_pin
                pin = safe_current_pin("desk")
            except Exception:
                try:
                    from lib.cio_theses import safe_current_pin  # type: ignore
                    pin = safe_current_pin("desk")
                except Exception:
                    pin = None
        payload: dict[str, Any] = {
            "plan_id": pid,
            "situation_type": situation_type,
            "symbols": [str(s).upper() for s in (symbols or [])],
            "status": status,
            "title": title,
            "summary": summary or "",
            "options": list(options or []),
            "recommendation": recommendation,
            "risks": list(risks or []),
            "evidence_refs": list(evidence_refs or []),
            "linked_goal_ids": list(linked_goal_ids or []),
            "linked_action_ids": list(linked_action_ids or []),
            "revisit_at": revisit_at,
            "owner_agent": owner_agent.strip().lower(),
            "cc_deep_links": list(cc_deep_links or []),
            "version": 1,
            "created_ts": ts,
            "updated_ts": ts,
            "detector_version": detector_version,
            "authority": "READ_ONLY_ADVISORY",
            "thesis_version": pin,
        }
        if extra:
            for k, v in extra.items():
                if k not in payload:
                    payload[k] = v
        errs = validate_plan_payload(payload)
        if errs:
            raise ValueError(f"plan validation failed: {errs}")
        self._append_event("PLAN_CREATED", pid, payload, actor_id=actor_id)
        return dict(self._plans[pid])

    def update_plan(
        self,
        plan_id: str,
        *,
        actor_id: str = "cio_plans",
        **fields: Any,
    ) -> dict[str, Any]:
        if plan_id not in self._plans:
            raise KeyError(f"unknown plan_id: {plan_id}")
        allowed = {
            "title", "summary", "options", "recommendation", "risks",
            "evidence_refs", "linked_goal_ids", "linked_action_ids",
            "revisit_at", "owner_agent", "cc_deep_links", "status",
            "narrative_source", "narrative_enriched_at", "evidence_hash",
            "llm_model", "llm_status", "llm_deferred", "fire_reasons",
            "thesis_version",
        }
        patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "status" in patch and patch["status"] not in VALID_STATUSES:
            raise ValueError(f"invalid status: {patch['status']}")
        patch["updated_ts"] = _now()
        merged = dict(self._plans[plan_id])
        merged.update(patch)
        errs = validate_plan_payload(merged, partial=False)
        if errs:
            raise ValueError(f"plan validation failed: {errs}")
        if "status" in patch and patch["status"] != self._plans[plan_id].get("status"):
            self._append_event(
                "PLAN_STATUS_CHANGED", plan_id,
                {"status": patch["status"], "updated_ts": patch["updated_ts"]},
                actor_id=actor_id,
            )
            # still apply other fields
            other = {k: v for k, v in patch.items() if k not in ("status",)}
            if other:
                self._append_event("PLAN_UPDATED", plan_id, other, actor_id=actor_id)
        else:
            self._append_event("PLAN_UPDATED", plan_id, patch, actor_id=actor_id)
        return dict(self._plans[plan_id])

    def get_plan(self, plan_id: str) -> Optional[dict[str, Any]]:
        p = self._plans.get(plan_id)
        return dict(p) if p else None

    def list_open_plans(
        self,
        *,
        situation_type: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = [dict(p) for p in self._plans.values() if p.get("status") in OPENISH]
        if situation_type:
            rows = [p for p in rows if p.get("situation_type") == situation_type]
        if symbol:
            sym = symbol.upper()
            rows = [p for p in rows if sym in (p.get("symbols") or [])]
        rows.sort(key=lambda p: p.get("created_ts") or "", reverse=True)
        return rows[:limit]

    def supersede_plan(
        self,
        plan_id: str,
        *,
        superseded_by: str = "",
        reason: str = "",
        actor_id: str = "cio_plans",
    ) -> dict[str, Any]:
        if plan_id not in self._plans:
            raise KeyError(f"unknown plan_id: {plan_id}")
        self._append_event(
            "PLAN_SUPERSEDED",
            plan_id,
            {
                "superseded_by": superseded_by,
                "reason": reason,
                "updated_ts": _now(),
            },
            actor_id=actor_id,
        )
        return dict(self._plans[plan_id])

    def find_recent_dedup(
        self,
        situation_type: str,
        symbols: list[str],
        *,
        within_hours: float = 6.0,
    ) -> Optional[dict[str, Any]]:
        """Return open plan matching type+symbol within window, if any."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=within_hours)
        syms = {s.upper() for s in symbols}
        for p in self.list_open_plans(situation_type=situation_type, limit=200):
            psyms = {s.upper() for s in (p.get("symbols") or [])}
            if not (psyms & syms) and syms:
                continue
            if not syms and psyms:
                # portfolio-level situations (S5/S8) — match type only
                pass
            ts = p.get("created_ts") or p.get("updated_ts")
            if not ts:
                return dict(p)
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    return dict(p)
            except Exception:
                return dict(p)
        return None
