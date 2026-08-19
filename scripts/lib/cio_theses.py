"""CIO versioned Thesis store (Phase P3) — append-only JSONL + projection.

READ_ONLY_ADVISORY. Desk living thesis and optional theme/symbol theses,
each with monotonic versions operators can pin on plans/wakes/traces.

Storage:
  data/cio/cio_theses.jsonl           — immutable events
  data/cio/cio_theses_projection.json — rebuildable snapshot

Canonical pin: ``{thesis_id}@v{version}`` e.g. ``desk@v3``
Default thesis_id: ``desk`` (platform living thesis).

Distinct from per-goal ``thesis_summary`` snippets in CIOGoalStore.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_EVENT_PATH = Path("data/cio/cio_theses.jsonl")
DEFAULT_PROJECTION_PATH = Path("data/cio/cio_theses_projection.json")

DEFAULT_THESIS_ID = "desk"

VALID_STATUSES = frozenset({"active", "superseded", "archived"})
VALID_OWNERS = frozenset({
    "alex", "morgan", "steph", "hermes", "maria", "guardian", "ledger",
    "sentinel", "darwin", "iris", "reflection", "operator", "system",
})

VALID_EVENT_TYPES = frozenset({
    "THESIS_CREATED",
    "THESIS_VERSION_PUBLISHED",
    "THESIS_STATUS_CHANGED",
    "THESIS_LINKED",
    "THESIS_LEARNING_APPENDED",
})

# Operator disposition learning (durable, append-only; not a thesis version rewrite)
DEFAULT_LEARNING_PATH = Path("data/cio/cio_operator_learning.jsonl")

PIN_RE = re.compile(r"^([a-z][a-z0-9_\-]*)@v(\d+)$", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def make_pin(thesis_id: str, version: int) -> str:
    tid = (thesis_id or DEFAULT_THESIS_ID).strip().lower()
    return f"{tid}@v{int(version)}"


def parse_pin(pin: str) -> Optional[tuple[str, int]]:
    if not pin:
        return None
    m = PIN_RE.match(str(pin).strip())
    if not m:
        return None
    return m.group(1).lower(), int(m.group(2))


def _normalize_thesis_id(thesis_id: str) -> str:
    tid = (thesis_id or DEFAULT_THESIS_ID).strip().lower()
    if not re.match(r"^[a-z][a-z0-9_\-]{0,63}$", tid):
        raise ValueError(f"invalid thesis_id: {thesis_id!r}")
    return tid


def _notify_thesis_publish(thesis_id: str, version: int, summary: str) -> None:
    """Phase 1: NO general-Telegram side effect on thesis persistence.

    Default: silent (CIO_THESIS_TELEGRAM unset/0). When explicitly enabled,
    routes ONLY through CIO-only transport (TELEGRAM_CIO_BOT_TOKEN + allowlist),
    with materiality + semantic dedupe + pytest interdiction.

    Never calls telegram_alert.send_telegram (general Maria channel).
    Never blocks the store write; any failure is swallowed.
    """
    try:
        from scripts.lib.cio_telegram_transport import notify_thesis_published
        notify_thesis_published(thesis_id, version, summary)
    except Exception:
        try:
            from lib.cio_telegram_transport import notify_thesis_published  # type: ignore
            notify_thesis_published(thesis_id, version, summary)
        except Exception:
            pass


class CIOThesisStore:
    """Versioned thesis store with rebuildable projection."""

    def __init__(
        self,
        event_path: Path | str | None = None,
        projection_path: Path | str | None = None,
    ):
        # Resolve defaults at call time so tests can monkeypatch DEFAULT_* paths
        self.event_path = Path(event_path if event_path is not None else DEFAULT_EVENT_PATH)
        self.projection_path = Path(
            projection_path if projection_path is not None else DEFAULT_PROJECTION_PATH
        )
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        # thesis_id -> current head record
        self._current: dict[str, dict[str, Any]] = {}
        # thesis_id -> {version_int -> record}
        self._versions: dict[str, dict[int, dict[str, Any]]] = {}
        self._load_or_rebuild()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_or_rebuild(self) -> None:
        if self.projection_path.exists():
            try:
                data = json.loads(self.projection_path.read_text())
                cur = data.get("current") or {}
                vers = data.get("versions") or {}
                if isinstance(cur, dict) and isinstance(vers, dict):
                    self._current = cur
                    # keys in versions are str in JSON
                    self._versions = {
                        tid: {int(v): dict(rec) for v, rec in (vmap or {}).items()}
                        for tid, vmap in vers.items()
                    }
                    return
            except Exception:
                pass
        self.rebuild_projection()

    def rebuild_projection(self) -> dict[str, Any]:
        current: dict[str, dict[str, Any]] = {}
        versions: dict[str, dict[int, dict[str, Any]]] = {}
        if self.event_path.exists():
            with open(self.event_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._apply_event(current, versions, ev)
        self._current = current
        self._versions = versions
        self._write_projection()
        return {
            "thesis_count": len(current),
            "version_count": sum(len(v) for v in versions.values()),
        }

    def _write_projection(self) -> None:
        # JSON-friendly version keys
        vers_out = {
            tid: {str(v): rec for v, rec in sorted(vmap.items())}
            for tid, vmap in self._versions.items()
        }
        payload = {
            "updated_ts": _now(),
            "thesis_count": len(self._current),
            "current": self._current,
            "versions": vers_out,
            "authority": "READ_ONLY_ADVISORY",
        }
        tmp = self.projection_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.projection_path)

    def _append_event(
        self,
        event_type: str,
        thesis_id: str,
        payload: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"invalid event_type: {event_type}")
        envelope = {
            "event_id": f"{int(time.time() * 1_000_000):020d}-{uuid.uuid4().hex[:8]}",
            "event_type": event_type,
            "thesis_id": thesis_id,
            "occurred_at": _now(),
            "actor_id": actor_id,
            "actor_type": (
                "system"
                if actor_id.startswith("cio_") or actor_id in ("system", "operator")
                else "agent"
            ),
            "authority": "READ_ONLY_ADVISORY",
            "payload": payload,
        }
        lock = _lock_path(self.event_path)
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                with open(self.event_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(envelope, sort_keys=True) + "\n")
                    fh.flush()
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        self._apply_event(self._current, self._versions, envelope)
        self._write_projection()
        return envelope

    def _apply_event(
        self,
        current: dict[str, dict[str, Any]],
        versions: dict[str, dict[int, dict[str, Any]]],
        ev: dict[str, Any],
    ) -> None:
        et = ev.get("event_type")
        tid = ev.get("thesis_id")
        if not tid:
            return
        p = ev.get("payload") or {}
        if et in ("THESIS_CREATED", "THESIS_VERSION_PUBLISHED"):
            ver = int(p.get("version") or 1)
            rec = dict(p)
            rec["thesis_id"] = tid
            rec["version"] = ver
            rec["thesis_version"] = make_pin(tid, ver)
            if "status" not in rec:
                rec["status"] = "active"
            versions.setdefault(tid, {})[ver] = rec
            # mark prior current as superseded in versions map (keep history)
            prev = current.get(tid)
            if prev and int(prev.get("version") or 0) != ver:
                pver = int(prev.get("version") or 0)
                if pver in versions.get(tid, {}):
                    old = dict(versions[tid][pver])
                    if old.get("status") == "active":
                        old["status"] = "superseded"
                        versions[tid][pver] = old
            current[tid] = dict(rec)
            return
        if et == "THESIS_STATUS_CHANGED":
            head = current.get(tid)
            if not head:
                return
            head = dict(head)
            head["status"] = p.get("status", head.get("status"))
            head["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            if p.get("reason"):
                head["status_reason"] = p["reason"]
            current[tid] = head
            ver = int(head.get("version") or 0)
            if ver and tid in versions and ver in versions[tid]:
                versions[tid][ver] = dict(head)
            return
        if et == "THESIS_LINKED":
            head = current.get(tid)
            if not head:
                return
            head = dict(head)
            for field in ("linked_goal_ids", "linked_plan_ids", "linked_symbols"):
                if field in p and isinstance(p[field], list):
                    existing = list(head.get(field) or [])
                    for item in p[field]:
                        if item not in existing:
                            existing.append(item)
                    head[field] = existing
            head["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            current[tid] = head
            ver = int(head.get("version") or 0)
            if ver and tid in versions and ver in versions[tid]:
                # links attach to head version only
                versions[tid][ver] = dict(head)
            return
        if et == "THESIS_LEARNING_APPENDED":
            head = current.get(tid)
            if not head:
                return
            head = dict(head)
            log = list(head.get("learning_log") or [])
            entry = p.get("entry") if isinstance(p.get("entry"), dict) else dict(p)
            if entry:
                log.append(entry)
            # keep last 40 on head projection
            head["learning_log"] = log[-40:]
            head["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            current[tid] = head
            ver = int(head.get("version") or 0)
            if ver and tid in versions and ver in versions[tid]:
                versions[tid][ver] = dict(head)
            return

    # ── Public API ───────────────────────────────────────────────────────

    def publish(
        self,
        summary: str,
        *,
        thesis_id: str = DEFAULT_THESIS_ID,
        stance: str = "",
        bullets: Optional[list[str]] = None,
        principles: Optional[list[str]] = None,
        risk_posture: str = "",
        escalation_rules: Optional[list[str]] = None,
        learning_log: Optional[list[dict[str, Any]]] = None,
        linked_symbols: Optional[list[str]] = None,
        linked_goal_ids: Optional[list[str]] = None,
        linked_plan_ids: Optional[list[str]] = None,
        evidence_refs: Optional[list[dict[str, Any]]] = None,
        owner_agent: str = "alex",
        change_note: str = "",
        actor_id: str = "cio_theses",
        extra: Optional[dict[str, Any]] = None,
        notify: bool = True,
    ) -> dict[str, Any]:
        """Publish a new version of a thesis (creates thesis_id on first publish).

        desk@v2+ fields: principles, risk_posture, escalation_rules, learning_log (seed).
        Ongoing operator learning also lands in cio_operator_learning.jsonl.
        notify=False suppresses Telegram (bulk symbol backfills / tests).
        """
        tid = _normalize_thesis_id(thesis_id)
        summary = (summary or "").strip()
        if not summary:
            raise ValueError("summary required")
        owner = (owner_agent or "alex").strip().lower()
        if owner not in VALID_OWNERS:
            raise ValueError(f"invalid owner_agent: {owner_agent}")

        prev = self._current.get(tid)
        next_ver = int(prev.get("version") or 0) + 1 if prev else 1
        ts = _now()
        # inherit links if not provided
        if linked_symbols is None and prev:
            linked_symbols = list(prev.get("linked_symbols") or [])
        if linked_goal_ids is None and prev:
            linked_goal_ids = list(prev.get("linked_goal_ids") or [])
        if linked_plan_ids is None and prev:
            linked_plan_ids = list(prev.get("linked_plan_ids") or [])
        # inherit desk structure fields when not re-specified
        if principles is None and prev:
            principles = list(prev.get("principles") or [])
        if not risk_posture and prev:
            risk_posture = str(prev.get("risk_posture") or "")
        if escalation_rules is None and prev:
            escalation_rules = list(prev.get("escalation_rules") or [])
        if learning_log is None and prev:
            # keep last N seed entries on version publish
            learning_log = list(prev.get("learning_log") or [])[-20:]

        payload: dict[str, Any] = {
            "thesis_id": tid,
            "version": next_ver,
            "thesis_version": make_pin(tid, next_ver),
            "summary": summary,
            "stance": (stance or "").strip(),
            "bullets": [str(b).strip() for b in (bullets or []) if str(b).strip()],
            "principles": [str(p).strip() for p in (principles or []) if str(p).strip()],
            "risk_posture": (risk_posture or "").strip(),
            "escalation_rules": [
                str(r).strip() for r in (escalation_rules or []) if str(r).strip()
            ],
            "learning_log": list(learning_log or [])[-30:],
            "linked_symbols": [str(s).upper() for s in (linked_symbols or [])],
            "linked_goal_ids": list(linked_goal_ids or []),
            "linked_plan_ids": list(linked_plan_ids or []),
            "evidence_refs": list(evidence_refs or []),
            "owner_agent": owner,
            "status": "active",
            "parent_version": int(prev["version"]) if prev else None,
            "change_note": (change_note or "").strip(),
            "created_ts": prev.get("created_ts") if prev else ts,
            "published_ts": ts,
            "updated_ts": ts,
            "authority": "READ_ONLY_ADVISORY",
        }
        if extra and isinstance(extra, dict):
            for k, v in extra.items():
                if k not in payload and v is not None:
                    payload[k] = v
        et = "THESIS_CREATED" if next_ver == 1 else "THESIS_VERSION_PUBLISHED"
        self._append_event(et, tid, payload, actor_id=actor_id)
        if notify:
            _notify_thesis_publish(tid, next_ver, summary)
        return dict(self._current[tid])

    def get_current(self, thesis_id: str = DEFAULT_THESIS_ID) -> Optional[dict[str, Any]]:
        tid = (thesis_id or DEFAULT_THESIS_ID).strip().lower()
        g = self._current.get(tid)
        return dict(g) if g else None

    def get_version(
        self,
        thesis_id: str,
        version: int,
    ) -> Optional[dict[str, Any]]:
        tid = (thesis_id or DEFAULT_THESIS_ID).strip().lower()
        rec = (self._versions.get(tid) or {}).get(int(version))
        return dict(rec) if rec else None

    def get_by_pin(self, pin: str) -> Optional[dict[str, Any]]:
        parsed = parse_pin(pin)
        if not parsed:
            return None
        tid, ver = parsed
        return self.get_version(tid, ver)

    def list_versions(
        self,
        thesis_id: str = DEFAULT_THESIS_ID,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        tid = (thesis_id or DEFAULT_THESIS_ID).strip().lower()
        vmap = self._versions.get(tid) or {}
        rows = [dict(vmap[v]) for v in sorted(vmap.keys(), reverse=True)]
        return rows[: max(1, min(int(limit or 20), 200))]

    def list_active(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = [
            dict(r) for r in self._current.values()
            if r.get("status") in ("active", None)
        ]
        rows.sort(key=lambda r: r.get("updated_ts") or r.get("published_ts") or "", reverse=True)
        return rows[:limit]

    def archive(
        self,
        thesis_id: str = DEFAULT_THESIS_ID,
        *,
        reason: str = "",
        actor_id: str = "cio_theses",
    ) -> dict[str, Any]:
        tid = _normalize_thesis_id(thesis_id)
        if tid not in self._current:
            raise KeyError(f"unknown thesis_id: {tid}")
        self._append_event(
            "THESIS_STATUS_CHANGED",
            tid,
            {"status": "archived", "reason": reason, "updated_ts": _now()},
            actor_id=actor_id,
        )
        return dict(self._current[tid])

    def link(
        self,
        thesis_id: str = DEFAULT_THESIS_ID,
        *,
        plan_ids: Optional[list[str]] = None,
        goal_ids: Optional[list[str]] = None,
        symbols: Optional[list[str]] = None,
        actor_id: str = "cio_theses",
    ) -> dict[str, Any]:
        tid = _normalize_thesis_id(thesis_id)
        if tid not in self._current:
            raise KeyError(f"unknown thesis_id: {tid}")
        payload: dict[str, Any] = {"updated_ts": _now()}
        if plan_ids:
            payload["linked_plan_ids"] = list(plan_ids)
        if goal_ids:
            payload["linked_goal_ids"] = list(goal_ids)
        if symbols:
            payload["linked_symbols"] = [str(s).upper() for s in symbols]
        self._append_event("THESIS_LINKED", tid, payload, actor_id=actor_id)
        return dict(self._current[tid])

    def current_pin(self, thesis_id: str = DEFAULT_THESIS_ID) -> Optional[str]:
        cur = self.get_current(thesis_id)
        if not cur:
            return None
        return cur.get("thesis_version") or make_pin(
            cur.get("thesis_id") or thesis_id,
            int(cur.get("version") or 1),
        )

    def context_block(
        self,
        thesis_id: str = DEFAULT_THESIS_ID,
        *,
        max_summary: int = 1200,
        full: bool = False,
    ) -> Optional[dict[str, Any]]:
        """Compact (or full) block for evidence packs / agent context."""
        cur = self.get_current(thesis_id)
        if not cur or cur.get("status") == "archived":
            return None
        summary = str(cur.get("summary") or "")
        if not full and len(summary) > max_summary:
            summary = summary[: max_summary - 1] + "…"
        block = {
            "thesis_id": cur.get("thesis_id"),
            "thesis_version": cur.get("thesis_version"),
            "version": cur.get("version"),
            "summary": summary if full else summary[:max_summary],
            "stance": cur.get("stance") or "",
            "bullets": list(cur.get("bullets") or [])[:12],
            "principles": list(cur.get("principles") or [])[:12],
            "risk_posture": cur.get("risk_posture") or "",
            "risk_posture_structured": cur.get("risk_posture_structured") or {},
            "escalation_rules": list(cur.get("escalation_rules") or [])[:12],
            "learning_log": list(cur.get("learning_log") or [])[-8:],
            "linked_symbols": list(cur.get("linked_symbols") or [])[:20],
            "watch_symbols": list(cur.get("watch_symbols") or cur.get("linked_symbols") or [])[:20],
            "last_reviewed": cur.get("last_reviewed") or cur.get("published_ts"),
            "owner_agent": cur.get("owner_agent"),
            "published_ts": cur.get("published_ts"),
            "intelligence_layer": cur.get("intelligence_layer") or "",
            "authority": "READ_ONLY_ADVISORY",
        }
        return block

    def append_learning(
        self,
        entry: dict[str, Any],
        *,
        thesis_id: str = DEFAULT_THESIS_ID,
        actor_id: str = "operator",
    ) -> Optional[dict[str, Any]]:
        """Append a learning entry to the active thesis head (and durable JSONL)."""
        tid = _normalize_thesis_id(thesis_id)
        if tid not in self._current:
            return None
        clean = {
            "ts": entry.get("ts") or _now(),
            "kind": str(entry.get("kind") or "disposition"),
            "plan_id": entry.get("plan_id"),
            "situation_type": entry.get("situation_type"),
            "symbols": list(entry.get("symbols") or [])[:8],
            "disposition": entry.get("disposition") or entry.get("status"),
            "note": str(entry.get("note") or "")[:400],
            "thesis_version": entry.get("thesis_version") or self.current_pin(tid),
            "authority": "READ_ONLY_ADVISORY",
        }
        # durable append-only log (cross-version)
        try:
            record_operator_learning(clean)
        except Exception:
            pass
        self._append_event(
            "THESIS_LEARNING_APPENDED",
            tid,
            {"entry": clean, "updated_ts": _now()},
            actor_id=actor_id,
        )
        return dict(self._current[tid])


def safe_current_pin(thesis_id: str = DEFAULT_THESIS_ID) -> Optional[str]:
    """Fail-soft current pin for callers that must never raise."""
    try:
        return CIOThesisStore().current_pin(thesis_id)
    except Exception:
        return None


def safe_context_block(
    thesis_id: str = DEFAULT_THESIS_ID,
    *,
    full: bool = False,
) -> Optional[dict[str, Any]]:
    try:
        return CIOThesisStore().context_block(thesis_id, full=full)
    except Exception:
        return None


def record_operator_learning(
    entry: dict[str, Any],
    *,
    path: Path | str | None = None,
) -> None:
    """Append-only operator learning log (dispositions, ratings). Fail-soft."""
    p = Path(path) if path else DEFAULT_LEARNING_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    row = dict(entry)
    row.setdefault("ts", _now())
    row.setdefault("authority", "READ_ONLY_ADVISORY")
    lock = _lock_path(p)
    try:
        with open(lock, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                with open(p, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
                    fh.flush()
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


def recent_operator_learning(
    *,
    situation_type: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 8,
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Recent operator dispositions for enrichment context. Fail-soft."""
    p = Path(path) if path else DEFAULT_LEARNING_PATH
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    st = (situation_type or "").strip()
    sym = (symbol or "").strip().upper()
    out: list[dict[str, Any]] = []
    for r in reversed(rows):
        r_st = str(r.get("situation_type") or "")
        rsyms = {str(x).upper() for x in (r.get("symbols") or [])}
        if st and sym:
            if r_st != st and sym not in rsyms:
                continue
        elif st and r_st != st:
            continue
        elif sym and sym not in rsyms:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def record_plan_disposition_learning(
    plan: dict[str, Any],
    disposition: str,
    *,
    note: str = "",
    actor_id: str = "operator",
) -> None:
    """Wire plan ack/defer/done/reject into thesis learning. Fail-soft."""
    entry = {
        "ts": _now(),
        "kind": "plan_disposition",
        "plan_id": plan.get("plan_id"),
        "situation_type": plan.get("situation_type"),
        "symbols": list(plan.get("symbols") or []),
        "disposition": disposition,
        "note": note,
        "thesis_version": plan.get("thesis_version"),
        "narrative_source": plan.get("narrative_source"),
    }
    try:
        record_operator_learning(entry)
    except Exception:
        pass
    try:
        CIOThesisStore().append_learning(entry, actor_id=actor_id)
    except Exception:
        pass


def safe_pin_plan(
    plan_id: str,
    *,
    thesis_id: str = DEFAULT_THESIS_ID,
    plan_store: Any = None,
) -> Optional[str]:
    """Attach current desk thesis pin to a plan if missing. Fail-soft; returns pin or None."""
    try:
        store = CIOThesisStore()
        pin = store.current_pin(thesis_id)
        if not pin:
            return None
        if plan_store is None:
            from scripts.lib.cio_plans import CIOPlanStore
            plan_store = CIOPlanStore()
        plan = plan_store.get_plan(plan_id) if hasattr(plan_store, "get_plan") else None
        if plan and plan.get("thesis_version"):
            return plan.get("thesis_version")
        if hasattr(plan_store, "update_plan"):
            try:
                plan_store.update_plan(plan_id, thesis_version=pin, actor_id="cio_theses")
            except TypeError:
                # older update_plan without field — try _patch style
                try:
                    plan_store.update_plan(plan_id, actor_id="cio_theses", **{"thesis_version": pin})
                except Exception:
                    pass
            except Exception:
                pass
        try:
            store.link(thesis_id, plan_ids=[plan_id], actor_id="cio_theses")
        except Exception:
            pass
        return pin
    except Exception:
        return None
