#!/usr/bin/env python3
"""Plan registry — every approved plan persisted on the server for every agent.

An operator-approved plan is written ONCE to
``${TRADEAI_STATE_ROOT}/data/coordination/plans/<plan-id>.md`` with front-matter, and its lifecycle
is followed from there: the agent that picks it up links its claim, branch and PR; steps are ticked
as they are done; the status moves approved -> in_progress -> done (or abandoned/stalled). Every
mutation also appends one line to the append-only ``ledger.jsonl`` beside the plans.

Claude Code registers plans through the PostToolUse hook on ``ExitPlanMode`` (see
``docs/ops/PLAN_REGISTRY.md`` for the settings snippet; the repository never edits the operator's
``~/.claude/settings.json``). Codex, Cursor and every other vendor use this CLI:

    python3 scripts/plan_registry.py add --title "..." --file plan.md --author <session> --vendor codex [--dry-run]
    python3 scripts/plan_registry.py status
    python3 scripts/plan_registry.py list [--status approved] [--json]
    python3 scripts/plan_registry.py show <plan-id>
    python3 scripts/plan_registry.py link <plan-id> --claim <claim-id> --branch wt/x --pr 123 [--dry-run]
    python3 scripts/plan_registry.py step done <plan-id> <step text or number> [--dry-run]
    python3 scripts/plan_registry.py set-status <plan-id> in_progress|done|abandoned|stalled [--dry-run]
    python3 scripts/plan_registry.py stale [--hours N] [--apply]

Writes are locked (flock) and atomic (tmp + replace); the ledger is append-only. Every mutation has
a ``--dry-run`` path that computes and reports the intended change without calling a writer
(AGENTS.md §6). Stall notifications are queued durably before the plan is marked stalled and are
delivered at-least-once, so a failed inbox write can never be recorded as sent. Stdlib only.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "plan_registry.json"
STATUSES = ("approved", "in_progress", "done", "abandoned", "stalled")
STALE_STATUSES = ("approved", "in_progress")
#: A plan id is a single path component; anything else is refused before it reaches the filesystem.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def state_root() -> Path:
    """The persistent store this registry writes to.

    ``TRADEAI_STATE_ROOT`` still wins when it is set (tests and one-off roots), but the fallback is the
    canonical resolver, not a literal home path: the claim board resolves its own directory through
    ``good_persistent_root()``, which honours ``TRADEAI_PERSISTENT_STATE_ROOT``. Reading only
    ``TRADEAI_STATE_ROOT`` wrote plans and coordinator alerts into the default tree while the claim board
    searched the configured one, so registration looked up the wrong board.
    """
    override = os.environ.get("TRADEAI_STATE_ROOT")
    if override:
        return Path(override)
    try:
        from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415
    except ImportError:  # pragma: no cover - package context
        from scripts.lib.persistent_state_root import good_persistent_root  # noqa: PLC0415
    return good_persistent_root()


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (s or "plan")[:40]


def plan_id(title: str, body: str, author: str = "") -> str:
    """Stable from the plan itself (title, text, author) — NOT the day, so a retry tomorrow dedupes."""
    digest = hashlib.sha256(f"{title}\n{body}\n{author}".encode("utf-8")).hexdigest()[:12]
    return f"{slug(title)}-{digest}"


# ------------------------------------------------------------------ document format
def parse_plan(text: str) -> dict[str, Any]:
    """Front-matter as ``key: <json value>`` lines between --- markers, then the body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {"front": {}, "body": text}
    front: dict[str, Any] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return {"front": front, "body": "\n".join(lines[i + 1:]).lstrip("\n")}
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip()
        try:
            front[key.strip()] = json.loads(raw)
        except ValueError:
            front[key.strip()] = raw
    return {"front": {}, "body": text}  # unterminated front-matter is body


def render_plan(front: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key in ("id", "title", "author_session", "author_proof", "vendor", "approved_at", "operator_quote",
                "status", "claim", "branch", "pr", "updated_at", "stalled_since"):
        if key in front and front[key] is not None:
            lines.append(f"{key}: {json.dumps(front[key], ensure_ascii=False)}")
    for key, value in front.items():
        if key not in {"id", "title", "author_session", "author_proof", "vendor", "approved_at",
                       "operator_quote", "status", "claim", "branch", "pr", "updated_at",
                       "stalled_since"} and value is not None:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")


def author_proof(author: str, *, root: Path | None = None) -> str:
    """How this author is evidenced — never a claim that it is authenticated.

    A session id is a self-declared string. When ``author`` matches a LIVE claim on the board, the
    record names that claim (``claim:<id>``); otherwise it says ``self-declared``. The distinction is
    recorded on the plan so a reader can weigh the authorship instead of assuming it.
    """
    author = str(author or "")
    if not author:
        return "self-declared"
    claims = Path(root or state_root()) / "data" / "coordination" / "claims"
    if not claims.is_dir():
        return "self-declared"
    for p in sorted(claims.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or str(doc.get("status") or "") != "active":
            continue
        if str(doc.get("session") or "") != author:
            continue
        return f"claim:{doc.get('claim_id') or p.stem}"
    return "self-declared"


# ------------------------------------------------------------------ registry
class Registry:
    def __init__(self, root: Path | None = None, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self.root = Path(root or state_root())
        self.plans = self.root / str(self.cfg.get("plans_rel") or "data/coordination/plans")
        self.ledger = self.plans / "ledger.jsonl"
        self.pending = self.plans / "pending_notifications.jsonl"
        self.inbox = self.root / str(self.cfg.get("inbox_rel") or "data/coordination/coordinator/inbox.md")
        self.stale_hours = float(self.cfg.get("stale_hours") or 72)
        #: What the last flush actually delivered: a failure is listed under "pending", never as sent.
        self.last_delivery: dict[str, list[str]] = {"delivered": [], "dropped": [], "pending": []}

    # -- io
    @contextmanager
    def _lock(self) -> Iterator[None]:
        # O_NOFOLLOW: the lock file is opened with the same containment rule as everything else in the
        # store. A symlink planted at plans/.lock is an error (ELOOP), never a lock held on some other
        # file; without this the store's own lock could be redirected outside it.
        self.plans.mkdir(parents=True, exist_ok=True)
        lock = self.plans / ".lock"
        try:
            fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise ValueError(f"plan store lock {lock} is not a regular file ({exc.strerror}); refusing") from None
        with os.fdopen(fd, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _write(self, pid: str, front: dict[str, Any], body: str) -> None:
        path = self._path(pid)
        # A pre-planted symlink at a predictable temp name must never be followed (review 2026-11-02,
        # B1): mkstemp creates a NEW 0600 file with O_EXCL inside the plan store, so the write can
        # neither land outside it nor replace someone else's file.
        fd, tmp_name = tempfile.mkstemp(prefix=".plan-", suffix=".tmp", dir=str(self.plans))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(render_plan(front, body))
                fh.flush()
                os.fsync(fh.fileno())  # durable BEFORE the rename: a crash never leaves a torn plan
            os.replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def _event(self, event: str, pid: str, **detail: Any) -> None:
        # O_NOFOLLOW: the append-only ledger cannot be redirected outside the store by a planted link.
        self.plans.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise ValueError(f"plan ledger {self.ledger} is not a regular file ({exc.strerror}); refusing") from None
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": _utc(), "event": event, "id": pid, "detail": detail},
                                sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _path(self, pid: str) -> Path:
        """Validate the id and prove the resolved file stays inside the plan store.

        Refuses traversal ("../x"), absolute ids ("/tmp/x"), slash-bearing ids and any existing
        symlink that resolves outside plans/ — before any read, write or render touches the disk.
        """
        pid = str(pid)
        if not ID_RE.match(pid):
            raise ValueError(f"invalid plan id {pid!r}: expected {ID_RE.pattern}")
        base = self.plans.resolve()
        path = self.plans / f"{pid}.md"
        try:
            path.resolve().relative_to(base)
        except ValueError:
            raise ValueError(f"plan id {pid!r} resolves outside the plan store") from None
        return path

    def _last_activity(self, pid: str, front: dict[str, Any]) -> datetime | None:
        """The last real plan event: the plan's own write, approval, or a ledger entry.

        ``updated_at`` is part of this, not decoration. A ``set-status in_progress`` or ``step done``
        that writes the plan and then fails appending its ledger line leaves the fresh activity ONLY in
        the plan front-matter; reading the ledger alone then reported the old approval time and the next
        ``stale --apply`` marked freshly resumed work stalled. The plan write is the durable fact — the
        ledger append is the one that can be interrupted.
        """
        last = _parse_ts(front.get("approved_at"))
        for key in ("updated_at", "created_at"):
            at = _parse_ts(front.get(key))
            if at and (last is None or at > last):
                last = at
        try:
            for line in self.ledger.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if str(row.get("id")) == pid and str(row.get("event")) != "add":
                    at = _parse_ts(row.get("at"))
                    if at and (last is None or at > last):
                        last = at
        except OSError:
            pass
        return last

    def _has_add_event(self, pid: str) -> bool:
        """Whether the ledger already records this plan's registration.

        An unreadable ledger is NOT evidence that the event is missing: that error is raised, never
        guessed, so a retry cannot append a duplicate registration.
        """
        try:
            text = self.ledger.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and str(row.get("id")) == pid and str(row.get("event")) == "add":
                return True
        return False

    def _preview(self, action: str, pid: str, *, front: dict[str, Any], body: str | None,
                 event: str, detail: dict[str, Any]) -> dict[str, Any]:
        """Render the intended mutation for ``--dry-run``; no writer is called from here (§6)."""
        report: dict[str, Any] = {
            "dry_run": True,
            "action": action,
            "id": pid,
            "path": str(self._path(pid)),
            "status": front.get("status"),
            "front": front,
            "ledger_event": {"event": event, "id": pid, "detail": detail},
        }
        if body is not None:
            report["body_bytes"] = len(body.encode("utf-8"))
        return report

    def _read_pending_unlocked(self) -> list[dict[str, Any]]:
        try:
            text = self.pending.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("id") and rec.get("message"):
                records.append(rec)
        return records

    def _rewrite_pending_unlocked(self, records: list[dict[str, Any]]) -> None:
        """Replace the queue atomically; only undelivered records survive a flush."""
        self.plans.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".pending-", suffix=".tmp", dir=str(self.plans))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.pending)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def _queue_notification_unlocked(self, pid: str, message: str) -> None:
        """Durably record a notification that has NOT been delivered.

        Called BEFORE the plan's status write: a crash between the two leaves a retryable record,
        whereas the reverse order loses the alert for good (once ``stalled`` the plan is no longer
        stale-eligible, so no later scan would ever select it again).
        """
        for rec in self._read_pending_unlocked():
            if str(rec.get("id")) == pid:
                return  # already queued: an undelivered stall alert is never duplicated
        self.plans.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.pending, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise ValueError(f"plan notification queue {self.pending} is not a regular file "
                             f"({exc.strerror}); refusing") from None
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": _utc(), "id": pid, "message": message,
                                 "stale_hours": self.stale_hours}, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _append_inbox_line_unlocked(self, message: str) -> None:
        self.inbox.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.inbox, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise OSError(f"coordinator inbox {self.inbox} is not writable ({exc.strerror})") from None
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _pending_still_true_unlocked(self, rec: dict[str, Any]) -> bool | None:
        """Whether a queued alert still describes the store; ``None`` = cannot tell, keep it."""
        pid = str(rec.get("id"))
        try:
            front = self.get(pid)["front"]
        except (KeyError, ValueError, OSError):
            return None  # missing or unreadable is unknown, not resolved — never silently dropped
        status = str(front.get("status") or "")
        if status == "stalled":
            return True  # queued by a mark that completed; its alert must be delivered
        if status not in STALE_STATUSES:
            return False  # done/abandoned: the alert is no longer true
        if any(front.get(k) for k in ("claim", "branch", "pr")):
            return False  # linked since the mark: it is not stalled work
        last = self._last_activity(pid, front)
        if last is None:
            return None
        try:
            hours = float(rec.get("stale_hours") or self.stale_hours)
        except (TypeError, ValueError):
            hours = self.stale_hours
        return datetime.now(timezone.utc) - last >= timedelta(hours=hours)

    def flush_notifications(self) -> dict[str, list[str]]:
        """Deliver queued stall notifications; retain anything that cannot be delivered.

        Delivery is at-least-once: a crash after the inbox line is written but before the queue is
        rewritten redelivers it next time. Anything not appended to the inbox is reported under
        ``pending`` — a failed or skipped delivery is never recorded as sent.
        """
        delivered: list[str] = []
        dropped: list[str] = []
        with self._lock():
            records = self._read_pending_unlocked()
            if not records:
                return {"delivered": [], "dropped": [], "pending": []}
            keep: list[dict[str, Any]] = []
            for rec in records:
                pid = str(rec.get("id"))
                still_true = self._pending_still_true_unlocked(rec)
                if still_true is False:
                    dropped.append(pid)
                    continue
                if still_true is None:
                    keep.append(rec)
                    continue
                try:
                    self._append_inbox_line_unlocked(str(rec.get("message") or ""))
                except OSError:
                    keep.append(rec)  # retained for the next run; NOT counted as delivered
                    continue
                delivered.append(pid)
            self._rewrite_pending_unlocked(keep)
        return {"delivered": delivered, "dropped": dropped,
                "pending": [str(r.get("id")) for r in keep]}

    # -- api
    def add(self, *, title: str, author: str, vendor: str, approved_at: str,
            body: str | None = None, body_path: Path | None = None, quote: str | None = None,
            pid: str | None = None, status: str = "approved", proof: str | None = None,
            dry_run: bool = False) -> str | dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"status {status!r} is not one of {STATUSES}")
        text = body if body is not None else (Path(body_path).read_text(encoding="utf-8") if body_path else "")
        new_id = pid if pid is not None else plan_id(title, text, author)
        if not ID_RE.match(str(new_id)):
            raise ValueError(f"invalid plan id {new_id!r}: expected {ID_RE.pattern}")
        detail = {"title": title, "vendor": vendor}
        front = {"id": new_id, "title": title, "author_session": author,
                 "author_proof": proof or author_proof(author, root=self.root), "vendor": vendor,
                 "approved_at": approved_at, "status": status, "updated_at": _utc()}
        if quote:
            front["operator_quote"] = quote
        if dry_run:
            # The preview is a read path: it takes no lock and creates nothing, so the store is
            # untouched even when it does not exist yet (AGENTS.md §6).
            existing = self._path(new_id)
            if existing.is_file():
                report = self._preview(
                    "add", new_id, front=parse_plan(existing.read_text(encoding="utf-8"))["front"],
                    body=None, event="add", detail=detail)
                report["already_registered"] = True
                report["ledger_reconcile_needed"] = not self._has_add_event(new_id)
                return report
            return self._preview("add", new_id, front=front, body=text, event="add", detail=detail)
        with self._lock():
            if self._path(new_id).is_file():
                # idempotent: the same plan is never written twice
                if not self._has_add_event(new_id):
                    # A crash between _write() and _event() left the plan file without its
                    # registration event; the retry repairs the ledger instead of reporting an
                    # incomplete registration as success.
                    self._event("add", new_id, **detail)
                return new_id
            self._write(new_id, front, text)
            self._event("add", new_id, **detail)
        return new_id

    def get(self, pid: str) -> dict[str, Any]:
        path = self._path(pid)
        if not path.is_file():
            raise KeyError(f"no plan {pid!r} in {self.plans}")
        doc = parse_plan(path.read_text(encoding="utf-8"))
        doc["front"].setdefault("id", pid)
        return doc

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        """Every plan in the store, held to the SAME containment as an id-addressed read.

        ``glob`` follows a symlink, so a plan-shaped link dropped in the store could otherwise be
        read by list()/stale() even though get() refuses it (review 2026-11-02, B1). A link that
        resolves outside the store is skipped here too.
        """
        rows = []
        for path in sorted(self.plans.glob("*.md")):
            try:
                path = self._path(path.stem)  # id rules + resolved containment
            except ValueError:
                continue  # a file that escapes the store is never served
            try:
                front = parse_plan(path.read_text(encoding="utf-8"))["front"]
            except OSError:
                continue  # one unreadable file must not take the whole listing down
            if not front:
                continue
            if status and front.get("status") != status:
                continue
            rows.append(front)
        return rows

    def _mutate(self, pid: str, event: str, change: dict[str, Any], *, dry_run: bool = False,
                action: str | None = None, revive_if_stalled: bool = False) -> dict[str, Any]:
        """One mutation under one lock.

        `revive_if_stalled` folds a second write (`status -> in_progress` for a stalled plan) into THIS
        lock. Doing it as two `_mutate` calls released the lock in between, so a concurrent `done` or
        `abandoned` could land there and be overwritten with `in_progress` (D52 triage KEEP_BLOCK #2489,
        plan_registry.py:509). The revival is also CONDITIONAL on the status read inside the lock, so it
        can never clobber a terminal state written a moment earlier.
        """
        if dry_run:
            # read path only: no lock, no write, nothing created
            doc = self.get(pid)
            front = {**doc["front"], **change, "updated_at": _utc()}
            detail = {k: v for k, v in change.items() if v is not None}
            report = self._preview(action or event, pid, front=front, body=doc["body"],
                                   event=event, detail=detail)
            if revive_if_stalled and str(front.get("status")) == "stalled":
                report["followup"] = {"event": "status", "id": pid, "detail": {"status": "in_progress"}}
                report["status"] = "in_progress"
                report["front"] = {**report["front"], "status": "in_progress"}
            return report
        with self._lock():
            doc = self.get(pid)
            front = {**doc["front"], **change, "updated_at": _utc()}
            revived = revive_if_stalled and str(front.get("status")) == "stalled"
            if revived:
                front["status"] = "in_progress"
            detail = {k: v for k, v in change.items() if v is not None}
            self._write(pid, front, doc["body"])
            self._event(event, pid, **detail)
            if revived:
                self._event("status", pid, status="in_progress")
        return front

    def link(self, pid: str, *, claim: str | None = None, branch: str | None = None,
             pr: int | None = None, dry_run: bool = False) -> dict[str, Any]:
        change = {k: v for k, v in (("claim", claim), ("branch", branch), ("pr", pr)) if v is not None}
        if not change:
            raise ValueError("link needs at least one of --claim, --branch, --pr")
        # One mutation, one lock: the link and the stalled->in_progress revival must not straddle a lock
        # boundary, or a concurrent terminal status gets overwritten (D52 triage, plan_registry.py:509).
        return self._mutate(pid, "link", change, dry_run=dry_run, revive_if_stalled=True)

    @staticmethod
    def _tick_step(doc: dict[str, Any], which: str, pid: str) -> tuple[list[str], int, str]:
        """Tick exactly one open step in ``doc``; return the new lines and the before/after text."""
        lines = doc["body"].splitlines()
        boxes = [i for i, ln in enumerate(lines) if re.match(r"^\s*[-*]\s*\[ \]\s+", ln)]
        target = None
        if which.isdigit():
            # A number names the step's POSITION, and positions must not shift when a step is ticked.
            # Indexing only the unticked steps renumbered every remaining step, so `step done 1` then
            # `step done 2` marked the first and the third.
            every = [i for i, ln in enumerate(lines) if re.match(r"^\s*[-*]\s*\[[ xX]\]\s+", ln)]
            n = int(which)
            if 1 <= n <= len(every):
                picked = every[n - 1]
                if re.match(r"^\s*[-*]\s*\[[xX]\]\s+", lines[picked]):
                    raise ValueError(f"step {n} in {pid} is already complete")
                target = picked
        else:
            needle = which.lower()
            target = next((i for i in boxes if needle in lines[i].lower()), None)
        if target is None:
            raise ValueError(f"no open step matching {which!r} in {pid}")
        before = lines[target].strip()
        lines[target] = re.sub(r"\[ \]", "[x]", lines[target], count=1)
        return lines, target, before

    def step_done(self, pid: str, which: str, *, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            # read path only: no lock, no write, nothing created
            doc = self.get(pid)
            lines, target, before = self._tick_step(doc, which, pid)
            detail = {"step": lines[target].strip()[:120]}
            report = self._preview("step_done", pid, front={**doc["front"], "updated_at": _utc()},
                                   body="\n".join(lines), event="step_done", detail=detail)
            report["step"] = {"before": before, "after": lines[target].strip()}
            return report
        with self._lock():
            doc = self.get(pid)
            lines, target, _ = self._tick_step(doc, which, pid)
            front = {**doc["front"], "updated_at": _utc()}
            detail = {"step": lines[target].strip()[:120]}
            self._write(pid, front, "\n".join(lines))
            self._event("step_done", pid, **detail)
        return front

    def set_status(self, pid: str, status: str, *, dry_run: bool = False) -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"status {status!r} is not one of {STATUSES}")
        return self._mutate(pid, "status", {"status": status}, dry_run=dry_run, action="set-status")

    def _stalled_notification(self, pid: str, limit: float) -> str:
        prefix = self.cfg.get("stalled_prefix") or "[PLAN-STALLED]"
        return (f"{prefix} {pid}: approved or in_progress for over {limit:g}h with no claim, "
                f"branch or PR ({_utc()})")

    def _mark_stalled(self, pid: str, *, current: datetime | None = None,
                      limit: float | None = None) -> bool:
        """Re-check under the lock: a linked OR freshly resumed plan is NOT stale.

        The scan's activity reading is not trusted across the lock boundary: the timestamps are
        re-read here, under the same lock that flips the status, so a plan resumed (or linked)
        while the scan ran can never be overwritten as stalled.
        """
        limit = float(limit if limit is not None else self.stale_hours)
        current = current or datetime.now(timezone.utc)
        with self._lock():
            doc = self.get(pid)
            front = doc["front"]
            if any(front.get(k) for k in ("claim", "branch", "pr")):
                return False
            if str(front.get("status")) not in STALE_STATUSES:
                return False
            last = self._last_activity(pid, front)
            if last is None or current - last < timedelta(hours=limit):
                return False  # resumed (or activity unknown) between the scan and this lock
            # Durable intent BEFORE the status write: a crash here leaves a retryable notification
            # rather than a stalled plan whose alert can never be sent.
            self._queue_notification_unlocked(pid, self._stalled_notification(pid, limit))
            self._write(pid, {**front, "status": "stalled", "stalled_since": _utc(), "updated_at": _utc()},
                        doc["body"])
            self._event("stalled", pid)
        return True

    def stale(self, *, now: str | None = None, apply: bool = False, hours: float | None = None) -> list[str]:
        """Approved/in-progress plans with no claim, branch or PR and no activity for N hours."""
        limit = float(hours if hours is not None else self.stale_hours)
        current = _parse_ts(now or _utc()) or datetime.now(timezone.utc)
        flagged: list[str] = []
        for front in self.list():
            if front.get("status") not in STALE_STATUSES:
                continue
            if any(front.get(k) for k in ("claim", "branch", "pr")):
                continue
            last = self._last_activity(str(front["id"]), front)
            if last is None or current - last < timedelta(hours=limit):
                continue
            if apply and not self._mark_stalled(str(front["id"]), current=current, limit=limit):
                continue  # linked or resumed between the scan and the lock
            flagged.append(str(front["id"]))
        if apply:
            # Retry delivery independently of stale-plan eligibility: a plan already marked stalled
            # is no longer selected above, yet its undelivered alert must still reach the coordinator.
            self.last_delivery = self.flush_notifications()
            if self.last_delivery["pending"]:
                print("plan_registry: "
                      f"{len(self.last_delivery['pending'])} stall notification(s) could not be "
                      "delivered and remain queued: "
                      + ", ".join(self.last_delivery["pending"]), file=sys.stderr)
        return flagged


# ------------------------------------------------------------------ cli
def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=1, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--state-root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("--title", required=True)
    a.add_argument("--file", default=None)
    a.add_argument("--body", default=None)
    a.add_argument("--author", required=True)
    a.add_argument("--vendor", default="other")
    a.add_argument("--approved-at", default=None)
    a.add_argument("--quote", default=None)
    a.add_argument("--id", default=None)
    a.add_argument("--json", action="store_true")
    a.add_argument("--dry-run", action="store_true",
                   help="report the intended registration; write neither the plan nor a ledger line")

    sub.add_parser("status")
    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=STATUSES, default=None)
    ls.add_argument("--json", action="store_true")
    sh = sub.add_parser("show")
    sh.add_argument("plan_id")
    sh.add_argument("--json", action="store_true")

    lk = sub.add_parser("link")
    lk.add_argument("plan_id")
    lk.add_argument("--claim", default=None)
    lk.add_argument("--branch", default=None)
    lk.add_argument("--pr", type=int, default=None)
    lk.add_argument("--dry-run", action="store_true",
                    help="report the intended link; write neither the plan nor a ledger line")

    st = sub.add_parser("set-status")
    st.add_argument("plan_id")
    st.add_argument("status", choices=STATUSES)
    st.add_argument("--dry-run", action="store_true",
                    help="report the intended status change; write neither the plan nor a ledger line")

    sp = sub.add_parser("step")
    sp.add_argument("action", choices=["done"])
    sp.add_argument("plan_id")
    sp.add_argument("which")
    sp.add_argument("--dry-run", action="store_true",
                    help="report the intended step tick; write neither the plan nor a ledger line")

    sl = sub.add_parser("stale")
    sl.add_argument("--hours", type=float, default=None)
    sl.add_argument("--apply", action="store_true")

    args = ap.parse_args(argv)
    r = Registry(Path(args.state_root) if args.state_root else None)
    try:
        if args.cmd == "add":
            result = r.add(title=args.title, author=args.author, vendor=args.vendor,
                           approved_at=args.approved_at or _utc(), body=args.body,
                           body_path=Path(args.file) if args.file else None, quote=args.quote,
                           pid=args.id, dry_run=args.dry_run)
            if isinstance(result, dict):
                _print(result)
            else:
                _print({"id": result}) if args.json else print(result)
        elif args.cmd == "status":
            counts: dict[str, int] = {s: 0 for s in STATUSES}
            for row in r.list():
                counts[str(row.get("status"))] = counts.get(str(row.get("status")), 0) + 1
            print(" ".join(f"{k}={v}" for k, v in counts.items() if v))
        elif args.cmd == "list":
            rows = r.list(args.status)
            if args.json:
                _print(rows)
            else:
                for row in rows:
                    linkbits = " ".join(str(row[k]) for k in ("claim", "branch", "pr") if row.get(k))
                    print(f"{row.get('id')}  {row.get('status'):<11} {row.get('vendor', ''):<7} "
                          f"{str(row.get('title'))[:70]}  {linkbits}")
        elif args.cmd == "show":
            doc = r.get(args.plan_id)
            _print(doc) if args.json else print(render_plan(doc["front"], doc["body"]))
        elif args.cmd == "link":
            _print(r.link(args.plan_id, claim=args.claim, branch=args.branch, pr=args.pr,
                          dry_run=args.dry_run))
        elif args.cmd == "set-status":
            _print(r.set_status(args.plan_id, args.status, dry_run=args.dry_run))
        elif args.cmd == "step":
            _print(r.step_done(args.plan_id, args.which, dry_run=args.dry_run))
        elif args.cmd == "stale":
            flagged = r.stale(hours=args.hours, apply=args.apply)
            _print({"flagged": flagged, "applied": bool(args.apply),
                    "delivered": r.last_delivery["delivered"],
                    "pending": r.last_delivery["pending"]})
    except (KeyError, ValueError, OSError) as exc:
        print(f"plan_registry: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
