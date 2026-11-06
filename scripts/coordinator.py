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
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
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
# Equal partners: a non-Claude coordinator runs sandboxed and cannot reach the tmux socket, so a host lane captures
# each agent session's visible screen to a file they can read. Patterns, not a fixed list (operator 2026-11-02).
DEFAULT_SNAPSHOT_SESSIONS = ("cc-deepseek-*", "codex", "cx-*")
SNAPSHOT_IDLE_SECONDS = 90
DEFAULT_ACK_TIMEOUT_MINUTES = 15
DEFAULT_ACK_ALERT_RETRY_MINUTES = 15


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
    """The ONE registry, beside BOARD.md and coord_status.py: the file the installed banner reads."""
    return notebook(root) / "coordinators.json"


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


def agents_dir(root: Path) -> Path:
    return notebook(root) / "agents"


_CLOCK: datetime | None = None


def _now_dt() -> datetime:
    return _CLOCK or datetime.now(timezone.utc)


def now_iso() -> str:
    return _now_dt().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return _now_dt().strftime("%Y%m%dT%H%M%SZ")


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
        except OSError:  # nosemgrep: tq-py-except-pass -- cleanup after a failed write: the original exception is re-raised on the next line, so nothing is swallowed; a failed unlink must not mask it
            pass
        raise


def append_event(root: Path, event: dict[str, Any]) -> None:
    """Append one validated ledger line. Caller holds the lock.

    A crash can leave the last line unterminated. Appending straight onto it glues the new event to
    the fragment, and ``read_events`` then discards BOTH lines, silently losing the event a successful
    command just reported. Terminate the damaged fragment first: its bytes stay exactly as written
    (skipped as an unparseable line) and the new event gets a line of its own.
    """
    line = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with ledger_path(root).open("a+b") as f:
        f.seek(0, os.SEEK_END)
        if f.tell():
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


# ── tolerant reads ────────────────────────────────────────────────────────────────────────────────────


class RegistryUnreadable(RuntimeError):
    """An existing registry that cannot be decoded. Mutators refuse; its bytes are never rewritten."""


def _decode_registry(p: Path) -> dict[str, Any]:
    """Decode a registry that exists. Raises instead of returning a reset document (CX2 @ a9668e01c)."""
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegistryUnreadable(
            f"registry {p} exists but cannot be decoded ({exc}); refusing to overwrite it — "
            "fix the file by hand (its bytes are preserved)") from exc
    if not isinstance(doc, dict):
        raise RegistryUnreadable(
            f"registry {p} exists but its top-level JSON is not an object; refusing to overwrite it")
    return doc


def registry_problem(root: Path) -> str | None:
    """Why an EXISTING registry cannot be read, or None when it is absent or decodable. Never writes."""
    p = registry_path(root)
    if not p.exists():
        return None
    try:
        _decode_registry(p)
    except RegistryUnreadable as exc:
        return str(exc)
    return None


def read_registry(root: Path, *, strict: bool = False) -> dict[str, Any]:
    """Load the registry. An absent store bootstraps; a present one that will not decode does not.

    ``strict`` is for every mutator: it raises ``RegistryUnreadable`` so a damaged store can never be
    mistaken for a new one and overwritten, losing the ownership and acknowledgement records.
    """
    p = registry_path(root)
    doc: dict[str, Any]
    if p.exists():
        try:
            doc = _decode_registry(p)
        except RegistryUnreadable:
            if strict:
                raise
            doc = {}
    else:
        doc = {}
    doc.setdefault("schema", SCHEMA_REGISTRY)
    # The hand-written seed's top-level fields survive every normalisation (the banner reads `lead` and `updated_at`).
    for key in ("lead", "updated_at", "updated_by", "operator_quote", "note"):
        doc.setdefault(key, None)
    doc.setdefault("stale_after_minutes", DEFAULT_STALE_MINUTES)
    doc.setdefault("territories", dict(DEFAULT_TERRITORIES))
    doc.setdefault("coordinators", [])
    doc.setdefault("assignments", {})
    doc.setdefault("ack_timeout_minutes", DEFAULT_ACK_TIMEOUT_MINUTES)
    doc.setdefault("pending_acks", {})
    if not isinstance(doc["coordinators"], list):
        doc["coordinators"] = []
    if not isinstance(doc["assignments"], dict):
        doc["assignments"] = {}
    if not isinstance(doc["pending_acks"], dict):
        doc["pending_acks"] = {}
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


def banner_text(registry: dict[str, Any], directory: str | Path) -> str:
    """Exactly the line the installed coord_status.py prints, from the SAME fields (lead, coordinators, updated_at)."""
    lead = registry.get("lead") or "?"
    parts = []
    for c in registry.get("coordinators") or []:
        terr = ",".join(c.get("territories") or []) or "none"
        parts.append(f"{c.get('id')}={c.get('role', '?')}[{terr}]")
    return (f"[COORDINATION] Lead: {lead}. Coordinators: {'; '.join(parts)}. "
            f"Report to the coordinator owning your work via {directory}/inbox/<id>/ (default: inbox/{lead}/). "
            f"Only the lead talks to the operator. Board: {directory}/BOARD.md "
            f"(updated {registry.get('updated_at') or '?'}).")


def registry_problems(registry: dict[str, Any]) -> list[str]:
    """Every way this registry can disagree with itself. Never repaired silently: the caller refuses or shows it."""
    rows = list(registry.get("coordinators") or [])
    ids = [str(c.get("id") or "") for c in rows]
    problems: list[str] = []
    if not ids:
        return ["no coordinators"]
    if any(not i for i in ids):
        problems.append("a coordinator has no id")
    if len(set(ids)) != len(ids):
        problems.append("duplicate coordinator id")
    for c in rows:
        if str(c.get("role")) not in ("lead", "member", "observer"):
            problems.append(f"{c.get('id')!r} has unknown role {c.get('role')!r}")
    role_leads = [str(c.get("id")) for c in rows if str(c.get("role")) == "lead"]
    top = str(registry.get("lead") or "")
    if len(role_leads) > 1:
        problems.append("more than one coordinator has role=lead")
    if role_leads and top != role_leads[0]:
        problems.append(f"top-level lead {top or '(none)'!r} does not match role lead {role_leads[0]!r}")
    if not role_leads and top:
        problems.append(f"top-level lead {top!r} but no coordinator has role=lead")
    if not role_leads and not top:
        problems.append("no lead")
    if top and top not in ids:
        problems.append(f"top-level lead {top!r} is not a coordinator")
    held: dict[str, str] = {}
    for c in rows:
        for terr in c.get("territories") or []:
            if terr in held and held[terr] != str(c.get("id")):
                problems.append(f"territory {terr!r} held by both {held[terr]!r} and {c.get('id')!r}")
            held.setdefault(terr, str(c.get("id")))
    return problems


def sync_lead(registry: dict[str, Any]) -> None:
    """Make the top-level ``lead`` agree with the role — the banner's one source. Ambiguity becomes None, never a pick."""
    leads = [str(c.get("id")) for c in registry["coordinators"] if str(c.get("role")) == "lead"]
    registry["lead"] = leads[0] if len(leads) == 1 else None


def touch(registry: dict[str, Any], *, by: str = "coordinator", quote: str | None = None) -> None:
    registry["updated_at"] = now_iso()
    registry["updated_by"] = by
    if quote is not None:
        registry["operator_quote"] = quote


def coherence_error(registry: dict[str, Any], *, allow_absent_lead: bool = False) -> str | None:
    """None when coherent (or empty: bootstrap), else the refusal text for a mutator.

    ``allow_absent_lead`` is for the recovery verbs (`lead`, `appoint`) that exist precisely to
    restore a lead after stand-down. Without it, standing down the lead left every mutator —
    including those recovery commands — refused forever (claude-lead BLOCK @ b22fb2f00).
    """
    if not registry.get("coordinators"):
        return None
    problems = registry_problems(registry)
    if allow_absent_lead:
        problems = [p for p in problems if p != "no lead"]
    return f"registry is divergent ({'; '.join(problems)}); fix or re-appoint before mutating" if problems else None


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
    lines.append(f"Lead (one voice to the operator): **{registry.get('lead') or '(none)'}**")
    problems = registry_problems(registry) if registry["coordinators"] else []
    if problems:
        lines.append("")
        lines.append("> **REGISTRY DIVERGENT** — mutations are refused until this is fixed: " + "; ".join(problems))
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


# ── agent screenshots (host lane; tmux) ───────────────────────────────────────────────────────────────


def _tmux(bin_: str, *args: str, timeout: float = 10.0) -> tuple[int, str]:
    try:
        p = subprocess.run([bin_, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return p.returncode, p.stdout


def tmux_sessions(bin_: str = "tmux") -> list[tuple[str, int | None]]:
    """[(session name, last-activity epoch)] or [] when tmux is unreachable (a sandboxed coordinator, no server)."""
    rc, out = _tmux(bin_, "list-sessions", "-F", "#{session_name}\t#{session_activity}")
    if rc != 0:
        return []
    rows: list[tuple[str, int | None]] = []
    for ln in out.splitlines():
        name, _, act = ln.partition("\t")
        name = name.strip()
        if not name:
            continue
        try:
            activity: int | None = int(act.strip())
        except ValueError:
            activity = None
        rows.append((name, activity))
    return rows


def snapshot_targets(sessions: list[tuple[str, int | None]], patterns: list[str]) -> list[tuple[str, int | None]]:
    return [(n, a) for n, a in sessions if any(fnmatch.fnmatchcase(n, p) for p in patterns)]


def agent_state(activity: int | None, now: float | None = None) -> str:
    """A guess from tmux's last-activity clock: busy within 90 s, idle after, unknown without it."""
    if activity is None:
        return "unknown"
    return "busy" if (now or time.time()) - activity <= SNAPSHOT_IDLE_SECONDS else "idle"


def cmd_snapshot(args) -> int:
    root = state_root(args.state_root)
    dry_run = bool(getattr(args, "dry_run", False))
    with (nullcontext() if dry_run else locked(root)):
        # Snapshot writes agent files into the coordination store, so an existing registry it cannot
        # read is refused exactly like every other writer's.
        reg = read_registry(root, strict=True)
        raw = args.sessions or ",".join(reg.get("snapshot_sessions") or DEFAULT_SNAPSHOT_SESSIONS)
        patterns = [p.strip() for p in str(raw).split(",") if p.strip()]
        lines = max(1, min(500, int(args.lines or 40)))
        tmux = args.tmux_bin or "tmux"
        started = time.time()
        rows = snapshot_targets(tmux_sessions(tmux), patterns)
        if dry_run:
            print(json.dumps({"schema": "CoordinatorSnapshotPlan@v1", "dry_run": True, "patterns": patterns,
                              "would_capture": [{"session": name, "state": agent_state(activity, started),
                                                 "path": str(agents_dir(root) / f"{_safe(name)}.txt")}
                                                for name, activity in rows]}, indent=1))
            return 0
        captured: list[dict[str, Any]] = []
        for name, activity in rows:
            rc, text = _tmux(tmux, "capture-pane", "-p", "-t", name, "-S", f"-{lines}")
            if rc != 0:
                continue
            body = "\n".join(text.rstrip("\n").splitlines()[-lines:])
            state = agent_state(activity, started)
            header = f"captured_at: {now_iso()}\nsession: {name}\nstate: {state}\nlines: {lines}\n---\n"
            _atomic_write(agents_dir(root) / f"{_safe(name)}.txt", header + body + "\n")
            captured.append({"session": name, "state": state, "lines": len(body.splitlines()), "chars": len(body)})
    print(json.dumps({"schema": "CoordinatorSnapshot@v1", "captured": captured, "patterns": patterns},
                     indent=1 if args.json else None))
    return 0


# ── operator transfers: give / lead / take-back / add / ack ───────────────────────────────────────────


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def _notify_session(tmux: str, session: str, text: str) -> bool:
    """One tmux message to a coordinator's registered session. False when the session is gone."""
    if not session:
        return False
    rc, _ = _tmux(tmux, "send-keys", "-t", session, text, "Enter")
    return rc == 0


def _queue_intent_fn():
    """The comms-intent queue callable. The fallback fires ONLY for a missing `lib` package (AGENTS §7), never for an
    ImportError raised inside the module itself."""
    try:
        from lib.host_comms_intents import queue_intent
    except ModuleNotFoundError as exc:
        if (getattr(exc, "name", "") or "") not in ("lib", "lib.host_comms_intents"):
            raise
        # The same module reached through the other tree root; the name is identical, so the redefinition is the point.
        from scripts.lib.host_comms_intents import queue_intent  # type: ignore[no-redef] -- same module via the scripts package root
    return queue_intent


def _operator_alert(subject: str, summary: str) -> bool:
    """Queue one operator alert through the EXISTING comms-intent chokepoint (never a direct send).

    The chokepoint is scripts/lib/host_comms_intents.queue_intent: it queues a comms intent into the coordination
    ledger and the host consumer delivers it. It refuses an unrouted (domain, kind); that refusal is recorded on the
    event as alert_queued=false, and routing it is an operator activation step (no route is added by this PR).
    """
    try:
        queue_intent = _queue_intent_fn()
        queue_intent(producer="coordinator", domain="coordination", kind="coordinator_ack_timeout",
                     subject=subject, summary=summary, execution_id=f"coordinator-{_stamp()}", node="coordinator")
        return True
    except Exception:  # noqa: BLE001 — a refused/absent chokepoint is reported, never a fallback send
        return False


def _all_territories(reg: dict[str, Any]) -> list[str]:
    known = set(reg.get("territories") or {})
    for c in reg["coordinators"]:
        known |= set(c.get("territories") or [])
    return sorted(known)


def _holders(reg: dict[str, Any], territory: str) -> list[str]:
    return [str(c.get("id")) for c in reg["coordinators"] if territory in (c.get("territories") or [])]


def sweep_acks(root: Path, reg: dict[str, Any], *, now: datetime | None = None, apply: bool = True,
               retry_minutes: float | None = None) -> list[dict[str, Any]]:
    """Expired, unacknowledged transfers. ``apply=False`` returns the plan and writes/notifies NOTHING.

    Delivery is best-effort through the comms-intent chokepoint: a queued alert marks the transfer alerted (never
    repeated); a REFUSED or absent chokepoint is recorded as alert_queued=false and the transfer stays retryable
    after ``ack_alert_retry_minutes`` (default 15). Processing happens only when a write command runs — there is no
    wall-clock timer in this PR; the host poll is the unactivated integration.
    """
    now = now or _now_dt()
    retry = float(retry_minutes if retry_minutes is not None
                  else reg.get("ack_alert_retry_minutes") or DEFAULT_ACK_ALERT_RETRY_MINUTES)
    out: list[dict[str, Any]] = []
    for tid, p in (reg.get("pending_acks") or {}).items():
        if p.get("acknowledged") or p.get("alerted"):
            continue
        due = _parse_iso(p.get("ack_by"))
        if due is None or now < due:
            continue
        last = _parse_iso(p.get("last_alert_at"))
        cooling = last is not None and (now - last).total_seconds() < retry * 60
        plan = {"transfer_id": tid, "to": p.get("to"), "kind": p.get("kind"),
                "territories": p.get("territories"), "ack_by": p.get("ack_by"),
                "alert_attempts": int(p.get("alert_attempts") or 0)}
        if not apply:
            out.append({**plan, "action": "would_alert" if not cooling else "would_wait_retry"})
            continue
        if cooling:
            continue  # a failed delivery is retried only after the backoff
        p["alert_attempts"] = int(p.get("alert_attempts") or 0) + 1
        p["last_alert_at"] = now_iso()
        summary = (f"no ack from {p.get('to')} for {p.get('kind')} "
                   f"({', '.join(p.get('territories') or []) or 'lead'}) since {p.get('issued_at')} "
                   f"(attempt {p['alert_attempts']})")
        # WRITE-AHEAD: the attempt is durable before the queue is reached (the queue can die mid-call).
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": None, "territory": None,
                            "kind": "ack_timeout_attempt", "subject": str(p.get("to") or ""),
                            "detail": summary, "attempt": p["alert_attempts"], "transfer_id": tid})
        queued = bool(_operator_alert(str(p.get("to") or "coordinator"), summary))
        p["alert_queued"] = queued
        if queued:
            p["alerted"] = True
            p["alerted_at"] = now_iso()
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": None, "territory": None,
                            "kind": "ack_timeout" if queued else "ack_alert_failed",
                            "subject": str(p.get("to") or ""), "detail": summary,
                            "alert_queued": queued, "attempt": p["alert_attempts"]})
        out.append({**plan, "action": "alerted" if queued else "alert_failed",
                    "attempt": p["alert_attempts"], "alert_queued": queued})
    return out


def _transfer_plan(reg: dict[str, Any], *, kind: str, to: str, territories: list[str], quote: str,
                   command: str) -> dict[str, Any]:
    """Validate and describe a transfer without touching the store (shared by --dry-run and apply)."""
    if not quote.strip():
        raise ValueError("refused: an operator transfer needs --quote with the operator's own words")
    dest = find(reg, to)
    if dest is None:
        raise ValueError(f"refused: no coordinator {to}")
    # Existence is not eligibility (D52 triage @046e73199). A stood-down destination used to be accepted, so a
    # lead transfer demoted the working lead and persisted a stood_down replacement that `heartbeat` then refuses.
    # Refuse before the plan exists: no ledger event, no handoff, no registry write, no session notice.
    if str(dest.get("status")) == "stood_down":
        raise ValueError(f"refused: destination {to} is ineligible (status stood_down); "
                         "the operator alone re-appoints")
    known = set(_all_territories(reg))
    bad = [t for t in territories if t not in known]
    if bad:
        raise ValueError(f"refused: unknown territory {', '.join(bad)}; known: {', '.join(sorted(known))}")
    givers: dict[str, list[str]] = {}
    for t in territories:
        for holder in _holders(reg, t):
            givers.setdefault(holder, []).append(t)
    former_lead = next((str(c.get("id")) for c in reg["coordinators"]
                        if str(c.get("role")) == "lead" and str(c.get("id")) != to), None)
    from_ids = sorted(set(givers) | ({former_lead} if kind == "lead" and former_lead else set()))
    tid = f"{_stamp()}-{kind}-{to}-{uuid.uuid4().hex[:8]}"  # unique even for two calls in the same second
    ack_min = float(reg.get("ack_timeout_minutes") or DEFAULT_ACK_TIMEOUT_MINUTES)
    ack_by = (_now_dt() + timedelta(minutes=ack_min)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    notices = []
    for cid in sorted(set(from_ids) | {to}):
        c = find(reg, cid)
        notices.append({"to": cid, "session": str((c or {}).get("session") or "") or None,
                        "sent": False, "planned": True})
    return {"transfer_id": tid, "kind": kind, "to": to, "territories": territories,
            "from": from_ids, "givers": givers, "former_lead": former_lead, "ack_by": ack_by,
            "handoff_name": f"{tid}-operator-to-{to}.md", "notices": notices,
            "ledger_event": {"kind": f"transfer_{kind}", "subject": to, "detail": command,
                             "operator_quote": quote, "transfer_id": tid,
                             "territories": territories, "from": from_ids,
                             "authority_note": "territory responsibility only; no broker, merge, deploy or "
                                               "scheduler authority is transferred by this event"}}


def _transfer(root: Path, reg: dict[str, Any], *, kind: str, to: str, territories: list[str],
              quote: str, command: str, tmux: str, dry_run: bool = False) -> dict[str, Any]:
    """Ledger-first transfer: plan -> ledger -> handoff -> registry/board -> tmux notices -> ack tracking."""
    plan = _transfer_plan(reg, kind=kind, to=to, territories=territories, quote=quote, command=command)
    hpath = handoffs_dir(root) / plan["handoff_name"]
    plan["handoff_path"] = str(hpath)
    if dry_run:
        return {"schema": "CoordinatorTransferPlan@v1", "dry_run": True, **plan}
    tid, givers = plan["transfer_id"], plan["givers"]
    # 1. WRITE-AHEAD: the ledger records the operator's command before the registry changes.
    append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": "operator", "territory": None,
                        **plan["ledger_event"]})
    # 2. The handoff note is generated from BOARD + ledger + assignments.
    body = [f"# Transfer {kind}: -> {to} ({now_iso()})", "",
            f"- command: `{command}`", f"- operator words (audit record, not a grant): {quote}",
            f"- territories: {', '.join(territories) or '(lead role only)'}",
            f"- from: {', '.join(plan['from']) or '(unheld)'}", "",
            "Territory transfer moves RESPONSIBILITY only: no broker, merge, deploy or scheduler authority.",
            "", "## Snapshot", "", render_board(root, reg, read_events(root)), ""]
    _atomic_write(hpath, "\n".join(body))
    # 3. Registry + BOARD.
    for holder, ts in givers.items():
        c = find(reg, holder)
        if c:
            c["territories"] = [t for t in (c.get("territories") or []) if t not in ts]
    if kind == "lead":
        for c in reg["coordinators"]:
            if str(c.get("role")) == "lead" and str(c.get("id")) != to:
                c["role"] = "member"
        find(reg, to)["role"] = "lead"
    if territories:
        target = find(reg, to)
        target["territories"] = sorted(set(target.get("territories") or []) | set(territories))
    reg.setdefault("pending_acks", {})[tid] = {
        "kind": kind, "from": plan["from"], "to": to, "territories": territories,
        "issued_at": now_iso(), "ack_by": plan["ack_by"], "command": command, "operator_quote": quote,
        "handoff": str(hpath), "acknowledged": False, "alerted": False, "alert_attempts": 0,
    }
    sync_lead(reg)
    touch(reg, quote=quote)
    reg["as_of"] = now_iso()
    _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
    _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    # 4. Notify every side (including the FORMER lead on a lead transfer) in its registered session.
    notices = []
    for cid in sorted(set(plan["from"]) | {to}):
        c = find(reg, cid)
        sess = str((c or {}).get("session") or "")
        if not sess:
            notices.append({"to": cid, "session": None, "sent": False})
            continue
        msg = (f"[coordinator] {kind}: {to} now holds {', '.join(territories) or 'the lead role'}. "
               f"Re-read BOARD.md and {hpath.name}; then run: coord ack {to}. "
               "Responsibility only: no broker/merge/deploy/scheduler authority.")
        notices.append({"to": cid, "session": sess, "sent": _notify_session(tmux, sess, msg)})
    append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": "operator", "territory": None,
                        "kind": "transfer_notified", "subject": to, "detail": json.dumps(notices),
                        "transfer_id": tid})
    return {"schema": "CoordinatorTransfer@v1", "dry_run": False, **plan, "notices": notices}


def cmd_give(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        err = coherence_error(reg)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        territories = (_all_territories(reg) if str(args.territories) == "all"
                       else [t.strip() for t in str(args.territories).split(",") if t.strip()])
        try:
            out = _transfer(root, reg, kind="give", to=_safe(args.id), territories=territories,
                            quote=str(args.quote or ""), command=" ".join(["coord"] + list(args.argv or [])),
                            tmux=args.tmux_bin or "tmux", dry_run=bool(args.dry_run))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if not args.dry_run:
            _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(json.dumps(out, indent=1))
    return 0


def cmd_lead(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        err = coherence_error(reg, allow_absent_lead=True)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        try:
            out = _transfer(root, reg, kind="lead", to=_safe(args.id), territories=[],
                            quote=str(args.quote or ""), command=" ".join(["coord"] + list(args.argv or [])),
                            tmux=args.tmux_bin or "tmux", dry_run=bool(args.dry_run))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(json.dumps(out, indent=1))
    return 0


def cmd_take_back(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        err = coherence_error(reg)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        c = find(reg, _safe(args.id))
        if not c:
            print(f"error: no coordinator {args.id}", file=sys.stderr)
            return 2
        territories = list(c.get("territories") or [])
        if not territories:
            print(f"error: {args.id} holds no territories; nothing to take back "
                  "(if it is the lead, move the lead with `coord lead <other>` first)", file=sys.stderr)
            return 2
        lead = next((x for x in reg["coordinators"] if str(x.get("role")) == "lead"), None)
        if lead is None:
            print("error: no lead to take the territories back to; appoint one with `coord lead <id>`",
                  file=sys.stderr)
            return 2
        if str(lead.get("id")) == str(c.get("id")):
            print(f"error: {args.id} is the lead; move the lead with `coord lead <other>` first", file=sys.stderr)
            return 2
        try:
            out = _transfer(root, reg, kind="take-back", to=str(lead.get("id")), territories=territories,
                            quote=str(args.quote or ""), command=" ".join(["coord"] + list(args.argv or [])),
                            tmux=args.tmux_bin or "tmux", dry_run=bool(args.dry_run))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(json.dumps(out, indent=1))
    return 0


def cmd_add(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        err = coherence_error(reg)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        cid = _safe(args.id)
        if find(reg, cid):
            print(f"error: {cid} already exists", file=sys.stderr)
            return 2
        if not str(args.quote or "").strip():
            print("error: --quote is required: adding a coordinator is the operator's act", file=sys.stderr)
            return 2
        territories = [t.strip() for t in (args.territories or "").split(",") if t.strip()]
        known = set(_all_territories(reg))
        if [t for t in territories if t not in known]:
            print(f"error: unknown territory; known: {', '.join(sorted(known))}", file=sys.stderr)
            return 2
        taken = {t: _holders(reg, t) for t in territories if _holders(reg, t)}
        if taken:
            print(f"error: territory already held ({taken}); use `coord give {cid} <territory>` to transfer it",
                  file=sys.stderr)
            return 2
        entry = {"id": cid, "vendor": args.vendor, "session": args.session or None, "where": args.where or None,
                 "territories": territories, "role": "member", "appointed_by": "operator",
                 "appointed_quote": str(args.quote), "appointed_at": now_iso(),
                 "last_heartbeat": now_iso(), "status": "active"}
        event = {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": "operator", "territory": None,
                 "kind": "appoint", "subject": cid, "detail": f"{args.vendor} as member: "
                                                              f"{', '.join(territories) or '(no territory)'}",
                 "operator_quote": str(args.quote)}
        joined = join_line(root, cid, args.vendor)
        if args.dry_run:
            print(json.dumps({"schema": "CoordinatorAddPlan@v1", "dry_run": True, "entry": entry,
                              "ledger_event": event, "join_line": joined}, indent=1))
            return 0
        # LEDGER FIRST: the event is written before the registry changes.
        append_event(root, event)
        reg["coordinators"].append(entry)
        sync_lead(reg)
        touch(reg, quote=str(args.quote))
        reg["as_of"] = now_iso()
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(joined or f"added {cid} ({args.vendor}); join line unavailable (template missing)")
    return 0


def join_line(root: Path, cid: str, vendor: str) -> str | None:
    try:
        text = (notebook(root) / "join_command.template").read_text(encoding="utf-8")
    except OSError:
        return None
    return text.replace("{id}", cid).replace("{vendor}", vendor).rstrip("\n")


def cmd_ack(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        err = coherence_error(reg)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        cid = _safe(args.id)
        if find(reg, cid) is None:
            print(f"error: no coordinator {cid}", file=sys.stderr)
            return 2
        pending = reg.get("pending_acks") or {}
        due = [(tid, p) for tid, p in pending.items()
               if str(p.get("to")) == cid and not p.get("acknowledged")
               and (not args.transfer or tid == args.transfer)]
        if not due:
            print(f"error: no pending transfer for {cid}", file=sys.stderr)
            return 2
        if args.dry_run:
            print(json.dumps({"schema": "CoordinatorAckPlan@v1", "dry_run": True, "id": cid,
                              "transfers": [tid for tid, _ in due]}, indent=1))
            return 0
        for tid, p in due:
            p["acknowledged"] = True
            p["acknowledged_at"] = now_iso()
            append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": cid, "territory": None,
                                "kind": "ack", "subject": cid, "detail": f"transfer {tid}",
                                "transfer_id": tid})
        touch(reg)
        reg["as_of"] = now_iso()
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{cid} acknowledged {len(due)} transfer(s)")
    return 0


def cmd_timeouts(args) -> int:
    """Process ack deadlines. --dry-run (default) never writes; --apply writes the bookkeeping and queues alerts."""
    root = state_root(args.state_root)
    if args.apply and args.dry_run:
        print("error: --dry-run and --apply are mutually exclusive", file=sys.stderr)
        return 2
    if args.apply:
        with locked(root):
            reg = read_registry(root, strict=True)
            err = coherence_error(reg)
            if err:
                print(f"error: {err}", file=sys.stderr)
                return 2
            fired = sweep_acks(root, reg, apply=True)
            if fired:
                _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
                _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    else:
        fired = sweep_acks(root, read_registry(root, strict=True), apply=False)
    print(json.dumps({"schema": "CoordinatorTimeouts@v1", "dry_run": not args.apply, "expired": fired}, indent=1))
    return 0


# ── commands ──────────────────────────────────────────────────────────────────────────────────────────


def cmd_status(args) -> int:
    root = state_root(args.state_root)
    reg = read_registry(root)  # strictly read-only: no lock, no sweep, no writes, no directories
    now = _now_dt()
    stale = float(reg.get("stale_after_minutes") or DEFAULT_STALE_MINUTES)
    events = read_events(root)
    doc = {
        "schema": "CoordinatorStatus@v1", "as_of": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "registry_present": registry_path(root).exists(),
        # An existing store that will not decode is NOT the same as an absent one: mutators refuse it.
        "registry_error": registry_problem(root),
        "lead": next((c.get("id") for c in reg["coordinators"] if str(c.get("role")) == "lead"), None),
        "coordinators": [{**c, "state": coordinator_state(c, stale, now)} for c in reg["coordinators"]],
        "assignments": reg["assignments"],
        "pending_checks": pending_checks(events),
        "pending_decisions": pending_decisions(events),
        "inbox": inbox_counts(root),
        "pending_acks": reg.get("pending_acks") or {},
        "ledger_events": len(events),
        "store": str(coord_root(root)),
    }
    if args.json:
        print(json.dumps(doc, indent=1))
        return 0
    if doc["registry_error"]:
        print(f"REGISTRY UNREADABLE (mutations refuse): {doc['registry_error']}")
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
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        err = coherence_error(reg, allow_absent_lead=True)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        tid = _safe(args.id)
        territories = [t.strip() for t in (args.territories or "").split(",") if t.strip()]
        if not territories:
            print("error: --territories is required (comma-separated)", file=sys.stderr)
            return 2
        # CX1 @ a9668e01c: an appointment must not duplicate a territory another coordinator holds —
        # that wrote a divergent registry which then refused every transfer and reappointment.
        taken = {t: [h for h in _holders(reg, t) if h != tid] for t in territories}
        taken = {t: hs for t, hs in taken.items() if hs}
        if taken:
            print(f"error: territory already held ({taken}); use `coord give {tid} <territory>` "
                  "to transfer it", file=sys.stderr)
            return 2
        existing = find(reg, tid)
        if existing and str(existing.get("role")) == "lead" and args.role != "lead":
            print(f"error: {tid} is the lead; re-appointing as {args.role} would leave no lead "
                  f"(use `coord lead <id>` or `coord stand-down`)", file=sys.stderr)
            return 2
        if args.role == "lead":
            other = next((c for c in reg["coordinators"]
                          if str(c.get("role")) == "lead" and str(c.get("id")) != tid
                          and str(c.get("status")) != "stood_down"), None)
            if other:
                print(f"error: {other.get('id')} is already lead; stand it down first (exactly one lead)",
                      file=sys.stderr)
                return 2
        stamp = now_iso()
        entry = {"id": tid, "vendor": args.vendor, "session": args.session or None,
                 "where": args.where or None, "territories": territories, "role": args.role,
                 "appointed_by": "operator", "appointed_quote": quote, "appointed_at": stamp,
                 "last_heartbeat": stamp, "status": "active"}
        if getattr(args, "dry_run", False):
            print(json.dumps({"schema": "CoordinatorAppointPlan@v1", "dry_run": True, "entry": entry,
                              "territories": territories,
                              "ledger_events": [
                                  {"kind": "appoint", "subject": tid,
                                   "detail": f"{args.vendor} as {args.role}: {', '.join(territories)}",
                                   "operator_quote": quote},
                                  {"kind": "heartbeat", "subject": tid, "detail": "initial"}],
                              "registry_path": str(registry_path(root)),
                              "board_path": str(board_path(root))}, indent=1))
            return 0
        reg["coordinators"] = [c for c in reg["coordinators"] if str(c.get("id")) != tid] + [entry]
        sync_lead(reg)
        touch(reg, quote=quote)
        reg["as_of"] = now_iso()
        # Write-ahead: the ledger line exists before the registry changes, so a crash between the two leaves an
        # auditable record of what was granted instead of a silent grant.
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": tid, "territory": None,
                            "kind": "appoint", "subject": tid,
                            "detail": f"{args.vendor} as {args.role}: {', '.join(territories)}",
                            "operator_quote": quote})
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": tid, "territory": None,
                            "kind": "heartbeat", "subject": tid, "detail": "initial"})
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{tid} appointed {args.role} ({args.vendor}) over {', '.join(territories)}")
    return 0


def cmd_stand_down(args) -> int:
    root = state_root(args.state_root)
    if not str(args.quote or "").strip():
        print("error: refused: an operator transfer needs --quote with the operator's own words", file=sys.stderr)
        return 2
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        c = find(reg, _safe(args.id))
        if not c:
            print(f"error: no coordinator {args.id}", file=sys.stderr)
            return 2
        if getattr(args, "dry_run", False):
            print(json.dumps({"schema": "CoordinatorStandDownPlan@v1", "dry_run": True, "id": c["id"],
                              "role": c.get("role"), "status": c.get("status")}, indent=1))
            return 0
        c["status"] = "stood_down"
        c["last_heartbeat"] = now_iso()
        if str(c.get("role")) == "lead":
            c["role"] = "member"
            sync_lead(reg)
        touch(reg)
        reg["as_of"] = now_iso()
        # Ledger first: a crash between these two must not leave a stood-down registry with no
        # stand_down event (and the reverse — event without registry — is recoverable by re-run).
        append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": c["id"], "territory": None,
                            "kind": "stand_down", "subject": c["id"], "detail": args.quote or None,
                            "operator_quote": args.quote or None})
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{args.id} stood down")
    return 0


def cmd_heartbeat(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        c = find(reg, _safe(args.id))
        if not c:
            print(f"error: no coordinator {args.id}", file=sys.stderr)
            return 2
        if str(c.get("status")) == "stood_down":
            print(f"error: {args.id} is stood down; the operator alone re-appoints", file=sys.stderr)
            return 2
        stamp = now_iso()
        event = {"schema": SCHEMA_EVENT, "ts": stamp, "coordinator": c["id"], "territory": None,
                 "kind": "heartbeat", "subject": c["id"], "detail": None}
        if getattr(args, "dry_run", False):
            print(json.dumps({"schema": "CoordinatorHeartbeatPlan@v1", "dry_run": True, "id": c["id"],
                              "heartbeat_at": stamp, "ledger_event": event,
                              "registry_path": str(registry_path(root))}, indent=1))
            return 0
        c["last_heartbeat"] = stamp
        c["status"] = "active"
        reg["as_of"] = stamp
        _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        append_event(root, event)
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{args.id} heartbeat {stamp}")
    return 0


def cmd_assign(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        tid = _safe(args.territory)
        known = set(reg["territories"]) | {t for c in reg["coordinators"] for t in (c.get("territories") or [])}
        if tid not in known:
            print(f"error: unknown territory {args.territory!r}; known: {', '.join(sorted(known))}", file=sys.stderr)
            return 2
        event = {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": args.coordinator, "territory": tid,
                 "kind": "assign", "subject": str(args.subject), "detail": f"territory {tid}"}
        if getattr(args, "dry_run", False):
            after = dict(reg["assignments"])
            after[str(args.subject)] = tid
            print(json.dumps({"schema": "CoordinatorAssignPlan@v1", "dry_run": True,
                              "subject": str(args.subject), "territory": tid,
                              "assignments_after": after, "ledger_event": event,
                              "registry_path": str(registry_path(root))}, indent=1))
            return 0
        reg["assignments"][str(args.subject)] = tid
        reg["as_of"] = now_iso()
        # LEDGER FIRST (cx-openai D52 KEEP_BLOCK at d0f84722c): the assignment event is appended before the
        # reassignment is persisted. The previous order wrote the registry first, so a failed append left the
        # territory reassigned with no record of who was told to take it -- the same durable audit inconsistency
        # the handoff verb had. `coord add` and `coord handoff` use this order.
        try:
            append_event(root, event)
        except OSError as exc:
            print(f"error: the assignment event could not be recorded ({exc}); the assignment is unchanged "
                  f"({args.subject} stays where it was)", file=sys.stderr)
            return 2
        try:
            _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        except OSError as exc:
            print(f"error: the assignment event is recorded but the registry write failed ({exc}); the assignment "
                  "has NOT moved -- re-run `coord assign`", file=sys.stderr)
            return 2
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"{args.subject} -> {tid}")
    return 0


#: Kinds whose meaning belongs to a verb with its own guards. The generic `event` append used to accept any word,
#: so `coord event check_ok ...` cleared a pending check (and `--coordinator` was whatever the caller typed),
#: bypassing the two-coordinator check path. Those kinds are refused here; use the owning verb.
RESERVED_EVENT_KINDS = frozenset({
    "check_request", "check_ok", "check_block",
    # The transfer verbs write transfer_give / transfer_lead / transfer_take-back (and
    # transfer_notified). A bare "transfer" never appears; blocking only that left the real
    # kinds forgeable through `coord event` (claude-lead BLOCK @ b22fb2f00).
    "transfer", "transfer_give", "transfer_lead", "transfer_take-back", "transfer_notified",
    "ack", "handoff", "stand_down",
    "appoint", "heartbeat", "inbox_send",
})


def cmd_event(args) -> int:
    root = state_root(args.state_root)
    if str(args.kind) in RESERVED_EVENT_KINDS:
        print(f"error: refused: '{args.kind}' belongs to its own verb; the generic event cannot state it",
              file=sys.stderr)
        return 2
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)  # refuse before appending to a store we cannot read
        event = {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": args.coordinator,
                 "territory": args.territory, "kind": str(args.kind), "subject": args.subject,
                 "detail": args.detail, "operator_quote": args.quote}
        if getattr(args, "dry_run", False):
            print(json.dumps({"schema": "CoordinatorEventPlan@v1", "dry_run": True, "ledger_event": event,
                              "board_path": str(board_path(root))}, indent=1))
            return 0
        append_event(root, event)
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(f"event {args.kind} recorded")
    return 0


def cmd_check(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        events = read_events(root)
        subject, sha = str(args.subject), str(args.sha or "")
        kind = "check_request" if args.action == "request" else f"check_{args.action}"
        if args.action == "request":
            event = {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": args.by, "territory": None,
                     "kind": kind, "subject": subject, "sha": sha, "detail": args.reason or None}
        else:
            # Answer the request the panel SHOWS as pending (codex-cloud P2 at :1248). ``pending_checks`` keeps the
            # OLDEST unanswered request per (subject, sha) and this lookup took the NEWEST, so a duplicate request
            # could make the panel show one coordinator's request while the different-coordinator guard judged
            # another's -- the reader was refused for answering a request they never saw.
            req = next((e for e in pending_checks(events)
                        if str(e.get("subject")) == subject and str(e.get("sha") or "") == sha), None)
            if not req:
                print(f"error: no check_request for {subject} @ {sha[:12]}", file=sys.stderr)
                return 2
            if str(req.get("coordinator")) == str(args.by):
                print("error: the check must come from a DIFFERENT active coordinator", file=sys.stderr)
                return 2
            if args.by not in active_ids(reg):
                print(f"error: {args.by} is not an active coordinator", file=sys.stderr)
                return 2
            event = {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": args.by, "territory": None,
                     "kind": kind, "subject": subject, "sha": sha, "detail": args.reason or None}
        if getattr(args, "dry_run", False):
            print(json.dumps({"schema": "CoordinatorCheckPlan@v1", "dry_run": True, "action": args.action,
                              "subject": subject, "sha": sha, "by": args.by, "ledger_event": event,
                              "board_path": str(board_path(root))}, indent=1))
            return 0
        append_event(root, event)
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
        dry_run = bool(getattr(args, "dry_run", False))
        with (nullcontext() if dry_run else locked(root)):
            read_registry(root, strict=True)  # an inbox send writes the store: a damaged registry refuses it
            d = inbox_dir(root, _safe(args.to))
            p = d / f"{_stamp()}-{uuid.uuid4().hex[:8]}-{sender}.md"  # unique even for two sends in the same second
            text = (body or "").rstrip() + "\n"
            event = {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": sender, "territory": None,
                     "kind": "inbox_send", "subject": _safe(args.to), "detail": p.name}
            if dry_run:
                print(json.dumps({"schema": "CoordinatorInboxSendPlan@v1", "dry_run": True,
                                  "to": _safe(args.to), "from": sender, "path": str(p),
                                  "bytes": len(text.encode("utf-8")), "ledger_event": event}, indent=1))
                return 0
            d.mkdir(parents=True, exist_ok=True)
            _atomic_write(p, text)
            append_event(root, event)
        print(p)
        return 0
    cid = _safe(args.id or "")
    if not cid:
        print("error: --id is required", file=sys.stderr)
        return 2
    d = inbox_dir(root, cid)
    dry_run = bool(getattr(args, "dry_run", False))
    keep = bool(getattr(args, "keep", False)) or dry_run
    moved = 0
    with (nullcontext() if dry_run else locked(root)):
        read_registry(root, strict=True)  # a read that moves files writes the store: refuse a damaged registry
        try:
            items = sorted(f for f in d.iterdir() if f.is_file() and not f.is_symlink())
        except OSError:
            items = []
        if not items:
            print(f"inbox {cid}: empty")
            return 0
        read = d / "read"
        for f in items:
            print(f"=== {f.name} ===")
            try:
                print(f.read_text(encoding="utf-8").rstrip())
            except OSError:
                print("(unreadable)")
            if not keep:
                # Listing and moving happen under the same lock: another reader that moved the file first must
                # not turn this into an uncaught FileNotFoundError.
                try:
                    read.mkdir(exist_ok=True)
                    os.replace(f, read / f.name)  # move, never delete
                    moved += 1
                except OSError:
                    continue
    if dry_run:
        print(f"(dry run: {len(items)} item(s) would move to {d / 'read'}; nothing written)")
    elif not args.keep:
        print(f"({moved} item(s) moved to {d / 'read'})")
    return 0


def cmd_handoff(args) -> int:
    root = state_root(args.state_root)
    src, dst = _safe(args.from_), _safe(args.to)
    # CX3 @ a9668e01c: a handoff to the same id emptied its own territories and returned 0.
    if src == dst:
        print(f"error: refused: --from and --to are the same coordinator ({src}); "
              "a handoff must move work to a different coordinator", file=sys.stderr)
        return 2
    if not str(args.quote or "").strip():
        print("error: refused: an operator transfer needs --quote with the operator's own words", file=sys.stderr)
        return 2
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        a, b = find(reg, src), find(reg, dst)
        if not a or not b:
            print(f"error: both coordinators must exist ({src}, {dst})", file=sys.stderr)
            return 2
        events = read_events(root)
        stamp = _stamp()
        p = handoffs_dir(root) / f"{stamp}-{uuid.uuid4().hex[:8]}-{src}-to-{dst}.md"
        if getattr(args, "dry_run", False):
            print(json.dumps({"schema": "CoordinatorHandoffPlan@v1", "dry_run": True, "from": src, "to": dst,
                              "territories": sorted(set(b.get("territories") or []) | set(a.get("territories") or [])),
                              "lead_moves": str(a.get("role")) == "lead", "snapshot": str(p)}, indent=1))
            return 0
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
            # The registry has TWO views of the lead (the top-level field and a role). Handoff used to move only
            # the role, leaving the registry divergent and every later mutation refused by coherence_error.
            sync_lead(reg)
        reg["as_of"] = now_iso()
        # LEDGER FIRST (cx-openai D52 triage at b10809549): the validated handoff event is appended before the
        # ownership change is persisted. The previous order fsynced the new registry first, so a failed append left
        # territories and the lead already moved with no handoff record to explain it -- durable ownership changed
        # and unexplained. The lock serialises the writers but gives no rollback; ordering is what makes a failed
        # append harmless. A recorded event whose registry write fails is recoverable by re-running the command.
        try:
            append_event(root, {"schema": SCHEMA_EVENT, "ts": now_iso(), "coordinator": src, "territory": None,
                                "kind": "handoff", "subject": dst, "detail": p.name})
        except OSError as exc:
            print(f"error: the handoff event could not be recorded ({exc}); ownership is unchanged "
                  f"(snapshot {p.name} was written)", file=sys.stderr)
            return 2
        try:
            _atomic_write(registry_path(root), json.dumps(reg, indent=1, sort_keys=True) + "\n")
        except OSError as exc:
            print(f"error: the handoff event is recorded but the registry write failed ({exc}); ownership has NOT "
                  "moved -- re-run `coord handoff`", file=sys.stderr)
            return 2
        _atomic_write(board_path(root), render_board(root, reg, read_events(root)))
    print(p)
    return 0


def cmd_board(args) -> int:
    root = state_root(args.state_root)
    with (nullcontext() if getattr(args, "dry_run", False) else locked(root)):
        reg = read_registry(root, strict=True)
        text = render_board(root, reg, read_events(root))
        if getattr(args, "dry_run", False):
            p = board_path(root)
            try:
                current = p.read_text(encoding="utf-8")
            except OSError:
                current = None
            print(json.dumps({"schema": "CoordinatorBoardPlan@v1", "dry_run": True, "board_path": str(p),
                              "bytes": len(text.encode("utf-8")), "would_change": text != current}, indent=1))
            return 0
        _atomic_write(board_path(root), text)
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


CLOCK_PARSER = argparse.ArgumentParser(add_help=False)
CLOCK_PARSER.add_argument("--now", default=None, help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Co-coordinators by territory: registry and shared notebook")
    ap.add_argument("--state-root", default=None, help="persistent-state root (default: TRADEAI_STATE_ROOT or ~)")
    ap.add_argument("--now", default=None, help="pin the clock (ISO with offset; tests and replays)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--coordinator", default=None, help="the acting coordinator id (ledger attribution)")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("status", parents=[CLOCK_PARSER], help="registry, freshness, pending checks and decisions")
    common(p)

    p = sub.add_parser("appoint", parents=[CLOCK_PARSER], help="operator: appoint a coordinator (--quote required)")
    p.add_argument("--id", required=True)
    p.add_argument("--vendor", required=True)
    p.add_argument("--session", default=None)
    p.add_argument("--where", default=None)
    p.add_argument("--territories", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--quote", required=True)
    p.add_argument("--dry-run", action="store_true", help="validate and show the intended writes; write nothing")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("stand-down", parents=[CLOCK_PARSER], help="operator: stand a coordinator down (--quote required)")
    p.add_argument("--id", required=True)
    p.add_argument("--quote", required=True, help="the operator's own words (recorded verbatim)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("heartbeat", parents=[CLOCK_PARSER], help="record liveness")
    p.add_argument("--id", required=True)
    p.add_argument("--dry-run", action="store_true", help="validate and show the intended writes; write nothing")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("assign", parents=[CLOCK_PARSER], help="assign an agent or pr:<n> to a territory")
    p.add_argument("subject")
    p.add_argument("territory")
    p.add_argument("--dry-run", action="store_true", help="validate and show the intended writes; write nothing")
    common(p)

    p = sub.add_parser("event", parents=[CLOCK_PARSER], help="append a ledger event (write-ahead)")
    p.add_argument("kind")
    p.add_argument("--subject", default=None)
    p.add_argument("--detail", default=None)
    p.add_argument("--territory", default=None)
    p.add_argument("--quote", default=None)
    p.add_argument("--dry-run", action="store_true", help="validate and show the intended writes; write nothing")
    common(p)

    p = sub.add_parser("check", parents=[CLOCK_PARSER], help="two-coordinator check: request | ok | block")
    p.add_argument("action", choices=("request", "ok", "block"))
    p.add_argument("subject")
    p.add_argument("--sha", default="")
    p.add_argument("--by", required=True)
    p.add_argument("--reason", default=None)
    p.add_argument("--dry-run", action="store_true", help="validate and show the intended writes; write nothing")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("inbox", parents=[CLOCK_PARSER], help="send a report to a coordinator, or read (and move) its inbox")
    p.add_argument("action", choices=("send", "read"))
    p.add_argument("--to", default=None)
    p.add_argument("--from", dest="from_", default=None)
    p.add_argument("--text", default=None)
    p.add_argument("--file", default=None)
    p.add_argument("--id", default=None)
    p.add_argument("--keep", action="store_true", help="read without moving to read/")
    p.add_argument("--dry-run", action="store_true", help="show what would be sent or moved; write nothing")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("handoff", parents=[CLOCK_PARSER], help="operator: hand territories and the lead role over (--quote required)")
    p.add_argument("--from", dest="from_", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--quote", required=True, help="the operator's own words (recorded verbatim)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("board", parents=[CLOCK_PARSER], help="regenerate BOARD.md")
    p.add_argument("--dry-run", action="store_true", help="show the board that would be written; write nothing")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("give", parents=[CLOCK_PARSER], help="operator: give a territory (or 'all') to a coordinator")
    p.add_argument("id")
    p.add_argument("territories")
    p.add_argument("--quote", required=True, help="the operator's own words (recorded verbatim)")
    p.add_argument("--tmux-bin", default="tmux")
    p.add_argument("--dry-run", action="store_true", help="show every intended effect; write and notify nothing")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("lead", parents=[CLOCK_PARSER], help="operator: make a coordinator the one lead")
    p.add_argument("id")
    p.add_argument("--quote", required=True)
    p.add_argument("--tmux-bin", default="tmux")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("take-back", parents=[CLOCK_PARSER], help="operator: take a coordinator's territories back to the lead")
    p.add_argument("id")
    p.add_argument("--quote", required=True)
    p.add_argument("--tmux-bin", default="tmux")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("add", parents=[CLOCK_PARSER], help="operator: add a coordinator and print its join line")
    p.add_argument("id")
    p.add_argument("--vendor", required=True)
    p.add_argument("--session", default=None)
    p.add_argument("--where", default=None)
    p.add_argument("--territories", default="")
    p.add_argument("--quote", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("ack", parents=[CLOCK_PARSER], help="receiver: acknowledge its pending transfer")
    p.add_argument("id")
    p.add_argument("--transfer", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("timeouts", parents=[CLOCK_PARSER],
                       help="process ack deadlines (--dry-run default; --apply writes bookkeeping and queues alerts)")
    p.add_argument("--apply", action="store_true", help="write the bookkeeping and queue alerts (default: plan only)")
    p.add_argument("--dry-run", action="store_true", help="explicit plan-only form (the default)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("snapshot", parents=[CLOCK_PARSER], help="host lane: capture each agent session's visible screen (tmux)")
    p.add_argument("--sessions", default=None, help="comma-separated tmux session patterns "
                                                    f"(default {'/'.join(DEFAULT_SNAPSHOT_SESSIONS)})")
    p.add_argument("--lines", type=int, default=40)
    p.add_argument("--tmux-bin", default="tmux")
    p.add_argument("--dry-run", action="store_true", help="list the sessions and files it would capture; write nothing")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("whoami", parents=[CLOCK_PARSER], help="which coordinator and territory is this session")
    p.add_argument("--session", default=None)
    p.add_argument("--json", action="store_true")
    return ap


COMMANDS = {"status": cmd_status, "appoint": cmd_appoint, "stand-down": cmd_stand_down,
            "heartbeat": cmd_heartbeat, "assign": cmd_assign, "event": cmd_event, "check": cmd_check,
            "inbox": cmd_inbox, "handoff": cmd_handoff, "board": cmd_board, "whoami": cmd_whoami,
            "snapshot": cmd_snapshot, "give": cmd_give, "lead": cmd_lead, "take-back": cmd_take_back,
            "add": cmd_add, "ack": cmd_ack, "timeouts": cmd_timeouts}


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw)
    global _CLOCK
    if getattr(args, "now", None):
        clock = datetime.fromisoformat(str(args.now).replace("Z", "+00:00"))
        _CLOCK = clock if clock.tzinfo else clock.replace(tzinfo=timezone.utc)
    else:
        _CLOCK = None
    # The original command, minus the test-only clock/root options, is what the ledger records verbatim.
    cleaned, skip = [], False
    for a in raw:
        if skip:
            skip = False
            continue
        if a in ("--now", "--state-root"):
            skip = True
            continue
        if a.startswith("--now=") or a.startswith("--state-root="):
            continue
        cleaned.append(a)
    args.argv = cleaned
    try:
        return COMMANDS[args.cmd](args)
    except RegistryUnreadable as exc:
        # Every mutator reads strictly; a damaged registry is refused, never reset (CX2 @ a9668e01c).
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
