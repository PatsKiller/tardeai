"""Bind a lesson + hypothesis to a *bound* outcome checkpoint. Support only.

Wave 3C item 2. After an `OutcomeCheckpoint` whose `plan_binding` is `bound`,
mint a `lesson_id` and a hypothesis and flag the row `REVIEW_READY`.

Three deliberate limits:

  * **Unbound checkpoints mint nothing.** A cash- or dust-bound checkpoint has
    no plan, so a lesson drawn from it would have no subject to be about. It is
    recorded as skipped with a reason, not silently dropped.
  * **Support only.** The hypothesis is a claim awaiting review, never an
    `AGENT_COMMITMENT`. `REVIEW_READY` means a human decides; it does not mean
    the system has decided and is informing anyone.
  * **MBI stays 0.** Nothing here feeds sizing or action. A lesson is a note.

Complements `outcome_to_lesson.py` (candidate generation from observations);
this is the narrower checkpoint→lesson binding step.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LESSON_BIND_SCHEMA = "LessonBind@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

BOUND = "bound"
REVIEW_READY = "REVIEW_READY"

# Statuses this module may never emit. An AGENT_COMMITMENT would turn an
# observation into a promise the system then acts on.
FORBIDDEN_STATUSES = frozenset({"AGENT_COMMITMENT", "COMMITTED", "ACTIONABLE"})


def lesson_id(plan_id: Any, checkpoint_id: Any) -> str:
    raw = f"{plan_id}|{checkpoint_id}"
    return "lsn_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_bound(checkpoint: dict[str, Any]) -> bool:
    """A checkpoint is bound when it names a plan, not merely a binding."""
    if not str(checkpoint.get("plan_id") or "").strip():
        return False
    binding = str(checkpoint.get("plan_binding") or BOUND).strip().lower()
    return binding == BOUND


def bind(checkpoint: dict[str, Any], *,
         observation: Optional[dict[str, Any]] = None,
         now: Optional[datetime] = None) -> dict[str, Any]:
    """Return a lesson binding, or a skip record for an unbound checkpoint."""
    ts = (now or datetime.now(timezone.utc)).isoformat()
    cid = checkpoint.get("checkpoint_id")
    pid = checkpoint.get("plan_id")

    if not is_bound(checkpoint):
        return {
            "schema": LESSON_BIND_SCHEMA,
            "bound": False,
            "lesson_id": None,
            "hypothesis": None,
            "checkpoint_id": cid,
            "plan_id": pid,
            "skip_reason": "checkpoint_not_plan_bound",
            "plan_binding": checkpoint.get("plan_binding"),
            "as_of": ts,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
        }

    obs = observation or {}
    horizon = checkpoint.get("horizon")
    subject = obs.get("symbol") or checkpoint.get("symbol")
    hypothesis = {
        "hypothesis_id": "hyp_" + lesson_id(pid, cid)[4:],
        # Phrased as a question under review, never as a finding to apply.
        "claim": (f"Outcome at {horizon} for plan {pid}"
                  + (f" ({subject})" if subject else "")
                  + " is consistent with the thesis recorded at decision time."),
        "status": REVIEW_READY,
        "support_only": True,
        "evidence_refs": list(obs.get("evidence_refs") or []),
        "requires_human_review": True,
    }
    return {
        "schema": LESSON_BIND_SCHEMA,
        "bound": True,
        "lesson_id": lesson_id(pid, cid),
        "hypothesis": hypothesis,
        "checkpoint_id": cid,
        "plan_id": pid,
        "horizon": horizon,
        "review_flag": REVIEW_READY,
        "as_of": ts,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def validate(row: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if row.get("schema") != LESSON_BIND_SCHEMA:
        problems.append("wrong_schema")
    if row.get("memory_behavior_influence") != 0:
        problems.append("mbi_must_be_zero")
    hyp = row.get("hypothesis") or {}
    if hyp:
        if hyp.get("status") in FORBIDDEN_STATUSES:
            problems.append("forbidden_status")
        if hyp.get("support_only") is not True:
            problems.append("hypothesis_must_be_support_only")
    if row.get("bound") and not row.get("lesson_id"):
        problems.append("bound_without_lesson_id")
    if not row.get("bound") and row.get("lesson_id"):
        problems.append("unbound_must_not_mint_lesson")
    return problems


STORE_REL = "data/cio/cio_lesson_binds.jsonl"


def store_path(root: Path | str) -> Path:
    return Path(root) / STORE_REL


def persist(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    """Append a lesson bind. An unbound checkpoint is recorded, not minted.

    The skip record is written too: "we looked and there was nothing to bind"
    is evidence, and dropping it silently is how a coverage number quietly
    becomes unverifiable.
    """
    problems = validate(row)
    if problems:
        return {"wrote": False, "problems": problems}
    p = store_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"wrote": True, "path": str(p), "lesson_id": row.get("lesson_id")}
