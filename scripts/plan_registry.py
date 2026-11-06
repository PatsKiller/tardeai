#!/usr/bin/env python3
"""Plan registry — every registered plan persisted on the server for every agent.

A plan is written ONCE to
``${TRADEAI_STATE_ROOT}/data/coordination/plans/<plan-id>.md`` with front-matter, and its lifecycle
is followed from there: the agent that picks it up links its claim, branch and PR; steps are ticked
as they are done; the status moves registered -> in_progress -> done (or abandoned/stalled). Every
mutation also appends one line to the append-only ``ledger.jsonl`` beside the plans.

A registration is NOT an approval: ``add`` defaults to ``status: registered`` and only an explicit
``status="approved"`` / ``--status approved`` records that a plan was approved. The hook registers
plans; it never claims approval.

Claude Code registers plans through the PostToolUse hook on ``ExitPlanMode`` (see
``docs/ops/PLAN_REGISTRY.md`` for the settings snippet; the repository never edits the operator's
``~/.claude/settings.json``). Codex, Cursor and every other vendor use this CLI:

    python3 scripts/plan_registry.py add --title "..." --file plan.md --author <session> --vendor codex
    python3 scripts/plan_registry.py status
    python3 scripts/plan_registry.py list [--status approved] [--json]
    python3 scripts/plan_registry.py show <plan-id>
    python3 scripts/plan_registry.py link <plan-id> --claim <claim-id> --branch wt/x --pr 123
    python3 scripts/plan_registry.py step done <plan-id> <step text or number>
    python3 scripts/plan_registry.py set-status <plan-id> in_progress|done|abandoned|stalled
    python3 scripts/plan_registry.py stale [--hours N] [--apply]

Writes are locked (flock) and atomic (tmp + replace); the ledger is append-only. Stdlib only.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

_LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "plan_registry.json"
STATUSES = ("registered", "approved", "in_progress", "done", "abandoned", "stalled")
STALE_STATUSES = ("approved", "in_progress")
VIEW_SCHEMA = "PlanRegistryView@v1"
#: Fixed store-state reasons. They are served over the read-only API, so they must never carry a
#: filesystem path or exception text.
STORE_ABSENT_REASON = "the plan store directory does not exist"
STORE_UNLISTABLE_REASON = "the plan store directory cannot be listed"
UNREADABLE_FILE_REASON = "the plan file cannot be read"
UNADDRESSABLE_NAME_REASON = "the plan filename is not a valid plan id"
NOT_REGULAR_REASON = "the plan entry is not a regular file"
_STEP_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s+(.*)$")
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
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


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


def front_matter_gap(text: str) -> str | None:
    """Why a plan file has no usable front matter, or ``None`` when it has one.

    ``parse_plan`` is deliberately lenient — an unterminated block is treated as body and parsed
    values fall back to raw strings — so an empty ``front`` is the signal that the file could not be
    read as a plan. The view turns that into an explicit ``unreadable`` row instead of dropping it.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "no front matter at the start of the file"
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            if any(":" in ln for ln in lines[1:i]):
                return None
            return "front matter has no key: value lines"
    return "truncated front matter (no closing --- marker)"


def unreadable_entry(path: Path, reason: str) -> dict[str, Any]:
    """A visible gap for a plan file whose front matter cannot be read.

    The page promises every plan, so the file is shown by the id and filename that could be read —
    never silently dropped, which made a real approved plan look like it did not exist.
    """
    return {"id": path.stem, "filename": path.name, "title": path.name,
            "status": "unreadable", "reason": reason,
            "steps": [], "steps_done": 0, "steps_left": 0}


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
def _open_regular(path: Path, flags: int, mode: int, what: str) -> int:
    """Open a store metadata file and refuse anything that is not a regular file.

    ``O_NOFOLLOW`` stops a planted symlink, but it does not stop a FIFO: opening a named pipe blocks
    until a reader or a writer exists, so a stray ``ledger.jsonl`` FIFO hung every ``add``. The
    ``fstat`` is on the descriptor just opened, so it cannot be raced by a rename.
    """
    try:
        # O_NONBLOCK is what actually stops the hang: open(O_WRONLY) on a FIFO blocks before it
        # returns a descriptor, so the fstat below would never run. It is a no-op for a regular file.
        fd = os.open(path, flags | os.O_NONBLOCK, mode)
    except OSError as exc:
        raise ValueError(f"{what} {path} is not usable ({exc.strerror}); refusing") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"{what} {path} is not a regular file; refusing")
    except BaseException:
        os.close(fd)
        raise
    return fd


class Registry:
    def __init__(self, root: Path | None = None, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self.root = Path(root or state_root())
        self.plans = self.root / str(self.cfg.get("plans_rel") or "data/coordination/plans")
        self.ledger = self.plans / "ledger.jsonl"
        #: the live coordinator inbox DIRECTORY; the stale scan writes one dated notice per run there
        self.inbox = self.root / str(self.cfg.get("inbox_rel") or "data/coordination/coordinator/inbox/codex")
        self.stale_hours = float(self.cfg.get("stale_hours") or 72)

    # -- io
    @contextmanager
    def _lock(self) -> Iterator[None]:
        # O_NOFOLLOW: the lock file is opened with the same containment rule as everything else in the
        # store. A symlink planted at plans/.lock is an error (ELOOP), never a lock held on some other
        # file; without this the store's own lock could be redirected outside it.
        self.plans.mkdir(parents=True, exist_ok=True)
        lock = self.plans / ".lock"
        fd = _open_regular(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, "plan store lock")
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
            except OSError as exc:
                _LOG.warning("plan_registry: could not remove temp file %s: %s", tmp, exc)
            raise

    def _event(self, event: str, pid: str, **detail: Any) -> None:
        # O_NOFOLLOW: the append-only ledger cannot be redirected outside the store by a planted link.
        # A FIFO (or any non-regular file) is refused before the open can block waiting for a peer.
        self.plans.mkdir(parents=True, exist_ok=True)
        fd = _open_regular(self.ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600, "plan ledger")
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
        """The last real plan event: approval or a ledger entry. Not the file's insert time."""
        last = _parse_ts(front.get("approved_at"))
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
        except OSError as exc:
            # Unreadable ledger: only front-matter timestamps remain; say so rather than looking complete.
            _LOG.warning("plan_registry: ledger unreadable for last activity of %s: %s", pid, exc)
        return last

    # -- api
    def add(self, *, title: str, author: str, vendor: str, approved_at: str | None = None,
            body: str | None = None, body_path: Path | None = None, quote: str | None = None,
            pid: str | None = None, status: str = "registered", proof: str | None = None) -> str:
        if status not in STATUSES:
            raise ValueError(f"status {status!r} is not one of {STATUSES}")
        text = body if body is not None else (Path(body_path).read_text(encoding="utf-8") if body_path else "")
        new_id = pid if pid is not None else plan_id(title, text, author)
        if not ID_RE.match(str(new_id)):
            raise ValueError(f"invalid plan id {new_id!r}: expected {ID_RE.pattern}")
        with self._lock():
            if self._path(new_id).is_file():
                return new_id  # idempotent: the same plan is never written twice
            front = {"id": new_id, "title": title, "author_session": author,
                     "author_proof": proof or author_proof(author, root=self.root), "vendor": vendor,
                     "status": status, "updated_at": _utc()}
            if approved_at:
                # Never defaulted from the clock: an approval time is recorded only when the caller
                # supplies it deliberately. Stamping a registration with its write time would read as
                # an approval the registry never received (review 4, 2026-11-03).
                front["approved_at"] = approved_at
            if quote:
                front["operator_quote"] = quote
            self._write(new_id, front, text)
            self._event("add", new_id, title=title, vendor=vendor)
        return new_id

    def get(self, pid: str) -> dict[str, Any]:
        path = self._path(pid)
        if not path.is_file():
            raise KeyError(f"no plan {pid!r} in {self.plans}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # A corrupt file is not a readable plan: KeyError keeps the API on its fixed 404 path
            # instead of publishing a 500 with the decode error.
            raise KeyError(f"no readable plan {pid!r} in {self.plans}") from None
        doc = parse_plan(text)
        if not doc["front"]:
            # parse_plan is lenient: a truncated/missing front-matter block is returned as body with
            # an empty front. That is not a readable plan, so detail takes the same fixed 404 path as
            # a non-UTF-8 file instead of publishing a plan with zero steps.
            raise KeyError(f"no readable plan {pid!r} in {self.plans}")
        doc["front"].setdefault("id", pid)
        return doc

    def _iter_plans(self) -> Iterator[Path]:
        """Every contained plan file, whatever its name.

        Containment is proven on each entry: a symlink (which ``glob`` would follow) and any path
        that resolves outside the store is skipped, exactly as ``get`` refuses it. A name that
        merely fails the id rule is NOT an escape — it is yielded so the listing can show it as an
        ``unreadable`` row instead of silently dropping a plan (review 4 ground 2).
        """
        base = self.plans.resolve()
        for path in sorted(self.plans.glob("*.md")):
            if path.is_symlink():
                continue
            try:
                path.resolve().relative_to(base)
            except (OSError, ValueError):
                continue
            yield path

    def _classify(self, path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """One contained file as ``(doc, gap)`` — exactly one of the two is non-None.

        A name the id rule refuses cannot be addressed by ``get()``, so it is shown as an
        ``unreadable`` row rather than dropped. A non-regular entry (FIFO, socket, device) is the
        same kind of gap and is never opened: ``read_text`` on a named pipe blocks forever, which
        would hang the read-only listing and the API request that serves it. Reasons are fixed
        strings: they are served over the read-only API and must never carry a filesystem path or
        exception text.
        """
        try:
            entry = path.lstat()
        except OSError:
            return None, unreadable_entry(path, UNREADABLE_FILE_REASON)
        if not stat.S_ISREG(entry.st_mode):
            return None, unreadable_entry(path, NOT_REGULAR_REASON)
        if not ID_RE.match(path.stem):
            return None, unreadable_entry(path, UNADDRESSABLE_NAME_REASON)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            # one unreadable file must not take the whole listing down, but it is a visible gap
            return None, unreadable_entry(path, UNREADABLE_FILE_REASON)
        except UnicodeDecodeError:
            return None, unreadable_entry(path, "file is not valid UTF-8 text")
        doc = parse_plan(text)
        if not doc["front"]:
            # Same gap the view shows: a file the store holds but cannot parse is still listed.
            return None, unreadable_entry(path, front_matter_gap(text) or "front matter is not readable")
        return doc, None

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        """Every plan in the store, held to the SAME containment as an id-addressed read.

        Each parsed row carries the id the store actually addresses it by — the file stem, which
        is what ``get()`` opens — so a plan whose front matter has no ``id`` still has an identity
        (review 4 ground 1: ``stale`` raised ``KeyError: 'id'`` on one). A contained file whose
        name is not a valid id is listed as an ``unreadable`` row, never dropped.
        """
        rows = []
        for path in self._iter_plans():
            doc, gap = self._classify(path)
            if gap is not None:
                rows.append(gap)
                continue
            front = doc["front"]
            if status and front.get("status") != status:
                continue
            rows.append({**front, "id": path.stem})
        return rows

    def _mutate(self, pid: str, event: str, change: dict[str, Any]) -> dict[str, Any]:
        with self._lock():
            doc = self.get(pid)
            front = {**doc["front"], **change, "updated_at": _utc()}
            self._write(pid, front, doc["body"])
            self._event(event, pid, **{k: v for k, v in change.items() if v is not None})
        return front

    def link(self, pid: str, *, claim: str | None = None, branch: str | None = None,
             pr: int | None = None) -> dict[str, Any]:
        change = {k: v for k, v in (("claim", claim), ("branch", branch), ("pr", pr)) if v is not None}
        if not change:
            raise ValueError("link needs at least one of --claim, --branch, --pr")
        front = self._mutate(pid, "link", change)
        if str(front.get("status")) == "stalled":  # activity revives a stalled plan
            front = self._mutate(pid, "status", {"status": "in_progress"})
        return front

    def step_done(self, pid: str, which: str) -> dict[str, Any]:
        with self._lock():
            doc = self.get(pid)
            lines = doc["body"].splitlines()
            boxes = [i for i, ln in enumerate(lines) if re.match(r"^\s*[-*]\s*\[ \]\s+", ln)]
            target = None
            if which.isdigit():
                n = int(which)
                if 1 <= n <= len(boxes):
                    target = boxes[n - 1]
            else:
                needle = which.lower()
                target = next((i for i in boxes if needle in lines[i].lower()), None)
            if target is None:
                raise ValueError(f"no open step matching {which!r} in {pid}")
            lines[target] = re.sub(r"\[ \]", "[x]", lines[target], count=1)
            front = {**doc["front"], "updated_at": _utc()}
            self._write(pid, front, "\n".join(lines))
            self._event("step_done", pid, step=lines[target].strip()[:120])
        return front

    def set_status(self, pid: str, status: str) -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"status {status!r} is not one of {STATUSES}")
        return self._mutate(pid, "status", {"status": status})

    def _mark_stalled(self, pid: str) -> bool:
        """Re-check under the lock: a plan linked while the scan ran is NOT stale."""
        with self._lock():
            doc = self.get(pid)
            front = doc["front"]
            if any(front.get(k) for k in ("claim", "branch", "pr")):
                return False
            if str(front.get("status")) not in STALE_STATUSES:
                return False
            self._write(pid, {**front, "status": "stalled", "stalled_since": _utc(), "updated_at": _utc()},
                        doc["body"])
            self._event("stalled", pid)
        return True

    def _entry(self, pid: str, doc: dict[str, Any], *, body: bool) -> dict[str, Any]:
        steps = []
        for line in doc["body"].splitlines():
            m = _STEP_RE.match(line)
            if m:
                steps.append({"done": m.group(1).lower() == "x", "text": m.group(2).strip()[:300]})
        entry = {**{k: doc["front"].get(k) for k in ("id", "title", "author_session", "author_proof",
                                                    "vendor", "approved_at",
                                                    "operator_quote", "status", "claim", "branch", "pr",
                                                    "updated_at", "stalled_since")},
                 "id": doc["front"].get("id") or pid, "steps": steps,
                 "steps_done": sum(1 for x in steps if x["done"]), "steps_left": sum(1 for x in steps if not x["done"])}
        if body:
            entry["body"] = doc["body"]
        return entry

    def _store_state(self) -> dict[str, Any]:
        """Whether the plan store can actually be listed, so a gap never renders as an empty store.

        ``absent`` and ``unlistable`` carry fixed strings — no filesystem path, no exception text —
        because they are served to every viewer over the read-only API. ``os.listdir`` is a probe
        only: ``_iter_plans`` stays the row source, so its containment rules are unchanged.
        """
        try:
            if not self.plans.is_dir():
                return {"state": "absent", "reason": STORE_ABSENT_REASON}
        except OSError:
            return {"state": "absent", "reason": STORE_ABSENT_REASON}
        try:
            os.listdir(self.plans)
        except OSError:
            return {"state": "unlistable", "reason": STORE_UNLISTABLE_REASON}
        return {"state": "ok", "reason": None}

    def view(self, pid: str | None = None) -> dict[str, Any]:
        """The read-only shape served by /api/v2/plans (list, or one plan with its body).

        ``store`` and ``as_of`` are always present: a directory that was never read (absent or
        unlistable) is reported as such instead of rendering byte-identically to a genuinely empty
        store. ``plans`` stays ``[]`` on a gap — no row is ever fabricated.
        """
        store = self._store_state()
        if pid:
            entry = self._entry(pid, self.get(pid), body=True)
            return {"schema": VIEW_SCHEMA, "as_of": _utc(), "store": store, "plan": entry}
        rows = []
        if store["state"] == "ok":  # build the listing only after the store state is established
            for path in self._iter_plans():
                doc, gap = self._classify(path)
                if gap is not None:
                    rows.append(gap)
                else:
                    rows.append(self._entry(path.stem, doc, body=False))
        rows.sort(key=lambda r: str(r.get("approved_at") or ""), reverse=True)
        return {"schema": VIEW_SCHEMA, "as_of": _utc(), "store": store, "plans": rows}

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
            pid = str(front.get("id") or "")
            if not pid:
                # ``list()`` gives every row it returns the id the store addresses it by, so this
                # is defensive only. Record the skip instead of raising KeyError on the scan.
                print(
                    f"plan_registry: stale scan skipped a {front.get('status')!r} plan row with no id", file=sys.stderr
                )
                continue
            last = self._last_activity(pid, front)
            if last is None or current - last < timedelta(hours=limit):
                continue
            if apply and not self._mark_stalled(pid):
                continue  # linked or resumed between the scan and the lock
            flagged.append(pid)
        if apply and flagged:
            self._write_stall_notice(flagged, limit)
        return flagged

    def _write_stall_notice(self, flagged: list[str], limit: float) -> None:
        """One dated notice per run, inside the live coordinator inbox DIRECTORY.

        The old destination was a single ``inbox.md`` file that no coordinator reads; the live inbox is
        ``data/coordination/coordinator/inbox/<coordinator>/``. A per-run file lands where the lead
        actually looks. The directory is opened O_NOFOLLOW so a planted symlink cannot redirect the write,
        and the file is created O_EXCL|O_NOFOLLOW so an existing name is never appended to or followed.
        """
        inbox_dir = self.inbox
        inbox_dir.mkdir(parents=True, exist_ok=True)
        try:
            dirfd = os.open(inbox_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise ValueError(f"coordinator inbox {inbox_dir} is not a directory "
                             f"({exc.strerror}); refusing") from None
        name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-plan-stalled.md"
        prefix = self.cfg.get("stalled_prefix") or "[PLAN-STALLED]"
        lines = [f"# {prefix} plans", "",
                 f"{len(flagged)} plan(s) approved or in_progress for over {limit:g}h with no claim, "
                 f"branch or PR ({_utc()}).", ""]
        lines += [f"- {pid}" for pid in flagged]
        lines.append("")
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines))
                    fh.flush()
                    os.fsync(fh.fileno())
            finally:
                pass
            os.fsync(dirfd)  # the directory entry is durable too
        finally:
            os.close(dirfd)


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
    a.add_argument("--status", choices=STATUSES, default="registered",
                   help="registered (default) records the plan; approved claims an approval")
    a.add_argument("--json", action="store_true")

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

    st = sub.add_parser("set-status")
    st.add_argument("plan_id")
    st.add_argument("status", choices=STATUSES)

    sp = sub.add_parser("step")
    sp.add_argument("action", choices=["done"])
    sp.add_argument("plan_id")
    sp.add_argument("which")

    sl = sub.add_parser("stale")
    sl.add_argument("--hours", type=float, default=None)
    sl.add_argument("--apply", action="store_true")

    args = ap.parse_args(argv)
    r = Registry(Path(args.state_root) if args.state_root else None)
    try:
        if args.cmd == "add":
            pid = r.add(title=args.title, author=args.author, vendor=args.vendor,
                        approved_at=args.approved_at, body=args.body,
                        body_path=Path(args.file) if args.file else None, quote=args.quote, pid=args.id,
                        status=args.status)
            _print({"id": pid}) if args.json else print(pid)
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
            _print(r.link(args.plan_id, claim=args.claim, branch=args.branch, pr=args.pr))
        elif args.cmd == "set-status":
            _print(r.set_status(args.plan_id, args.status))
        elif args.cmd == "step":
            _print(r.step_done(args.plan_id, args.which))
        elif args.cmd == "stale":
            flagged = r.stale(hours=args.hours, apply=args.apply)
            _print({"flagged": flagged, "applied": bool(args.apply)})
    except (KeyError, ValueError, OSError) as exc:
        print(f"plan_registry: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
