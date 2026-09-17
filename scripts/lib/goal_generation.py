"""Generation-token dedup for goal laps — the producer-side fix for a goal that
can be worked forever and never progress.

Measured on the live ledger 2026-09-16 (`data/cio/cio_goals.jsonl`, 29 MB):

    GOAL_THESIS_UPDATED      29,774   of which shadow_run= 29,774 (100%)
                                      of which PROVIDER_BLOCKED 29,774 (100%)
                                      of which retrieval_n=0    29,774 (100%)
    GOAL_WAKE_RECORDED       34,809
    GOAL_STATUS_CHANGED           0
    distinct thesis prefixes 29,774   (every one a unique run id — no content)

One goal was worked 11,457 times and never moved. The enqueue side is why:

    ON CONFLICT (agent_id, trigger_kind, dedup_key) DO NOTHING

`agentic_runtime.trigger_intake`'s conflict target carries **no state column**, so
a row in ANY terminal state blocks re-enqueue of that key forever. With the old
constant key ``goal:<goal_id>`` a goal got exactly one lap for all time —
measured 29,653 duplicate enqueues against 1,759 accepted.

**This fix is producer-side on purpose.** `trigger_intake` has no DDL in this
repo (`migrations/agentic_runtime/` holds only `0001_mvl`'s eight tables and
`0002_roles`, and `tests/test_agent_runtime_migration_contract.py` asserts
exactly those eight); the tables were created out of band. Amending the
constraint is a §7A/§17 operator-gated change to an authoritative store, so the
key itself is made to carry the generation instead:

    dedup_key = goal:{goal_id}:{predicate_version}:{ledger_digest}

The digest is taken over what is still OUTSTANDING and what has been LEARNED:
open needs, closed needs and the evidence set. Therefore

  * same goal + same outstanding needs + nothing learned  -> correctly REFUSED
    (this is why the 29,653-duplicate storm cannot recur: a lap that ends
    PROVIDER_BLOCKED with retrieval_n=0 learns nothing, so it earns no new key);
  * a need closes, or new evidence lands, or the lap reaches a finding it had
    not reached before -> exactly ONE new lap.

Dedup keeps doing its real job (never enqueue the same live work twice) and
stops doing the job it was never meant to do (prevent a second lap).

AUTHORITY: READ_ONLY_ADVISORY. Advisory only, append-only, nothing is deleted.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

SCHEMA = "GoalGenerationToken@v1"

# The append-only record of what each lap produced. This is P4's own store; P5's
# `cio_goal_need_ledger.jsonl` is read here when it exists and is never written
# by this module, so the two phases cannot fight over one file.
DEFAULT_LAP_LEDGER_PATH = Path("data/cio/cio_goal_laps.jsonl")
DEFAULT_NEED_LEDGER_PATH = Path("data/cio/cio_goal_need_ledger.jsonl")

# P2 introduces GOAL_PREDICATE_SET and a predicate_version on the projection.
# Until a goal carries one, every goal is at the same v0 generation line, which
# keeps the key well-formed and makes P2's arrival a pure version bump.
PREDICATE_VERSION_FALLBACK = "v0"

DIGEST_CHARS = 16

__all__ = [
    "SCHEMA",
    "DEFAULT_LAP_LEDGER_PATH",
    "DEFAULT_NEED_LEDGER_PATH",
    "PREDICATE_VERSION_FALLBACK",
    "predicate_version",
    "declared_needs",
    "read_laps",
    "append_lap",
    "ledger_digest",
    "generation_key",
    "generation_for_goal",
    "goal_context_block",
    "goal_id_from_dedup_key",
    "finding_ref",
    "goal_trigger_candidate",
    "enqueue_goal_lap",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha(value: Any, chars: int = 64) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:chars]


# ── the goal's declared work ────────────────────────────────────────────────


def predicate_version(goal: Mapping[str, Any]) -> str:
    """The goal's predicate version, or the v0 line for a goal that has none yet.

    The projection NESTS the predicate: ``CIOGoalStore._apply_event`` writes
    ``goal["predicate"]["predicate_version"]`` and never a top-level key. Reading
    only the top level therefore returned ``v0`` for goal_695a5dbe2401, whose own
    stored identity is ``goal_695a5dbe2401:v1:cd0065040125a4cc``.

    That is load-bearing, not cosmetic. The generation key is
    ``goal:{goal_id}:{predicate_version}:{ledger_digest}``, so setting a new
    predicate left the key byte-identical, the next generation was refused as
    DUPLICATE, and the restart-on-new-predicate guarantee was inert.

    Nested wins; a flattened top-level value is still honoured so a caller that
    passes a summary dict keeps working. Integers render ``v<N>`` to match
    ``cio_goals.predicate_identity`` and the ``read_laps`` filter.
    """
    nested = goal.get("predicate")
    raw = ""
    if isinstance(nested, Mapping):
        raw = str(nested.get("predicate_version") or "").strip()
    if not raw:
        raw = str(goal.get("predicate_version") or "").strip()
    if not raw:
        return PREDICATE_VERSION_FALLBACK
    return raw if raw.startswith("v") else f"v{raw}"


def declared_needs(goal: Mapping[str, Any]) -> tuple[str, ...]:
    """What this goal must obtain before it can be called answered.

    Prefers an explicit `needs` list (P5 writes one). Falls back to the goal's
    own `success_criteria`, split on ';' or newline — the operator already writes
    these as a list of conditions, and reading them is honest where inventing a
    need would not be. A goal that declares nothing gets one named need rather
    than an empty ledger that would look satisfied.
    """
    raw = goal.get("needs")
    if isinstance(raw, (list, tuple)):
        needs = [str(n).strip() for n in raw if str(n).strip()]
        if needs:
            return tuple(sorted(set(needs)))
    criteria = str(goal.get("success_criteria") or "").strip()
    if criteria:
        parts: list[str] = []
        for chunk in criteria.replace("\n", ";").split(";"):
            chunk = chunk.strip()
            if chunk:
                parts.append(chunk)
        if parts:
            return tuple(sorted(set(parts)))
    return ("unspecified",)


# ── the append-only lap ledger ──────────────────────────────────────────────


def _lap_path(path: Path | str | None) -> Path:
    return Path(path) if path is not None else Path(DEFAULT_LAP_LEDGER_PATH)


def read_laps(
    goal_id: str,
    *,
    path: Path | str | None = None,
    predicate_version_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Every lap recorded for this goal, oldest first. Missing store -> no laps."""
    p = _lap_path(path)
    if not p.exists():
        return []
    laps: list[dict[str, Any]] = []
    try:
        with open(p, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a torn line never hides the laps around it
                if row.get("goal_id") != goal_id:
                    continue
                if (
                    predicate_version_filter is not None
                    and str(row.get("predicate_version") or PREDICATE_VERSION_FALLBACK)
                    != predicate_version_filter
                ):
                    continue
                laps.append(row)
    except OSError:
        return []
    return laps


def append_lap(record: Mapping[str, Any], *, path: Path | str | None = None) -> dict[str, Any]:
    """Append one lap record. Append-only, flock-guarded, never rewritten."""
    p = _lap_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = dict(record)
    row.setdefault("schema", SCHEMA)
    row.setdefault("created_ts", _now())
    row.setdefault("authority", "READ_ONLY_ADVISORY")
    lock = p.with_suffix(p.suffix + ".lock")
    with open(lock, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            with open(p, "a") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    return row


def _closed_needs(laps: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    closed: set[str] = set()
    for lap in laps:
        for need in lap.get("closed_needs") or ():
            closed.add(str(need))
    return tuple(sorted(closed))


def _evidence(laps: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    refs: set[str] = set()
    for lap in laps:
        for ref in lap.get("evidence_refs") or ():
            refs.add(str(ref))
    return tuple(sorted(refs))


def _need_ledger_rows(goal_id: str, *, path: Path | str | None = None) -> list[dict[str, Any]]:
    """P5's ledger, read-only and optional. Absent today; wired when it lands."""
    p = Path(path) if path is not None else Path(DEFAULT_NEED_LEDGER_PATH)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(p, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("goal_id") == goal_id:
                    rows.append(row)
    except OSError:
        return []
    return rows


def finding_ref(text: str) -> str:
    """A content-addressed reference to one lap's finding.

    Two laps that reach the SAME conclusion produce the same ref and therefore
    the same generation — so an agent that repeats itself is refused a new lap
    instead of looping. A genuinely new conclusion is new evidence.
    """
    cleaned = " ".join(str(text or "").split())
    return f"finding:{_sha(cleaned, 12)}" if cleaned else ""


# ── the generation token ────────────────────────────────────────────────────


def ledger_digest(
    goal: Mapping[str, Any],
    laps: Sequence[Mapping[str, Any]] = (),
    *,
    need_rows: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Digest over what is still outstanding and what has been learned."""
    pv = predicate_version(goal)
    closed = set(_closed_needs(laps))
    for row in need_rows:
        if str(row.get("state") or "").upper() in {"CLOSED", "SATISFIED"} and row.get("need"):
            closed.add(str(row["need"]))
    declared = declared_needs(goal)
    open_needs = tuple(n for n in declared if n not in closed)
    return _sha(
        {
            "schema": SCHEMA,
            "goal_id": str(goal.get("goal_id") or ""),
            "predicate_version": pv,
            "open_needs": list(open_needs),
            "closed_needs": sorted(closed),
            "evidence": list(_evidence(laps)),
        },
        DIGEST_CHARS,
    )


def generation_key(goal_id: str, predicate_version_value: str, digest: str) -> str:
    """``goal:{goal_id}:{predicate_version}:{ledger_digest}`` — the whole fix."""
    return f"goal:{goal_id}:{predicate_version_value}:{digest}"


def goal_id_from_dedup_key(dedup_key: str) -> str:
    """Recover the goal id from a generation key, or from the legacy ``goal:<id>``."""
    raw = str(dedup_key or "")
    if not raw.startswith("goal:"):
        return ""
    return raw.split(":")[1] if len(raw.split(":")) > 1 else ""


def generation_for_goal(
    goal: Mapping[str, Any],
    *,
    laps_path: Path | str | None = None,
    need_ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    """The goal's current generation: its key, its ledger and its prior lap."""
    goal_id = str(goal.get("goal_id") or "")
    pv = predicate_version(goal)
    laps = read_laps(goal_id, path=laps_path, predicate_version_filter=pv)
    need_rows = _need_ledger_rows(goal_id, path=need_ledger_path)
    closed = set(_closed_needs(laps))
    for row in need_rows:
        if str(row.get("state") or "").upper() in {"CLOSED", "SATISFIED"} and row.get("need"):
            closed.add(str(row["need"]))
    declared = declared_needs(goal)
    open_needs = tuple(n for n in declared if n not in closed)
    digest = ledger_digest(goal, laps, need_rows=need_rows)
    return {
        "schema": SCHEMA,
        "goal_id": goal_id,
        "predicate_version": pv,
        "ledger_digest": digest,
        "dedup_key": generation_key(goal_id, pv, digest),
        "lap": len(laps) + 1,
        "declared_needs": list(declared),
        "open_needs": list(open_needs),
        "closed_needs": sorted(closed),
        "evidence_refs": list(_evidence(laps)),
        "prior_lap": dict(laps[-1]) if laps else None,
    }


# ── what the agent is finally allowed to see ────────────────────────────────


def goal_context_block(goal: Mapping[str, Any], generation: Mapping[str, Any]) -> str:
    """Goal + predicate + need ledger + prior artifact, as prompt text.

    Before this, the prompt was built from retrieval rows alone and the goal was
    loaded AFTER the model call — so every one of 11,457 laps was a cold start
    and no lap could see what the last one found.
    """
    prior = generation.get("prior_lap") or {}
    lines = [
        f"GOAL {generation.get('goal_id')} — {goal.get('title') or '(untitled)'}",
        f"  status={goal.get('status')} owner={goal.get('owner_agent')} "
        f"predicate={generation.get('predicate_version')} "
        f"generation={generation.get('ledger_digest')} lap={generation.get('lap')}",
    ]
    if goal.get("description"):
        lines.append(f"  description: {goal['description']}")
    lines.append(f"PREDICATE (success criteria): {goal.get('success_criteria') or '(none declared)'}")
    lines.append("NEED LEDGER:")
    lines.append(f"  OPEN:   {', '.join(generation.get('open_needs') or []) or '(none)'}")
    lines.append(f"  CLOSED: {', '.join(generation.get('closed_needs') or []) or '(none)'}")
    lines.append(f"  EVIDENCE: {', '.join(generation.get('evidence_refs') or []) or '(none yet)'}")
    if goal.get("thesis_summary"):
        lines.append(f"THESIS SO FAR: {goal['thesis_summary']}")
    if prior:
        lines.append(
            f"PRIOR LAP {prior.get('lap')} (artifact {prior.get('artifact_id')}, "
            f"payload_hash {str(prior.get('payload_hash') or '')[:12]}):"
        )
        lines.append(f"  finding: {prior.get('finding') or '(no finding recorded)'}")
        if prior.get("model_error"):
            lines.append(f"  provider: {prior['model_error']}")
    else:
        lines.append("PRIOR LAP: none — this is the first lap of this generation.")
    lines.append(
        "CONTINUE that work: do not restate it. Close an OPEN need with evidence, "
        "or state precisely what is still missing. Never invent numbers."
    )
    return "\n".join(lines)


# ── enqueue ─────────────────────────────────────────────────────────────────


def _trigger_candidate_cls():
    try:
        from agent_runtime.trigger_intake import TriggerCandidate  # type: ignore
    except ImportError:  # pragma: no cover - path shape depends on the caller
        import sys

        scripts_dir = Path(__file__).resolve().parents[1]
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from agent_runtime.trigger_intake import TriggerCandidate  # type: ignore
    return TriggerCandidate


def goal_trigger_candidate(
    goal: Mapping[str, Any],
    generation: Mapping[str, Any],
    *,
    agent_id: str | None = None,
    job_type: str = "goal_shadow_review",
    trigger_kind: str = "GOAL_DUE",
    source_timestamp: str | None = None,
):
    """One lap of one goal, as a governed trigger candidate."""
    cls = _trigger_candidate_cls()
    owner = (agent_id or goal.get("owner_agent") or "").strip().lower()
    payload = {
        "goal_id": generation.get("goal_id"),
        "predicate_version": generation.get("predicate_version"),
        "ledger_digest": generation.get("ledger_digest"),
        "lap": generation.get("lap"),
        "open_needs": list(generation.get("open_needs") or []),
        "title": goal.get("title") or "",
    }
    return cls(
        agent_id=owner,
        trigger_kind=trigger_kind,
        dedup_key=str(generation.get("dedup_key")),
        job_type=job_type,
        payload=payload,
        source_ref=f"cio_goals:{generation.get('goal_id')}",
        source_hash=_sha(payload),
        source_timestamp=source_timestamp
        or str(goal.get("updated_ts") or goal.get("created_ts") or _now()),
    )


def enqueue_goal_lap(
    store: Any,
    goal: Mapping[str, Any],
    *,
    agent_id: str | None = None,
    laps_path: Path | str | None = None,
    need_ledger_path: Path | str | None = None,
    job_type: str = "goal_shadow_review",
    trigger_kind: str = "GOAL_DUE",
) -> tuple[Any, dict[str, Any]]:
    """Enqueue this goal's CURRENT generation. Returns (EnqueueOutcome, generation).

    Called twice with nothing learned in between, the second call is DUPLICATE
    and writes no row — the dedup guarantee is intact. Called after a lap that
    closed a need or landed evidence, the key is different and exactly one new
    lap is admitted.
    """
    generation = generation_for_goal(
        goal, laps_path=laps_path, need_ledger_path=need_ledger_path
    )
    candidate = goal_trigger_candidate(
        goal,
        generation,
        agent_id=agent_id,
        job_type=job_type,
        trigger_kind=trigger_kind,
    )
    return store.enqueue(candidate), generation


def merge_evidence(existing: Iterable[str], new: Iterable[str]) -> list[str]:
    """Union of evidence refs, sorted and de-duplicated."""
    return sorted({str(r) for r in existing if str(r)} | {str(r) for r in new if str(r)})
