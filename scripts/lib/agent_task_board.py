"""Agent task board: open work any agent can pick up, register, do and finish without further instruction.

Operator 2026-10-23: tell any agent "read AGENTS.md, pick up open work". AGENTS.md 20.0.0 §28.3a pins the command
names: ``task add | split | list | show | done | release`` and ``next``.

Store (same coordination directory as the claims)::

    <claims_dir>/tasks/<task_id>.json      one AgentTask@v1 per task (temp + os.replace under the task lock)
    <claims_dir>/tasks/tasks_history.jsonl append-only, one AgentTaskEvent@v1 per change (fsynced)
    <claims_dir>/tasks/.task.lock          flock; ``next`` holds it across pick + claim, so two concurrent ``next``
                                           calls can never hand out overlapping work

Status: ``free`` -> ``taken`` (by ``next``; a claim on the task's areas exists) -> ``done``; ``task release`` puts a
taken task back to ``free`` with its history and hand-off note; a task split into children reads ``split`` and
counts as done for dependencies once every child is done. The board shows ``in_progress`` for a taken task whose
claim has reached ``building`` or later.

``next`` picks the highest-priority free task (priority 1 is highest, then oldest) whose dependencies are all done
and whose areas overlap no live claim at all (the caller's own included: one session never holds two overlapping
tasks); it claims the areas, opens the worklog with the task's
acceptance criteria as the Plan seed (the operator quote in the Goal), and marks the task taken -- all under the
task lock and the claim board's own lock. On re-pick after a release the new worklog carries the old one forward.

Stdlib only. AUTHORITY: READ_ONLY_ADVISORY (coordination files only; no broker, DB, Telegram, scheduler or remote).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    from scripts.lib import agent_claim_board as B
except ImportError:  # scripts/ on sys.path (api_v2)
    from lib import agent_claim_board as B  # type: ignore[no-redef]

SCHEMA = "AgentTask@v1"
EVENT_SCHEMA = "AgentTaskEvent@v1"
KINDS = ("design", "build", "fix", "review")
STATUSES = ("free", "taken", "done", "split")
BOARD_COLUMNS = ("free", "taken", "in_progress", "done")
TASKS_DIRNAME = "tasks"
HISTORY_NAME = "tasks_history.jsonl"
DEFAULT_PRIORITY = 3
MAX_TASKS_READ = 2000
# T-<date>-<hex> (generated) or a design task id DSN-<YYYYMMDD>-<slug>-P<n>-T<m> (AGENTS.md 20.0.0 §28)
_ID_RE = re.compile(r"^(T-[0-9]{8}-[0-9a-f]{6}|DSN-[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*-P[0-9]{1,3}-T[0-9]{1,3})$")
DESIGN_TASK_RE = re.compile(r"^DSN-[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*-P[0-9]{1,3}-T[0-9]{1,3}$")
IN_PROGRESS_STAGES = ("building", "pr_open", "ci_green", "merged", "released")


class TaskError(Exception):
    """Refused or invalid task operation."""


def valid_task_id(task_id: str) -> bool:
    return bool(_ID_RE.match(task_id or ""))


class TaskBoard:
    def __init__(self, claims: "B.ClaimBoard"):
        self.claims = claims
        self.dir = claims.dir / TASKS_DIRNAME
        self.history = self.dir / HISTORY_NAME

    # -- io -----------------------------------------------------------------------------------------

    def now_iso(self) -> str:
        return B.iso(self.claims.now())

    def path(self, task_id: str) -> Path:
        if not valid_task_id(task_id):
            raise TaskError(f"bad task id {task_id!r}")
        return self.dir / f"{task_id}.json"

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / ".task.lock", "a", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write(self, doc: dict[str, Any]) -> None:
        target = self.path(doc["task_id"])
        tmp = self.dir / f".{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(target))

    def _event(self, doc: dict[str, Any], event: str, **fields: Any) -> dict[str, Any]:
        ev = {"at": self.now_iso(), "event": event, **{k: v for k, v in fields.items() if v is not None}}
        doc.setdefault("history", []).append(ev)
        line = json.dumps({"schema": EVENT_SCHEMA, "task_id": doc["task_id"], **ev}, sort_keys=True) + "\n"
        fd = os.open(str(self.history), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return ev

    def read_all(self) -> list[dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        out = []
        for i, p in enumerate(sorted([*self.dir.glob("T-*.json"), *self.dir.glob("DSN-*.json")])):
            if i >= MAX_TASKS_READ:
                break
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d.get("schema") == SCHEMA and d.get("task_id") == p.stem:
                out.append(d)
        return out

    def get(self, task_id: str) -> dict[str, Any]:
        try:
            return json.loads(self.path(task_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise TaskError(f"task {task_id} not found in {self.dir}") from None

    # -- create ---------------------------------------------------------------------------------------

    def add(
        self,
        *,
        title: str,
        kind: str,
        areas: Iterable[str],
        depends_on: Iterable[str] = (),
        priority: int = DEFAULT_PRIORITY,
        acceptance: Iterable[str] = (),
        operator_quote: str | None = None,
        estimate: str | None = None,
        created_by: str | None = None,
        parent: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if task_id is not None and not DESIGN_TASK_RE.match(task_id):
            raise TaskError(f"--id must be a design task id DSN-<YYYYMMDD>-<slug>-P<n>-T<m>, got {task_id!r}")
        if kind not in KINDS:
            raise TaskError(f"kind must be one of {', '.join(KINDS)}")
        title = B.clip(title, 200) or ""
        if not title:
            raise TaskError("title is required")
        canon: list[str] = []
        for a in areas:
            c = B.canonical_pattern(a)
            if c not in canon:
                canon.append(c)
        if not canon:
            raise TaskError("at least one area (file, directory or glob) is required")
        deps = [d for d in depends_on if d]
        for d in deps:
            if not valid_task_id(d):
                raise TaskError(f"bad dependency id {d!r}")
        try:
            prio = int(priority)
        except (TypeError, ValueError):
            raise TaskError("priority must be an integer (1 highest)") from None
        with self.locked():
            for d in deps:
                if not self.path(d).is_file():
                    raise TaskError(f"dependency {d} does not exist")
            now = self.claims.now()
            doc: dict[str, Any] = {
                "schema": SCHEMA,
                "task_id": task_id or f"T-{now.strftime('%Y%m%d')}-{secrets.token_hex(3)}",
                "design_id": task_id.rsplit("-P", 1)[0] if task_id else None,
                "phase_id": task_id.rsplit("-T", 1)[0] if task_id else None,
                "title": title,
                "kind": kind,
                "areas": canon,
                "depends_on": deps,
                "priority": prio,
                "acceptance": [B.clip(x, 300) for x in acceptance if B.clip(x, 300)],
                "operator_quote": B.clip(operator_quote, 4000),
                "estimate": B.clip(estimate, 80),
                "actual": None,
                "status": "free",
                "owner": None,
                "claim_id": None,
                "claims": [],
                "parent": parent,
                "children": [],
                "created_at": B.iso(now),
                "created_by": B.clip(created_by, 120),
                "taken_at": None,
                "done_at": None,
                "handoff": None,
                "history": [],
            }
            if task_id and self.path(task_id).exists():
                raise TaskError(f"task {task_id} already exists")
            while self.path(doc["task_id"]).exists():
                doc["task_id"] = f"T-{now.strftime('%Y%m%d')}-{secrets.token_hex(3)}"
            self._event(doc, "added", by=doc["created_by"])
            self._write(doc)
        return doc

    def split(self, task_id: str, parts: list[dict[str, Any]], *, by: str | None = None) -> list[dict[str, Any]]:
        """Split a free task into children (each {title, areas, acceptance?, kind?, priority?}). The parent reads
        ``split`` and counts as done for its dependents once every child is done."""
        parent = self.get(task_id)
        if parent["status"] != "free":
            raise TaskError(f"task {task_id} is {parent['status']}; only a free task can be split")
        if not parts:
            raise TaskError("split needs at least one part")
        kids = [
            self.add(
                title=p["title"],
                kind=p.get("kind") or parent["kind"],
                areas=p.get("areas") or parent["areas"],
                depends_on=parent.get("depends_on") or [],
                priority=p.get("priority", parent["priority"]),
                acceptance=p.get("acceptance") or [],
                operator_quote=parent.get("operator_quote"),
                created_by=by,
                parent=task_id,
            )
            for p in parts
        ]
        with self.locked():
            parent = self.get(task_id)
            parent["status"] = "split"
            parent["children"] = [k["task_id"] for k in kids]
            self._event(parent, "split", by=by, children=parent["children"])
            self._write(parent)
        return kids

    # -- state ----------------------------------------------------------------------------------------

    def _done_ids(self, tasks: list[dict[str, Any]]) -> set[str]:
        by_id = {t["task_id"]: t for t in tasks}
        done = {t["task_id"] for t in tasks if t.get("status") == "done"}
        changed = True
        while changed:  # a split parent is done when every child is
            changed = False
            for t in tasks:
                if t["task_id"] not in done and t.get("status") == "split" and t.get("children"):
                    if all(c in done for c in t["children"] if c in by_id):
                        done.add(t["task_id"])
                        changed = True
        return done

    def column(self, t: dict[str, Any], views: dict[str, "B.ClaimView"], done: set[str] = frozenset()) -> str:
        st = t.get("status")
        if st == "done":
            return "done"
        if st == "split":  # divided into children: done when they all are, else in progress
            return "done" if t["task_id"] in done else "in_progress"
        if st == "taken":
            v = views.get(t.get("claim_id") or "")
            return "in_progress" if v is not None and v.stage in IN_PROGRESS_STAGES else "taken"
        return "free"

    def blocked_by(self, t: dict[str, Any], done: set[str]) -> list[str]:
        return [d for d in t.get("depends_on") or [] if d not in done]

    # -- next -----------------------------------------------------------------------------------------

    def next(
        self,
        *,
        vendor: str,
        session: str,
        agent: str | None,
        kind: str | None = None,
        branch: str | None = None,
        worktree: str | None = None,
        head_sha: str | None = None,
        task_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Pick, claim and mark one task atomically. None when nothing is free, unblocked and unclaimed.

        ``task_id`` (``take <task-id>``): that task only; a refusal says why (taken, blocked, overlapping claim)."""
        if kind and kind not in KINDS:
            raise TaskError(f"kind must be one of {', '.join(KINDS)}")
        with self.locked():
            tasks = self.read_all()
            done = self._done_ids(tasks)
            views = self.claims.views()[0]
            cands = [
                t
                for t in tasks
                if t.get("status") == "free" and (not kind or t.get("kind") == kind) and not self.blocked_by(t, done)
            ]
            cands.sort(key=lambda t: (t.get("priority", DEFAULT_PRIORITY), t.get("created_at") or "", t["task_id"]))
            if task_id is not None:
                want = next((t for t in tasks if t["task_id"] == task_id), None)
                if want is None:
                    raise TaskError(f"task {task_id} not found")
                if want.get("status") != "free":
                    who = want.get("owner") or {}
                    raise TaskError(
                        f"task {task_id} is {want.get('status')}"
                        + (f" (held by {who.get('vendor')}/{who.get('session')})" if who else "")
                    )
                blocked = self.blocked_by(want, done)
                if blocked:
                    raise TaskError(f"task {task_id} waits on {', '.join(blocked)}")
                rows = self.claims.conflicts(want["areas"], session=None, views=views)
                if rows:
                    raise B.ClaimConflict(B.describe_conflicts(rows), rows)
                cands = [want]
            for t in cands:
                if self.claims.conflicts(t["areas"], session=None, views=views):
                    continue
                prev_claim = t.get("claim_id") or (t.get("claims") or [None])[-1]
                try:
                    claim = self.claims.claim(
                        vendor=vendor,
                        session=session,
                        agent=agent,
                        task=f"[{t['task_id']}] {t['title']}",
                        paths=t["areas"],
                        branch=branch,
                        note=f"task {t['task_id']}",
                        worktree=worktree,
                        head_sha=head_sha,
                    )
                except B.ClaimConflict:
                    if task_id is not None:
                        raise
                    continue  # lost to a claim made outside the task lock; try the next task
                self._open_worklog(t, claim, prev_claim)
                t["status"] = "taken"
                t["owner"] = {"vendor": claim["vendor"], "session": claim["session"], "agent": claim.get("agent")}
                t["claim_id"] = claim["claim_id"]
                t.setdefault("claims", []).append(claim["claim_id"])
                t["taken_at"] = claim["started_at"]
                self._event(t, "taken", by=f"{claim['vendor']}/{claim['session']}", claim_id=claim["claim_id"])
                self._write(t)
                return t, claim
        return None

    def _open_worklog(self, t: dict[str, Any], claim: dict[str, Any], prev_claim: str | None) -> None:
        wl = self.claims.worklog(claim["claim_id"])
        old = self.claims.worklog(prev_claim) if prev_claim and B.valid_claim_id(prev_claim) else None
        old_text = None
        if old is not None:
            found = B.WL.read_any(self.claims.dir, prev_claim)
            old_text = found[1] if found else None
        if old_text:
            line = f"task {t['task_id']} re-picked by {claim['vendor']}/{claim['session']} from claim {prev_claim}"
            if t.get("handoff"):
                line += f"; hand-off: {t['handoff']}"
            wl.carry_forward(old_text, claim, line)
            return
        goal = f"[{t['task_id']}] {t['title']} ({t['kind']}, priority {t['priority']})"
        wl.create(
            claim,
            goal=goal,
            request=t.get("operator_quote"),
            plan=list(t.get("acceptance") or []),
            worktree=claim.get("worktree"),
        )

    # -- finish / release -----------------------------------------------------------------------------

    def _own_taken(self, task_id: str, session: str | None, force: bool) -> dict[str, Any]:
        t = self.get(task_id)
        if t.get("status") != "taken":
            raise TaskError(f"task {task_id} is {t.get('status')}, not taken")
        owner = (t.get("owner") or {}).get("session")
        if not force and owner != session:
            raise TaskError(f"task {task_id} is taken by session {owner!r}, not {session!r} (--force overrides)")
        return t

    def done(
        self,
        task_id: str,
        *,
        session: str | None,
        summary: str | None = None,
        force: bool = False,
        actual_cost: str | None = None,
    ) -> dict[str, Any]:
        """Mark done and check every acceptance box in the claim's worklog."""
        with self.locked():
            t = self._own_taken(task_id, session, force)
            wl = self.claims.worklog(t["claim_id"]) if t.get("claim_id") else None
            if wl is not None and wl.exists():
                for acc in t.get("acceptance") or []:
                    try:
                        wl.done(acc)
                    except B.WL.WorklogError:
                        pass
                wl.status(f"task {task_id} done" + (f": {summary}" if summary else ""))
            now = self.claims.now()
            t["status"] = "done"
            t["done_at"] = B.iso(now)
            started = B.parse_iso(t.get("taken_at"))
            t["actual"] = {
                "minutes": round((now - started).total_seconds() / 60, 1) if started else None,
                "cost": B.clip(actual_cost, 80),
            }
            self._event(t, "done", by=session, summary=B.clip(summary, 500))
            self._write(t)
        return t

    def release(self, task_id: str, *, session: str | None, handoff: str, force: bool = False) -> dict[str, Any]:
        """Put a taken task back on the board (free) with its history and the hand-off note; the claim is released
        as abandoned and its worklog keeps the note, so the next picker continues from it."""
        handoff = B.clip(handoff, 1000) or ""
        if not handoff:
            raise TaskError('task release needs --handoff "<next step>"')
        with self.locked():
            t = self._own_taken(task_id, session, force)
            cid = t.get("claim_id")
            if cid:
                wl = self.claims.worklog(cid)
                if wl.exists():
                    wl.handoff(next_step=handoff)
                try:
                    self.claims.release(
                        cid,
                        session=(t.get("owner") or {}).get("session"),
                        status="abandoned",
                        note=f"task {task_id} released: {handoff}",
                        summary=f"task {task_id} put back on the board; next step: {handoff}",
                        force=force,
                        released_by=session,
                    )
                except B.ClaimError:
                    pass  # claim already released / compacted: the task still goes back
            t["status"] = "free"
            t["handoff"] = handoff
            t["owner"] = None
            t["claim_id"] = None
            self._event(t, "released", by=session, handoff=handoff, claim_id=cid)
            self._write(t)
        return t

    # -- read model -----------------------------------------------------------------------------------

    def board(self) -> dict[str, Any]:
        tasks = self.read_all()
        done = self._done_ids(tasks)
        views = {v.claim_id: v for v in self.claims.views()[0]}
        rows = []
        for t in tasks:
            v = views.get(t.get("claim_id") or "")
            rows.append(
                {
                    **{
                        k: t.get(k)
                        for k in (
                            "task_id",
                            "design_id",
                            "phase_id",
                            "title",
                            "kind",
                            "areas",
                            "depends_on",
                            "priority",
                            "acceptance",
                            "operator_quote",
                            "estimate",
                            "actual",
                            "status",
                            "owner",
                            "claim_id",
                            "parent",
                            "children",
                            "created_at",
                            "taken_at",
                            "done_at",
                            "handoff",
                        )
                    },
                    "column": self.column(t, views, done),
                    "blocked_by": self.blocked_by(t, done),
                    "claim_stage": v.stage if v is not None else None,
                    "history_len": len(t.get("history") or []),
                }
            )
        rows.sort(key=lambda r: (BOARD_COLUMNS.index(r["column"]), r.get("priority") or 9, r.get("created_at") or ""))
        counts = {c: sum(1 for r in rows if r["column"] == c) for c in BOARD_COLUMNS}
        return {"schema": "AgentTaskBoard@v1", "columns": list(BOARD_COLUMNS), "counts": counts, "tasks": rows}


def parse_part(spec: str) -> dict[str, Any]:
    """CLI split part: ``title | area1,area2 | acceptance1; acceptance2`` (areas and acceptance optional)."""
    bits = [b.strip() for b in spec.split("|")]
    if not bits[0]:
        raise TaskError(f"split part needs a title: {spec!r}")
    return {
        "title": bits[0],
        "areas": [a.strip() for a in bits[1].split(",") if a.strip()] if len(bits) > 1 else [],
        "acceptance": [a.strip() for a in bits[2].split(";") if a.strip()] if len(bits) > 2 else [],
    }
