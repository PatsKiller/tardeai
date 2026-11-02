#!/usr/bin/env python3
"""Co-coordinators by territory, with checks: the registry and the shared, vendor-neutral notebook.

Plan: persistent-state/handoffs/PLAN_CO_COORDINATORS_20261102.md (operator 2026-11-02, "option 2 with checks").
Why: several coordinators (any vendor) must work at once without conflicting orders, double-merges or asking the
operator the same question twice; nothing a coordinator knows may live only in its own chat; and the operator must be
able to see who coordinates what on the Command Center. This CLI is the ONLY writer of the coordination store; the
API and the page read it (scripts/lib/coordination_view.py).

STORE (under TRADEAI_STATE_ROOT, default ~/trade-ai-releases/persistent-state)
  data/coordination/coordinators.json        CoordinatorRegistry@v1  (who coordinates what; exactly one lead)
  data/coordination/coordinator/ledger.jsonl CoordinatorEvent@v1, append-only, written BEFORE acting
  data/coordination/coordinator/BOARD.md     generated live state (this CLI regenerates it)
  data/coordination/coordinator/LESSONS.md   durable traps (seeded by the operator after merge; never by this PR)
  data/coordination/coordinator/inbox/<id>/<ts>-<from>.md   messages; read items move to inbox/<id>/read/
  data/coordination/coordinator/handoffs/<ts>-<from>-to-<to>.md

Every write takes one flock over <coordinator>/.lock and is atomic (temp file + os.replace, fsync). Reads never
create the directory. Nothing is ever deleted: inbox reads move, handoffs and events append.

    python3 scripts/coordinator.py status [--json]
    python3 scripts/coordinator.py appoint --id codex-a --vendor codex --session s1 --where tmux:cc1 \
        --territories agents --role member --quote "<operator words>"
    python3 scripts/coordinator.py heartbeat --id claude-lead
    python3 scripts/coordinator.py assign pr:2485 release
    python3 scripts/coordinator.py event review_verdict --subject pr:2485 --detail "MERGE"
    python3 scripts/coordinator.py check request pr:2485 --sha 45b92a4e --by claude-lead
    python3 scripts/coordinator.py check ok pr:2485 --sha 45b92a4e --by codex-a
    python3 scripts/coordinator.py inbox send --to codex-a --from claude-lead --text "one voice: hold"
    python3 scripts/coordinator.py inbox read --id codex-a
    python3 scripts/coordinator.py handoff --from claude-lead --to codex-a
    python3 scripts/coordinator.py board
    python3 scripts/coordinator.py whoami --session s1

AUTHORITY: READ_ONLY_ADVISORY. It coordinates agents; it sizes, orders, stops or writes nothing to a broker
(MBI_BEHAVIOR = 0). Appointing is the operator's act: --quote records their words and is required.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_REGISTRY = "CoordinatorRegistry@v1"
SCHEMA_EVENT = "CoordinatorEvent@v1"
VENDORS = ("claude", "codex", "cursor", "grok", "other")
ROLES = ("lead", "member", "observer")
STATUSES = ("active", "stale", "stood_down")
DEFAULT_STALE_MINUTES = 30
# Starting territories (plan §1); names are data, not code: anything the operator appoints is allowed, but an
# assignment must use a territory some coordinator holds.
DEFAULT_TERRITORIES = {
    "release": "merges, deploy, schedules, crontab/timers, held PRs",
    "agents": "dispatching and supervising the worker agents",
    "ui": "Command Center pages",
    "ops": "incidents, breakers, disk",
}


# ── store roots ────────────────────────────────────────────────────────────────────────────────────────


def state_root(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / "trade-ai-releases" / "persistent-state"


def coord_root(root: Path) -> Path:
    return root / "data" / "coordination"


def registry_path(root: Path) -> Path:
    return coord_root(root) / "coordinators.json"


def notebook(root: Path) -> Path:
    return coord_root(root) / "coordinator"


def ledger_path(root: Path) -> Path:
    return notebook(root) / "ledger.jsonl"


def board_path(root: Path) -> Path:
    return notebook(root) / "BOARD.md"


def inbox_dir(root: Path, cid: str) -> Path:
    return notebook(root) / "inbox" / _safe(cid)


def handoffs_dir(root: Path) -> Path:
    return notebook(root) / "handoffs"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe(name: str) -> str:
    """A filesystem-safe id: letters, digits, dot, dash, underscore only (no traversal)."""
    out = "".join(c for c in str(name) if c.isalnum() or c in "._-").strip("._-")
    if not out:
        raise SystemExit(f"invalid id: {name!r}")
    return out[:80]


# ── locking + atomic writes ───────────────────────────────────────────────────────────────────────────


@contextmanager
def locked(root: Path) -> Iterator[None]:
    """One exclusive flock for every write of the coordination store. Readers do not lock."""
    d = notebook(root)
    d.mkdir(parents=True, exist_ok=True)
    lock = d / ".lock"
    fh = lock.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_event(root: Path, event: dict[str, Any]) -> None:
    """Append one validated ledger line. Caller holds the lock."""
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    with ledger_path(root).open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


# ── tolerant reads ────────────────────────────────────────────────────────────────────────────────────


def read_registry(root: Path) -> dict[str, Any]:
    p = registry_path(root)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    doc.setdefault("schema", SCHEMA_REGISTRY)
    doc.setdefault("stale_after_minutes", DEFAULT_STALE_MINUTES)
    doc.setdefault("territories", dict(DEFAULT_TERRITORIES))
    doc.setdefault("coordinators", [])
    doc.setdefault("assignments", {})
    if not isinstance(doc["coordinators"], list):
        doc["coordinators"] = []
    if not isinstance(doc["assignments"], dict):
        doc["assignments"] = {}
    if not isinstance(doc["territories"], dict):
        doc["territories"] = dict(DEFAULT_TERRITORIES)
    return doc


def read_events(root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with ledger_path(root).open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue  # a torn tail is skipped, never repaired in place
                if isinstance(doc, dict):
                    out.append(doc)
    except OSError:
        return []
    return out[-limit:] if limit else out


def _age_minutes(ts: str | None, now: datetime | None = None) -> float | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        return None
    return ((now or datetime.now(timezone.utc)) - t).total_seconds() / 60.0


def coordinator_state(doc: dict[str, Any], stale_minutes: float, now: datetime | None = None) -> str:
    if str(doc.get("status") or "") == "stood_down":
        return "stood_down"
    age = _age_minutes(doc.get("last_heartbeat"), now)
    return "active" if age is not None and age <= stale_minutes else "stale"


def find(registry: dict[str, Any], cid: str) -> dict[str, Any] | None:
    for c in registry["coordinators"]:
        if str(c.get("id")) == cid:
            return c
    return None


def active_ids(registry: dict[str, Any], now: datetime | None = None) -> list[str]:
    stale = float(registry.get("stale_after_minutes") or DEFAULT_STALE_MINUTES)
    return [str(c.get("id")) for c in registry["coordinators"]
            if coordinator_state(c, stale, now) == "active"]


# ── rendering ─────────────────────────────────────────────────────────────────────────────────────────


def pending_checks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """check_request rows with no later check_ok/check_block for the same (subject, sha)."""
    open_reqs: dict[tuple[str, str], dict[str, Any]] = {}
    for e in events:
        kind = str(e.get("kind") or "")
        key = (str(e.get("subject") or ""), str(e.get("sha") or ""))
        if kind == "check_request":
            open_reqs.setdefault(key, e)
        elif kind in ("check_ok", "check_block"):
            open_reqs.pop(key, None)
    return sorted(open_reqs.values(), key=lambda e: str(e.get("ts") or ""))


def pending_decisions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """decision_pending rows with no later approval_recorded/decision_resolved for the same subject."""
    out: dict[str, dict[str, Any]] = {}
    for e in events:
        kind = str(e.get("kind") or "")
        subj = str(e.get("subject") or "")
        if kind == "decision_pending":
            out.setdefault(subj, e)
        elif kind in ("approval_recorded", "decision_resolved"):
            out.pop(subj, None)
    return sorted(out.values(), key=lambda e: str(e.get("ts") or ""))


def inbox_counts(root: Path) -> dict[str, int]:
    base = notebook(root) / "inbox"
    out: dict[str, int] = {}
    try:
        for d in sorted(base.iterdir()):
            if d.is_dir() and not d.is_symlink():
                out[d.name] = sum(1 for f in d.iterdir() if f.is_file() and not f.is_symlink())
    except OSError:
        return {}
    return out


def render_board(root: Path, registry: dict[str, Any], events: list[dict[str, Any]], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    stale = float(registry.get("stale_after_minutes") or DEFAULT_STALE_MINUTES)
    leads = [c for c in registry["coordinators"] if str(c.get("role")) == "lead"]
    lines = [f"# Coordination board — {now.replace(microsecond=0).isoformat().replace('+00:00', 'Z')}", ""]
    lines.append(f"Lead (one voice to the operator): **{leads[0].get('id') if leads else '(none appointed)'}**")
    lines.append("")
    lines.append("## Coordinators")
    lines.append("| id | vendor | role | territories | status | last heartbeat | session | where |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for c in sorted(registry["coordinators"], key=lambda x: str(x.get("id"))):
        lines.append("| {id} | {vendor} | {role} | {terr} | {state} | {hb} | {sess} | {where} |".format(
            id=c.get("id"), vendor=c.get("vendor"), role=c.get("role"),
            terr=", ".join(c.get("territories") or []) or "—",
            state=coordinator_state(c, stale, now), hb=c.get("last_heartbeat") or "—",
            sess=c.get("session") or "—", where=c.get("where") or "—"))
    lines += ["", "## Assignments (each agent or PR belongs to exactly one territory)"]
    if registry["assignments"]:
        lines += ["| subject | territory |", "|---|---|"]
        for subj, terr in sorted(registry["assignments"].items()):
            lines.append(f"| {subj} | {terr} |")
    else:
        lines.append("_none yet_")
    checks = pending_checks(events)
    lines += ["", "## Pending checks (a different active coordinator must answer)"]
    if checks:
        lines += ["| subject | sha | requested by | since |", "|---|---|---|---|"]
        for e in checks:
            lines.append(f"| {e.get('subject')} | {str(e.get('sha') or '')[:12]} | {e.get('coordinator')} | {e.get('ts')} |")
    else:
        lines.append("_none_")
    decs = pending_decisions(events)
    lines += ["", "## Waiting on the operator"]
    if decs:
        for e in decs:
            lines.append(f"- **{e.get('subject')}** — {e.get('detail') or ''} ({e.get('ts')})")
    else:
        lines.append("_nothing pending_")
    lines += ["", "## Recent events"]
    for e in events[-40:]:
        det = str(e.get("detail") or "")
        lines.append(f"- `{e.get('ts')}` **{e.get('kind')}** {e.get('subject') or ''}"
                     + (f" — {det}" if det else "") + (f" (by {e.get('coordinator')})" if e.get("coordinator") else ""))
    counts = inbox_counts(root)
    lines += ["", "## Inbox"]
    if counts:
        lines += ["| coordinator | unread |", "|---|---|"]
        for cid, n in counts.items():
            lines.append(f"| {cid} | {n} |")
    else:
        lines.append("_empty_")
    lines += ["", "## Lessons", ""]
    lessons = notebook(root) / "LESSONS.md"
    lines.append(f"Durable traps live in `{lessons}`." if lessons.exists() else
                 "`LESSONS.md` is not seeded yet (the operator seeds it after merge).")
    lines.append("")
    return "\n".join(lines)


# ── commands ──────────────────────────────────────────────────────────────────────────────────────────


def cmd_status(args) -> int:
    root = state_root(args.state_root)
    reg = read_registry(root)
    now = datetime.now(timezone.utc)
    stale = float(reg.get("stale_after_minutes") or DEFAULT_STALE_MINUTES)
    events = read_events(root)
    doc = {
        "schema": "CoordinatorStatus@v1", "as_of": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "registry_present": registry_path(root).exists(),
        "lead": next((c.get("id") for c in reg["coordinators"] if str(c.get("role")) == "lead"), None),
        "coordinators": [{**c, "state": coordinator_state(c, stale, now)} for c in reg["coordinators"]],
        "assignments": reg["assignments"],
        "pending_checks": pending_checks(events),
        "pending_decisions": pending_decisions(events),
        "inbox": inbox_counts(root),
        "ledger_events": len(events),
        "store": str(coord_root(root)),
    }
    if args.json:
        print(json.dumps(doc, indent=1))
        return 0
    print(f"lead: {doc['lead'] or '(none appointed)'}   store: {doc['store']}")
    for c in doc["coordinators"]:
        print(f"  {c.get('id'):20s} {str(c.get('vendor') or ''):7s} {str(c.get('role') or ''):7s} "
              f"{c['state']:10s} territories={','.join(c.get('territories') or []) or '-'}")
    print(f"pending checks: {len(doc['pending_checks'])}   waiting on operator: {len(doc['pending_decisions'])}")
    return 0


def cmd_appoint(args) -> int:
    quote = str(args.quote or "").strip()
    if not quote:
        print("error: --quote is required: appointing a coordinator is the operator's act, recorded verbatim", file=sys.stderr)
        return 2
    if args.vendor not in VENDORS:
        print(f"error: --vendor must be one of {', '.join(VENDORS)}", file=sys.stderr)
        return 2
    if args.role not in ROLES:
        print(f"error: --role must be one of {', '.join(ROLES)}", file=sys.stderr)
        return 2
    root = state_root(args.state_root)
    with locked(root):
        reg = read_registry(root)
        tid = _safe(args.id)
        territories = [t.strip() for t in (args.territories or "").split(",") if t.strip()]
        if not territories:
            print("error: --territories is required (comma-separated)", file=sys.stderr)
            return 2
        if args.role == "lead":
            other = next((c for c in reg["coordinators"]
                          if str(c.get("role")) == "lead" and str(c.get("id")) != tid
                          and str(c.get("status")) != "stood_down"), None)
            if other:
                print(f"error: {other.get('id')} is already lead; stand it down first (exactly one lead)",
                      file=sys.stderr)
                return 2
        entry = {"id": tid, "vendor": args.vendor, "session": args.session or None,
                 "where": args.where or None, "territories": territories, "role": args.role,
                 "appointed_by": "operator", "appointed_quote": quote, "appointed_at": now_iso(),
                 "last_heartbeat": now_iso(), "status": "active"}
        reg["coordinators"] = [c for c in reg["coordinators"] if str(c.get("id")) != tid] + [entry]
        reg["as_of"] = now_iso()
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": tid, "territory": None,
                            "kind": "appoint", "subject": tid,
                            "detail": f"{args.vendor} as {args.role}: {', '.join(territories)}",
                            "operator_quote": quote})
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": tid, "territory": None,
                            "kind": "heartbeat", "subject": tid, "detail": "initial"})
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{tid} appointed {args.role} ({args.vendor}) over {', '.join(territories)}")
    return 0


def cmd_stand_down(args) -> int:
    root = state_root(args.state_root)
    with locked(root):
        reg = read_registry(root)
        c = find(reg, _safe(args.id))
        if not c:
            print(f"error: no coordinator {args.id}", file=sys.stderr)
            return 2
        c["status"] = "stood_down"
        c["last_heartbeat"] = now_iso()
        reg["as_of"] = now_iso()
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": c["id"], "territory": None,
                            "kind": "stand_down", "subject": c["id"], "detail": args.quote or None,
                            "operator_quote": args.quote or None})
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{args.id} stood down")
    return 0


def cmd_heartbeat(args) -> int:
    root = state_root(args.state_root)
    with locked(root):
        reg = read_registry(root)
        c = find(reg, _safe(args.id))
        if not c:
            print(f"error: no coordinator {args.id}", file=sys.stderr)
            return 2
        if str(c.get("status")) == "stood_down":
            print(f"error: {args.id} is stood down; the operator alone re-appoints", file=sys.stderr)
            return 2
        c["last_heartbeat"] = now_iso()
        c["status"] = "active"
        reg["as_of"] = now_iso()
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": c["id"], "territory": None,
                            "kind": "heartbeat", "subject": c["id"], "detail": None})
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{args.id} heartbeat {now_iso()}")
    return 0


def cmd_assign(args) -> int:
    root = state_root(args.state_root)
    with locked(root):
        reg = read_registry(root)
        tid = _safe(args.territory)
        known = set(reg["territories"]) | {t for c in reg["coordinators"] for t in (c.get("territories") or [])}
        if tid not in known:
            print(f"error: unknown territory {args.territory!r}; known: {', '.join(sorted(known))}", file=sys.stderr)
            return 2
        reg["assignments"][str(args.subject)] = tid
        reg["as_of"] = now_iso()
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": args.coordinator, "territory": tid,
                            "kind": "assign", "subject": str(args.subject), "detail": f"territory {tid}"})
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{args.subject} -> {tid}")
    return 0


def cmd_event(args) -> int:
    root = state_root(args.state_root)
    with locked(root):
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": args.coordinator,
                            "territory": args.territory, "kind": str(args.kind), "subject": args.subject,
                            "detail": args.detail, "operator_quote": args.quote})
        _atomic_write(board_path(root), render_board(root, read_registry(root), read_events(root)))
    print(f"event {args.kind} recorded")
    return 0


def cmd_check(args) -> int:
    root = state_root(args.state_root)
    with locked(root):
        reg = read_registry(root)
        events = read_events(root)
        subject, sha = str(args.subject), str(args.sha or "")
        if args.action == "request":
            append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": args.by, "territory": None,
                                "kind": "check_request", "subject": subject, "sha": sha,
                                "detail": args.reason or None})
            _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
            print(f"check requested: {subject} @ {sha[:12]} by {args.by}")
            return 0
        req = next((e for e in reversed(events) if str(e.get("kind")) == "check_request"
                    and str(e.get("subject")) == subject and str(e.get("sha") or "") == sha), None)
        if not req:
            print(f"error: no check_request for {subject} @ {sha[:12]}", file=sys.stderr)
            return 2
        if str(req.get("coordinator")) == str(args.by):
            print("error: the check must come from a DIFFERENT active coordinator", file=sys.stderr)
            return 2
        if args.by not in active_ids(reg):
            print(f"error: {args.by} is not an active coordinator", file=sys.stderr)
            return 2
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": args.by, "territory": None,
                            "kind": f"check_{args.action}", "subject": subject, "sha": sha,
                            "detail": args.reason or None})
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"check {args.action}: {subject} @ {sha[:12]} by {args.by}")
    return 0


def cmd_inbox(args) -> int:
    root = state_root(args.state_root)
    if args.action == "send":
        if not args.to:
            print("error: --to is required", file=sys.stderr)
            return 2
        sender = _safe(args.from_ or "unknown")
        body = args.text
        if args.file:
            try:
                body = Path(args.file).expanduser().read_text(encoding="utf-8")
            except OSError as exc:
                print(f"error: cannot read {args.file}: {exc}", file=sys.stderr)
                return 2
        if not (body or "").strip():
            print("error: --text or --file with content is required", file=sys.stderr)
            return 2
        with locked(root):
            d = inbox_dir(root, _safe(args.to))
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{_stamp()}-{sender}.md"
            _atomic_write(p, (body or "").rstrip() + "\n")
            append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": sender, "territory": None,
                                "kind": "inbox_send", "subject": _safe(args.to), "detail": p.name})
        print(p)
        return 0
    cid = _safe(args.id or "")
    if not cid:
        print("error: --id is required", file=sys.stderr)
        return 2
    d = inbox_dir(root, cid)
    items = []
    try:
        items = sorted(f for f in d.iterdir() if f.is_file() and not f.is_symlink())
    except OSError:
        items = []
    if not items:
        print(f"inbox {cid}: empty")
        return 0
    for f in items:
        print(f"=== {f.name} ===")
        try:
            print(f.read_text(encoding="utf-8").rstrip())
        except OSError:
            print("(unreadable)")
        if not args.keep:
            with locked(root):
                read = d / "read"
                read.mkdir(exist_ok=True)
                os.replace(f, read / f.name)  # move, never delete
    if not args.keep:
        print(f"({len(items)} item(s) moved to {d / 'read'})")
    return 0


def cmd_handoff(args) -> int:
    root = state_root(args.state_root)
    src, dst = _safe(args.from_), _safe(args.to)
    with locked(root):
        reg = read_registry(root)
        a, b = find(reg, src), find(reg, dst)
        if not a or not b:
            print(f"error: both coordinators must exist ({src}, {dst})", file=sys.stderr)
            return 2
        events = read_events(root)
        stamp = _stamp()
        p = handoffs_dir(root) / f"{stamp}-{src}-to-{dst}.md"
        body = [f"# Handoff {src} -> {dst} ({now_iso()})", "",
                f"- territories moved: {', '.join(a.get('territories') or []) or '(none)'}",
                f"- role: {a.get('role')} -> {b.get('role')}", "",
                "## Snapshot", "", render_board(root, reg, events), ""]
        _atomic_write(p, "\n".join(body))
        b["territories"] = sorted(set(b.get("territories") or []) | set(a.get("territories") or []))
        a["territories"] = []
        if str(a.get("role")) == "lead":
            a["role"] = "member"
            b["role"] = "lead"
        reg["as_of"] = now_iso()
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": src, "territory": None,
                            "kind": "handoff", "subject": dst, "detail": p.name})
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(p)
    return 0


def cmd_board(args) -> int:
    root = state_root(args.state_root)
    with locked(root):
        reg = read_registry(root)
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    p = board_path(root)
    if args.json:
        print(json.dumps({"schema": "CoordinationBoard@v1", "path": str(p), "text": p.read_text(encoding="utf-8")}))
    else:
        print(p)
    return 0


def cmd_whoami(args) -> int:
    root = state_root(args.state_root)
    reg = read_registry(root)
    stale = float(reg.get("stale_after_minutes") or DEFAULT_STALE_MINUTES)
    sess = str(args.session or "").strip()
    for c in reg["coordinators"]:
        if sess and str(c.get("session") or "") == sess:
            print(json.dumps({"coordinator": c.get("id"), "role": c.get("role"), "vendor": c.get("vendor"),
                              "territories": c.get("territories") or [],
                              "state": coordinator_state(c, stale),
                              "assignments": [s for s, t in reg["assignments"].items()
                                              if t in (c.get("territories") or [])]}, indent=1))
            return 0
    print(json.dumps({"coordinator": None, "session": sess, "detail": "no coordinator appointed for this session"},
                     indent=1))
    return 1


# ── entry ─────────────────────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Co-coordinators by territory: registry and shared notebook")
    ap.add_argument("--state-root", default=None, help="persistent-state root (default: TRADEAI_STATE_ROOT or ~)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--coordinator", default=None, help="the acting coordinator id (ledger attribution)")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("status", help="registry, freshness, pending checks and decisions")
    common(p)

    p = sub.add_parser("appoint", help="operator: appoint a coordinator (--quote required)")
    p.add_argument("--id", required=True)
    p.add_argument("--vendor", required=True)
    p.add_argument("--session", default=None)
    p.add_argument("--where", default=None)
    p.add_argument("--territories", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--quote", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("stand-down", help="operator: stand a coordinator down")
    p.add_argument("--id", required=True)
    p.add_argument("--quote", default=None)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("heartbeat", help="record liveness")
    p.add_argument("--id", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("assign", help="assign an agent or pr:<n> to a territory")
    p.add_argument("subject")
    p.add_argument("territory")
    common(p)

    p = sub.add_parser("event", help="append a ledger event (write-ahead)")
    p.add_argument("kind")
    p.add_argument("--subject", default=None)
    p.add_argument("--detail", default=None)
    p.add_argument("--territory", default=None)
    p.add_argument("--quote", default=None)
    common(p)

    p = sub.add_parser("check", help="two-coordinator check: request | ok | block")
    p.add_argument("action", choices=("request", "ok", "block"))
    p.add_argument("subject")
    p.add_argument("--sha", default="")
    p.add_argument("--by", required=True)
    p.add_argument("--reason", default=None)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("inbox", help="send a report to a coordinator, or read (and move) its inbox")
    p.add_argument("action", choices=("send", "read"))
    p.add_argument("--to", default=None)
    p.add_argument("--from", dest="from_", default=None)
    p.add_argument("--text", default=None)
    p.add_argument("--file", default=None)
    p.add_argument("--id", default=None)
    p.add_argument("--keep", action="store_true", help="read without moving to read/")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("handoff", help="snapshot, move territories and record the handover")
    p.add_argument("--from", dest="from_", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("board", help="regenerate BOARD.md")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("whoami", help="which coordinator and territory is this session")
    p.add_argument("--session", default=None)
    p.add_argument("--json", action="store_true")
    return ap


COMMANDS = {"status": cmd_status, "appoint": cmd_appoint, "stand-down": cmd_stand_down,
            "heartbeat": cmd_heartbeat, "assign": cmd_assign, "event": cmd_event, "check": cmd_check,
            "inbox": cmd_inbox, "handoff": cmd_handoff, "board": cmd_board, "whoami": cmd_whoami}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
