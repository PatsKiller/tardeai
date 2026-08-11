"""CIO Goal + Thesis store — durable JSONL beside action/wake ledgers.

READ_ONLY_ADVISORY. No broker/order/risk/secret authority.

Storage (append-only event log + rebuildable projection):
  data/cio/cio_goals.jsonl          — immutable events
  data/cio/cio_goals_projection.json — rebuildable snapshot

Statuses: open | blocked | achieved | cancelled | superseded
Owners: alex | morgan | steph | hermes (and other roster ids allowed)
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_GOALS_PATH = Path("data/cio/cio_goals.jsonl")
DEFAULT_PROJECTION_PATH = Path("data/cio/cio_goals_projection.json")
DEFAULT_EVENT_CURSOR_PATH = Path("data/cio/cio_goal_event_cursors.json")

VALID_STATUSES = frozenset({"open", "blocked", "achieved", "cancelled", "superseded"})
OPENISH = frozenset({"open", "blocked"})
VALID_OWNERS = frozenset({
    "alex", "morgan", "steph", "hermes", "maria", "guardian", "ledger",
    "sentinel", "darwin", "iris", "reflection",
})

VALID_EVENT_TYPES = frozenset({
    "GOAL_CREATED",
    "GOAL_UPDATED",
    "GOAL_STATUS_CHANGED",
    "GOAL_THESIS_UPDATED",
    "GOAL_WAKE_RECORDED",
    "GOAL_LINKED",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _goal_id() -> str:
    return f"goal_{uuid.uuid4().hex[:12]}"


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


class CIOGoalStore:
    """Durable goal + thesis store with rebuildable projection."""

    def __init__(
        self,
        event_path: Path | str = DEFAULT_GOALS_PATH,
        projection_path: Path | str = DEFAULT_PROJECTION_PATH,
        cursor_path: Path | str = DEFAULT_EVENT_CURSOR_PATH,
    ):
        self.event_path = Path(event_path)
        self.projection_path = Path(projection_path)
        self.cursor_path = Path(cursor_path)
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        self._goals: dict[str, dict[str, Any]] = {}
        self._load_or_rebuild()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_or_rebuild(self) -> None:
        if self.projection_path.exists():
            try:
                data = json.loads(self.projection_path.read_text())
                goals = data.get("goals") or {}
                if isinstance(goals, dict):
                    self._goals = goals
                    return
            except Exception:
                pass
        self.rebuild_projection()

    def rebuild_projection(self) -> dict[str, Any]:
        goals: dict[str, dict[str, Any]] = {}
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
                    self._apply_event(goals, ev)
        self._goals = goals
        self._write_projection()
        return {"goal_count": len(goals)}

    def _write_projection(self) -> None:
        payload = {
            "updated_ts": _now(),
            "goal_count": len(self._goals),
            "goals": self._goals,
        }
        tmp = self.projection_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, self.projection_path)

    def _append_event(self, event_type: str, goal_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"invalid event_type: {event_type}")
        envelope = {
            "event_id": f"{int(time.time() * 1_000_000):020d}-{uuid.uuid4().hex[:8]}",
            "event_type": event_type,
            "goal_id": goal_id,
            "occurred_at": _now(),
            "actor_id": actor_id,
            "actor_type": "system" if actor_id.startswith("cio_") or actor_id.endswith("_worker") else "agent",
            "authority": "READ_ONLY_ADVISORY",
            "payload": payload,
        }
        lock = _lock_path(self.event_path)
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                with open(self.event_path, "a") as fh:
                    fh.write(json.dumps(envelope, sort_keys=True) + "\n")
                    fh.flush()
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        self._apply_event(self._goals, envelope)
        self._write_projection()
        return envelope

    def _apply_event(self, goals: dict[str, dict[str, Any]], ev: dict[str, Any]) -> None:
        et = ev.get("event_type")
        gid = ev.get("goal_id")
        if not gid:
            return
        p = ev.get("payload") or {}
        if et == "GOAL_CREATED":
            goals[gid] = dict(p)
            goals[gid]["goal_id"] = gid
            return
        g = goals.get(gid)
        if g is None:
            # orphan update — ignore fail-closed for projection
            return
        if et == "GOAL_UPDATED":
            for k, v in p.items():
                if k in ("goal_id", "created_ts"):
                    continue
                g[k] = v
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
        elif et == "GOAL_STATUS_CHANGED":
            g["status"] = p.get("status", g.get("status"))
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            if p.get("reason"):
                g["status_reason"] = p["reason"]
        elif et == "GOAL_THESIS_UPDATED":
            g["thesis_summary"] = p.get("thesis_summary", g.get("thesis_summary", ""))
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            hist = list(g.get("thesis_history") or [])
            hist.append({
                "ts": g["updated_ts"],
                "thesis_summary": g["thesis_summary"],
                "agent_id": p.get("agent_id"),
            })
            g["thesis_history"] = hist[-20:]
        elif et == "GOAL_WAKE_RECORDED":
            g["last_wake_ts"] = p.get("last_wake_ts") or ev.get("occurred_at")
            g["wake_count"] = int(g.get("wake_count") or 0) + 1
            g["last_outcome"] = p.get("outcome", g.get("last_outcome"))
            g["updated_ts"] = g["last_wake_ts"]
        elif et == "GOAL_LINKED":
            for field in ("linked_event_types", "linked_symbols", "linked_action_ids"):
                if field in p and isinstance(p[field], list):
                    existing = list(g.get(field) or [])
                    for item in p[field]:
                        if item not in existing:
                            existing.append(item)
                    g[field] = existing
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()

    # ── Public API ───────────────────────────────────────────────────────

    def create_goal(
        self,
        *,
        owner_agent: str,
        title: str,
        description: str = "",
        priority: str = "NORMAL",
        success_criteria: str = "",
        linked_event_types: Optional[list[str]] = None,
        linked_symbols: Optional[list[str]] = None,
        linked_action_ids: Optional[list[str]] = None,
        thesis_summary: str = "",
        due_ts: Optional[str] = None,
        actor_id: str = "cio_goals",
        goal_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_agent.strip().lower()
        if owner not in VALID_OWNERS:
            raise ValueError(f"invalid owner_agent: {owner_agent}")
        if not title or not title.strip():
            raise ValueError("title required")
        gid = goal_id or _goal_id()
        ts = _now()
        payload = {
            "goal_id": gid,
            "owner_agent": owner,
            "title": title.strip(),
            "description": description or "",
            "status": "open",
            "priority": (priority or "NORMAL").upper(),
            "created_ts": ts,
            "updated_ts": ts,
            "due_ts": due_ts,
            "success_criteria": success_criteria or "",
            "linked_event_types": list(linked_event_types or []),
            "linked_symbols": [s.upper() for s in (linked_symbols or [])],
            "linked_action_ids": list(linked_action_ids or []),
            "thesis_summary": thesis_summary or "",
            "last_wake_ts": None,
            "wake_count": 0,
            "last_outcome": None,
            "thesis_history": [],
        }
        self._append_event("GOAL_CREATED", gid, payload, actor_id=actor_id)
        return dict(self._goals[gid])

    def update_goal(
        self,
        goal_id: str,
        *,
        actor_id: str = "cio_goals",
        **fields: Any,
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        allowed = {
            "title", "description", "priority", "success_criteria", "due_ts",
            "linked_event_types", "linked_symbols", "linked_action_ids", "owner_agent",
        }
        patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "owner_agent" in patch:
            patch["owner_agent"] = str(patch["owner_agent"]).strip().lower()
            if patch["owner_agent"] not in VALID_OWNERS:
                raise ValueError(f"invalid owner_agent: {patch['owner_agent']}")
        if "linked_symbols" in patch and isinstance(patch["linked_symbols"], list):
            patch["linked_symbols"] = [str(s).upper() for s in patch["linked_symbols"]]
        patch["updated_ts"] = _now()
        self._append_event("GOAL_UPDATED", goal_id, patch, actor_id=actor_id)
        return dict(self._goals[goal_id])

    def close_goal(
        self,
        goal_id: str,
        *,
        status: str = "achieved",
        reason: str = "",
        actor_id: str = "cio_goals",
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        status = status.lower()
        if status not in VALID_STATUSES - {"open"}:
            raise ValueError(f"close status must be terminal-ish, got {status}")
        self._append_event(
            "GOAL_STATUS_CHANGED",
            goal_id,
            {"status": status, "reason": reason, "updated_ts": _now()},
            actor_id=actor_id,
        )
        return dict(self._goals[goal_id])

    def set_status(
        self,
        goal_id: str,
        status: str,
        *,
        reason: str = "",
        actor_id: str = "cio_goals",
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        status = status.lower()
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        self._append_event(
            "GOAL_STATUS_CHANGED",
            goal_id,
            {"status": status, "reason": reason, "updated_ts": _now()},
            actor_id=actor_id,
        )
        return dict(self._goals[goal_id])

    def update_thesis(
        self,
        goal_id: str,
        thesis_summary: str,
        *,
        agent_id: str = "",
        actor_id: str = "cio_goals",
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        self._append_event(
            "GOAL_THESIS_UPDATED",
            goal_id,
            {
                "thesis_summary": thesis_summary,
                "agent_id": agent_id,
                "updated_ts": _now(),
            },
            actor_id=actor_id or agent_id or "cio_goals",
        )
        return dict(self._goals[goal_id])

    def record_wake(
        self,
        goal_id: str,
        *,
        agent_id: str = "",
        outcome: str = "",
        actor_id: str = "cio_wake_dispatcher",
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        self._append_event(
            "GOAL_WAKE_RECORDED",
            goal_id,
            {
                "last_wake_ts": _now(),
                "outcome": outcome,
                "agent_id": agent_id,
            },
            actor_id=actor_id,
        )
        return dict(self._goals[goal_id])

    def list_open_goals(
        self,
        *,
        owner_agent: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = [
            dict(g) for g in self._goals.values()
            if g.get("status") in OPENISH
        ]
        if owner_agent:
            owner = owner_agent.strip().lower()
            rows = [g for g in rows if g.get("owner_agent") == owner]
        rows.sort(key=lambda g: (g.get("priority") != "HIGH", g.get("due_ts") or "9999", g.get("created_ts") or ""))
        return rows[:limit]

    def get_goal(self, goal_id: str) -> Optional[dict[str, Any]]:
        g = self._goals.get(goal_id)
        return dict(g) if g else None

    def list_due_or_idle_goals(
        self,
        *,
        owner_agent: Optional[str] = None,
        limit: int = 10,
        idle_hours: float = 24.0,
    ) -> list[dict[str, Any]]:
        """Goals that are due (due_ts <= now) OR never woken OR idle past idle_hours."""
        now = datetime.now(timezone.utc)
        out: list[dict[str, Any]] = []
        for g in self.list_open_goals(owner_agent=owner_agent, limit=200):
            due = g.get("due_ts")
            last_wake = g.get("last_wake_ts")
            reason = None
            if due:
                try:
                    due_dt = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                    if due_dt.tzinfo is None:
                        due_dt = due_dt.replace(tzinfo=timezone.utc)
                    if due_dt <= now:
                        reason = "due"
                except Exception:
                    pass
            if reason is None and not last_wake:
                reason = "never_woken"
            if reason is None and last_wake:
                try:
                    lw = datetime.fromisoformat(str(last_wake).replace("Z", "+00:00"))
                    if lw.tzinfo is None:
                        lw = lw.replace(tzinfo=timezone.utc)
                    age_h = (now - lw).total_seconds() / 3600.0
                    if age_h >= idle_hours:
                        reason = "idle"
                except Exception:
                    pass
            if reason:
                row = dict(g)
                row["_wake_reason"] = reason
                out.append(row)
            if len(out) >= limit:
                break
        return out

    def goals_for_event_types(self, event_types: list[str], *, limit: int = 20) -> list[dict[str, Any]]:
        et_set = {e.upper() for e in event_types}
        out = []
        for g in self.list_open_goals(limit=200):
            linked = {str(x).upper() for x in (g.get("linked_event_types") or [])}
            if linked & et_set:
                out.append(dict(g))
            if len(out) >= limit:
                break
        return out

    def get_context_for_agent(self, agent_id: str, *, limit_goals: int = 10, limit_events: int = 20) -> dict[str, Any]:
        """Assemble agent context: open goals + thesis + recent goal events + open actions."""
        agent = agent_id.strip().lower()
        open_goals = self.list_open_goals(owner_agent=agent, limit=limit_goals)
        thesis_snippets = [
            {
                "goal_id": g.get("goal_id"),
                "title": g.get("title"),
                "thesis_summary": g.get("thesis_summary") or "",
                "status": g.get("status"),
            }
            for g in open_goals
            if g.get("thesis_summary")
        ]

        # Recent goal events for this owner
        recent_events: list[dict[str, Any]] = []
        if self.event_path.exists():
            try:
                lines = self.event_path.read_text().splitlines()
                for line in reversed(lines[-500:]):
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    gid = ev.get("goal_id")
                    g = self._goals.get(gid or "")
                    if g and g.get("owner_agent") == agent:
                        recent_events.append(ev)
                    if len(recent_events) >= limit_events:
                        break
                recent_events.reverse()
            except Exception:
                pass

        open_actions: list[dict[str, Any]] = []
        try:
            from scripts.lib.cio_action_ledger import CIOActionLedger
            ledger = CIOActionLedger()
            # best-effort list open actions
            if hasattr(ledger, "list_actions"):
                open_actions = ledger.list_actions(status="OPEN", limit=15)  # type: ignore
            elif hasattr(ledger, "project_open_actions"):
                open_actions = ledger.project_open_actions(limit=15)  # type: ignore
        except Exception:
            open_actions = []

        # Recent material events from CIO event bus (fail-open if missing)
        bus_events: list[dict[str, Any]] = []
        try:
            from scripts.lib.cio_event_bus import CIOEventBus, AGENT_EVENT_ROUTING
            bus = CIOEventBus()
            types = list(AGENT_EVENT_ROUTING.get(agent, frozenset()))
            polled = bus.poll(consumer=f"context:{agent}", event_types=types or None, limit=limit_events)
            for ev in polled:
                if hasattr(ev, "__dict__"):
                    bus_events.append({
                        "event_id": getattr(ev, "event_id", None),
                        "event_type": getattr(ev, "event_type", None),
                        "payload": getattr(ev, "payload", None),
                        "occurred_at": getattr(ev, "occurred_at", None),
                    })
                elif isinstance(ev, dict):
                    bus_events.append(ev)
            # Do NOT advance cursor here — context reads are non-destructive
        except Exception:
            bus_events = []

        return {
            "agent_id": agent,
            "as_of": _now(),
            "authority": "READ_ONLY_ADVISORY",
            "open_goals": open_goals,
            "thesis_snippets": thesis_snippets,
            "recent_goal_events": recent_events,
            "recent_bus_events": bus_events[:limit_events],
            "open_actions": open_actions[:15],
        }

    # ── Event-bus cursor helpers (per-consumer) ──────────────────────────

    def load_cursor(self, consumer_id: str) -> str:
        if not self.cursor_path.exists():
            return ""
        try:
            data = json.loads(self.cursor_path.read_text())
            return str((data.get("cursors") or {}).get(consumer_id) or "")
        except Exception:
            return ""

    def save_cursor(self, consumer_id: str, event_id: str) -> None:
        data: dict[str, Any] = {"cursors": {}}
        if self.cursor_path.exists():
            try:
                data = json.loads(self.cursor_path.read_text())
            except Exception:
                data = {"cursors": {}}
        data.setdefault("cursors", {})[consumer_id] = event_id
        data["updated_ts"] = _now()
        tmp = self.cursor_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, self.cursor_path)

    def dedup_key(self, agent_id: str, goal_id: str, window_bucket: str) -> str:
        raw = f"{agent_id}:{goal_id}:{window_bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
