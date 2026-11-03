"""Read-only explicit coordinator decisions for the shared operator approval queue.

Convention: decision_needed / decision_pending events carry decision_id (or an
explicit subject ``decision:<id>``), title or question, and an aware ts. A
``decision_type: keep_retire`` question offers keep / retire. Only an explicit
resolution carrying that same id closes it; freeform directives never open or
close a decision. Public fields are allowlisted, never the raw ledger payload.

AUTHORITY: READ_ONLY_ADVISORY. This adapter neither records nor applies decisions.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib import operator_approvals as core

SOURCE = "coordinator_decisions"
LEDGER_REL = "data/coordination/coordinator/ledger.jsonl"
MAX_BYTES = 2_000_000
MAX_EVENTS = 20_000
MAX_ITEMS = 200
IDENT = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
PENDING = frozenset({"decision_needed", "decision_pending"})
TERMINAL = frozenset({"decision_resolved", "decision_cancelled", "decision_superseded", "approval_recorded"})


def _instant(value: Any) -> str | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _id(row: dict) -> str | None:
    value = row.get("decision_id")
    subject = row.get("subject")
    subject_id = subject[9:] if isinstance(subject, str) and subject.startswith("decision:") else None
    if value is not None and subject_id is not None and value != subject_id:
        return None
    value = value if value is not None else subject_id
    return value if isinstance(value, str) and IDENT.fullmatch(value) else None


def _text(row: dict, name: str, limit: int) -> str | None:
    value = row.get(name)
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _failure(reason: str) -> dict:
    return {"rows": [], "resolved": [], "gap": reason, "as_of": None,
            "source": SOURCE, "source_ref": LEDGER_REL}


def load(state_root: Path, source_sha: str, now: datetime | None = None) -> dict:
    """Bounded immutable ledger snapshot -> core queue source {rows,resolved,gap}.

    state_root is the durable persistent-state root, never a code release folder.
    Source timestamps remain unknown when absent; reading never refreshes a fact.
    """
    if not isinstance(source_sha, str) or not core.SHA.fullmatch(source_sha):
        return _failure("COORDINATOR_DECISION_SOURCE_SHA_REQUIRED")
    path = Path(state_root) / LEDGER_REL
    if path.is_symlink():
        return _failure("COORDINATOR_DECISION_LEDGER_UNSAFE")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return _failure("COORDINATOR_DECISION_LEDGER_MISSING")
    except OSError:
        return _failure("COORDINATOR_DECISION_LEDGER_UNREADABLE")
    if len(raw) > MAX_BYTES:
        return _failure("COORDINATOR_DECISION_LEDGER_BYTE_BUDGET_EXCEEDED")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return _failure("COORDINATOR_DECISION_LEDGER_CORRUPT")
    if len(lines) > MAX_EVENTS:
        return _failure("COORDINATOR_DECISION_LEDGER_EVENT_BUDGET_EXCEEDED")
    opened: dict[str, dict] = {}
    resolved: dict[str, dict] = {}
    observed = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            return _failure("COORDINATOR_DECISION_LEDGER_CORRUPT")
        if not isinstance(row, dict):
            return _failure("COORDINATOR_DECISION_LEDGER_CORRUPT")
        kind = row.get("kind")
        if not isinstance(kind, str):
            return _failure("COORDINATOR_DECISION_LEDGER_CORRUPT")
        if kind not in PENDING | TERMINAL:
            continue
        ident = _id(row)
        # Historical approval records without a decision id are unrelated authority,
        # not evidence that any coordinator question has been answered.
        if not ident and kind == "approval_recorded" and "decision_id" not in row:
            continue
        at = _instant(row.get("observed_at") or row.get("ts"))
        if not ident or not at:
            return _failure("COORDINATOR_DECISION_EVENT_INVALID")
        observed.append(at)
        if kind in TERMINAL:
            item = opened.pop(ident, None)
            if item is not None:
                resolved[ident] = {**item, "resolution": kind, "resolved_at": at}
            continue
        title = _text(row, "title", 300) or _text(row, "question", 300)
        if not title:
            return _failure("COORDINATOR_DECISION_PUBLIC_QUESTION_REQUIRED")
        category = row.get("decision_type") or "question"
        if category not in ("question", "keep_retire"):
            return _failure("COORDINATOR_DECISION_TYPE_INVALID")
        public = {"decision_id": ident, "title": title, "question": _text(row, "question", 1200),
                  "why": _text(row, "why", 1200), "decision_type": category,
                  "options": ["keep", "retire"] if category == "keep_retire" else [],
                  "source_ref": LEDGER_REL, "as_of": at}
        item = core.item(ident="decision:" + ident, kind="FINDING", title=title,
                         proposed_by=_text(row, "coordinator", 100) or _text(row, "actor_session", 100),
                         created_at=at, source=SOURCE,
                         doc=core.document(json.dumps(public, ensure_ascii=True, sort_keys=True),
                                           source_sha=source_sha, version=at),
                         governed_href="/coordination?decision=" + ident,
                         source_refs=[SOURCE + ":" + ident])
        # The existing coordinator owns resolution. A generic RECORD approval cannot
        # retire work or resolve a coordinator question as a side effect.
        item.update({"decision_mode": "GOVERNED_PATH", "decision_id": ident,
                     "decision_type": category, "options": public["options"],
                     "as_of": at, "source_ref": LEDGER_REL, "next_actor": "operator"})
        opened[ident] = item
        resolved.pop(ident, None)
        if len(opened) + len(resolved) > MAX_ITEMS:
            return _failure("COORDINATOR_DECISION_ITEM_BUDGET_EXCEEDED")
    return {"rows": sorted(opened.values(), key=lambda row: (row["created_at"], row["id"])),
            "resolved": sorted(resolved.values(), key=lambda row: (row["resolved_at"], row["id"])),
            "gap": None, "as_of": max(observed) if observed else None,
            "source": SOURCE, "source_ref": LEDGER_REL}
