"""Incident ledger — IncidentRecord@v1, the one writer (operator 2026-10-27).

Operator, 2026-10-27: "agents … if they have an error, they can't just drop and leave it. They need to fix it and
report it somewhere in a log that you could come back in as a coordinator and look at it."

Store (``incidents_dir()``; default ``<persistent-state>/data/coordination/incidents/``):

* ``events.jsonl`` — append-only ``IncidentEvent@v1`` rows. Never rewritten, never truncated (AGENTS.md §0 rule 6).
* ``index.json`` — ``IncidentIndex@v1``, the materialised fold of the events. Derived: ``rebuild_index()`` recreates
  it byte-for-byte from the events, so it is never the authority.

Every writer (agents through ``scripts/incident.py``, the watchers, the supervisor, the Command Center operator
routes) goes through ``append_event`` here, which takes an exclusive ``flock`` on ``.lock``, appends one line and
re-materialises the index under the same lock. Stdlib only. AUTHORITY: READ_ONLY_ADVISORY — the ledger records; it
never orders, sizes, stops, writes a broker, reads a secret, merges or promotes (§0 rules 1–2).

Statuses: ``open`` → ``fixing`` → ``fixed`` | ``blocked`` (handoff recorded) | ``closed`` (operator won't-fix).
``fixed`` and ``closed`` are terminal; a new occurrence of the same fingerprint opens a NEW incident that links the
previous one (``recurrence_of``), so history is never edited.

Incident ids are ``INC-YYMMDD-xxxxxx`` with a suffix drawn from a non-hex alphabet: the comms editor fingerprint
(scripts/lib/comms_editor.py) strips 7–40 char hex runs and timestamps, and 386 deploy alerts were suppressed on
2026-10-26/27 because the only distinguishing token was a SHA. An incident id survives that normalisation.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "IncidentRecord@v1"
EVENT_SCHEMA = "IncidentEvent@v1"
INDEX_SCHEMA = "IncidentIndex@v1"

STATUSES = ("open", "fixing", "fixed", "blocked", "closed")
TERMINAL = frozenset({"fixed", "closed"})
UNRESOLVED = frozenset({"open", "fixing"})
SOURCE_KINDS = ("agent", "job", "lane", "deploy", "ci", "watcher", "operator")
FIX_REF_KINDS = ("pr", "commit", "receipt", "doc", "incident")
EVENT_KINDS = (
    "open",  # new incident
    "update",  # owner / note / evidence / status open<->fixing
    "attempt",  # an action was tried (agent, runbook action, fixer dispatch, model triage)
    "fix",  # status -> fixed with fix_refs
    "block",  # status -> blocked with blocked_reason + handoff
    "resolve",  # watcher: condition cleared -> fixed (auto_resolved)
    "escalate",  # a P1 left the chokepoint for this incident
    "ack",  # operator acknowledged (no status change)
    "close",  # operator: close as won't-fix -> closed
    "reopen",  # blocked -> open (a person picked it up again)
)

_ID_ALPHABET = "ghjkmnpqrstvwxyz"  # no hex letters, no digits: survives comms_editor.fingerprint
_ID_RE = re.compile(r"^INC-\d{6}-[g-z]{6}$")

DEFAULT_REL = Path("data") / "coordination" / "incidents"


# ---------------------------------------------------------------- paths


def incidents_dir(root: Optional[Path | str] = None) -> Path:
    """``$TRADEAI_INCIDENTS_DIR`` → ``root``/data/coordination/incidents → persistent-state root."""
    env = os.environ.get("TRADEAI_INCIDENTS_DIR")
    if env:
        return Path(env)
    if root is not None:
        return Path(root) / DEFAULT_REL
    try:
        from scripts.lib.persistent_state_root import good_persistent_root
    except ImportError:
        try:  # api_v2 puts scripts/ on sys.path
            from lib.persistent_state_root import good_persistent_root  # type: ignore[no-redef]
        except ImportError:  # callers that only put scripts/lib on sys.path
            from persistent_state_root import good_persistent_root  # type: ignore[no-redef]
    return Path(good_persistent_root()) / DEFAULT_REL


def events_path(d: Path) -> Path:
    return d / "events.jsonl"


def index_path(d: Path) -> Path:
    return d / "index.json"


# ---------------------------------------------------------------- time + ids


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def make_id(seed: str, opened_at: datetime) -> str:
    h = hashlib.sha256(f"{seed}|{iso(opened_at)}".encode()).digest()
    suffix = "".join(_ID_ALPHABET[b % len(_ID_ALPHABET)] for b in h[:6])
    return f"INC-{opened_at.astimezone(timezone.utc):%y%m%d}-{suffix}"


def valid_id(s: str) -> bool:
    return bool(_ID_RE.match(str(s or "")))


def fingerprint_of(*parts: Any) -> str:
    """Stable fingerprint. Callers pass the distinguishing tokens (job, SHA, lane); nothing is normalised away."""
    return "fp-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- the fold


def _blank(ev: Mapping[str, Any]) -> dict:
    return {
        "schema": SCHEMA,
        "id": ev["incident_id"],
        "opened_at": ev["at"],
        "source": dict(ev.get("source") or {}),
        "title": ev.get("title") or "",
        "where": ev.get("where") or "",
        "fingerprint": ev.get("fingerprint"),
        "severity": ev.get("severity") or "P2",
        "evidence": list(ev.get("evidence") or []),
        "owner": ev.get("owner") or "",
        "status": "open",
        "attempts": [],
        "fix_refs": [],
        "notes": [],
        "blocked_reason": None,
        "handoff": None,
        "resolution": None,
        "closed_at": None,
        "acknowledged": None,
        "escalations": [],
        "recurrence_of": ev.get("recurrence_of"),
        "updated_at": ev["at"],
        "event_count": 0,
    }


def _apply(rec: dict, ev: Mapping[str, Any]) -> None:
    kind = ev["kind"]
    at = ev["at"]
    actor = ev.get("actor") or ""
    rec["updated_at"] = at
    rec["event_count"] += 1
    if ev.get("evidence") and kind != "open":
        rec["evidence"].extend(e for e in ev["evidence"] if e not in rec["evidence"])
    if ev.get("fix_refs"):
        rec["fix_refs"].extend(r for r in ev["fix_refs"] if r not in rec["fix_refs"])
    if ev.get("note"):
        rec["notes"].append({"at": at, "actor": actor, "text": ev["note"]})
    if ev.get("owner"):
        rec["owner"] = ev["owner"]
    if kind == "update":
        if ev.get("status") in ("open", "fixing") and rec["status"] in UNRESOLVED:
            rec["status"] = ev["status"]
    elif kind == "attempt":
        a = dict(ev.get("attempt") or {})
        a.setdefault("at", at)
        a.setdefault("actor", actor)
        rec["attempts"].append(a)
        if rec["status"] == "open" and a.get("sets_fixing"):
            rec["status"] = "fixing"
    elif kind in ("fix", "resolve"):
        rec["status"] = "fixed"
        rec["closed_at"] = at
        rec["resolution"] = ev.get("resolution") or ("auto_resolved" if kind == "resolve" else "fixed")
    elif kind == "block":
        rec["status"] = "blocked"
        rec["blocked_reason"] = ev.get("blocked_reason")
        rec["handoff"] = ev.get("handoff")
    elif kind == "reopen":
        rec["status"] = "open"
        rec["closed_at"] = None
        rec["resolution"] = None
    elif kind == "escalate":
        rec["escalations"].append({"at": at, "reason": ev.get("reason"), "delivered": ev.get("delivered")})
    elif kind == "ack":
        rec["acknowledged"] = {"at": at, "actor": actor, "decision_ref": ev.get("decision_ref"), "comment": ev.get("note")}
    elif kind == "close":
        rec["status"] = "closed"
        rec["closed_at"] = at
        rec["resolution"] = "wont_fix"
        rec["acknowledged"] = rec["acknowledged"] or {"at": at, "actor": actor, "decision_ref": ev.get("decision_ref")}
        if ev.get("decision_ref"):
            rec["fix_refs"].append({"kind": "doc", "ref": ev["decision_ref"]})


def fold(events: Iterable[Mapping[str, Any]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ev in events:
        iid = ev.get("incident_id")
        if not iid or ev.get("kind") not in EVENT_KINDS:
            continue
        if ev["kind"] == "open":
            if iid in out:
                continue
            out[iid] = _blank(ev)
        if iid not in out:
            continue
        _apply(out[iid], ev)
    return out


def read_events(d: Path) -> list[dict]:
    p = events_path(d)
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            continue  # a torn tail line from a crash is skipped, never repaired in place
        if isinstance(doc, dict) and doc.get("schema") == EVENT_SCHEMA:
            out.append(doc)
    return out


def summarize(records: Mapping[str, Mapping[str, Any]], now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    counts = {s: 0 for s in STATUSES}
    oldest_open = None
    for r in records.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] in UNRESOLVED:
            t = parse_ts(r["opened_at"])
            if t and (oldest_open is None or t < oldest_open[0]):
                oldest_open = (t, r["id"])
    return {
        "counts": counts,
        "unresolved": counts["open"] + counts["fixing"],
        "oldest_unresolved_id": oldest_open[1] if oldest_open else None,
        "oldest_unresolved_age_min": int((now - oldest_open[0]).total_seconds() // 60) if oldest_open else None,
    }


def build_index(events: list[dict], now: Optional[datetime] = None) -> dict:
    recs = fold(events)
    ordered = sorted(recs.values(), key=lambda r: (r["status"] in TERMINAL, r["opened_at"]), reverse=False)
    # unresolved first (oldest first), then terminal newest first
    unresolved = [r for r in ordered if r["status"] not in TERMINAL]
    terminal = sorted((r for r in ordered if r["status"] in TERMINAL), key=lambda r: r["updated_at"], reverse=True)
    return {
        "schema": INDEX_SCHEMA,
        "generated_at": iso(now or utcnow()),
        "event_count": len(events),
        "summary": summarize(recs, now),
        "incidents": unresolved + terminal,
    }


# ---------------------------------------------------------------- the one writer


@contextmanager
def _locked(d: Path) -> Iterator[None]:
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _write_index(d: Path, index: Mapping[str, Any]) -> None:
    p = index_path(d)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(index, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


class LedgerError(ValueError):
    pass


def _validate(ev: Mapping[str, Any], current: Optional[Mapping[str, Any]]) -> None:
    kind = ev.get("kind")
    if kind not in EVENT_KINDS:
        raise LedgerError(f"unknown event kind {kind!r}")
    if kind == "open":
        src = ev.get("source") or {}
        if src.get("kind") not in SOURCE_KINDS:
            raise LedgerError(f"source.kind must be one of {SOURCE_KINDS}")
        if not str(ev.get("title") or "").strip():
            raise LedgerError("title is required")
        return
    if current is None:
        raise LedgerError(f"no such incident {ev.get('incident_id')!r}")
    st = current["status"]
    if kind in ("fix", "resolve", "block", "attempt", "update") and st in TERMINAL:
        raise LedgerError(f"{current['id']} is {st}; open a new incident (recurrence) instead")
    if kind == "fix" and not ev.get("fix_refs"):
        raise LedgerError("fix needs at least one fix_ref (pr/commit/receipt)")
    if kind == "block" and not (ev.get("blocked_reason") and ev.get("handoff")):
        raise LedgerError("block needs blocked_reason and handoff (the exact next step for whoever picks it up)")
    if kind == "close" and st in TERMINAL:
        raise LedgerError(f"{current['id']} is already {st}")
    if kind == "reopen" and st != "blocked":
        raise LedgerError("only a blocked incident can be reopened")
    for r in ev.get("fix_refs") or []:
        if not isinstance(r, dict) or r.get("kind") not in FIX_REF_KINDS or not r.get("ref"):
            raise LedgerError(f"fix_ref must be {{kind in {FIX_REF_KINDS}, ref}}: {r!r}")


def append_event(ev: dict, *, d: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    """Validate, append one IncidentEvent@v1, re-materialise the index. Returns the folded record."""
    d = d or incidents_dir()
    t = now or utcnow()
    with _locked(d):
        events = read_events(d)
        recs = fold(events)
        ev = {"schema": EVENT_SCHEMA, "at": iso(t), **{k: v for k, v in ev.items() if v is not None}}
        _validate(ev, recs.get(ev.get("incident_id")))
        line = json.dumps(ev, sort_keys=True, ensure_ascii=False)
        with open(events_path(d), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        events.append(ev)
        index = build_index(events, t)
        _write_index(d, index)
        return fold(events)[ev["incident_id"]]


def rebuild_index(d: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    d = d or incidents_dir()
    with _locked(d):
        index = build_index(read_events(d), now)
        _write_index(d, index)
        return index


def load_records(d: Optional[Path] = None) -> dict[str, dict]:
    return fold(read_events(d or incidents_dir()))


def load_index(d: Optional[Path] = None) -> dict:
    """Read the materialised index; falls back to folding the events (never writes)."""
    d = d or incidents_dir()
    try:
        doc = json.loads(index_path(d).read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("schema") == INDEX_SCHEMA:
            return doc
    except (OSError, ValueError):
        pass
    return build_index(read_events(d))


def find_unresolved_by_fingerprint(recs: Mapping[str, Mapping[str, Any]], fp: str) -> Optional[dict]:
    for r in recs.values():
        if r.get("fingerprint") == fp and r["status"] not in TERMINAL:
            return dict(r)
    return None


def last_terminal_by_fingerprint(recs: Mapping[str, Mapping[str, Any]], fp: str) -> Optional[dict]:
    hits = [r for r in recs.values() if r.get("fingerprint") == fp and r["status"] in TERMINAL]
    return dict(max(hits, key=lambda r: r["updated_at"])) if hits else None


# ---------------------------------------------------------------- verbs


def open_incident(
    *,
    source: Mapping[str, Any],
    title: str,
    where: str = "",
    evidence: Optional[list] = None,
    owner: str = "",
    fingerprint: Optional[str] = None,
    severity: str = "P2",
    actor: str = "",
    note: Optional[str] = None,
    d: Optional[Path] = None,
    now: Optional[datetime] = None,
    incident_id: Optional[str] = None,
) -> tuple[dict, bool]:
    """Open an incident, or return the unresolved one with the same fingerprint. ``(record, created)``."""
    d = d or incidents_dir()
    t = now or utcnow()
    fp = fingerprint or fingerprint_of(source.get("kind"), source.get("job") or source.get("lane") or "", title, where)
    recs = load_records(d)
    existing = find_unresolved_by_fingerprint(recs, fp)
    if existing and existing["status"] != "blocked":
        return existing, False
    if existing:  # blocked: a person owns it; the occurrence is noted, not duplicated
        return existing, False
    prev = last_terminal_by_fingerprint(recs, fp)
    iid = incident_id or make_id(fp, t)
    ev = {
        "kind": "open",
        "incident_id": iid,
        "source": dict(source),
        "title": title.strip()[:300],
        "where": where,
        "evidence": list(evidence or []),
        "owner": owner,
        "fingerprint": fp,
        "severity": severity,
        "actor": actor or source.get("session") or source.get("agent") or source.get("kind"),
        "note": note,
        "recurrence_of": prev["id"] if prev else None,
    }
    return append_event(ev, d=d, now=t), True


def update(incident_id: str, *, actor: str, note: Optional[str] = None, status: Optional[str] = None,
           owner: Optional[str] = None, evidence: Optional[list] = None, d: Optional[Path] = None,
           now: Optional[datetime] = None) -> dict:
    return append_event({"kind": "update", "incident_id": incident_id, "actor": actor, "note": note,
                         "status": status, "owner": owner, "evidence": evidence}, d=d, now=now)


def attempt(incident_id: str, *, actor: str, action: str, result: str, ok: Optional[bool] = None,
            detail: Optional[Mapping[str, Any]] = None, fix_refs: Optional[list] = None, sets_fixing: bool = True,
            d: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    a = {"action": action, "result": result, "ok": ok, "sets_fixing": sets_fixing, **dict(detail or {})}
    return append_event({"kind": "attempt", "incident_id": incident_id, "actor": actor, "attempt": a,
                         "fix_refs": fix_refs}, d=d, now=now)


def fix(incident_id: str, *, actor: str, fix_refs: list, note: Optional[str] = None, d: Optional[Path] = None,
        now: Optional[datetime] = None) -> dict:
    return append_event({"kind": "fix", "incident_id": incident_id, "actor": actor, "fix_refs": fix_refs,
                         "note": note}, d=d, now=now)


def resolve(incident_id: str, *, actor: str, note: str, d: Optional[Path] = None,
            now: Optional[datetime] = None) -> dict:
    return append_event({"kind": "resolve", "incident_id": incident_id, "actor": actor, "note": note}, d=d, now=now)


def block(incident_id: str, *, actor: str, blocked_reason: str, handoff: str, d: Optional[Path] = None,
          now: Optional[datetime] = None) -> dict:
    return append_event({"kind": "block", "incident_id": incident_id, "actor": actor,
                         "blocked_reason": blocked_reason, "handoff": handoff}, d=d, now=now)


def escalate(incident_id: str, *, actor: str, reason: str, delivered: bool, d: Optional[Path] = None,
             now: Optional[datetime] = None) -> dict:
    return append_event({"kind": "escalate", "incident_id": incident_id, "actor": actor, "reason": reason,
                         "delivered": bool(delivered)}, d=d, now=now)


def operator_ack(incident_id: str, *, decision_ref: str, comment: str = "", actor: str = "operator",
                 d: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    return append_event({"kind": "ack", "incident_id": incident_id, "actor": actor, "decision_ref": decision_ref,
                         "note": comment or None}, d=d, now=now)


def operator_close(incident_id: str, *, decision_ref: str, comment: str, actor: str = "operator",
                   d: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    if not str(comment or "").strip():
        raise LedgerError("close as won't-fix needs a comment")
    return append_event({"kind": "close", "incident_id": incident_id, "actor": actor, "decision_ref": decision_ref,
                         "note": comment}, d=d, now=now)


def parse_ref(s: str) -> dict:
    """``pr:2232`` | ``commit:<sha>`` | ``receipt:<path>`` | ``doc:<path>`` | ``#2232`` → FixRef."""
    s = str(s).strip()
    if s.startswith("#") and s[1:].isdigit():
        return {"kind": "pr", "ref": s[1:]}
    kind, _, ref = s.partition(":")
    if kind not in FIX_REF_KINDS or not ref:
        raise LedgerError(f"ref must be kind:value with kind in {FIX_REF_KINDS} (or #<pr>): {s!r}")
    return {"kind": kind, "ref": ref}


def unresolved_for_session(recs: Mapping[str, Mapping[str, Any]], session: str) -> list[dict]:
    """Incidents a session opened or owns that are still ``open``/``fixing`` (blocked = handed off, allowed)."""
    out = []
    for r in recs.values():
        if r["status"] not in UNRESOLVED:
            continue
        src = r.get("source") or {}
        if session and (src.get("session") == session or r.get("owner") == session):
            out.append(dict(r))
    return sorted(out, key=lambda r: r["opened_at"])
