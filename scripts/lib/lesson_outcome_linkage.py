"""lesson_outcome_linkage — bind a lesson to the settled outcomes of the plan it came from.

LQ-20261107-1884 root cause 3: 2,309 CASE_SUMMARY_CONTEXT lessons carried
``supporting_outcome_ids: []`` because ``outcome_to_lesson.candidates_from_case_summaries``
stamps the field empty (it is not outcome evidence). The plan a case summary was written
about, however, *does* settle: ``outcome_checkpoints.jsonl`` carries ``plan_id`` and, once
the hourly resolver runs, ``status: RESOLVED`` plus an ``outcome_id``. Nothing joined the
two stores, so an outcome such as ``4a8607cf`` (MRVL, resolved 2026-11-11T14:20:04Z) could
not be found from any lesson.

This module is that join, and ONLY that join:

* ``plan_outcome_index(cio_dir)`` — pure: ``plan_id -> [outcome_id, ...]`` from the
  latest row per checkpoint whose status is RESOLVED.
* ``lesson_links(cio_dir)`` — pure: one ``LessonOutcomeLink@v1`` row per
  (lesson_id, outcome_id) for lessons that carry a ``plan_id``.
* ``apply(root, env, apply=True)`` — append-only write of the new rows to
  ``data/cio/lesson_outcome_links.jsonl`` (idempotent on (lesson_id, outcome_id)).

The link is PROVENANCE, never evidence: it does not touch ``supporting_outcome_ids``,
``status``, ``promotion_stage`` or the P2 eligibility rule. A CASE_SUMMARY_CONTEXT lesson
stays ineligible for the promotion queue (``queue_verdict``) whether it links one outcome
or fifty; inventing a directional reading would manufacture a result (outcome_to_lesson
``_direction``). The link makes the chain auditable and answers "which lesson knows about
outcome X" without changing a decision.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No financial action.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "LessonOutcomeLink@v1"
BASIS = "checkpoint_plan_binding"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
#: The outcome checkpoint store is append-only; a full pass is ~53k rows and is cached per
#: (path, size, mtime) so enqueue + digest + the lane do not re-read it three times.
_INDEX_CACHE: dict[tuple[str, int, int], dict[str, list[str]]] = {}


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _cio_dir(root: Path | None, env: dict | None) -> Path:
    env = os.environ if env is None else env
    if env.get("TRADEAI_CIO_DIR"):
        return Path(env["TRADEAI_CIO_DIR"])
    if root is not None:
        return Path(root) / "data" / "cio"
    try:
        from scripts.lib import canonical_store_registry as csr  # type: ignore
        return Path(csr.production_state_root()) / "data" / "cio"
    except Exception:  # noqa: BLE001
        return Path.cwd() / "data" / "cio"


def _rows(path: Path, limit: int = 500_000):
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= limit:
                    break
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def plan_outcome_index(cio_dir: Path) -> dict[str, list[str]]:
    """plan_id -> sorted outcome ids of its RESOLVED checkpoints (latest row per checkpoint)."""
    path = Path(cio_dir) / "outcome_checkpoints.jsonl"
    try:
        st = path.stat()
        key = (str(path), int(st.st_size), int(st.st_mtime_ns))
    except OSError:
        return {}
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    latest: dict[str, dict[str, Any]] = {}
    for row in _rows(path):
        cid = str(row.get("checkpoint_id") or "")
        if cid:
            latest[cid] = {**latest.get(cid, {}), **row}
    index: dict[str, list[str]] = {}
    for row in latest.values():
        if str(row.get("status") or "") != "RESOLVED":
            continue
        oid = str(row.get("outcome_id") or "")
        plan = str(row.get("plan_id") or row.get("decision_id") or "")
        if oid and plan:
            index.setdefault(plan, []).append(oid)
    index = {k: sorted(set(v)) for k, v in index.items()}
    _INDEX_CACHE[key] = index
    return index


def lesson_rows(cio_dir: Path) -> dict[str, dict[str, Any]]:
    """Latest row per lesson_id (the lessons file is append-only with amendments)."""
    out: dict[str, dict[str, Any]] = {}
    for row in _rows(Path(cio_dir) / "lesson_candidates.jsonl"):
        lid = str(row.get("lesson_id") or "")
        if lid:
            out[lid] = {**out.get(lid, {}), **row}
    return out


def linked_by_lesson(cio_dir: Path) -> dict[str, list[str]]:
    """lesson_id -> outcome ids, computed from the two stores (no link file needed)."""
    index = plan_outcome_index(cio_dir)
    out: dict[str, list[str]] = {}
    for lid, row in lesson_rows(cio_dir).items():
        plan = str(row.get("plan_id") or "")
        if plan and index.get(plan):
            out[lid] = list(index[plan])
    return out


def lesson_links(cio_dir: Path) -> list[dict[str, Any]]:
    """One LessonOutcomeLink@v1 row per (lesson_id, outcome_id)."""
    index = plan_outcome_index(cio_dir)
    rows: list[dict[str, Any]] = []
    for lid, row in sorted(lesson_rows(cio_dir).items()):
        plan = str(row.get("plan_id") or "")
        for oid in index.get(plan, []):
            rows.append({
                "schema": SCHEMA,
                "lesson_id": lid,
                "plan_id": plan,
                "outcome_id": oid,
                "basis": BASIS,
                "task_class": row.get("task_class"),
                "authority": AUTHORITY,
                "memory_behavior_influence": MBI,
            })
    return rows


def links_path(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TRADEAI_LESSON_OUTCOME_LINKS_PATH"):
        return Path(env["TRADEAI_LESSON_OUTCOME_LINKS_PATH"])
    return _cio_dir(root, env) / "lesson_outcome_links.jsonl"


def state(root: Path | None = None, env: dict | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    env = os.environ if env is None else env
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _rows(links_path(root, env)):
        lid, oid = str(row.get("lesson_id") or ""), str(row.get("outcome_id") or "")
        if lid and oid:
            out[(lid, oid)] = row
    return out


def apply(root: Path | None = None, env: dict | None = None, *, apply: bool = False) -> dict[str, Any]:
    """Append the links not yet present. Dry run by default."""
    env = os.environ if env is None else env
    cio = _cio_dir(root, env)
    computed = lesson_links(cio)
    existing = state(root, env)
    new = [r for r in computed if (r["lesson_id"], r["outcome_id"]) not in existing]
    written = 0
    path = links_path(root, env)
    if apply and new:
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = _now_iso()
        with path.open("a", encoding="utf-8") as fh:
            for row in new:
                fh.write(json.dumps({**row, "ts": ts}, sort_keys=True, default=str) + "\n")
                written += 1
    lessons = {r["lesson_id"] for r in computed}
    return {
        "schema": "LessonOutcomeLinkRun@v1",
        "applied": bool(apply),
        "lessons_with_plan": len(lesson_rows(cio)),
        "lessons_linked": len(lessons),
        "links_computed": len(computed),
        "links_existing": len(existing),
        "links_new": len(new),
        "written": written,
        "path": str(path),
        "sample": new[:5],
    }
