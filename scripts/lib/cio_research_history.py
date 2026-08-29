"""Prior research outcomes per plan, read from the request stream.

Wave 3D. `ResearchNeedDecision@v2` already fails closed on a prior
`execution_language` outcome — but only if the caller *tells* it. Nothing did:
the dry report built its input from the plan projection alone, so four plans
carrying a prior "execution language not allowed in research output" failure
were presented as eligible for a paid first pass.

A guard that exists but is not wired to its inputs is not a guard. This module
is the wiring.

Read-only over `data/cio/hermes_research_requests.jsonl`; mints nothing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

RESEARCH_HISTORY_SCHEMA = "ResearchHistory@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

REQUESTS_REL = "data/cio/hermes_research_requests.jsonl"

# The worker's error text for a failed execution-language lint. Matching the
# phrase rather than a status keeps this honest when a status is merely
# "failed" for an unrelated reason.
_EXEC_LANG_MARKERS = ("execution language", "execution_language")


def _rows(root: Path | str) -> list[dict[str, Any]]:
    p = Path(root) / REQUESTS_REL
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def history_by_plan(root: Path | str) -> dict[str, dict[str, Any]]:
    """Per-plan prior outcome summary, newest-wins for the terminal state."""
    out: dict[str, dict[str, Any]] = {}
    for row in _rows(root):
        pid = str(row.get("plan_id") or "")
        if not pid:
            continue
        rec = out.setdefault(pid, {
            "plan_id": pid, "events": 0, "statuses": {},
            "research_ids": [], "errors": [],
            "execution_language": False, "completed": False,
        })
        rec["events"] += 1
        st = str(row.get("status") or "")
        if st:
            rec["statuses"][st] = rec["statuses"].get(st, 0) + 1
            if st == "completed":
                rec["completed"] = True
        rid = row.get("research_id")
        if rid and rid not in rec["research_ids"]:
            rec["research_ids"].append(rid)
        err = str(row.get("error") or "")
        if err:
            rec["errors"].append(err[:160])
            if any(m in err.lower() for m in _EXEC_LANG_MARKERS):
                rec["execution_language"] = True
    return out


def prior_outcome_for(plan_id: Any, hist: dict[str, dict[str, Any]]
                      ) -> Optional[str]:
    """Map history to the gate's `prior_outcome` vocabulary.

    execution_language wins over everything: it is a fail-closed state, not one
    signal among several.
    """
    rec = hist.get(str(plan_id or ""))
    if not rec:
        return None
    if rec.get("execution_language"):
        return "execution_language"
    if rec.get("completed"):
        return "VALID"
    if rec.get("statuses", {}).get("failed"):
        return "FAIL"
    return None


def gate_inputs_for(plan_id: Any, hist: dict[str, dict[str, Any]]
                    ) -> dict[str, Any]:
    """The history-derived fields a caller should pass to `decide()`."""
    rec = hist.get(str(plan_id or "")) or {}
    return {
        "prior_outcome": prior_outcome_for(plan_id, hist),
        "prior_artifact_ids": list(rec.get("research_ids") or []),
        "research_id": (rec.get("research_ids") or [None])[-1],
    }
