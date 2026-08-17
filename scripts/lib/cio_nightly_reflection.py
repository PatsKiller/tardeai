"""Nightly reflection — propose only.

Consumes *materialized* production cases (disposition + note + outcome on
one case_id) and writes candidate lessons / hypotheses / unresolved
contradictions. Never mutates production config or ratifies itself.

Never auto-scores OPEN rows. Never auto-ratifies. auto_promotions=0.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_production_case import materialize_cases

AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = PROJECT_ROOT / "data" / "cio" / "cio_reflection_candidates.jsonl"

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
    dest = out_path or OUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    with dest.with_suffix(".jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
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
