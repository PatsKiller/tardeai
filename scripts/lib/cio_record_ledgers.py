"""Read-only tail readers for the CIO's own record ledgers.

The CIO writes its learning and thesis records to append-only stores:
outcome checkpoints and observations, lesson binds, thesis revisions and
change cards, instrument records (with their belief blocks), the belief-writer
receipt, the held-book thesis coverage report, research-driven product
reassessments, linked operator feedback and its ingest receipts, and the goal
loop's predicates.
Nothing served those rows to the Command Center; only counts or capability
states were visible.  Each reader here returns the most recent rows of ONE
contract, filtered by that contract's own schema constant, from a bounded tail
window, with the store's present/size/window facts and the rows' own clock.

AUTHORITY: READ_ONLY_ADVISORY.  No writes, no locks, no LLM, no network.
A missing store is reported as MISSING, an empty window as EMPTY — never as a
healthy zero.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_belief_writer import SCHEMA as BELIEF_WRITER_SCHEMA
from scripts.lib.cio_feedback_learning_v1 import FEEDBACK_SCHEMA
from scripts.lib.cio_goals import PREDICATE_SCHEMA
from scripts.lib.cio_held_thesis_coverage import (
    REVISION_SCHEMA,
    SCHEMA as HELD_COVERAGE_SCHEMA,
    THESIS_CHANGE_SCHEMA,
)
from scripts.lib.cio_institutional_learning import SCHEMA_OUTCOME
from scripts.lib.cio_instrument_record import BELIEF_SCHEMA, SCHEMA as INSTRUMENT_RECORD_SCHEMA
from scripts.lib.cio_lesson_bind import LESSON_BIND_SCHEMA
from scripts.lib.cio_lineage import CHECKPOINT_SCHEMA
from scripts.lib.cio_operator_feedback_loop import SCHEMA as FEEDBACK_INGEST_SCHEMA
from scripts.lib.cio_operator_product import SCHEMA as OPERATOR_PRODUCT_SCHEMA
from scripts.lib.cio_product_reassessment import REASSESS_SCHEMA

AUTHORITY = "READ_ONLY_ADVISORY"
TAIL_BYTES = 512 * 1024
DEFAULT_LIMIT = 12
# cio_goals.evaluate_predicate stamps this literal inline (no module constant).
GOAL_VERDICT_SCHEMA = "GoalPredicateVerdict@v1"
_OPERATOR_PRODUCT_HEADER = (
    "schema", "available", "status", "reason", "product_id", "generation_id", "as_of", "source_store",
    "executive_summary", "executive_summary_class", "action_now", "action_now_class",
)
_CLOCK_KEYS = ("as_of", "updated_ts", "observed_at", "created_at", "created_ts", "recorded_at", "ts", "due_at")


def default_cio_root() -> Path:
    env = os.getenv("TRADEAI_CIO_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "data" / "cio"


def _tail_rows(path: Path, max_bytes: int = TAIL_BYTES) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Complete JSON rows from the last ``max_bytes`` of ``path`` plus store facts."""
    facts: dict[str, Any] = {"store": path.name, "present": path.is_file(), "bytes": 0, "window_bytes": 0, "complete": True}
    if not facts["present"]:
        return [], facts
    size = path.stat().st_size
    facts.update(bytes=size, window_bytes=min(size, max_bytes), complete=size <= max_bytes)
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()  # drop the partial first line
        raw = fh.read().decode("utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, facts


def _clock(row: dict[str, Any]) -> Optional[str]:
    for key in _CLOCK_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _block(rows: list[dict[str, Any]], facts: dict[str, Any], limit: int) -> dict[str, Any]:
    clocks = [c for c in (_clock(r) for r in rows) if c]
    state = "MISSING" if not facts["present"] else ("EMPTY" if not rows else "PRESENT")
    return {
        **facts,
        "state": state,
        "rows_in_window": len(rows),
        "rows": rows[-max(1, int(limit)):][::-1],
        "source_as_of": max(clocks) if clocks else None,
        "authority": AUTHORITY,
    }


def recent_outcome_checkpoints(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "outcome_checkpoints.jsonl")
    return _block([r for r in rows if r.get("schema") == CHECKPOINT_SCHEMA], facts, limit)


def recent_outcome_observations(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "outcome_observations.jsonl")
    return _block([r for r in rows if r.get("schema") == SCHEMA_OUTCOME], facts, limit)


def recent_thesis_revisions(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "thesis_revision_ledger.jsonl")
    return _block([r for r in rows if r.get("schema") == REVISION_SCHEMA], facts, limit)


def recent_thesis_change_cards(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "thesis_change_cards.jsonl")
    return _block([r for r in rows if r.get("schema") == THESIS_CHANGE_SCHEMA], facts, limit)


def recent_instrument_records(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "cio_instrument_records.jsonl")
    return _block([r for r in rows if r.get("schema") == INSTRUMENT_RECORD_SCHEMA], facts, limit)


def recent_instrument_beliefs(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Belief blocks carried on instrument records (``beliefs[]``), newest record first."""
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "cio_instrument_records.jsonl")
    beliefs: list[dict[str, Any]] = []
    for record in rows:
        for belief in record.get("beliefs") or []:
            if isinstance(belief, dict) and belief.get("schema") == BELIEF_SCHEMA:
                beliefs.append({**belief, "subject_key": record.get("subject_key")})
    return _block(beliefs, facts, limit)


def _latest_json(path: Path) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    facts: dict[str, Any] = {"store": path.name, "present": path.is_file(), "bytes": 0, "window_bytes": 0, "complete": True}
    if not facts["present"]:
        return None, facts
    facts.update(bytes=path.stat().st_size, window_bytes=path.stat().st_size)
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None, {**facts, "error": "UNPARSEABLE"}
    return (doc if isinstance(doc, dict) else None), facts


def latest_belief_writer_receipt(root: Path | str | None = None) -> dict[str, Any]:
    doc, facts = _latest_json(Path(root or default_cio_root()) / "instrument_belief_latest.json")
    if not doc or doc.get("schema") != BELIEF_WRITER_SCHEMA:
        return {**facts, "state": "MISSING" if not facts["present"] else "EMPTY", "receipt": None, "authority": AUTHORITY}
    return {**facts, "state": "PRESENT", "receipt": doc, "source_as_of": _clock(doc), "authority": AUTHORITY}


def latest_held_thesis_coverage(root: Path | str | None = None) -> dict[str, Any]:
    doc, facts = _latest_json(Path(root or default_cio_root()) / "held_thesis_coverage_latest.json")
    if not doc or doc.get("schema") != HELD_COVERAGE_SCHEMA:
        return {**facts, "state": "MISSING" if not facts["present"] else "EMPTY", "report": None, "authority": AUTHORITY}
    return {**facts, "state": "PRESENT", "report": doc, "source_as_of": _clock(doc), "authority": AUTHORITY}


def recent_reassessments(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "cio_reassessments.jsonl")
    return _block([r for r in rows if r.get("schema") == REASSESS_SCHEMA], facts, limit)


def recent_lesson_binds(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "cio_lesson_binds.jsonl")
    return _block([r for r in rows if r.get("schema") == LESSON_BIND_SCHEMA], facts, limit)


def recent_linked_feedback(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Operator feedback linked to decisions (POST /api/v3/cio/brain/feedback)."""
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "cio_linked_feedback.jsonl")
    return _block([r for r in rows if r.get("schema") == FEEDBACK_SCHEMA], facts, limit)


def recent_feedback_ingests(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """What explicit conversational feedback became (AgentEpisode + PreferenceCandidate)."""
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "preference_candidates.jsonl")
    return _block([r for r in rows if r.get("schema") == FEEDBACK_INGEST_SCHEMA], facts, limit)


def goal_predicates(root: Path | str | None = None, limit: int = 24) -> dict[str, Any]:
    """Goals in the rebuildable goal projection whose predicate carries GoalPredicate@v1."""
    doc, facts = _latest_json(Path(root or default_cio_root()) / "cio_goals_projection.json")
    goals = (doc or {}).get("goals") or {}
    rows: list[dict[str, Any]] = []
    for goal in (goals.values() if isinstance(goals, dict) else goals):
        predicate = goal.get("predicate") if isinstance(goal, dict) else None
        if isinstance(predicate, dict) and predicate.get("schema") == PREDICATE_SCHEMA:
            rows.append({
                "goal_id": goal.get("goal_id"), "owner_agent": goal.get("owner_agent"),
                "status": goal.get("status"), "last_outcome": goal.get("last_outcome"),
                "due_ts": goal.get("due_ts"), "as_of": goal.get("last_wake_ts") or goal.get("created_ts"),
                "predicate": predicate,
            })
    block = _block(rows, facts, limit)
    block["goal_count"] = (doc or {}).get("goal_count")
    block["projection_updated_ts"] = (doc or {}).get("updated_ts")
    return block


def goal_predicate_verdicts(root: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Predicate verdicts recorded by the material-change goal pilot (result.rows[].verdict)."""
    rows, facts = _tail_rows(Path(root or default_cio_root()) / "goal_pilot_material_change.jsonl")
    verdicts: list[dict[str, Any]] = []
    for row in rows:
        for item in ((row.get("result") or {}).get("rows") or []):
            verdict = item.get("verdict") if isinstance(item, dict) else None
            if isinstance(verdict, dict) and verdict.get("schema") == GOAL_VERDICT_SCHEMA:
                verdicts.append({**verdict, "goal_id": item.get("goal_id"), "as_of": row.get("as_of") or row.get("ts")})
    return _block(verdicts, facts, limit)


def operator_product_envelope(root: Path | str | None = None) -> dict[str, Any]:
    """Header of the persisted CIOOperatorProduct@v1 envelope (cio_operator_product.json):
    status, ids, clock, executive summary and action-now line, plus decision counts.
    The full decisions list is rendered via home.operator_product."""
    doc, facts = _latest_json(Path(root or default_cio_root()) / "cio_operator_product.json")
    if not doc or doc.get("schema") != OPERATOR_PRODUCT_SCHEMA:
        return {**facts, "state": "MISSING" if not facts["present"] else "EMPTY", "envelope": None, "authority": AUTHORITY}
    header = {k: doc.get(k) for k in _OPERATOR_PRODUCT_HEADER}
    header["decisions_n"] = len(doc.get("decisions") or [])
    header["standing_decisions_n"] = len(doc.get("standing_decisions") or [])
    return {**facts, "state": "PRESENT", "envelope": header, "source_as_of": doc.get("as_of"), "authority": AUTHORITY}
