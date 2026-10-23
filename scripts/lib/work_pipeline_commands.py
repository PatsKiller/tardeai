"""Work pipeline commands: the operator's one-click actions on the Work pipeline (Tier 1), one governed endpoint.

Operator 2026-10-23, on the approved Work pipeline mockup: "the HTML looks great. But nothing is actionable on
there", then approved both action tiers ("both"). This module is Tier 1: one click, CSRF and same-origin, actor from
auth (never from the request body), idempotent, audited. Served as ``POST /api/v2/coordination/commands``.

Commands (``COMMANDS``); every one writes only the coordination store under the claims directory:

* ``note``                 {item, text}             operator line on the item: the claim worklog (Decisions, tagged
                                                     "operator") when the item has a claim, else the task history,
                                                     else the PR's note list in the batch queue.
* ``set_priority``         {task_id, priority 1-4}  task-board write.
* ``hold`` / ``unhold``    {item, reason?}          a task (``agent_claim.py next``/``take`` skip a held task) or a PR
                                                     (recorded in the batch queue's ``held_prs``; the batch builder
                                                     skips it).
* ``batch_add`` / ``batch_remove`` {pr}             the ordered next-batch list (``next_batch``) in the batch queue.
                                                     ``batch_add`` refuses a held PR and, when the census knows it, a PR
                                                     that is not open, not CI green, or already in an open batch.
* ``task_add``             {title, kind, areas, priority?, acceptance?}   a new task on the board (source operator).
* ``task_split``           {task_id, parts:[{title, areas?, acceptance?}]}
* ``release_stale_claim``  {claim_id}               only for a RED-stale claim (no heartbeat for the stale window and
                                                     pre-PR, or CI failing): released ``abandoned`` with
                                                     ``released_by=operator:<login>``, worklog kept with a final
                                                     summary, its task (if any) back on the board, audited as an
                                                     operator takeover.

The batch queue (``<claims_dir>/tasks/batch_queue.json``, ``BatchQueue@v1``) is where a batch builder reads which
green PRs go into the next release batch, in order, and which PRs are held: ``python3 scripts/batch_queue.py show``.

Refused here, always (``NEVER_ON_BOARD``): broker orders, stops, kill-switch clearing, issuing grants. Tier 2
(approve design, contract reviewed, merge, release, approval-list item) is not served by this endpoint: it needs a
passkey assertion per act and goes through the host applier (follow-up PR).

Order of checks on every POST: method -> operator principal (``tailnet:<login>`` on the serve_proxy listener, login
allowlisted; the service token -- agents, n8n, cron -- is refused) -> CSRF (``cc_auth.command_csrf_check``, enforced
whatever report_only says) -> idempotency key -> the command's own validation. Every outcome, refusals included, is
one append-only line in ``<claims_dir>/pipeline/commands_audit.jsonl`` (fsynced). A repeated idempotency key replays
the recorded result and writes nothing.

AUTHORITY: OPERATOR_ONLY (coordination files only; no broker, DB, GitHub, scheduler or remote). MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

try:
    from scripts.lib import agent_claim_board as B
    from scripts.lib import agent_task_board as TB
except ImportError:  # scripts/ on sys.path (api_v2)
    from lib import agent_claim_board as B  # type: ignore[no-redef]
    from lib import agent_task_board as TB  # type: ignore[no-redef]

PATH = "/api/v2/coordination/commands"
AUDIT_SCHEMA = "WorkPipelineCommandAudit@v1"
QUEUE_SCHEMA = "BatchQueue@v1"
QUEUE_NAME = "batch_queue.json"
PIPELINE_DIRNAME = "pipeline"
AUDIT_NAME = "commands_audit.jsonl"
SERVE_PROXY = "serve_proxy"
IDEM_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,100}$")
PR_RE = re.compile(r"^(?:PR-|#)?(\d{1,7})$")
COMMANDS = (
    "note",
    "set_priority",
    "hold",
    "unhold",
    "batch_add",
    "batch_remove",
    "task_add",
    "task_split",
    "release_stale_claim",
)
TIER2 = ("approve_design", "contract_reviewed", "merge_pr", "release_now", "approve_item")
NEVER_ON_BOARD = (
    "order",
    "place_order",
    "cancel_order",
    "stop",
    "set_stop",
    "kill_switch_clear",
    "clear_kill_switch",
    "issue_grant",
    "grant",
)
AUDIT_TAIL_BYTES = 512 * 1024
MAX_NOTES_PER_PR = 20
MAX_QUEUE = 60


class CommandError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.status = status
        self.code = code
        self.detail = detail


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------------------------- context


@dataclass
class Ctx:
    principal: Callable[[], str]
    listener: Callable[[], Optional[str]]
    csrf: Callable[[str, str], tuple[bool, str]]
    allowed_logins: frozenset
    claims_dir: Optional[Path] = None
    census: Callable[[], Optional[Mapping[str, Any]]] = field(default=lambda: None)
    now: Callable[[], datetime] = _utc_now


def _default_ctx() -> Ctx:
    try:
        from lib import cc_auth  # type: ignore
    except ImportError:  # pragma: no cover
        from scripts.lib import cc_auth  # type: ignore
    auth_cfg = cc_auth.load_config()

    def listener() -> Optional[str]:
        return (cc_auth.current_request_context() or {}).get("listener")

    def census() -> Optional[Mapping[str, Any]]:
        try:
            try:
                from scripts.lib.work_pipeline import work_pipeline
            except ImportError:
                from lib.work_pipeline import work_pipeline  # type: ignore[no-redef]
            return work_pipeline().census.snapshot()[0]  # never refreshes: the last census only
        except Exception:  # noqa: BLE001 - validation degrades to "census unknown"
            return None

    return Ctx(
        principal=cc_auth.current_principal,
        listener=listener,
        csrf=lambda m, p: cc_auth.command_csrf_check(auth_cfg, m, p),
        allowed_logins=frozenset(auth_cfg.allowed_logins),
        census=census,
    )


_CTX: Optional[Ctx] = None


def context() -> Ctx:
    global _CTX
    if _CTX is None:
        _CTX = _default_ctx()
    return _CTX


def operator_of(ctx: Ctx) -> Optional[str]:
    """``tailnet:<login>`` when the request is the operator's on the serve_proxy listener, else None. Never the body."""
    p = ctx.principal() or ""
    if not p.startswith("tailnet:") or ctx.listener() != SERVE_PROXY:
        return None
    login = p[len("tailnet:") :].strip().lower()
    return p if login and login in ctx.allowed_logins else None


# --------------------------------------------------------------------------------------------- stores


def claims_dir_of(ctx: Ctx) -> Path:
    return Path(ctx.claims_dir) if ctx.claims_dir else B.default_claims_dir()


def audit_path(claims_dir: Path) -> Path:
    return Path(claims_dir) / PIPELINE_DIRNAME / AUDIT_NAME


def queue_path(claims_dir: Path) -> Path:
    return Path(claims_dir) / TB.TASKS_DIRNAME / QUEUE_NAME


def append_audit(claims_dir: Path, row: Mapping[str, Any]) -> None:
    p = audit_path(claims_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"schema": AUDIT_SCHEMA, **row}, sort_keys=True, default=str) + "\n"
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def find_idempotent(claims_dir: Path, key: str) -> Optional[dict[str, Any]]:
    """The last audited OK result for ``key`` from a bounded tail of the audit file, else None."""
    p = audit_path(claims_dir)
    try:
        with open(p, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - AUDIT_TAIL_BYTES))
            text = fh.read(AUDIT_TAIL_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    hit = None
    for ln in text.splitlines():
        if key not in ln:
            continue
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if row.get("idempotency_key") == key and row.get("outcome") == "ok":
            hit = row
    return hit


def empty_queue() -> dict[str, Any]:
    return {"schema": QUEUE_SCHEMA, "next_batch": [], "held_prs": {}, "pr_notes": {}, "updated_at": None, "history": []}


def read_queue(claims_dir: Path | str | None = None) -> dict[str, Any]:
    """The batch queue (read-only, never creates it). What a batch builder reads before building a batch."""
    p = queue_path(Path(claims_dir) if claims_dir else B.default_claims_dir())
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_queue()
    if not isinstance(doc, dict) or doc.get("schema") != QUEUE_SCHEMA:
        return empty_queue()
    base = empty_queue()
    base.update({k: doc.get(k) or base[k] for k in base})
    return base


def _write_queue(claims_dir: Path, doc: Mapping[str, Any]) -> None:
    p = queue_path(claims_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.parent / f".{p.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(p))


@contextmanager
def _queue_locked(claims_dir: Path) -> Iterator[dict[str, Any]]:
    d = Path(claims_dir) / TB.TASKS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".task.lock", "a", encoding="utf-8") as lock:  # the task board's lock: one writer at a time
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            doc = read_queue(claims_dir)
            yield doc
            doc["history"] = list(doc.get("history") or [])[-200:]
            _write_queue(claims_dir, doc)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def batch_builder_view(claims_dir: Path | str | None = None) -> dict[str, Any]:
    """For the batch builder: PRs to include in order (held ones dropped) and the held set."""
    q = read_queue(claims_dir)
    held = {str(k) for k in (q.get("held_prs") or {})}
    order = [e for e in q.get("next_batch") or [] if str(e.get("pr")) not in held]
    return {"next_batch": [int(e["pr"]) for e in order], "held_prs": sorted(int(k) for k in held), "queue": q}


# --------------------------------------------------------------------------------------------- targets


def _pr(value: Any) -> Optional[int]:
    m = PR_RE.match(str(value or "").strip())
    return int(m.group(1)) if m else None


def _target(item: Any) -> tuple[str, Any]:
    s = str(item or "").strip()
    if TB.valid_task_id(s):
        return "task", s
    if B.valid_claim_id(s):
        return "claim", s
    n = _pr(s)
    if n is not None:
        return "pr", n
    raise CommandError(400, "BAD_ITEM", f"item {s[:60]!r} is not a task id, claim id or PR number")


def _text(params: Mapping[str, Any], key: str, n: int, *, required: bool = True) -> Optional[str]:
    v = B.clip(params.get(key), n)
    if required and not (v or "").strip():
        raise CommandError(400, "PARAMS_INVALID", f"{key} is required")
    return v


# --------------------------------------------------------------------------------------------- commands


def _boards(claims_dir: Path, now: Callable[[], datetime]) -> tuple["B.ClaimBoard", "TB.TaskBoard"]:
    cb = B.ClaimBoard(claims_dir, now=now)
    return cb, TB.TaskBoard(cb)


def cmd_note(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    text = _text(p, "text", 1000)
    kind, ref = _target(p.get("item"))
    cb, tb = _boards(cd, ctx.now)
    line = f"operator ({op}): {text}"
    if kind == "task":
        try:
            t = tb.get(ref)
        except TB.TaskError as exc:
            raise CommandError(404, "NOT_FOUND", str(exc)) from None
        if t.get("claim_id") and cb.worklog(t["claim_id"]).exists():
            cb.worklog(t["claim_id"]).note(line)
            return {"wrote": "worklog", "claim_id": t["claim_id"], "task_id": ref}
        tb.note(ref, text or "", by=op)
        return {"wrote": "task_history", "task_id": ref}
    if kind == "claim":
        wl = cb.worklog(ref)
        if not wl.exists():
            raise CommandError(404, "NOT_FOUND", f"claim {ref} has no worklog")
        wl.note(line)
        return {"wrote": "worklog", "claim_id": ref}
    # a PR: its claims' worklogs when it has any, else the batch queue's note list
    views = [v for v in cb.views()[0] if str(v.lifecycle.get("pr_number") or "") == str(ref)]
    wrote = []
    for v in views[:5]:
        wl = cb.worklog(v.claim_id)
        if wl.exists():
            wl.note(line)
            wrote.append(v.claim_id)
    if wrote:
        return {"wrote": "worklog", "claim_ids": wrote, "pr": ref}
    with _queue_locked(cd) as q:
        notes = dict(q.get("pr_notes") or {})
        lst = list(notes.get(str(ref)) or [])
        lst.append({"by": op, "at": _iso(ctx.now()), "text": text})
        notes[str(ref)] = lst[-MAX_NOTES_PER_PR:]
        q["pr_notes"] = notes
        q["updated_at"] = _iso(ctx.now())
    return {"wrote": "batch_queue.pr_notes", "pr": ref}


def cmd_set_priority(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    tid = str(p.get("task_id") or "")
    if not TB.valid_task_id(tid):
        raise CommandError(400, "PARAMS_INVALID", "task_id is required")
    _cb, tb = _boards(cd, ctx.now)
    try:
        t = tb.set_priority(tid, p.get("priority"), by=op)  # type: ignore[arg-type]
    except TB.TaskError as exc:
        raise CommandError(404 if "not found" in str(exc) else 400, "TASK_REFUSED", str(exc)) from None
    return {"task_id": tid, "priority": t["priority"]}


def _hold(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx, held: bool) -> dict[str, Any]:
    kind, ref = _target(p.get("item"))
    reason = _text(p, "reason", 300, required=False)
    if kind == "task":
        _cb, tb = _boards(cd, ctx.now)
        try:
            t = tb.set_hold(ref, held, by=op, reason=reason)
        except TB.TaskError as exc:
            raise CommandError(404, "NOT_FOUND", str(exc)) from None
        return {"task_id": ref, "held": t.get("held")}
    if kind == "pr":
        with _queue_locked(cd) as q:
            hp = dict(q.get("held_prs") or {})
            if held:
                hp[str(ref)] = {"by": op, "at": _iso(ctx.now()), "reason": reason}
            else:
                hp.pop(str(ref), None)
            q["held_prs"] = hp
            q["history"] = [*(q.get("history") or []), {"at": _iso(ctx.now()), "by": op, "event": "hold" if held else "unhold", "pr": ref}]
            q["updated_at"] = _iso(ctx.now())
        return {"pr": ref, "held": held}
    raise CommandError(400, "BAD_ITEM", "hold applies to a task or a PR")


def cmd_hold(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    return _hold(cd, op, p, ctx, True)


def cmd_unhold(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    return _hold(cd, op, p, ctx, False)


def _census_pr(ctx: Ctx, n: int) -> tuple[Optional[Mapping[str, Any]], Optional[int]]:
    """(open PR from the last census, open batch containing it) -- (None, None) when the census is unknown."""
    c = ctx.census() or {}
    pr = next((x for x in c.get("open") or [] if int(x.get("number") or 0) == n), None)
    in_batch = next(
        (int(bn) for bn, b in (c.get("batches") or {}).items() if n in (b.get("members") or []) and int(bn) != n),
        None,
    )
    return pr, in_batch


def cmd_batch_add(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    n = _pr(p.get("pr"))
    if n is None:
        raise CommandError(400, "PARAMS_INVALID", "pr is required")
    census = ctx.census()
    if census:
        pr, in_batch = _census_pr(ctx, n)
        if pr is None:
            raise CommandError(409, "PR_NOT_OPEN", f"#{n} is not an open PR in the last census")
        if ((pr.get("ci") or {}).get("state")) != "green":
            raise CommandError(409, "CI_NOT_GREEN", f"#{n} CI is {(pr.get('ci') or {}).get('state')}")
        if in_batch:
            raise CommandError(409, "ALREADY_IN_BATCH", f"#{n} is already in batch #{in_batch}")
    with _queue_locked(cd) as q:
        if str(n) in (q.get("held_prs") or {}):
            raise CommandError(409, "PR_HELD", f"#{n} is on hold; unhold it first")
        nb = list(q.get("next_batch") or [])
        if any(int(e.get("pr")) == n for e in nb):
            return {"pr": n, "position": [int(e["pr"]) for e in nb].index(n) + 1, "already": True}
        if len(nb) >= MAX_QUEUE:
            raise CommandError(409, "QUEUE_FULL", f"next batch already lists {MAX_QUEUE} PRs")
        nb.append({"pr": n, "by": op, "at": _iso(ctx.now())})
        q["next_batch"] = nb
        q["history"] = [*(q.get("history") or []), {"at": _iso(ctx.now()), "by": op, "event": "batch_add", "pr": n}]
        q["updated_at"] = _iso(ctx.now())
        pos = len(nb)
    return {"pr": n, "position": pos, "census": bool(census)}


def cmd_batch_remove(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    n = _pr(p.get("pr"))
    if n is None:
        raise CommandError(400, "PARAMS_INVALID", "pr is required")
    with _queue_locked(cd) as q:
        nb = [e for e in q.get("next_batch") or [] if int(e.get("pr")) != n]
        removed = len(nb) != len(q.get("next_batch") or [])
        q["next_batch"] = nb
        if removed:
            q["history"] = [*(q.get("history") or []), {"at": _iso(ctx.now()), "by": op, "event": "batch_remove", "pr": n}]
            q["updated_at"] = _iso(ctx.now())
    return {"pr": n, "removed": removed}


def cmd_task_add(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    _cb, tb = _boards(cd, ctx.now)
    areas = p.get("areas")
    areas = [a for a in (areas if isinstance(areas, list) else str(areas or "").split(",")) if str(a).strip()]
    acc = p.get("acceptance")
    acc = acc if isinstance(acc, list) else [a for a in str(acc or "").split(";") if a.strip()]
    try:
        t = tb.add(
            title=_text(p, "title", 200) or "",
            kind=str(p.get("kind") or "build"),
            areas=[str(a).strip() for a in areas][:40],
            priority=int(p.get("priority") or TB.DEFAULT_PRIORITY),
            acceptance=[str(a).strip() for a in acc][:20],
            operator_quote=B.clip(p.get("operator_quote"), 2000),
            created_by=op,
            source="operator",
        )
    except (TB.TaskError, ValueError) as exc:
        raise CommandError(400, "TASK_REFUSED", str(exc)) from None
    return {"task_id": t["task_id"], "title": t["title"]}


def cmd_task_split(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    tid = str(p.get("task_id") or "")
    parts = p.get("parts")
    if not TB.valid_task_id(tid) or not isinstance(parts, list) or not parts:
        raise CommandError(400, "PARAMS_INVALID", "task_id and a non-empty parts list are required")
    clean = []
    for part in parts[:12]:
        if isinstance(part, str):
            part = TB.parse_part(part)
        if not isinstance(part, Mapping) or not str(part.get("title") or "").strip():
            raise CommandError(400, "PARAMS_INVALID", "every part needs a title")
        clean.append({"title": str(part["title"])[:200], "areas": list(part.get("areas") or []), "acceptance": list(part.get("acceptance") or [])})
    _cb, tb = _boards(cd, ctx.now)
    try:
        kids = tb.split(tid, clean, by=op)
    except TB.TaskError as exc:
        raise CommandError(409, "TASK_REFUSED", str(exc)) from None
    return {"task_id": tid, "children": [k["task_id"] for k in kids]}


def red_stale(v: "B.ClaimView") -> tuple[bool, str]:
    """A claim the board shows RED stale: no heartbeat for the stale window and pre-PR, or CI failing and idle."""
    if v.doc.get("status") != "active":
        return False, f"claim is {v.doc.get('status')}"
    if v.state != "stale":
        return False, "claim has a recent heartbeat"
    stage = v.stage
    ci = (v.lifecycle.get("ci") or {}).get("state")
    if stage in ("claimed", "building"):
        return True, "no heartbeat, no PR"
    if stage == "pr_open" and ci == "failing":
        return True, "CI failing, no activity"
    return False, f"claim is at {stage} (CI {ci or 'unknown'}): not stale work"


def cmd_release_stale_claim(cd: Path, op: str, p: Mapping[str, Any], ctx: Ctx) -> dict[str, Any]:
    cid = str(p.get("claim_id") or "")
    if not B.valid_claim_id(cid):
        raise CommandError(400, "PARAMS_INVALID", "claim_id is required")
    cb, tb = _boards(cd, ctx.now)
    try:
        cb.extra_obs = {}
        v = next((x for x in cb.views()[0] if x.claim_id == cid), None)
    except B.ClaimError as exc:
        raise CommandError(404, "NOT_FOUND", str(exc)) from None
    if v is None:
        raise CommandError(404, "NOT_FOUND", f"claim {cid} not found")
    ok, why = red_stale(v)
    if not ok:
        raise CommandError(409, "NOT_STALE", why)
    summary = f"released by the operator ({op}) from the Work pipeline: stale ({why}); files freed, worklog kept"
    task = next((t for t in tb.read_all() if t.get("claim_id") == cid and t.get("status") == "taken"), None)
    if task is not None:
        tb.release(task["task_id"], session=op, handoff=f"operator released the stale claim {cid}: continue from its worklog", force=True)
    else:
        cb.release(cid, session=op, status="abandoned", note="operator takeover: stale", summary=summary if cb.worklog(cid).exists() else None, force=True, released_by=op)
    if cb.worklog(cid).exists():
        try:
            cb.worklog(cid).status(f"operator takeover: {summary}")
        except Exception:  # noqa: BLE001 - the release stands; the audit line is the record
            pass
    return {"claim_id": cid, "released": "abandoned", "why": why, "task_id": (task or {}).get("task_id"), "takeover": "operator"}


HANDLERS: dict[str, Callable[[Path, str, Mapping[str, Any], Ctx], dict[str, Any]]] = {
    "note": cmd_note,
    "set_priority": cmd_set_priority,
    "hold": cmd_hold,
    "unhold": cmd_unhold,
    "batch_add": cmd_batch_add,
    "batch_remove": cmd_batch_remove,
    "task_add": cmd_task_add,
    "task_split": cmd_task_split,
    "release_stale_claim": cmd_release_stale_claim,
}


# --------------------------------------------------------------------------------------------- entry point


def _err(status: int, code: str, detail: str = "") -> tuple[int, dict[str, Any]]:
    return status, {"ok": False, "error": code, "detail": detail}


def handle(method: str, body: Any, *, ctx: Optional[Ctx] = None) -> tuple[int, dict[str, Any]]:
    """POST /api/v2/coordination/commands. GET answers the command catalogue (no state)."""
    m = (method or "GET").upper()
    if m == "GET":
        return 200, {
            "ok": True,
            "data": {
                "commands": list(COMMANDS),
                "tier2": list(TIER2),
                "never_on_board": list(NEVER_ON_BOARD),
                "path": PATH,
            },
        }
    if m != "POST":
        return _err(405, "METHOD_NOT_ALLOWED")
    try:
        ctx = ctx or context()
    except Exception as exc:  # noqa: BLE001
        return _err(503, "CONFIG_UNAVAILABLE", type(exc).__name__)
    cd = claims_dir_of(ctx)
    b = body if isinstance(body, dict) else {}
    cmd = str(b.get("command") or "")[:40]
    params = b.get("params") if isinstance(b.get("params"), dict) else {}
    key = str(b.get("idempotency_key") or "")
    now = ctx.now()
    row: dict[str, Any] = {
        "at": _iso(now),
        "command": cmd,
        "params": {k: (str(v)[:300] if not isinstance(v, (list, dict)) else json.dumps(v, default=str)[:600]) for k, v in list(params.items())[:12]},
        "idempotency_key": key[:100] or None,
        "principal": (ctx.principal() or "")[:80],
        "listener": ctx.listener(),
    }

    def refuse(status: int, code: str, detail: str = "") -> tuple[int, dict[str, Any]]:
        try:
            append_audit(cd, {**row, "outcome": "refused", "error": code, "detail": detail[:300]})
        except OSError:
            pass
        return _err(status, code, detail)

    op = operator_of(ctx)
    if not op:
        return refuse(403, "AGENT_CALLER_REFUSED", "only the operator's tailnet identity may act on the Work pipeline; agents, n8n and the service token are refused")
    row["actor"] = op
    ok, why = ctx.csrf("POST", PATH)
    if not ok:
        return refuse(403, "CSRF_REFUSED", why)
    if cmd in NEVER_ON_BOARD:
        return refuse(403, "NEVER_ON_BOARD", "broker orders, stops, kill-switch clearing and grants are never on the board")
    if cmd in TIER2:
        return refuse(403, "STEP_UP_REQUIRED", f"{cmd} is a Tier 2 act: passkey assertion + typed phrase through the host applier")
    if cmd not in HANDLERS:
        return refuse(400, "UNKNOWN_COMMAND", f"command must be one of {', '.join(COMMANDS)}")
    if not IDEM_RE.match(key):
        return refuse(400, "IDEMPOTENCY_KEY_REQUIRED", "idempotency_key: 8-100 chars [A-Za-z0-9_.:-]")
    prior = find_idempotent(cd, key)
    if prior is not None:
        if prior.get("command") != cmd:
            return refuse(409, "IDEMPOTENCY_KEY_REUSED", f"key already used for {prior.get('command')}")
        return 200, {"ok": True, "replayed": True, "command": cmd, "result": prior.get("result"), "at": prior.get("at")}
    try:
        result = HANDLERS[cmd](cd, op, params, ctx)
    except CommandError as exc:
        return refuse(exc.status, exc.code, exc.detail)
    except (B.ClaimError, TB.TaskError) as exc:
        return refuse(409, "REFUSED", str(exc)[:300])
    append_audit(cd, {**row, "outcome": "ok", "result": result})
    return 200, {"ok": True, "command": cmd, "actor": op, "result": result, "at": row["at"]}
