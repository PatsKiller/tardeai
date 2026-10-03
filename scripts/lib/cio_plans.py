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
    "draft", "proposed", "accepted", "superseded", "cancelled", "expired",
})
# Draft/proposed plans the expiry sweep may close (accepted plans are the operator's).
EXPIRABLE = frozenset({"draft", "proposed"})
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
        # Byte offset of the event log the in-memory plans reflect. Every writer
        # used to rewrite the whole projection from its own in-memory copy, so a
        # concurrent writer silently undid another's changes (2026-10-03: 52
        # plans cancelled in the log still read draft, 7 created plans missing).
        # The log is the truth; the projection now records how far it got and
        # every load/write first catches up from there.
        # None = loaded from a pre-offset projection; the first write migrates it.
        self._offset: Optional[int] = 0
        self._load_or_rebuild()

    def _event_size(self) -> int:
        try:
            return self.event_path.stat().st_size
        except OSError:
            return 0

    def _load_projection(self) -> bool:
        if not self.projection_path.exists():
            return False
        try:
            data = json.loads(self.projection_path.read_text())
        except Exception:
            return False
        plans = data.get("plans") or {}
        if not isinstance(plans, dict):
            return False
        offset = data.get("event_offset")
        self._plans = plans
        if isinstance(offset, int) and 0 <= offset <= self._event_size():
            self._offset = offset
            self._catch_up()
        else:
            # Pre-offset projection: serve it as-is (reads stay read-only); the
            # first locked write rebuilds from the log and records the offset.
            self._offset = None
        return True

    def _load_or_rebuild(self) -> None:
        if self._load_projection():
            return
        # One rebuild at a time: a projection without an offset (pre-2026-10-03)
        # is rebuilt once under the event lock; concurrent loaders wait and then
        # read the rebuilt projection instead of each replaying the full log.
        lock = _lock_path(self.event_path)
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if not self._load_projection():
                    self.rebuild_projection()
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def _catch_up(self) -> int:
        """Apply events appended to the log since ``self._offset``. Returns how many."""
        if self._offset is None:
            return 0
        size = self._event_size()
        if size < self._offset:
            # The log shrank (rotated/restored): the offset is meaningless.
            self._plans, self._offset = {}, 0
        if size == self._offset:
            return 0
        n = 0
        with open(self.event_path, "rb") as fh:
            fh.seek(self._offset)
            chunk = fh.read()
        # Only consume complete lines; a writer may be mid-append.
        end = chunk.rfind(b"\n") + 1
        for raw in chunk[:end].splitlines():
            if not raw.strip():
                continue
            try:
                ev = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            self._apply_event(self._plans, ev)
            n += 1
        self._offset += end
        return n

    def _replay_log(self) -> None:
        self._plans, self._offset = {}, 0
        self._catch_up()

    def refresh_from_log(self) -> bool:
        """Read-only: replace a pre-offset projection's view with the log's. True if replayed."""
        if self._offset is not None:
            return False
        self._replay_log()
        return True

    def rebuild_projection(self) -> dict[str, Any]:
        self._replay_log()
        self._write_projection()
        return {"plan_count": len(self._plans)}

    def _write_projection(self) -> None:
        payload = {
            "updated_ts": _now(),
            "plan_count": len(self._plans),
            "event_offset": self._offset,
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
        self._locked_append([envelope])
        return envelope

    def _locked_append(self, envelopes: Any) -> list[dict[str, Any]]:
        """Catch up, append, apply and persist the projection under one lock.

        ``envelopes`` may be a callable: it is evaluated after the catch-up, so a
        decision that depends on current state (e.g. "still draft?") sees the
        latest log, not a stale in-memory copy.
        """
        lock = _lock_path(self.event_path)
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if self._offset is None:
                    self._replay_log()
                self._catch_up()
                if callable(envelopes):
                    envelopes = envelopes()
                if not envelopes:
                    return []
                with open(self.event_path, "a") as fh:
                    for env in envelopes:
                        fh.write(json.dumps(env, sort_keys=True, default=str) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                for env in envelopes:
                    self._apply_event(self._plans, env)
                self._offset = self._event_size()
                self._write_projection()
                return list(envelopes)
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

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
        # Always pin LIVE desk@vN (safe_current_pin). Stale caller pins are ignored.
        pin = None
        try:
            from scripts.lib.cio_theses import safe_current_pin
            pin = safe_current_pin("desk")
        except Exception:
            try:
                from lib.cio_theses import safe_current_pin  # type: ignore
                pin = safe_current_pin("desk")
            except Exception:
                pin = thesis_version  # last resort only
        if not pin:
            pin = thesis_version
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
            "thesis_version", "thesis_alignment", "multi_domain_summary",
            "material", "evidence_domains", "hermes_suggested", "hermes_challenge_id",
            "hermes_research_id", "hermes_result_id", "research_id",
            "hermes_completed_ts", "completed_ts",
            "status_reason",
            "prompt_version", "prompt_content_hash", "prompt_alias",
            "eval_structural_score", "eval_quality_total", "eval_judge_total", "eval_judge_scores", "judge_prompt_version", "judge_scored_ts",
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

    def expire_plans(
        self,
        items: list[tuple[str, str]],
        *,
        actor_id: str = "cio_plan_expiry",
        recheck: Any = None,
    ) -> list[str]:
        """Append one PLAN_STATUS_CHANGED -> expired per (plan_id, reason).

        Batched: every event is written under one lock and the (tens of MB)
        projection is rewritten once, not once per plan. Only draft/proposed
        plans are expired; anything else is skipped. Append-only. ``recheck``,
        if given, is called with the plan's CURRENT state (after catching up on
        the log, under the lock) and must return the reason to use, or None to
        leave the plan open.
        """
        def build() -> list[dict[str, Any]]:
            now = _now()
            out: list[dict[str, Any]] = []
            for plan_id, reason in items:
                cur = self._plans.get(plan_id)
                if not cur or cur.get("status") not in EXPIRABLE:
                    continue
                if recheck is not None:
                    reason = recheck(dict(cur))
                    if not reason:
                        continue
                out.append({
                    "event_id": f"{int(time.time() * 1_000_000):020d}-{uuid.uuid4().hex[:8]}",
                    "event_type": "PLAN_STATUS_CHANGED",
                    "plan_id": plan_id,
                    "occurred_at": now,
                    "actor_id": actor_id,
                    "authority": "READ_ONLY_ADVISORY",
                    "payload": {"status": "expired", "reason": reason, "updated_ts": now},
                })
            return out

        return [env["plan_id"] for env in self._locked_append(build)]

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
