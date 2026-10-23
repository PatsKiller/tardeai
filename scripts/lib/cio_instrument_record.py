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
# Registered subject prefixes that are deliberately NOT record kinds: they are
# GUID tags on securities (ticker_knowledge_graph.entity_guid) and narrative
# subjects, never wakeable InstrumentRecords. is_mintable names the policy.
TAGS_ONLY_KINDS = ("INDUSTRY", "THEME")

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
    if k in TAGS_ONLY_KINDS:
        # Not a gap. AGENTS.md §13.4 registers INDUSTRY:/THEME: as prefixes
        # with no producer and no scheduled consumer; narrative links carry
        # them as tags on securities ("tags, not records"). Settled 2026-09-24
        # (agentic-memory tranche 1): tags-only, formalized — see
        # docs/architecture/narrative-subject-identity.md, "Entity policy".
        return (False, f"tags_only_by_policy:{k}")
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
    # Identity 4/5: registry GUID beside subject_key (alias). Lookup only.
    kind_u = str(kind or "").strip().upper()
    name_u = str(name or "").strip().upper()
    if kind_u in {"HELD", "EXIT", "WATCH"} and name_u:
        if not rec.get("symbols"):
            rec["symbols"] = [name_u]
        try:
            from scripts.lib.identity_carriage import stamp_security_fields
            stamped = stamp_security_fields(rec, symbol=name_u, root=fields.get("_root"))
            for k in ("subject_guid", "issuer_guid", "security_guid", "identity_status", "identity_lookup"):
                if stamped.get(k) is not None:
                    rec[k] = stamped[k]
        except Exception:
            pass
    rec.pop("_root", None)
    return rec


def normalize_writer_author(
    *,
    writer: Optional[str] = None,
    author: Optional[str] = None,
) -> dict[str, Any]:
    """AGENTS §9.2 — ``writer`` names the **author**, not the copy step.

    Legacy seed stamped ``migration:deterministic`` (the migration *lane*).
    That asserts the wrong thing on generated prose: migration copied the
    blob; it did not author it. Strip a ``migration:`` prefix so writer and
    author name the prose author. When a copy-step prefix was present, keep
    it as ``copy_step`` so the hand that touched the record is still visible
    without polluting authorship.
    """
    raw_writer = str(writer or "").strip()
    raw_author = str(author or "").strip()
    copy_step: Optional[str] = None

    def _strip_migration(value: str) -> tuple[str, Optional[str]]:
        if value.lower().startswith("migration:"):
            rest = value.split(":", 1)[1].strip() or "deterministic"
            return rest, "migration"
        return value, None

    # Prefer an already-honest author over a copy-step writer.
    if raw_author and not raw_author.lower().startswith("migration:"):
        author_name = raw_author
        if raw_writer.lower().startswith("migration:"):
            copy_step = "migration"
    else:
        primary = raw_writer or raw_author or "deterministic"
        author_name, copy_step = _strip_migration(primary)
        if not author_name:
            author_name = "deterministic"

    out: dict[str, Any] = {"writer": author_name, "author": author_name}
    if copy_step:
        out["copy_step"] = copy_step
    return out


def cc_narrative(
    *,
    what: str = "",
    thesis_fit: str = "",
    recommendation_option_id: Optional[str] = None,
    risks: Optional[list[str]] = None,
    evidence_refs: Optional[list[dict[str, Any]]] = None,
    writer: str = "deterministic",
    author: Optional[str] = None,
    as_of: Optional[str] = None,
) -> dict[str, Any]:
    stamps = normalize_writer_author(writer=writer, author=author)
    out: dict[str, Any] = {
        "what": what,
        "thesis_fit": thesis_fit,
        "recommendation_option_id": recommendation_option_id,
        "risks": list(risks or []),
        "evidence_refs": list(evidence_refs or []),
        "as_of": as_of or _now(),
        "writer": stamps["writer"],
        "author": stamps["author"],
    }
    if stamps.get("copy_step"):
        out["copy_step"] = stamps["copy_step"]
    return out


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

    def upsert_prospect(self, record: dict[str, Any], *,
                        backend: Optional["ProspectPgBackend"] = None,
                        registry: Optional[dict[str, Any]] = None,
                        env: Optional[dict[str, str]] = None,
                        lifecycle_events: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
        """The single write path for a CIO prospect (AGENTS.md §26.1).

        ``lifecycle_events`` (``cio_prospect_lifecycle.lifecycle_events``) are appended to ``cio_prospect_events`` in
        the same transaction, one idempotent row per fact (entry fill, observed stop change, exit fill, review ...).

        jsonl append first (the store of record in P1), then the Postgres dual-write when —
        and only when — ``prospect_store_status`` is live (row granted + operator flag + table
        present). Returns ``{"row": <jsonl row>, "pg": {...}}``; ``pg.mode`` is ``inert`` with
        its reasons until the operator's grants land. A Postgres failure never loses the jsonl
        write and is reported, never swallowed.
        """
        if not is_prospect_record(record):
            raise ProspectInvalid("upsert_prospect takes a record that passed apply_prospect")
        table_row = prospect_row(record)                  # validate before any write
        prior = self.load(str(record.get("subject_key") or ""))
        stored = self.upsert(record)
        status = prospect_store_status(registry=registry, env=env,
                                       table_probe=(backend.table_present if backend else None))
        pg: dict[str, Any] = dict(status)
        if status["live"] and backend is not None:
            event = prospect_event(prospect_row(prior) if is_prospect_record(prior) else None, table_row)
            try:
                pg.update(backend.write(table_row, event, list(lifecycle_events)))
            except Exception as exc:  # noqa: BLE001
                pg.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]})
        return {"row": stored, "pg": pg}


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

    ``outcome`` is the research-gate ROUTE the last cycle took (``flash`` /
    ``pro`` / ``reuse`` — ``cio_rehydrate.apply_after_cycle`` writes
    ``decision["decision"]`` here) and it feeds ``gate_input_from_record`` as
    ``prior_outcome``. It is NOT a market outcome. Settled market outcomes live
    in the record's ``beliefs`` block (``apply_belief``), never here.
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


# ── beliefs: settled outcomes on the record ─────────────────────────────────
#
# Agentic-memory tranche 1, Slice 2 (2026-09-24). A belief is what settled
# outcomes say about the desk's own prior calls on this subject: for one
# (subject_key, recommendation, horizon) it carries sample_size / successful /
# success_rate and the outcome ids that produced them. It is written ONLY by
# the belief writer from settled rows (advisory_outcomes, resolved checkpoints,
# CONFIRMED/REFUTED commitments) and ratified lessons; wake decide() reads it
# before authoring. MBI_BEHAVIOR=0 applies unchanged: a belief may move the
# next question, the research route and the narrative — never size, order,
# stop, weight or execution, and apply_belief refuses those keys anywhere in
# the block. `live_mutation` is always False: the record holds the belief, it
# does not act on it.

BELIEF_SCHEMA = "InstrumentBelief@v1"
BELIEF_REQUIRED = (
    "belief_key", "population", "horizon", "recommendation", "sample_size",
    "successful", "success_rate", "outcome_ids", "belief_proposal_id",
    "revision", "as_of",
)
# A prior call is "weak" when at least this many settled outcomes exist and
# fewer than this share went the way the desk said. Mirrors
# settle_agent_commitments.MIN_SAMPLES for the sample floor.
BELIEF_MIN_SAMPLES = 5
BELIEF_WEAK_SUCCESS_RATE = 0.4


def _walk_keys(obj: Any, out: Optional[set[str]] = None) -> set[str]:
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _walk_keys(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_keys(v, out)
    return out


def apply_belief(
    record: dict[str, Any],
    *,
    belief: dict[str, Any],
    strict: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Return (updated_record, changed_fields) with ``beliefs`` moved, or raise.

    The rail: any BEHAVIOR_FIELDS key anywhere inside the block raises
    BehaviorWriteRefused (a belief is about what happened, never what to do);
    ``live_mutation`` other than False raises the same. A block whose
    ``belief_proposal_id`` equals the stored one for its belief_key moved
    nothing and is a CognitionNoOp under ``strict`` — a re-write that changes
    no belief is not learning.
    """
    if not isinstance(belief, dict):
        raise ValueError("belief must be a dict")
    bad = sorted(k for k in _walk_keys(belief) if k in BEHAVIOR_FIELDS)
    if bad:
        raise BehaviorWriteRefused(f"MBI_BEHAVIOR=0: a belief may not carry {bad}")
    if belief.get("live_mutation") not in (False, None):
        raise BehaviorWriteRefused("MBI_BEHAVIOR=0: a belief may not request live_mutation")
    missing = [k for k in BELIEF_REQUIRED if k not in belief]
    if missing:
        raise ValueError(f"belief is missing {missing}")

    blk = dict(belief)
    blk["schema"] = BELIEF_SCHEMA
    blk["live_mutation"] = False
    blk["memory_behavior_influence"] = MBI_BEHAVIOR
    blk["authority"] = AUTHORITY

    rec = dict(record)
    beliefs = [dict(b) for b in (rec.get("beliefs") or []) if isinstance(b, dict)]
    idx = next((i for i, b in enumerate(beliefs) if b.get("belief_key") == blk["belief_key"]), None)
    if idx is not None and beliefs[idx].get("belief_proposal_id") == blk["belief_proposal_id"]:
        if strict:
            raise CognitionNoOp(
                f"{rec.get('subject_key')}: belief {blk['belief_key']} unchanged "
                f"({blk['belief_proposal_id']}) — a re-write that moves no belief is not persisted")
        return rec, []
    if idx is None:
        beliefs.append(blk)
    else:
        beliefs[idx] = blk
    rec["beliefs"] = beliefs
    rec["updated_ts"] = _now()
    return rec, ["beliefs"]


def latest_belief(record: Optional[dict[str, Any]], *,
                  recommendation: Optional[str] = None) -> Optional[dict[str, Any]]:
    """The most recently written belief on a record (optionally for one recommendation)."""
    if not record:
        return None
    rows = [b for b in (record.get("beliefs") or []) if isinstance(b, dict)]
    if recommendation:
        want = str(recommendation).upper()
        rows = [b for b in rows if str(b.get("recommendation") or "").upper() == want]
    if not rows:
        return None
    return max(rows, key=lambda b: (str(b.get("as_of") or ""), int(b.get("revision") or 0)))


def weak_beliefs(record: Optional[dict[str, Any]], *,
                 min_samples: int = BELIEF_MIN_SAMPLES,
                 threshold: float = BELIEF_WEAK_SUCCESS_RATE) -> list[dict[str, Any]]:
    """Beliefs with enough settled outcomes and a success rate below threshold."""
    if not record:
        return []
    out = []
    for b in record.get("beliefs") or []:
        if not isinstance(b, dict):
            continue
        try:
            n = int(b.get("sample_size") or 0)
            rate = float(b.get("success_rate"))
        except (TypeError, ValueError):
            continue
        if n >= min_samples and rate < threshold:
            out.append(b)
    return sorted(out, key=lambda b: float(b.get("success_rate") or 0.0))


def salient_belief(record: Optional[dict[str, Any]], *,
                   min_samples: int = BELIEF_MIN_SAMPLES,
                   threshold: float = BELIEF_WEAK_SUCCESS_RATE) -> Optional[dict[str, Any]]:
    """The belief a wake should reason from.

    2026-09-25: the wake surfaced `latest_belief` (newest write) while the
    research gate escalated on `weak_beliefs` (settled, below threshold). On a
    record whose newest belief is strong and an older one weak, the two paths
    disagreed about which belief mattered. The weakest sufficiently-sampled
    belief is the one that should change a judgment; absent any, the latest.
    """
    weak = weak_beliefs(record, min_samples=min_samples, threshold=threshold)
    if weak:
        return weak[0]
    return latest_belief(record)


def belief_sentence(belief: Optional[dict[str, Any]]) -> str:
    """One plain sentence a model can be shown. Numbers, no instructions."""
    if not belief:
        return ""
    try:
        n = int(belief.get("sample_size") or 0)
        k = int(belief.get("successful") or 0)
        rate = float(belief.get("success_rate") or 0.0)
    except (TypeError, ValueError):
        return ""
    return (f"Settled outcomes on record: prior {belief.get('recommendation')} calls on this "
            f"subject were right {k} of {n} times over {belief.get('horizon')} "
            f"(success rate {rate:.2f}, population {belief.get('population')}, "
            f"belief {belief.get('belief_key')} rev {belief.get('revision')}).")


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
    """The record store for a state root; ``None`` means the registered store.

    2026-09-24 (agentic-memory tranche 1, R6): ``resolve_store`` returns a
    ``dict`` (``{"ok", "path", ...}``), and the previous body did
    ``Path(getattr(loc, "path", None) or loc)`` on it, which raised
    ``TypeError`` and fell through to the cwd-relative ``DEFAULT_PATH`` on every
    call. In production the two coincide only because the release's ``data/cio``
    is a symlink into persistent-state; from a worktree, a health probe or a test
    they are two different files. Resolve the registry path properly and record
    which file was read (``store_path``) so the consult evidence can prove it.
    """
    if root is None:
        try:
            from scripts.lib.canonical_store_registry import resolve_store

            loc = resolve_store(STORE_ID)
            path = loc.get("path") if isinstance(loc, dict) else getattr(loc, "path", None)
            if path:
                return InstrumentRecordStore(Path(path))
        except Exception:  # noqa: BLE001
            pass
        return InstrumentRecordStore(DEFAULT_PATH)
    root_p = Path(root)
    return InstrumentRecordStore(root_p / DEFAULT_PATH)


def subject_key_for_symbol(symbol: Any, *, store: InstrumentRecordStore | None = None,
                           root: Path | str | None = None) -> Optional[str]:
    """The subject_key an existing record holds for a bare symbol, or None.

    Probes HELD, then EXIT, then WATCH, then SECTOR — the same order the wake
    loader uses — and returns the first key with a record. Lookup only: a
    symbol with no record yields None; nothing is minted here.
    """
    raw = str(symbol or "").strip()
    if not raw:
        return None
    st = store or _store_for_root(root)
    for key in _candidate_keys(raw):
        if st.load(key):
            return key
    return None


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

    Prefers ``subject_key_hint``, then a registry ``subject_guid`` match on
    stored records, then ``subject_guid`` if it is already a ``KIND:NAME`` key,
    then symbol probes ``HELD|EXIT|WATCH|SECTOR:SYM``.
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
    # Prefer true registry GUID join when the tip store carries subject_guid.
    guid_probe = str(subject_guid or "").strip()
    if guid_probe and ":" not in guid_probe and len(guid_probe) >= 32:
        try:
            store = _store_for_root(root)
            for rec in store.all():
                if not isinstance(rec, dict):
                    continue
                if str(rec.get("subject_guid") or "") == guid_probe:
                    return {
                        **base,
                        "ok": True,
                        "record": dict(rec),
                        "status": "OK",
                        "subject_key": rec.get("subject_key"),
                        "subject_guid": guid_probe,
                    }
        except Exception:
            pass
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


# ── CIO prospect: InstrumentRecord@v1 extended (AGENTS.md §26, §13.5) ─────────
#
# 18.0.0 (ACTIVE) makes the CIO prospect record the single per-security truth:
# one row per security_guid, written only by THIS store. The prospect is not a
# new type — it is InstrumentRecord@v1 with the §4 fields of
# docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md added at the top level of
# the record, through `apply_prospect`, a named rail beside `apply_cognition`
# and `apply_belief`. MBI_BEHAVIOR = 0 is unchanged: the rail refuses any
# BEHAVIOR_FIELDS key anywhere in the block, outright, never filtered. Stance is
# posture and priority; next_trigger is a reference level, never an order.
#
# P1 (shadow): the jsonl stays the store of record. The Postgres table
# `cio_prospect` (migrations/2026_10_22_cio_prospect.sql, NOT applied) receives
# a dual-write only when `prospect_store_status()` says live: the registry row is
# granted (domains[], with an approval), the operator's flag is set, and the
# table exists. Until all three hold the dual-write is inert and says why.

PROSPECT_SCHEMA = "CIOProspect@v1-ext"          # field-set tag on the record; the type stays InstrumentRecord@v1
PROSPECT_DOMAIN = "cio_prospect"
PROSPECT_TABLE = "cio_prospect"
PROSPECT_EVENTS_TABLE = "cio_prospect_events"
PROSPECT_WRITER = "InstrumentRecordStore"
PROSPECT_DUAL_WRITE_ENV = "TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE"

PROSPECT_STAGES = ("watching", "setup_forming", "actionable", "proposed", "held", "exit", "re_entry")
PROSPECT_STANCES = ("BUY_SETUP", "ADD", "HOLD", "TRIM_REVIEW", "EXIT_REVIEW", "WATCH", "AVOID")
CONVICTION_COMPONENTS = (
    "unified_edge", "fused_score", "catalyst_grade", "thesis_quality", "risk_reward", "regime_fit",
    "opportunity_score", "hermes_score", "scanner_score",
)
PROSPECT_FIELDS = (
    "security_guid", "issuer_guid", "aliases", "stage", "stage_phase", "stage_changed_at", "stage_evidence",
    "conviction", "conviction_components", "stance", "catalyst_grade", "next_trigger", "whats_missing",
    "next_action", "research", "position_ref", "watchlist", "conflicts", "evidence_at", "expires_at",
    "provenance",
    # Operator 2026-10-22 (NAVN): where a position came from, its lifecycle, why it ended and when to get back in —
    # on the same record (scripts/lib/cio_prospect_lifecycle.py builds them; observed facts, never behaviour).
    "origin", "position_lifecycle", "post_exit_review", "reentry_advice",
)
# held -> exit (exit_review) -> re_entry (re_entry_watch): display phases inside the §26.1 stages.
PROSPECT_STAGE_PHASES = ("exit_review", "re_entry_watch")
PROSPECT_EVENT_TYPES = (
    "mint", "update", "stage_change", "conflict_opened", "conflict_resolved", "rollback",
    "origin_attributed", "entry_fill", "stop_change", "conviction_change", "excursion", "exit_fill",
    "exit_review", "reentry_advice",
)
# The fields a prospect write must carry (DATA_DICTIONARY.md CIOProspect, "Required").
PROSPECT_REQUIRED = ("security_guid", "issuer_guid", "stage", "conviction", "stance", "evidence_at", "expires_at")


class ProspectInvalid(ValueError):
    """A prospect block that would not be a truthful record (bad enum, no identity, no expiry)."""


def _parse_ts(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_uuid(value: Any) -> bool:
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def conviction_from_components(components: Optional[dict[str, Any]]) -> Optional[float]:
    """The conviction, reproduced from its named components (weighted mean, 0–100).

    Each component is ``{"value": 0..100, "weight": w (default 1), "source", "evidence_at"}``.
    A component with ``value`` None is carried (so "missing" is visible) and does not vote.
    Returns None when no component votes — a conviction with no evidence is not a number.
    """
    num = 0.0
    den = 0.0
    for comp in (components or {}).values():
        if not isinstance(comp, dict) or comp.get("value") is None:
            continue
        try:
            v = float(comp["value"])
            w = float(comp.get("weight", 1.0))
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        num += max(0.0, min(100.0, v)) * w
        den += w
    if den <= 0:
        return None
    return round(num / den, 2)


def unified_edge_component(ctx: dict[str, Any], *, source: str, evidence_at: Any,
                           weight: float = 1.0) -> dict[str, Any]:
    """Persist the unified edge as a conviction component (DATA_DICTIONARY.md "unified edge").

    The number was computed in memory inside auto_proposal_generator and never stored;
    nobody could replay it. Here it is computed with the SAME function
    (``unified_edge_score.edge_from_trade_context``) and stored with its inputs, so it
    is inspectable and reproducible. Inputs are scores and ratios only — a BEHAVIOR key
    in ``ctx`` raises (MBI_BEHAVIOR = 0).
    """
    bad = sorted(k for k in _walk_keys(ctx or {}) if k in BEHAVIOR_FIELDS)
    if bad:
        raise BehaviorWriteRefused(f"MBI_BEHAVIOR=0: a unified-edge input may not carry {bad}")
    try:
        from scripts.unified_edge_score import edge_from_trade_context
    except ImportError:  # imported with scripts/ on sys.path
        from unified_edge_score import edge_from_trade_context  # type: ignore
    inputs = {k: ctx.get(k) for k in (
        "pop_pct", "iv_rank", "risk_reward", "catalyst_strength", "confidence",
        "regime_alignment", "technical_score") if ctx.get(k) is not None}
    return {
        "value": float(edge_from_trade_context(dict(ctx or {}))),
        "weight": float(weight),
        "source": source,
        "evidence_at": evidence_at,
        "method": "unified_edge_score.edge_from_trade_context",
        "inputs": inputs,
    }


def _validate_prospect(rec: dict[str, Any]) -> None:
    missing = [k for k in PROSPECT_REQUIRED if rec.get(k) in (None, "")]
    if missing:
        raise ProspectInvalid(f"prospect is missing {missing}")
    if not _is_uuid(rec.get("security_guid")) or not _is_uuid(rec.get("issuer_guid")):
        raise ProspectInvalid("security_guid / issuer_guid must be registry GUIDs (never a placeholder, §7)")
    if rec.get("stage") not in PROSPECT_STAGES:
        raise ProspectInvalid(f"stage must be one of {PROSPECT_STAGES}")
    if rec.get("stance") not in PROSPECT_STANCES:
        raise ProspectInvalid(f"stance must be one of {PROSPECT_STANCES}")
    try:
        conv = float(rec.get("conviction"))
    except (TypeError, ValueError):
        raise ProspectInvalid("conviction must be a number 0-100") from None
    if not 0.0 <= conv <= 100.0:
        raise ProspectInvalid("conviction must be within 0-100")
    comps = rec.get("conviction_components") or {}
    if not isinstance(comps, dict):
        raise ProspectInvalid("conviction_components must be an object")
    unknown = sorted(set(comps) - set(CONVICTION_COMPONENTS))
    if unknown:
        raise ProspectInvalid(f"unknown conviction components {unknown}")
    derived = conviction_from_components(comps)
    if derived is not None and abs(derived - conv) > 0.01:
        raise ProspectInvalid(
            f"conviction {conv} is not reproducible from its components ({derived})")
    ev, ex = _parse_ts(rec.get("evidence_at")), _parse_ts(rec.get("expires_at"))
    if ev is None or ex is None:
        raise ProspectInvalid("evidence_at / expires_at must be ISO timestamps")
    if ex < ev:
        raise ProspectInvalid("expires_at precedes evidence_at")
    conflicts = rec.get("conflicts") or []
    if not isinstance(conflicts, list):
        raise ProspectInvalid("conflicts must be a list")
    for c in conflicts:
        vals = (c or {}).get("values") if isinstance(c, dict) else None
        if not isinstance(c, dict) or not c.get("field") or not isinstance(vals, list) or len(vals) < 2:
            raise ProspectInvalid("each conflict names a field and at least two {value, source, at} values")
        for v in vals:
            if not isinstance(v, dict) or not v.get("source"):
                raise ProspectInvalid("each conflicting value names its source")
    if not isinstance(rec.get("whats_missing") or [], list):
        raise ProspectInvalid("whats_missing must be a list")
    if rec.get("stage_phase") is not None and rec.get("stage_phase") not in PROSPECT_STAGE_PHASES:
        raise ProspectInvalid(f"stage_phase must be one of {PROSPECT_STAGE_PHASES}")
    origin = rec.get("origin")
    if origin is not None and (not isinstance(origin, dict) or origin.get("classification") not in (
            "internal", "operator_initiated")):
        raise ProspectInvalid("origin.classification is internal or operator_initiated — never null (learning loop)")


def apply_prospect(
    record: dict[str, Any],
    *,
    prospect: dict[str, Any],
    strict: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Return (updated_record, changed_prospect_fields) or raise.

    The rail, in order: any BEHAVIOR_FIELDS key anywhere in ``prospect`` raises
    BehaviorWriteRefused; a key outside PROSPECT_FIELDS raises ProspectInvalid (the
    prospect is a named field set, not a bag); a ``conviction`` the caller omitted is
    reproduced from ``conviction_components``; the merged record must validate; a
    stage move must name its evidence; a write that changes nothing is a CognitionNoOp
    under ``strict``. ``subject_guid`` on the record is an alias of ``security_guid``
    (identity table) and is mapped into ``aliases``, never a second key.
    """
    if not isinstance(prospect, dict):
        raise ValueError("prospect must be a dict")
    bad = sorted(k for k in _walk_keys(prospect) if k in BEHAVIOR_FIELDS)
    if bad:
        raise BehaviorWriteRefused(f"MBI_BEHAVIOR=0: a prospect may not carry {bad}")
    extra = sorted(k for k in prospect if k not in PROSPECT_FIELDS)
    if extra:
        raise ProspectInvalid(f"not prospect fields: {extra}")

    rec = dict(record)
    block = dict(prospect)
    if block.get("conviction") is None and block.get("conviction_components") is not None:
        block["conviction"] = conviction_from_components(block["conviction_components"])

    changed: list[str] = []
    prior_stage = rec.get("stage")
    for k, v in block.items():
        if rec.get(k) != v:
            rec[k] = v
            changed.append(k)

    if "stage" in changed:
        if prior_stage is not None and not block.get("stage_evidence"):
            raise ProspectInvalid("a stage move names the evidence that moved it (stage_evidence)")
        if "stage_changed_at" not in block:
            rec["stage_changed_at"] = (rec.get("evidence_at") if prior_stage is None else None) or _now()

    aliases = dict(rec.get("aliases") or {})
    sg = rec.get("subject_guid")
    if sg:
        aliases["subject_guid"] = sg
    if rec.get("subject_key"):
        aliases["subject_key"] = rec["subject_key"]
    syms = rec.get("symbols") or []
    if syms:
        aliases["symbol"] = syms[0]
    rec["aliases"] = aliases
    rec.setdefault("conflicts", [])
    rec.setdefault("whats_missing", [])

    _validate_prospect(rec)
    if strict and not changed:
        raise CognitionNoOp(f"{rec.get('subject_key')}: prospect unchanged — not persisted")
    rec["prospect_schema"] = PROSPECT_SCHEMA
    rec["prospect_revision"] = int(record.get("prospect_revision") or 0) + (1 if changed else 0)
    rec["memory_behavior_influence"] = MBI_BEHAVIOR
    rec["updated_ts"] = _now()
    return rec, changed


def is_prospect_record(record: Optional[dict[str, Any]]) -> bool:
    return bool(record) and record.get("prospect_schema") == PROSPECT_SCHEMA


def prospect_row(record: dict[str, Any]) -> dict[str, Any]:
    """The ``cio_prospect`` table row for a prospect-bearing record (validated)."""
    _validate_prospect(record)
    syms = record.get("symbols") or []
    cognition = {k: record.get(k) for k in COGNITION_FIELDS}
    return {
        "security_guid": str(record["security_guid"]),
        "issuer_guid": str(record["issuer_guid"]),
        "symbol": str((syms[0] if syms else (record.get("aliases") or {}).get("symbol")) or ""),
        "subject_key": record.get("subject_key"),
        "aliases": record.get("aliases") or {},
        "stage": record["stage"],
        "stage_changed_at": record.get("stage_changed_at"),
        "stage_evidence": record.get("stage_evidence"),
        "conviction": round(float(record["conviction"]), 2),
        "conviction_components": record.get("conviction_components") or {},
        "stance": record["stance"],
        "catalyst_grade": record.get("catalyst_grade"),
        "next_trigger": record.get("next_trigger"),
        "whats_missing": record.get("whats_missing") or [],
        "next_action": record.get("next_action"),
        "thesis_ref": record.get("thesis_ref"),
        "research": record.get("research"),
        "position_ref": record.get("position_ref"),
        "watchlist": record.get("watchlist"),
        "stage_phase": record.get("stage_phase"),
        "origin": record.get("origin"),
        "position_lifecycle": record.get("position_lifecycle"),
        "post_exit_review": record.get("post_exit_review"),
        "reentry_advice": record.get("reentry_advice"),
        "conflicts": record.get("conflicts") or [],
        "cognition": cognition,
        "provenance": record.get("provenance") or {},
        "evidence_at": record["evidence_at"],
        "expires_at": record["expires_at"],
        "as_of": record.get("updated_ts") or _now(),
        "writer": PROSPECT_WRITER,
        "revision": max(1, int(record.get("prospect_revision") or 1)),
    }


def prospect_event(prior: Optional[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    """The append-only ``cio_prospect_events`` row describing prior → row (both table rows)."""
    if prior is None:
        etype, change = "mint", {k: row.get(k) for k in ("stage", "stance", "conviction")}
    else:
        diff = {k: {"from": prior.get(k), "to": row.get(k)}
                for k in ("stage", "stance", "conviction", "catalyst_grade", "conflicts", "next_trigger", "expires_at")
                if prior.get(k) != row.get(k)}
        n_new, n_old = len(row.get("conflicts") or []), len(prior.get("conflicts") or [])
        if "stage" in diff:
            etype = "stage_change"
        elif n_new > n_old:
            etype = "conflict_opened"
        elif n_new < n_old:
            etype = "conflict_resolved"
        else:
            etype = "update"
        change = diff
    return {
        "security_guid": row["security_guid"],
        "at": row["as_of"],
        "writer": PROSPECT_WRITER,
        "event_type": etype,
        "event_key": f"rev:{row['revision']}",
        "change": change,
        "evidence": row.get("stage_evidence"),
        "revision": row["revision"],
    }


def _registry_doc(registry_path: Path | str | None = None) -> dict[str, Any]:
    p = (Path(registry_path) if registry_path
         else Path(__file__).resolve().parents[2] / "config" / "data_source_authority.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def prospect_row_granted(registry: Optional[dict[str, Any]] = None, *,
                         registry_path: Path | str | None = None) -> bool:
    """True only when the operator granted the ``cio_prospect`` row (§17): it sits in
    ``domains[]`` with an ``approval`` naming who approved it. A proposed row is not a grant."""
    doc = registry if registry is not None else _registry_doc(registry_path)
    for row in doc.get("domains") or []:
        if isinstance(row, dict) and row.get("domain") == PROSPECT_DOMAIN:
            appr = row.get("approval") or {}
            return bool(isinstance(appr, dict) and str(appr.get("approved_by") or "").strip())
    return False


def prospect_store_status(*, registry: Optional[dict[str, Any]] = None,
                          env: Optional[dict[str, str]] = None,
                          table_probe: Any = None) -> dict[str, Any]:
    """Whether the Postgres dual-write may run, and every reason it may not.

    Three conditions, all required: the registry row is granted; the operator's flag
    ``TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1`` is set; the table exists (``table_probe``,
    a zero-arg callable returning bool, is only called after the first two hold — so an
    ungranted store never touches the database).
    """
    environ = os.environ if env is None else env
    reasons: list[str] = []
    granted = prospect_row_granted(registry)
    if not granted:
        reasons.append("registry_row_not_granted")
    flag = str(environ.get(PROSPECT_DUAL_WRITE_ENV) or "").strip() == "1"
    if not flag:
        reasons.append("dual_write_flag_off")
    table_present: Optional[bool] = None
    if granted and flag:
        if table_probe is None:
            reasons.append("no_table_probe")
        else:
            try:
                table_present = bool(table_probe())
                if not table_present:
                    reasons.append("table_absent")
            except Exception as exc:  # noqa: BLE001
                table_present = False
                reasons.append(f"table_probe_failed:{type(exc).__name__}")
    return {
        "live": not reasons,
        "reasons": reasons,
        "row_granted": granted,
        "flag": flag,
        "table_present": table_present,
        "mode": "dual_write" if not reasons else "inert",
        "store_of_record": "jsonl",
        "memory_behavior_influence": MBI_BEHAVIOR,
    }


UPSERT_PROSPECT_SQL = (
    "INSERT INTO cio_prospect (security_guid, issuer_guid, symbol, subject_key, aliases, stage, stage_changed_at, "
    "stage_evidence, conviction, conviction_components, stance, catalyst_grade, next_trigger, whats_missing, "
    "next_action, thesis_ref, research, position_ref, watchlist, stage_phase, origin, position_lifecycle, "
    "post_exit_review, reentry_advice, conflicts, cognition, provenance, evidence_at, "
    "expires_at, as_of, writer, revision) VALUES (%(security_guid)s, %(issuer_guid)s, %(symbol)s, %(subject_key)s, "
    "%(aliases)s, %(stage)s, %(stage_changed_at)s, %(stage_evidence)s, %(conviction)s, %(conviction_components)s, "
    "%(stance)s, %(catalyst_grade)s, %(next_trigger)s, %(whats_missing)s, %(next_action)s, %(thesis_ref)s, "
    "%(research)s, %(position_ref)s, %(watchlist)s, %(stage_phase)s, %(origin)s, %(position_lifecycle)s, "
    "%(post_exit_review)s, %(reentry_advice)s, %(conflicts)s, %(cognition)s, %(provenance)s, %(evidence_at)s, "
    "%(expires_at)s, %(as_of)s, %(writer)s, %(revision)s) "
    "ON CONFLICT (security_guid) DO UPDATE SET issuer_guid = EXCLUDED.issuer_guid, symbol = EXCLUDED.symbol, "
    "subject_key = EXCLUDED.subject_key, aliases = EXCLUDED.aliases, stage = EXCLUDED.stage, "
    "stage_changed_at = EXCLUDED.stage_changed_at, stage_evidence = EXCLUDED.stage_evidence, "
    "conviction = EXCLUDED.conviction, conviction_components = EXCLUDED.conviction_components, "
    "stance = EXCLUDED.stance, catalyst_grade = EXCLUDED.catalyst_grade, next_trigger = EXCLUDED.next_trigger, "
    "whats_missing = EXCLUDED.whats_missing, next_action = EXCLUDED.next_action, thesis_ref = EXCLUDED.thesis_ref, "
    "research = EXCLUDED.research, position_ref = EXCLUDED.position_ref, watchlist = EXCLUDED.watchlist, "
    "stage_phase = EXCLUDED.stage_phase, origin = EXCLUDED.origin, position_lifecycle = EXCLUDED.position_lifecycle, "
    "post_exit_review = EXCLUDED.post_exit_review, reentry_advice = EXCLUDED.reentry_advice, "
    "conflicts = EXCLUDED.conflicts, cognition = EXCLUDED.cognition, provenance = EXCLUDED.provenance, "
    "evidence_at = EXCLUDED.evidence_at, expires_at = EXCLUDED.expires_at, as_of = EXCLUDED.as_of, "
    "writer = EXCLUDED.writer, revision = EXCLUDED.revision "
    "WHERE cio_prospect.revision < EXCLUDED.revision"
)
INSERT_PROSPECT_EVENT_SQL = (
    "INSERT INTO cio_prospect_events (security_guid, at, writer, event_type, event_key, change, evidence, revision) "
    "VALUES (%(security_guid)s, %(at)s, %(writer)s, %(event_type)s, %(event_key)s, %(change)s, %(evidence)s, "
    "%(revision)s) ON CONFLICT (security_guid, event_key) DO NOTHING"
)
_JSON_COLUMNS = ("aliases", "stage_evidence", "conviction_components", "catalyst_grade", "next_trigger",
                 "whats_missing", "next_action", "research", "position_ref", "watchlist", "conflicts",
                 "cognition", "provenance", "change", "evidence", "origin", "position_lifecycle",
                 "post_exit_review", "reentry_advice")


def _jsonify(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k in _JSON_COLUMNS:
        if k in out and out[k] is not None:
            out[k] = json.dumps(out[k], sort_keys=True, default=str)
    return out


class ProspectPgBackend:
    """Postgres side of the P1 dual-write. ``connect`` is a zero-arg DB-API connection factory.

    One transaction per write: the row upsert (applied only when the revision advances) and
    its event. Never deletes, never DDL. Called only when ``prospect_store_status`` is live.
    """

    def __init__(self, connect: Any) -> None:
        self._connect = connect

    def table_present(self) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.cio_prospect') IS NOT NULL "
                            "AND to_regclass('public.cio_prospect_events') IS NOT NULL")
                return bool(cur.fetchone()[0])
        finally:
            conn.close()

    def write(self, row: dict[str, Any], event: dict[str, Any],
              lifecycle: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(UPSERT_PROSPECT_SQL, _jsonify(row))
                upserted = cur.rowcount
                cur.execute(INSERT_PROSPECT_EVENT_SQL, _jsonify(event))
                appended = cur.rowcount
                for ev in lifecycle:          # idempotent: one row per fact (event_key)
                    cur.execute(INSERT_PROSPECT_EVENT_SQL, _jsonify(
                        {"evidence": None, "revision": row["revision"], **ev}))
                    appended += cur.rowcount
            conn.commit()
            return {"ok": True, "upserted": upserted, "event_appended": appended}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
