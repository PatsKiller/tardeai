"""The need ledger — what a goal still does not know, per lap (P5).

WHY
---
Measured 2026-09-16 on the live stores: `GOAL_STATUS_CHANGED` is 0 against 34,704
wakes over 37 days, and `success_criteria` is empty on all three goals. The runtime
records *that a lap ran*; nothing anywhere records *what the lap still needs*. So a
goal cannot be shown to be converging, a second lap cannot be aimed at the gap the
first one left, and "done" is indistinguishable from "ran again".

`research_circle.score_lap()` already computes exactly that missing thing — a score
per operator sub-question, which of them are unanswered, which publishers spoke to
each, and where the evidence contradicts itself. It computes it and throws it away
when the lap ends.

This module is a PROJECTION of that existing computation, not a second scorer. It
re-derives nothing: `score_lap` decides, and every number here is copied from its
output. If the two ever disagree, `score_lap` is right and this module has a bug.

KEY
---
`(goal_id, predicate_version, lap)`. `predicate_version` is supplied by the caller
and defaults to `DEFAULT_PREDICATE_VERSION`: the goal predicate (`GOAL_PREDICATE_SET`)
is a later phase, and this ledger must not mint an identity of its own that the
predicate would then have to migrate. No sixth ID scheme — the goal_id is the
`cio_goals` id and the lap is the research circle's own lap number.

`need_digest()` is the outstanding-need fingerprint. A lap that closes a need or
lands new evidence changes it; a lap that learns nothing leaves it identical. That
is the signal a producer needs to decide whether another lap is new work or a repeat,
and it is why this ledger is a prerequisite for a goal that can terminate.

AUTHORITY: READ_ONLY_ADVISORY. Projection and receipts only. MBI_BEHAVIOR = 0 —
nothing here sizes, orders, stops, weights, or writes to a broker. Append-only:
rows are added, never rewritten and never removed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOGoalNeedLedger@v1"
NEED_LEDGER_PATH = PROJECT_ROOT / "data" / "cio" / "cio_goal_need_ledger.jsonl"

#: Until GOAL_PREDICATE_SET exists, every row carries this. Callers that have a
#: real predicate version pass it; nothing here invents one.
DEFAULT_PREDICATE_VERSION = "v0"  # canonical: matches goal_generation.
#: PREDICATE_VERSION_FALLBACK and P2's `v{int}` identity rendering. P4 and P5 were
#: briefed separately and independently chose "v0" and "v0-unset" for the SAME
#: condition (a goal with no GOAL_PREDICATE_SET yet), which would key the generation
#: token, this ledger row and the budget bucket under different strings for one
#: goal-lap -- the five-identities-no-join-key defect this plan exists to remove,
#: reintroduced. Pinned by test_predicate_version_is_canonical_across_modules.

#: A need at or above this scores as answered. Same threshold `deterministic_decision`
#: uses for `missing_facts`, referenced rather than re-chosen.
ANSWERED_AT = 40


def ledger_key(goal_id: str, predicate_version: str, lap: int) -> str:
    """The row's identity. Pure."""
    return f"{goal_id}|{predicate_version}|{int(lap)}"


def project_needs(score: dict[str, Any]) -> list[dict[str, Any]]:
    """`score_lap`'s `per_need`, flattened into ledger rows. Pure, and derivative.

    Every field is copied from `score_lap`. `open` is the only thing computed here,
    and it is the same comparison `deterministic_decision` makes when it builds
    `missing_facts` — so the two can never disagree about what is outstanding.
    """
    out: list[dict[str, Any]] = []
    for need, v in sorted((score.get("per_need") or {}).items()):
        out.append({
            "need": need,
            "score": v.get("score", 0),
            "open": v.get("score", 0) < ANSWERED_AT,
            "fresh_items": v.get("fresh_items", 0),
            "stale_only": bool(v.get("stale_only")),
            # Publishers, not retrieval channels. See research_circle.publisher_host.
            "publishers": list(v.get("sources") or []),
            "independence_keys": list(v.get("independence_keys") or []),
            "corroborated": bool(v.get("corroborated")),
        })
    return out


def need_digest(needs: Iterable[dict[str, Any]]) -> str:
    """Fingerprint of what is still outstanding. Pure and order-independent.

    Covers the open needs and, for each, how many distinct publishers have spoken
    and whether they corroborate. A lap that finds a new publisher for an open need
    changes the digest even though the need is still open — that is progress, and a
    producer keyed on this digest will allow the next lap. A lap that finds nothing
    leaves it byte-identical, which is what makes "no new evidence" detectable.
    """
    material = sorted(
        (str(n.get("need")), bool(n.get("open")), len(n.get("publishers") or []), bool(n.get("corroborated")))
        for n in needs
    )
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_row(
    goal_id: str,
    score: dict[str, Any],
    *,
    lap: int,
    predicate_version: str = DEFAULT_PREDICATE_VERSION,
    decision: Optional[dict[str, Any]] = None,
    question_guid: Optional[str] = None,
    subject_guids: Optional[dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """One ledger row projecting one lap. Pure — builds, never writes."""
    now = now or datetime.now(timezone.utc)
    needs = project_needs(score)
    decision = decision or {}
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "key": ledger_key(goal_id, predicate_version, lap),
        "goal_id": goal_id,
        "predicate_version": predicate_version,
        "lap": int(lap),
        "ts": now.isoformat(),
        "question_guid": question_guid,
        "subject_guids": dict(subject_guids or {}),
        "overall": score.get("overall"),
        "maturity": score.get("maturity"),
        "weakest_need": score.get("weakest_need"),
        "per_need": needs,
        "open_needs": [n["need"] for n in needs if n["open"]],
        # score_lap's own words for what is missing, carried through unmodified.
        "missing_facts": list(decision.get("missing_facts") or []),
        "contradictions": list(score.get("contradictions") or []),
        "corroboration": dict(score.get("corroboration") or {}),
        "decision": decision.get("decision"),
        "next_channel": decision.get("next_channel"),
        "need_digest": need_digest(needs),
    }


class NeedLedger:
    """Append-only need rows keyed by (goal_id, predicate_version, lap).

    Dry-run by default, like `research_circle.Ledger`: a lap that is not applied
    leaves no trace on disk. Rows are appended and never rewritten — a corrected
    lap is a NEW row for the same key, and `latest()` reads the last one.
    """

    def __init__(self, path: Path = NEED_LEDGER_PATH, *, apply: bool = False):
        self.path = Path(path)
        self.apply = apply
        self.rows: list[dict[str, Any]] = []

    def record(self, goal_id: str, score: dict[str, Any], *, lap: int,
               predicate_version: str = DEFAULT_PREDICATE_VERSION, **fields: Any) -> dict[str, Any]:
        row = build_row(goal_id, score, lap=lap, predicate_version=predicate_version, **fields)
        self.rows.append(row)
        if self.apply:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                # allow_nan=False: a NaN serialises to a bare token that the
                # downstream JSON readers reject, which silently destroys the
                # write. Refuse to emit one instead.
                fh.write(json.dumps(row, default=str, allow_nan=False) + "\n")
        return row

    def read(self, goal_id: Optional[str] = None,
             predicate_version: Optional[str] = None) -> list[dict[str, Any]]:
        """Every row on disk, oldest first, optionally narrowed. Never raises on a
        damaged line: a partial write must not hide the rows written before it."""
        out: list[dict[str, Any]] = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return out
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if goal_id is not None and row.get("goal_id") != goal_id:
                continue
            if predicate_version is not None and row.get("predicate_version") != predicate_version:
                continue
            out.append(row)
        return out

    def latest(self, goal_id: str, predicate_version: str = DEFAULT_PREDICATE_VERSION) -> Optional[dict[str, Any]]:
        """The most recent row for the goal, or None. Append-only means last wins."""
        rows = self.read(goal_id, predicate_version)
        return rows[-1] if rows else None


__all__ = ["ANSWERED_AT", "AUTHORITY", "DEFAULT_PREDICATE_VERSION", "NEED_LEDGER_PATH", "NeedLedger",
           "SCHEMA", "build_row", "ledger_key", "need_digest", "project_needs"]
