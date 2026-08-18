"""Nightly reflection — propose only.

Consumes *materialized* production cases (disposition + note + outcome on
one case_id) and writes candidate lessons / hypotheses / unresolved
contradictions. Never mutates production config or ratifies itself.

Never auto-scores OPEN rows. Never auto-ratifies. auto_promotions=0.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_production_case import materialize_cases

AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "cio" / "cio_reflection_candidates.json"
HISTORY_PATH = PROJECT_ROOT / "data" / "cio" / "cio_reflection_candidates.jsonl"
# Legacy alias — do not write pretty JSON to this path.
OUT_PATH = HISTORY_PATH

LESSON_STATES = (
    "CANDIDATE", "RATIFIED", "DISPUTED", "DEPRECATED", "SUPERSEDED", "REJECTED",
)


def _is_scored(case: dict[str, Any]) -> bool:
    darwin = case.get("darwin") or {}
    if not isinstance(darwin, dict):
        return False
    if darwin.get("eligible") is True:
        return True
    return str(darwin.get("darwin_status") or "").upper() == "SCORED"


def resolve_journal_paths(out_path: Optional[Path] = None) -> tuple[Path, Path]:
    """Return (snapshot.json, history.jsonl). Never the same file."""
    if out_path is None:
        return SNAPSHOT_PATH, HISTORY_PATH
    p = Path(out_path)
    if p.suffix == ".jsonl":
        return p.with_suffix(".json"), p
    if p.suffix == ".json":
        return p, p.with_name(p.stem + ".jsonl")
    return p.with_suffix(".json"), p.with_suffix(".jsonl")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def extract_last_valid_jsonl_record(path: Path) -> Optional[dict[str, Any]]:
    """Best-effort recover of the last compact JSON object from a malformed file."""
    if not path.is_file():
        return None
    last = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line in ("{", "}"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last = obj
    return last


def persist_reflection(rec: dict[str, Any], *, snapshot_path: Path, history_path: Path) -> None:
    """Atomically replace snapshot JSON and append exactly one compact JSONL row."""
    if snapshot_path.resolve() == history_path.resolve():
        raise ValueError("snapshot and history must be distinct paths")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(snapshot_path, json.dumps(rec, indent=2, default=str) + "\n")
    line = json.dumps(rec, sort_keys=True, default=str, separators=(",", ":")) + "\n"
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def reflect(*, cases_path: Optional[Path] = None, out_path: Optional[Path] = None) -> dict[str, Any]:
    cases = materialize_cases(path=cases_path)
    proposals: list[dict[str, Any]] = []
    scored = 0
    for c in cases:
        if _is_scored(c):
            scored += 1
        disp = c.get("operator_disposition")
        note = c.get("note") or ""
        outcome = c.get("outcome")
        cid = c.get("case_id")
        did = c.get("decision_id")
        if disp and note and outcome:
            proposals.append({
                "kind": "candidate_lesson",
                "state": "CANDIDATE",
                "text": f"Case {cid} has disposition, note, and outcome on one case.",
                "decision_id": did,
                "case_id": cid,
                "operator_disposition": disp,
                "disposition": disp,
                "note": note,
                "outcome": outcome,
            })
        elif disp and not outcome:
            proposals.append({
                "kind": "unresolved_contradiction",
                "state": "CANDIDATE",
                "text": f"Case {cid} has disposition but no outcome window.",
                "decision_id": did,
                "case_id": cid,
            })
        if str((c.get("research") or {}).get("decision_use_audit", {}).get("status")) == "UNAVAILABLE":
            proposals.append({
                "kind": "candidate_lesson",
                "state": "CANDIDATE",
                "text": "Retrieval-before-reasoning missing — record MEMORY_NOT_CONSULTED.",
                "decision_id": did,
                "case_id": cid,
            })
        if c.get("auto_promoted"):
            proposals.append({
                "kind": "unresolved_contradiction",
                "state": "DISPUTED",
                "text": "auto_promoted=true is forbidden; human ratify required.",
                "decision_id": did,
                "case_id": cid,
            })
        if c.get("challenge") and not c.get("review"):
            proposals.append({
                "kind": "unresolved_contradiction",
                "state": "CANDIDATE",
                "text": f"Case {cid} has a thesis challenge without a review result.",
                "decision_id": did,
                "case_id": cid,
            })
    rec = {
        "at": datetime.now(timezone.utc).isoformat(),
        "cases_seen": len(cases),
        "scored": scored,
        "proposals": proposals,
        "joined_cases": [
            {
                "case_id": c.get("case_id"),
                "decision_id": c.get("decision_id"),
                "status": c.get("status"),
                "operator_disposition": c.get("operator_disposition"),
                "note": c.get("note"),
                "notes": c.get("notes"),
                "outcome": c.get("outcome"),
                "darwin": c.get("darwin"),
            }
            for c in cases
        ],
        "mutates_production": False,
        "auto_promotions": 0,
        "authority": AUTHORITY,
    }
    snapshot_path, history_path = resolve_journal_paths(out_path)
    persist_reflection(rec, snapshot_path=snapshot_path, history_path=history_path)
    return rec


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: read-only reflection. Never auto-promotes."""
    import argparse
    p = argparse.ArgumentParser(description="CIO nightly reflection (READ_ONLY_ADVISORY)")
    p.add_argument("--cases-path", default=None)
    p.add_argument("--out-path", default=None)
    args = p.parse_args(argv)
    rec = reflect(
        cases_path=Path(args.cases_path) if args.cases_path else None,
        out_path=Path(args.out_path) if args.out_path else None,
    )
    summary = {
        "at": rec.get("at"),
        "cases_seen": rec.get("cases_seen"),
        "scored": rec.get("scored"),
        "proposal_count": len(rec.get("proposals") or []),
        "auto_promotions": rec.get("auto_promotions"),
        "mutates_production": rec.get("mutates_production"),
        "authority": rec.get("authority"),
    }
    print(json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
