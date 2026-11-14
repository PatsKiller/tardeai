"""Ask the CIO — the asks event ledger and its thread projection. READ_ONLY_ADVISORY.

Not a silo (AGENTS.md §26, "NO SILOS"): this ledger is the append-only log of ask events, and every event that
concerns a security is ALSO appended to CIO memory keyed by security_guid (``cio_ask_memory``). "My questions" reads
the thread projection folded from this log; the CIO's recall reads CIO memory. Nothing here holds a per-security
judgment: stance and conviction stay on the CIO prospect record.

Store: ``data/cio/cio_ask_events.jsonl`` (one JSON object per line; fcntl lock + fsync; the same shape as
``cio_wake_jobs.jsonl``). Data-dictionary row ``cio_asks`` is PROPOSED in ``config/data_source_authority.json``
(``proposed_domains``) and awaits the operator's grant (§7A, §17); the Postgres-portable table shape is in
``docs/ops/ASK_THE_CIO.md``. Single writer: this module.

Idempotent: every event carries a deterministic ``event_id``; appending an id already present is a no-op that returns
the stored event. Never deletes or rewrites a line (§0 rule 6).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from scripts.lib.cio_ask_contract import typed_tracking_class, utc_now_iso

STORE_SCHEMA = "CioAskEvent@v1"
EVENT_KINDS = (
    "ask.asked",
    "ask.entity_resolved",
    "ask.answer_version",
    "ask.follow_up",
    "ask.tracking_changed",
    "ask.reanswer_triggered",
    "ask.reanswer_skipped",
    "ask.channel_link",
    "ask.cost",
    # Operator manual regroup on "My questions" (scripts/lib/cio_ask_groups.py): an event, never a history edit.
    "ask.group_override",
    "ask.check_requested",
    "ask.check_started",
    "ask.check_finished",
    "ask.research_started",
    "ask.research_finished",
    "ask.memory_synced",
    "ask.delivery_status",
    "ask.mirror_status",
    "ask.source_checkpoint",
)


def default_path() -> Path:
    root = os.environ.get("TRADEAI_ROOT")
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    return base / "data" / "cio" / "cio_ask_events.jsonl"


def event_id_for(kind: str, *parts: Any) -> str:
    return "ake_" + hashlib.sha256("\x1f".join([kind, *[str(p) for p in parts]]).encode()).hexdigest()[:24]


class AskEventStore:
    """Append-only JSONL ledger. Reads replay the file; it is small (one line per ask event)."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_path()
        self._default_store = path is None

    def write_authorized(self) -> bool:
        """An injected fixture store is explicit; the host store needs its granted domain.

        proposed_domains is deliberately excluded by the common authority reader.
        This checks authority, never grants it or consults an environment bypass.
        """
        if not self._default_store:
            return True
        try:
            from scripts.lib.data_source_authority import domain

            row = domain("cio_asks")
            approval = row.get("approval") or {}
            return isinstance(approval, dict) and bool(approval.get("approved_by") and approval.get("reference"))
        except (KeyError, OSError, ValueError, TypeError):
            return False

    # ── write ──────────────────────────────────────────────────────────────────────────────────────────────────────
    def append(self, kind: str, payload: dict[str, Any], *, event_id: str) -> tuple[dict[str, Any], bool]:
        """Append one event. Returns (event, created). An existing event_id is returned unchanged (idempotent)."""
        event, created, reason = self.append_guarded(kind, payload, event_id=event_id)
        if reason or event is None:
            raise ValueError(reason or "ASK_APPEND_REFUSED")
        return event, created

    def append_guarded(
        self, kind: str, payload: dict[str, Any], *, event_id: str,
        guard: Optional[Callable[[list[dict]], Optional[str]]] = None,
    ) -> tuple[Optional[dict], bool, Optional[str]]:
        """Read, admit and append under the same ledger lock (budget and job claims)."""
        if not self.write_authorized():
            raise PermissionError("CIO_ASK_STORE_NOT_APPROVED: cio_asks remains proposed")
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown ask event kind {kind!r}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = Path(str(self.path) + ".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            rows = list(self._iter_raw(strict=True))
            for ev in rows:
                if ev.get("event_id") == event_id:
                    return ev, False, None
            reason = guard(rows) if guard is not None else None
            if reason:
                return None, False, reason
            ev = {
                "schema": STORE_SCHEMA,
                "event_id": event_id,
                "kind": kind,
                "at": utc_now_iso(),
                "authority": "READ_ONLY_ADVISORY",
                **payload,
            }
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, sort_keys=True, default=str, separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return ev, True, None
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    # ── read ───────────────────────────────────────────────────────────────────────────────────────────────────────
    def _iter_raw(self, *, strict: bool = False) -> Iterable[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("non-object ask event")
                    out.append(row)
                except (ValueError, TypeError):
                    if strict:
                        raise ValueError("CIO_ASK_LEDGER_CORRUPT") from None
                    continue  # a torn line is skipped, never repaired in place
        return out

    @contextmanager
    def thread_lock(self, thread_id: str):
        """Serialize a thread's sources/models across API and native n8n workers."""
        if not self.write_authorized():
            raise PermissionError("CIO_ASK_STORE_NOT_APPROVED")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = hashlib.sha256(str(thread_id).encode()).hexdigest()[:24]
        fd = os.open(str(self.path.parent / (".ask-thread-" + token + ".lock")), os.O_CREAT | os.O_RDWR, 0o600)
        locked = False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError:
                pass
            yield locked
        finally:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def events(self, *, thread_id: Optional[str] = None) -> list[dict[str, Any]]:
        evs = list(self._iter_raw())
        if thread_id:
            evs = [e for e in evs if e.get("thread_id") == thread_id]
        return evs

    def thread_for_ask(self, ask_id: str) -> Optional[str]:
        for e in self._iter_raw():
            if e.get("kind") == "ask.asked" and e.get("ask_id") == ask_id:
                return e.get("thread_id")
        return None

    def thread_for_channel_message(self, channel: str, chat_id: str, message_id: str) -> Optional[str]:
        """Which thread an outbound or inbound channel message belongs to (Telegram reply → follow-up)."""
        for e in self._iter_raw():
            if (
                e.get("kind") == "ask.channel_link"
                and e.get("channel") == channel
                and str(e.get("chat_id")) == str(chat_id)
                and str(e.get("message_id")) == str(message_id)
            ):
                return e.get("thread_id")
        return None

    def channel_links(self, thread_id: str) -> list[dict[str, Any]]:
        return [e for e in self.events(thread_id=thread_id) if e.get("kind") == "ask.channel_link"]

    def next_version(self, ask_id: str) -> int:
        vs = [
            int(e.get("version") or 0)
            for e in self._iter_raw()
            if e.get("kind") == "ask.answer_version" and e.get("ask_id") == ask_id
        ]
        return (max(vs) if vs else 0) + 1

    def cost_today(self, *, day: Optional[str] = None) -> float:
        d = day or utc_now_iso()[:10]
        rows = list(self._iter_raw(strict=True))
        terminal = {e.get("request_id"): e for e in rows if e.get("kind") == "ask.research_finished"}
        # The cost event meters settled actuals. Unknown/interrupted holds remain binding.
        actual = sum(float(e.get("usd") or 0) for e in rows
                     if e.get("kind") == "ask.cost" and str(e.get("at"))[:10] == d)
        holds = sum(float(e.get("reserved_usd") or 0) for e in rows
                    if e.get("kind") == "ask.research_started" and str(e.get("at"))[:10] == d
                    and not (terminal.get(e.get("request_id")) or {}).get("usage_known"))
        return round(actual + holds, 8)

    # ── projection ─────────────────────────────────────────────────────────────────────────────────────────────────
    def threads(self, *, rows: Optional[list[dict[str, Any]]] = None) -> dict[str, dict[str, Any]]:
        """Fold the ledger into thread views. Pure replay; same input → same output.

        The ledger is parsed ONCE per call (LQ-20261107-2215). It used to be parsed once more per thread
        for the lifecycle projection, which made a GET of /cio/asks cost (threads + 1) full parses.
        ``rows`` lets a caller that already parsed the ledger (``snapshot``) reuse that parse.
        """
        if rows is None:
            rows = list(self._iter_raw())
        th: dict[str, dict[str, Any]] = {}
        by_thread: dict[str, list[dict[str, Any]]] = {}
        for e in rows:
            if e.get("thread_id"):
                by_thread.setdefault(e.get("thread_id"), []).append(e)
        for e in rows:
            tid = e.get("thread_id")
            if not tid:
                continue
            t = th.setdefault(
                tid,
                {
                    "thread_id": tid,
                    "title": None,
                    "created_at": e.get("at"),
                    "updated_at": e.get("at"),
                    "channels": [],
                    "turns": [],
                    "entities": {},
                    "status": None,
                    "reanswers": 0,
                    "cost_usd": 0.0,
                },
            )
            t["updated_at"] = max(str(t["updated_at"] or ""), str(e.get("at") or ""))
            k = e.get("kind")
            if k == "ask.asked":
                if not t["title"]:
                    t["title"] = e.get("question")
                ch = e.get("channel")
                if ch and ch not in t["channels"]:
                    t["channels"].append(ch)
                t["turns"].append(
                    {
                        "ask_id": e.get("ask_id"),
                        "question": e.get("question"),
                        "channel": ch,
                        "asked_at": e.get("asked_at") or e.get("at"),
                        "turn_kind": e.get("turn_kind") or "ask",
                        "parent_ask_id": e.get("parent_ask_id"),
                        "trigger": e.get("trigger"),
                        "answers": [],
                    }
                )
            elif k == "ask.entity_resolved":
                ent = e.get("entity") or {}
                key = ent.get("security_guid") or ent.get("entity_guid") or f"name:{ent.get('name')}"
                cur = t["entities"].setdefault(key, {"key": key, "tracking": {"state": None}})
                for kk, vv in ent.items():  # identity fields from the resolution win; None is a real value
                    if vv is not None or kk not in cur:
                        cur[kk] = vv
            elif k == "ask.answer_version":
                ans = e.get("answer") or {}
                for turn in t["turns"]:
                    if turn["ask_id"] == e.get("ask_id"):
                        turn["answers"] = [a for a in turn["answers"] if a.get("version") != ans.get("version")]
                        turn["answers"].append(ans)
                        turn["answers"].sort(key=lambda a: int(a.get("version") or 0))
                t["status"] = ans.get("status") or t["status"]
                if ans.get("status") == "reanswer":
                    t["reanswers"] += 1
            elif k == "ask.tracking_changed":
                key = e.get("entity_key")
                cur = t["entities"].setdefault(
                    key, {"key": key, "name": e.get("name"), "symbol": e.get("symbol"), "tracking": {}}
                )
                cur["tracking"] = {
                    "state": e.get("state"),
                    "at": e.get("at"),
                    "actions": e.get("actions") or {},
                    "by": e.get("by"),
                }
            elif k == "ask.channel_link":
                ch = e.get("channel")
                if ch and ch not in t["channels"]:
                    t["channels"].append(ch)
            elif k == "ask.cost":
                t["cost_usd"] = round(t["cost_usd"] + float(e.get("usd") or 0), 6)
        for t in th.values():
            t["entities"] = list(t["entities"].values())
            from scripts.lib.cio_ask_lifecycle import project_lifecycle

            t["lifecycle"] = project_lifecycle(t, by_thread.get(t["thread_id"], []))
        return th

    def snapshot(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """(threads, events) from ONE parse of the ledger, for a request that needs both."""
        rows = list(self._iter_raw())
        return self.threads(rows=rows), rows

    def thread(self, thread_id: str) -> Optional[dict[str, Any]]:
        return self.threads().get(thread_id)

    def tracked_entities(self) -> list[dict[str, Any]]:
        """Entities currently tracked by any thread: [{thread_id, key, security_guid, symbol, ...}], TYPED only.

        OBS-H1 (operator live Chrome 2026-11-14): a tracked entity with no typed identity — a name-only "private
        entity", which the resolver's fallback minted for a pasted card's headings ("Review BHVN", "WATCH Card",
        "Risk") — is still tracked on its own thread (My questions shows it there) but is not a shared-header chip.
        The ledger is append-only, so historical rows are not rewritten; the projection simply does not promote a
        name to a global entity."""
        out = []
        for t in self.threads().values():
            for ent in t["entities"]:
                if (ent.get("tracking") or {}).get("state") == "tracked" and typed_tracking_class(ent):
                    out.append({"thread_id": t["thread_id"], **ent})
        return out

    def untyped_tracked_entities(self) -> list[dict[str, Any]]:
        """Tracked entities the shared header CANNOT name — the census that rides beside ``tracked_entities``.

        OBS-H1 F1 (review cc-deepseek-2, 2026-11-14): filtering untyped rows out of ``tracked_entities`` made
        ``tracked: []`` mean two different things — nothing tracked, or something tracked that cannot be a chip.
        This read names the second population (and only it), so a caller can tell the states apart. Same read
        projection as its sibling: no ledger rewrite, no tracking-state change, each row keeps its thread context.
        """
        out = []
        for t in self.threads().values():
            for ent in t["entities"]:
                if (ent.get("tracking") or {}).get("state") == "tracked" and not typed_tracking_class(ent):
                    out.append({"thread_id": t["thread_id"], "key": ent.get("key"), "kind": ent.get("kind"),
                                "name": ent.get("name"), "entity_guid": ent.get("entity_guid")})
        return out


__all__ = ["AskEventStore", "STORE_SCHEMA", "EVENT_KINDS", "default_path", "event_id_for"]
