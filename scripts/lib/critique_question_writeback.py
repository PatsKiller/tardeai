"""Critique → InstrumentRecord next_research_question writeback (M2).

AGENTS.md §15 M2: a critique verdict must change ``next_research_question`` on
the live InstrumentRecord — not only log beside it. L3 historically persisted
AgentView rows while leaving the record untouched, and wake selection never
picked InstrumentRecord subjects (0 overlap measured 2026-09-19).

This module:
  * resolves a subject_key (prefer selection source_id for instrument_record_due)
  * applies cognition via ``apply_cognition`` (MBI_BEHAVIOR=0 still enforced)
  * appends a durable evidence row for the maturity bar

Fail-soft: missing record / no question change → reported, never raised.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

SCHEMA = "CritiqueQuestionWriteback@v1"
ARTIFACT_REL = Path("data/cio/wake_critique_question.jsonl")
SOURCE_INSTRUMENT_RECORD = "instrument_record_due"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _persistent_records_path() -> Path:
    shared = (
        Path.home()
        / "trade-ai-releases"
        / "persistent-state"
        / "data"
        / "cio"
        / "cio_instrument_records.jsonl"
    )
    if shared.is_file():
        return shared
    return Path("data/cio/cio_instrument_records.jsonl")


def _artifact_path(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root) / ARTIFACT_REL
    shared = (
        Path.home()
        / "trade-ai-releases"
        / "persistent-state"
        / "data"
        / "cio"
        / "wake_critique_question.jsonl"
    )
    # Prefer the served persistent-state tree when present.
    shared.parent.mkdir(parents=True, exist_ok=True)
    return shared


def extract_question_delta(
    critique: Mapping[str, Any] | None,
    author: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return {verdict, before, after, critique_id} for next_research_question."""
    critique = critique or {}
    author = author or {}
    verdict = str(critique.get("verdict") or "").strip().lower()
    critique_id = critique.get("critique_id")
    before = None
    after = None
    for ch in critique.get("field_changes") or []:
        if not isinstance(ch, Mapping):
            continue
        if str(ch.get("field") or "") != "next_research_question":
            continue
        before = ch.get("before")
        after = ch.get("after")
        break
    # Accept still mediates writeback when the author named a next question:
    # the critique verdict authorized applying it onto the record.
    if after is None and verdict == "accept":
        after = author.get("next_research_question")
    if after is not None:
        after = str(after).strip() or None
    if before is not None:
        before = str(before).strip() or None
    return {
        "verdict": verdict,
        "before": before,
        "after": after,
        "critique_id": critique_id,
    }


def resolve_subject_key(
    *,
    subject_guid: str | None,
    selection: Mapping[str, Any] | None = None,
    store: Any = None,
) -> Optional[str]:
    """Prefer instrument_record_due source_id; else registry symbol → IR key."""
    selection = selection or {}
    if str(selection.get("source") or "") == SOURCE_INSTRUMENT_RECORD:
        sk = str(selection.get("source_id") or "").strip()
        if sk:
            return sk
    if store is None:
        return None
    guid = str(subject_guid or "").strip()
    if not guid:
        return None
    try:
        from scripts.lib import identity_registry as ir

        doc = ir.load()
        symbols = [
            sym
            for sym, g in (doc.get("by_symbol") or {}).items()
            if g == guid or ir.resolve_guid(doc, g) == guid
        ]
    except Exception:
        return None
    for sym in symbols:
        for kind in ("HELD", "WATCH", "EXIT"):
            sk = f"{kind}:{sym}"
            try:
                if store.load(sk):
                    return sk
            except Exception:
                continue
    return None


def apply_critique_question_writeback(
    *,
    subject_guid: str | None,
    selection: Mapping[str, Any] | None = None,
    critique: Mapping[str, Any] | None = None,
    author: Mapping[str, Any] | None = None,
    store: Any = None,
    artifact_path: Path | str | None = None,
    unattended: bool = True,
) -> dict[str, Any]:
    """Write critique-mediated next_research_question onto InstrumentRecord.

    Returns a receipt dict always (never raises to the wake loop).
    """
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "as_of": _now(),
        "unattended": bool(unattended),
        "applied": False,
        "reason": None,
        "subject_key": None,
        "subject_guid": subject_guid,
        "before": None,
        "after": None,
        "critique_verdict": None,
        "critique_id": None,
    }
    delta = extract_question_delta(critique, author)
    out["critique_verdict"] = delta["verdict"]
    out["critique_id"] = delta["critique_id"]
    out["after"] = delta["after"]
    if not delta["after"]:
        out["reason"] = "no_question_from_critique"
        return out
    if delta["verdict"] not in ("revise", "accept"):
        out["reason"] = f"verdict_not_writeback:{delta['verdict'] or 'empty'}"
        return out

    try:
        from scripts.lib.cio_instrument_record import (
            InstrumentRecordStore,
            apply_cognition,
        )

        if store is None:
            store = InstrumentRecordStore(_persistent_records_path())
        subject_key = resolve_subject_key(
            subject_guid=subject_guid, selection=selection, store=store
        )
        out["subject_key"] = subject_key
        if not subject_key:
            out["reason"] = "no_instrument_record"
            return out
        rec = store.load(subject_key)
        if not rec:
            out["reason"] = "record_missing"
            return out
        before = str(rec.get("next_research_question") or "") or None
        if delta["before"] is not None:
            out["before"] = delta["before"]
        else:
            out["before"] = before
        if (out["before"] or "") == (delta["after"] or ""):
            out["reason"] = "question_unchanged"
            return out
        updated, changed = apply_cognition(
            rec,
            next_research_question=delta["after"],
            strict=False,
        )
        if "next_research_question" not in changed:
            out["reason"] = "cognition_noop"
            return out
        store.upsert(updated)
        out["applied"] = True
        out["reason"] = "persisted"
        out["changed"] = changed
    except Exception as exc:  # noqa: BLE001 — wake fail-soft
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out

    try:
        _append_artifact(out, path=artifact_path)
    except Exception as exc:  # noqa: BLE001
        out["artifact_error"] = f"{type(exc).__name__}: {exc}"
    return out


def _append_artifact(row: dict[str, Any], *, path: Path | str | None = None) -> Path:
    p = Path(path) if path else _artifact_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return p


def latest_applied_writeback(path: Path | str | None = None) -> dict[str, Any] | None:
    """Most recent applied writeback row (for maturity reporter)."""
    p = Path(path) if path else _artifact_path()
    if not p.is_file() or p.stat().st_size == 0:
        return None
    last = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("applied"):
            last = row
    return last
