"""InstrumentRecord@v1 — the persistent unit the CIO thinks with.

One record per SUBJECT, not per plan. Plans are episodic: a new one is minted
every wake and the previous one's reasoning is lost, which is why the desk kept
re-asking the same research question and kept forgetting an operator defer.
The record is the thing that survives.

    HELD:<SYM> | EXIT:<SYM> | WATCH:<SYM> | SECTOR:<name> | SLEEVE:CASH

**MBI_BEHAVIOR = 0. MBI_COGNITION = 1.** A record may change what the desk
ASKS, SKIPS, SAYS, or WHEN it looks again. It may never produce size, a broker
action, or a recommended_delta_usd. `apply_cognition` enforces that split in
code: it writes only cognition fields, and a write that changes none of them is
a failed persist rather than a silent no-op.

Not every subject earns a record. Dust (aggregate market value < $50/ticker),
TEST tickers and cash-as-a-ticker are refused at mint time — the $630k cash
question is SLEEVE:CASH, a sleeve, not a fake holding.

READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "InstrumentRecord@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
MBI_COGNITION = 1

STORE_ID = "cio.instrument_records"
DEFAULT_PATH = Path("data/cio/cio_instrument_records.jsonl")

CASH_SLEEVE = "SLEEVE:CASH"
KINDS = ("HELD", "EXIT", "WATCH", "SECTOR", "SLEEVE")

# The four cognition fields. A persist must move at least one of these, or the
# lesson did nothing and calling it "applied" would be a lie.
COGNITION_FIELDS = (
    "next_research_question",
    "next_eligible_at",
    "notify_priority",
    "cc_narrative",
)

NOTIFY_PRIORITIES = ("none", "cc", "digest", "immediate_candidate")

# Never minted. Cash is a sleeve; these tickers are how it leaks in as a
# holding, and dust is noise the desk already refuses to act on.
NON_INSTRUMENT_SYMBOLS = {
    "CASH", "USD", "USD CASH", "SPAXX", "FDRXX", "SPRXX", "FZFXX",
    "TEST", "SPACEX_TEST", "DUMMY",
}
DUST_MAX_MARKET_VALUE_USD = 50.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def subject_key(kind: str, name: str) -> str:
    k = str(kind or "").strip().upper()
    n = str(name or "").strip().upper()
    if k == "SLEEVE":
        return f"SLEEVE:{n or 'CASH'}"
    if k == "SECTOR":
        return f"SECTOR:{str(name or '').strip()}"
    return f"{k}:{n}"


def parse_subject_key(key: str) -> tuple[str, str]:
    raw = str(key or "")
    if ":" not in raw:
        return ("", raw)
    kind, _, name = raw.partition(":")
    return (kind.strip().upper(), name.strip())


def is_mintable(kind: str, name: str, *, market_value: Optional[float] = None) -> tuple[bool, str]:
    """Return (ok, reason). Refusals are explicit so a caller can log them."""
    k = str(kind or "").strip().upper()
    n = str(name or "").strip().upper()
    if k not in KINDS:
        return (False, f"unknown_kind:{k}")
    if k == "SLEEVE":
        return (True, "sleeve")
    if k == "SECTOR":
        return ((bool(n)), "sector" if n else "empty_sector")
    if not n:
        return (False, "empty_symbol")
    if n in NON_INSTRUMENT_SYMBOLS:
        return (False, "cash_or_test_ticker")
    if market_value is not None:
        try:
            if abs(float(market_value)) < DUST_MAX_MARKET_VALUE_USD:
                return (False, "dust_residual")
        except (TypeError, ValueError):
            pass
    return (True, "ok")


def content_hash(value: Any) -> str:
    """Stable hash so 'did this change?' is answerable without a diff."""
    try:
        blob = json.dumps(value, sort_keys=True, default=str)
    except Exception:                                            # noqa: BLE001
        blob = str(value)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def new_record(kind: str, name: str, **fields: Any) -> dict[str, Any]:
    key = subject_key(kind, name)
    rec: dict[str, Any] = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "memory_cognition_influence": MBI_COGNITION,
        "subject_key": key,
        "kind": str(kind or "").strip().upper(),
        "symbols": [],
        "thesis_ref": None,
        "desk_pin": None,
        "cc_narrative": None,
        "last_operator_turn": None,
        "last_artifact_id": None,
        "last_outcome": None,
        "last_event_hash": None,
        "lessons": [],
        "next_research_question": None,
        "next_eligible_at": None,
        "notify_priority": "none",
        "hashes": {"price": None, "weight": None, "earnings": None, "analyst": None},
        "created_ts": _now(),
        "updated_ts": _now(),
    }
    rec.update({k: v for k, v in fields.items() if v is not None})
    rec["subject_key"] = key
    return rec


def cc_narrative(
    *,
    what: str = "",
    thesis_fit: str = "",
    recommendation_option_id: Optional[str] = None,
    risks: Optional[list[str]] = None,
    evidence_refs: Optional[list[dict[str, Any]]] = None,
    writer: str = "deterministic",
    as_of: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "what": what,
        "thesis_fit": thesis_fit,
        "recommendation_option_id": recommendation_option_id,
        "risks": list(risks or []),
        "evidence_refs": list(evidence_refs or []),
        "as_of": as_of or _now(),
        "writer": writer,
    }


class InstrumentRecordStore:
    """Append-only JSONL; the projection is the last row per subject_key.

    Append-only because the value here is the HISTORY of what the desk believed
    and when — collapsing to a mutable row would destroy the evidence that a
    lesson actually changed the next question.
    """

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._cache: Optional[dict[str, dict[str, Any]]] = None

    # ---------------------------------------------------------------- read
    def _load(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        proj: dict[str, dict[str, Any]] = {}
        try:
            if self.path.is_file():
                with open(self.path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:                        # noqa: BLE001
                            continue
                        key = str(row.get("subject_key") or "")
                        if key:
                            proj[key] = row
        except OSError:
            pass
        self._cache = proj
        return proj

    def load(self, key: str) -> Optional[dict[str, Any]]:
        return self._load().get(str(key))

    def all(self) -> list[dict[str, Any]]:
        return list(self._load().values())

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        k = str(kind or "").upper()
        return [r for r in self.all() if str(r.get("kind") or "").upper() == k]

    def counts_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.all():
            k = str(r.get("kind") or "?")
            out[k] = out.get(k, 0) + 1
        return out

    def history(self, key: str) -> list[dict[str, Any]]:
        """All append rows for ``subject_key`` in file order (oldest → newest).

        Corrupt / partial lines are skipped the same way ``_load`` skips them,
        so a truncated final write does not hide earlier complete versions.
        """
        want = str(key)
        out: list[dict[str, Any]] = []
        try:
            if not self.path.is_file():
                return out
            with open(self.path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:                            # noqa: BLE001
                        continue
                    if str(row.get("subject_key") or "") == want:
                        out.append(row)
        except OSError:
            return out
        return out

    def rollback(self, key: str, *, to_index: int = -2) -> dict[str, Any]:
        """Re-append a prior version as the new tip (append-only rollback).

        Default ``to_index=-2`` restores the previous tip. Index is into
        ``history(key)`` (0 = first mint). Raises ``IndexError`` when the
        subject has no such version. Does not rewrite or delete history.
        """
        versions = self.history(key)
        if not versions:
            raise IndexError(f"no history for {key}")
        prior = dict(versions[to_index])
        prior["rollback_of_updated_ts"] = prior.get("updated_ts")
        prior["rollback_source_index"] = to_index if to_index >= 0 else len(versions) + to_index
        return self.upsert(prior)

    # --------------------------------------------------------------- write
    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        key = str(record.get("subject_key") or "")
        if not key:
            raise ValueError("record has no subject_key")
        row = dict(record)
        row["schema"] = SCHEMA
        row["authority"] = AUTHORITY
        row["memory_behavior_influence"] = MBI_BEHAVIOR
        row["updated_ts"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        proj = self._load()
        proj[key] = row
        return row


def thesis_summary(record: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Operator-facing thesis slice recovered from a record version."""
    if not record:
        return {"thesis_ref": None, "what": None, "thesis_fit": None}
    narr = record.get("cc_narrative") or {}
    if not isinstance(narr, dict):
        narr = {}
    return {
        "thesis_ref": record.get("thesis_ref"),
        "what": narr.get("what"),
        "thesis_fit": narr.get("thesis_fit"),
        "next_research_question": record.get("next_research_question"),
        "updated_ts": record.get("updated_ts"),
    }


# ── cognition apply ────────────────────────────────────────────────────────
#
# MBI_COGNITION=1 is a licence to change what the desk THINKS NEXT, and nothing
# else. These are the only fields a lesson, an artifact or an operator turn may
# move. Anything resembling behaviour is refused outright rather than filtered,
# because a silently dropped size field looks like it was honoured.

BEHAVIOR_FIELDS = (
    "recommended_delta_usd", "size_usd", "shares", "qty", "order",
    "stop", "limit", "target_weight_pct", "trade", "execution",
)


class BehaviorWriteRefused(ValueError):
    """Raised when a caller tries to persist behaviour through cognition."""


class CognitionNoOp(ValueError):
    """Raised when an 'apply' moved none of the cognition fields.

    Per the operator's law: a write that does not change the next question,
    the eligibility, the notify priority or the narrative is a FAILED persist.
    Silence here is how a memory system convinces itself it is learning.
    """


def apply_cognition(
    record: dict[str, Any],
    *,
    next_research_question: Optional[str] = None,
    next_eligible_at: Optional[str] = None,
    notify_priority: Optional[str] = None,
    narrative: Optional[dict[str, Any]] = None,
    lesson: Optional[dict[str, Any]] = None,
    operator_turn: Optional[dict[str, Any]] = None,
    artifact_id: Optional[str] = None,
    outcome: Optional[str] = None,
    hashes: Optional[dict[str, Any]] = None,
    strict: bool = True,
    **forbidden: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Return (updated_record, changed_cognition_fields).

    `strict` raises CognitionNoOp when nothing moved. Callers that legitimately
    expect a no-op (a probe, a dry run) pass strict=False and check the list.
    """
    if forbidden:
        bad = sorted(k for k in forbidden if k in BEHAVIOR_FIELDS) or sorted(forbidden)
        raise BehaviorWriteRefused(
            f"MBI_BEHAVIOR=0: cognition may not carry {bad}")

    rec = dict(record)
    changed: list[str] = []

    if notify_priority is not None and notify_priority not in NOTIFY_PRIORITIES:
        raise ValueError(f"notify_priority must be one of {NOTIFY_PRIORITIES}")

    for field, value in (
        ("next_research_question", next_research_question),
        ("next_eligible_at", next_eligible_at),
        ("notify_priority", notify_priority),
        ("cc_narrative", narrative),
    ):
        if value is None:
            continue
        if rec.get(field) != value:
            rec[field] = value
            changed.append(field)

    # Provenance. These are not cognition fields — they record WHY cognition
    # moved, and on their own they are not a persist.
    if lesson:
        les = dict(lesson)
        les.setdefault("support_only", True)
        les.setdefault("applied_to", "cognition")
        rec["lessons"] = list(rec.get("lessons") or []) + [les]
    if operator_turn:
        rec["last_operator_turn"] = dict(operator_turn)
    if artifact_id:
        rec["last_artifact_id"] = artifact_id
    if outcome:
        rec["last_outcome"] = outcome
    if hashes:
        merged = dict(rec.get("hashes") or {})
        merged.update({k: v for k, v in hashes.items() if v is not None})
        rec["hashes"] = merged

    rec["last_event_hash"] = content_hash({
        "q": rec.get("next_research_question"),
        "e": rec.get("next_eligible_at"),
        "n": rec.get("notify_priority"),
        "c": rec.get("cc_narrative"),
    })
    rec["updated_ts"] = _now()

    if strict and not changed:
        raise CognitionNoOp(
            f"{rec.get('subject_key')}: nothing in {COGNITION_FIELDS} changed — "
            "a lesson that moves no decision is not persisted")
    return rec, changed


def hash_changed(record: dict[str, Any], name: str, value: Any) -> bool:
    """True when an observable (price/weight/earnings/analyst) actually MOVED.

    An UNSET hash is not a change. First contact means the desk has no prior
    belief to contradict, and treating it as an event fired a spurious override
    on every freshly migrated record — overriding the very defer the record was
    created to remember.
    """
    prior = (record.get("hashes") or {}).get(name)
    if prior in (None, ""):
        return False
    return prior != content_hash(value)


# ── G-IR-01 wake load ─────────────────────────────────────────────────────
#
# Persistence alone is not universal wake load. Every subject wake should
# explicitly LOADED | IR_MISSING | IR_ERROR rather than silently empty.


def _store_for_root(root: Path | str | None = None) -> InstrumentRecordStore:
    if root is None:
        try:
            from scripts.lib.canonical_store_registry import resolve_store

            loc = resolve_store(STORE_ID)
            path = Path(getattr(loc, "path", None) or loc)
            return InstrumentRecordStore(path)
        except Exception:  # noqa: BLE001
            return InstrumentRecordStore(DEFAULT_PATH)
    root_p = Path(root)
    return InstrumentRecordStore(root_p / DEFAULT_PATH)


def _candidate_keys(subject: Any) -> list[str]:
    raw = str(subject or "").strip()
    if not raw:
        return []
    if ":" in raw:
        kind, _, name = raw.partition(":")
        return [subject_key(kind, name)]
    sym = raw.upper()
    return [subject_key(k, sym) for k in ("HELD", "EXIT", "WATCH", "SECTOR")]


def load_instrument_record_for_wake(
    subject_guid: Any = None,
    *,
    subject_key_hint: Any = None,
    symbol: Any = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """RO tip load for a wake. Never raises for missing store/subject.

    Prefers ``subject_key_hint``, then ``subject_guid`` (may already be a
    ``KIND:NAME`` key), then symbol probes ``HELD|EXIT|WATCH|SECTOR:SYM``.
    """
    base: dict[str, Any] = {
        "ok": False,
        "record": None,
        "status": "NO_SUBJECT",
        "subject_key": None,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "schema": "InstrumentRecordWake@v1",
    }
    probe = subject_key_hint or subject_guid or symbol
    keys = _candidate_keys(probe)
    if not keys:
        return base
    try:
        store = _store_for_root(root)
        for key in keys:
            rec = store.load(key)
            if rec:
                return {
                    **base,
                    "ok": True,
                    "record": dict(rec),
                    "status": "LOADED",
                    "subject_key": key,
                }
        return {**base, "status": "IR_MISSING", "subject_key": keys[0]}
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "status": "IR_ERROR",
            "subject_key": keys[0] if keys else None,
            "error": f"{type(exc).__name__}: {exc}"[:200],
        }


def stamp_last_artifact_id(
    subject_key_or_symbol: Any,
    artifact_id: Any,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Append tip update with last_artifact_id. MBI stays 0. Fail-soft."""
    out: dict[str, Any] = {
        "ok": False,
        "wrote": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI_BEHAVIOR,
    }
    aid = str(artifact_id or "").strip()
    if not aid:
        out["reason"] = "empty_artifact_id"
        return out
    wake = load_instrument_record_for_wake(subject_key_or_symbol, root=root)
    if wake.get("status") != "LOADED" or not wake.get("record"):
        out["reason"] = str(wake.get("status") or "IR_MISSING")
        out["subject_key"] = wake.get("subject_key")
        return out
    try:
        store = _store_for_root(root)
        rec = dict(wake["record"])
        rec["last_artifact_id"] = aid
        rec["memory_behavior_influence"] = MBI_BEHAVIOR
        stored = store.upsert(rec)
        return {
            **out,
            "ok": True,
            "wrote": True,
            "subject_key": stored.get("subject_key"),
            "last_artifact_id": aid,
        }
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"{type(exc).__name__}: {exc}"[:200]
        return out
