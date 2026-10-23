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
from pathlib import Path
from typing import Any, Iterable, Optional

from scripts.lib.cio_ask_contract import utc_now_iso

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

    # ── write ──────────────────────────────────────────────────────────────────────────────────────────────────────
    def append(self, kind: str, payload: dict[str, Any], *, event_id: str) -> tuple[dict[str, Any], bool]:
        """Append one event. Returns (event, created). An existing event_id is returned unchanged (idempotent)."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown ask event kind {kind!r}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = Path(str(self.path) + ".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            for ev in self._iter_raw():
                if ev.get("event_id") == event_id:
                    return ev, False
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
            return ev, True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    # ── read ───────────────────────────────────────────────────────────────────────────────────────────────────────
    def _iter_raw(self) -> Iterable[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a torn line is skipped, never repaired in place
        return out

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
        return round(
            sum(
                float(e.get("usd") or 0)
                for e in self._iter_raw()
                if e.get("kind") == "ask.cost" and str(e.get("at"))[:10] == d
            ),
            6,
        )

    # ── projection ─────────────────────────────────────────────────────────────────────────────────────────────────
    def threads(self) -> dict[str, dict[str, Any]]:
        """Fold the ledger into thread views. Pure replay; same input → same output."""
        th: dict[str, dict[str, Any]] = {}
        for e in self._iter_raw():
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
        return th

    def thread(self, thread_id: str) -> Optional[dict[str, Any]]:
        return self.threads().get(thread_id)

    def tracked_entities(self) -> list[dict[str, Any]]:
        """Entities currently tracked by any thread: [{thread_id, key, security_guid, symbol, ...}]."""
        out = []
        for t in self.threads().values():
            for ent in t["entities"]:
                if (ent.get("tracking") or {}).get("state") == "tracked":
                    out.append({"thread_id": t["thread_id"], **ent})
        return out


__all__ = ["AskEventStore", "STORE_SCHEMA", "EVENT_KINDS", "default_path", "event_id_for"]
