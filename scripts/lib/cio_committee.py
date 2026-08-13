"""CIO Advisory Committee — deterministic specialist committee under a chair.

Phase 4. Alex (CIO) is the CHAIR and sole producer of the final investment
recommendation. Morgan (CWO), Steph, Maria, Guardian (risk), and Ledger (tax)
are MEMBERS who cast advisory votes. This module computes the committee result
deterministically: quorum, consensus direction, dissent, and the fail-closed
defense veto.

Pure, provider-call-free. No broker/order/stop/2FA authority. No writes.

Vote vocabulary (member level) mirrors cio_advisory_schema.SpecialistAdvisoryPosition:
  SUPPORT, OPPOSE, NEUTRAL, DEFER, INSUFFICIENT_EVIDENCE

Consensus outcome:
  UNANIMOUS_SUPPORT   — all actionable votes SUPPORT
  UNANIMOUS_OPPOSE    — all actionable votes OPPOSE
  CONSENSUS_SUPPORT   — >=2/3 SUPPORT, no blocking dissent
  CONSENSUS_OPPOSE    — >=2/3 OPPOSE, no blocking dissent
  CONSENSUS_NEUTRAL   — no actionable votes (all NEUTRAL/DEFER/INSUFFICIENT)
  MIXED               — actionable SUPPORT and OPPOSE both present
  BLOCKED_QUORUM      — fewer than quorum members cast a decision
  BLOCKED_DEFENSE     — a blocking office (Guardian) cast OPPOSE
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Vote / position vocabulary ────────────────────────────────────────────────

POSITION_SUPPORT = "SUPPORT"
POSITION_OPPOSE = "OPPOSE"
POSITION_NEUTRAL = "NEUTRAL"
POSITION_DEFER = "DEFER"
POSITION_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

VALID_VOTE_POSITIONS = frozenset({
    POSITION_SUPPORT,
    POSITION_OPPOSE,
    POSITION_NEUTRAL,
    POSITION_DEFER,
    POSITION_INSUFFICIENT_EVIDENCE,
})

# A member vote that signals intent to act or not (DEFER/INSUFFICIENT are neither).
ACTIONABLE_VOTES = frozenset({POSITION_SUPPORT, POSITION_OPPOSE})

# Offices with veto authority over an execution-leaning position.
BLOCKING_OFFICES = frozenset({"guardian", "risk_agent"})

# Office map for display + blocking determination (member_id -> office).
OFFICE_BY_MEMBER = {
    "alex": "Chief Investment Officer (Chair)",
    "morgan": "Chief Wealth Officer",
    "steph": "Senior Portfolio & Wealth Strategist",
    "maria": "Research Director",
    "guardian": "Independent Risk Officer",
    "risk_agent": "Independent Risk Officer",
    "ledger": "Tax & Account-Constraint Specialist",
    "tax_agent": "Tax & Account-Constraint Specialist",
}

DEFAULT_QUORUM = 3
CONSENSUS_RATIO = 2.0 / 3.0


@dataclass
class CommitteeVote:
    """One member's advisory vote. member_id and position are required."""

    member_id: str
    position: str
    confidence: float = 0.5
    rationale: str = ""
    office: str = ""

    def __post_init__(self) -> None:
        self.member_id = (self.member_id or "").strip().lower()
        if self.position not in VALID_VOTE_POSITIONS:
            raise ValueError(
                f"Invalid vote position {self.position!r}; "
                f"expected one of {sorted(VALID_VOTE_POSITIONS)}"
            )
        if not self.office:
            self.office = OFFICE_BY_MEMBER.get(self.member_id, "Specialist")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    @property
    def is_actionable(self) -> bool:
        return self.position in ACTIONABLE_VOTES

    @property
    def is_blocking_office(self) -> bool:
        return self.member_id in BLOCKING_OFFICES or self.office.lower().startswith("independent risk")

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "office": self.office,
            "position": self.position,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


def vote(member_id: str, position: str, *, confidence: float = 0.5,
         rationale: str = "", office: str = "") -> CommitteeVote:
    """Convenience constructor for a committee vote."""
    return CommitteeVote(
        member_id=member_id,
        position=position,
        confidence=confidence,
        rationale=rationale,
        office=office,
    )


def vote_from_specialist_advisory(advisory: Any) -> CommitteeVote:
    """Map a frozen SpecialistAdvisory (cio_advisory_schema) to a committee vote.

    Accepts either a SpecialistAdvisory dataclass or a dict carrying
    `specialist_id` and `position`. The specialist position vocabulary
    (SUPPORT/OPPOSE/NEUTRAL/DEFER/INSUFFICIENT_EVIDENCE) is a 1:1 subset of the
    committee vocabulary, so no translation is needed beyond normalization.
    """
    if hasattr(advisory, "specialist_id") and hasattr(advisory, "position"):
        member_id = str(advisory.specialist_id)
        position = advisory.position
        if hasattr(position, "value"):
            position = position.value
        confidence = float(getattr(advisory, "confidence", 0.5) or 0.5)
        rationale = str(getattr(advisory, "rationale", "") or "")
    elif isinstance(advisory, dict):
        member_id = str(advisory.get("specialist_id") or advisory.get("member_id") or "")
        position = str(advisory.get("position") or "")
        confidence = float(advisory.get("confidence") or 0.5)
        rationale = str(advisory.get("rationale") or "")
    else:
        raise TypeError("expected a SpecialistAdvisory or dict with specialist_id/position")

    return vote(member_id, position, confidence=confidence, rationale=rationale)


@dataclass
class CommitteeResult:
    """Deterministic outcome of convening the committee."""

    consensus: str
    quorum_met: bool
    actionable: bool
    tally: dict[str, int] = field(default_factory=dict)
    votes: list[CommitteeVote] = field(default_factory=list)
    dissenters: list[str] = field(default_factory=list)
    material_disagreements: list[str] = field(default_factory=list)
    blocking_vetoes: list[str] = field(default_factory=list)
    quorum: int = DEFAULT_QUORUM

    def to_dict(self) -> dict[str, Any]:
        return {
            "consensus": self.consensus,
            "quorum_met": self.quorum_met,
            "actionable": self.actionable,
            "quorum": self.quorum,
            "tally": dict(self.tally),
            "votes": [v.to_dict() for v in self.votes],
            "dissenters": list(self.dissenters),
            "material_disagreements": list(self.material_disagreements),
            "blocking_vetoes": list(self.blocking_vetoes),
        }


def convene(
    votes: list[CommitteeVote],
    *,
    quorum: int = DEFAULT_QUORUM,
) -> CommitteeResult:
    """Convene the committee and compute consensus deterministically.

    Rules (fail-closed):
      1. Votes from blocking offices (Guardian) are counted, and any OPPOSE
         veto from such an office hard-blocks the decision.
      2. Fewer than `quorum` decision votes (SUPPORT/OPPOSE/NEUTRAL) → BLOCKED_QUORUM.
      3. DEFER / INSUFFICIENT_EVIDENCE are non-actionable; they do not count toward
         quorum but are recorded and surface as material disagreements when they
         co-occur with an actionable majority.
      4. A SUPPORT + OPPOSE split that is not a super-majority is MIXED.
    """
    if quorum < 1:
        raise ValueError("quorum must be >= 1")

    tally = {p: 0 for p in VALID_VOTE_POSITIONS}
    for v in votes:
        tally[v.position] = tally.get(v.position, 0) + 1

    decision_votes = [
        v for v in votes
        if v.position in (POSITION_SUPPORT, POSITION_OPPOSE, POSITION_NEUTRAL)
    ]
    support = [v for v in votes if v.position == POSITION_SUPPORT]
    oppose = [v for v in votes if v.position == POSITION_OPPOSE]
    defer_or_insufficient = [
        v for v in votes
        if v.position in (POSITION_DEFER, POSITION_INSUFFICIENT_EVIDENCE)
    ]

    blocking_vetoes = [
        v.member_id for v in oppose if v.is_blocking_office
    ]

    # 1. Quorum
    if len(decision_votes) < quorum:
        return CommitteeResult(
            consensus="BLOCKED_QUORUM",
            quorum_met=False,
            actionable=False,
            tally=tally,
            votes=list(votes),
            material_disagreements=[
                f"quorum not met: {len(decision_votes)} decision votes < {quorum}"
            ],
            blocking_vetoes=blocking_vetoes,
            quorum=quorum,
        )

    # 2. Defense veto
    if blocking_vetoes:
        return CommitteeResult(
            consensus="BLOCKED_DEFENSE",
            quorum_met=True,
            actionable=False,
            tally=tally,
            votes=list(votes),
            blocking_vetoes=blocking_vetoes,
            material_disagreements=[
                f"defense veto by {v} on an execution-leaning position" for v in blocking_vetoes
            ],
            quorum=quorum,
        )

    n_support = len(support)
    n_oppose = len(oppose)
    n_neutral = tally[POSITION_NEUTRAL]
    n_decision = len(decision_votes)

    dissenters: list[str] = []
    material_disagreements: list[str] = []

    # 3. No actionable votes → neutral posture
    if n_support == 0 and n_oppose == 0:
        return CommitteeResult(
            consensus="CONSENSUS_NEUTRAL",
            quorum_met=True,
            actionable=False,
            tally=tally,
            votes=list(votes),
            material_disagreements=[
                f"{v.member_id}: {v.position} (non-actionable)" for v in defer_or_insufficient
            ],
            blocking_vetoes=[],
            quorum=quorum,
        )

    # 4. Pure support / pure oppose
    if n_oppose == 0:
        consensus = "UNANIMOUS_SUPPORT" if n_support == n_decision else "CONSENSUS_SUPPORT"
        dissenters = [v.member_id for v in defer_or_insufficient]
        if defer_or_insufficient:
            material_disagreements.append(
                f"{len(defer_or_insufficient)} member(s) DEFER/INSUFFICIENT_EVIDENCE against SUPPORT"
            )
        return CommitteeResult(
            consensus=consensus,
            quorum_met=True,
            actionable=True,
            tally=tally,
            votes=list(votes),
            dissenters=dissenters,
            material_disagreements=material_disagreements,
            blocking_vetoes=[],
            quorum=quorum,
        )

    if n_support == 0:
        consensus = "UNANIMOUS_OPPOSE" if n_oppose == n_decision else "CONSENSUS_OPPOSE"
        dissenters = [v.member_id for v in defer_or_insufficient]
        return CommitteeResult(
            consensus=consensus,
            quorum_met=True,
            actionable=False,
            tally=tally,
            votes=list(votes),
            dissenters=dissenters,
            material_disagreements=material_disagreements,
            blocking_vetoes=[],
            quorum=quorum,
        )

    # 5. Both support and oppose present → super-majority or mixed
    total_actionable = n_support + n_oppose
    support_ratio = n_support / total_actionable if total_actionable else 0.0
    oppose_ratio = n_oppose / total_actionable if total_actionable else 0.0

    if support_ratio >= CONSENSUS_RATIO:
        dissenters = [v.member_id for v in oppose]
        material_disagreements.append(
            f"{n_oppose} OPPOSE vote(s) overruled by {n_support} SUPPORT super-majority"
        )
        return CommitteeResult(
            consensus="CONSENSUS_SUPPORT",
            quorum_met=True,
            actionable=True,
            tally=tally,
            votes=list(votes),
            dissenters=dissenters,
            material_disagreements=material_disagreements,
            blocking_vetoes=[],
            quorum=quorum,
        )

    if oppose_ratio >= CONSENSUS_RATIO:
        dissenters = [v.member_id for v in support]
        material_disagreements.append(
            f"{n_support} SUPPORT vote(s) overruled by {n_oppose} OPPOSE super-majority"
        )
        return CommitteeResult(
            consensus="CONSENSUS_OPPOSE",
            quorum_met=True,
            actionable=False,
            tally=tally,
            votes=list(votes),
            dissenters=dissenters,
            material_disagreements=material_disagreements,
            blocking_vetoes=[],
            quorum=quorum,
        )

    # No super-majority → MIXED (conflict unresolved at committee level)
    dissenters = sorted({v.member_id for v in support} | {v.member_id for v in oppose})
    material_disagreements.append(
        f"mixed committee: {n_support} SUPPORT vs {n_oppose} OPPOSE (no super-majority)"
    )
    return CommitteeResult(
        consensus="MIXED",
        quorum_met=True,
        actionable=False,
        tally=tally,
        votes=list(votes),
        dissenters=dissenters,
        material_disagreements=material_disagreements,
        blocking_vetoes=[],
        quorum=quorum,
    )
