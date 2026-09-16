"""ValidatorCalibration@v1 — a validator that has never disagreed is not a control.

WHY THIS EXISTS
---------------
The operator's ask was: *"I need not just one agent to actually say that its work is
golden. We need to validate and litmus test."* The measurement that followed found the
validators already exist and have **never contested anything**:

===================================  =====================================================
validator                            measured 2026-09-16
===================================  =====================================================
``independent_critic``               31/31 ``accept``; zero disagreements; every one on a
                                     judgment whose stance is ABSTAIN/INSUFFICIENT
``agent_view_v1.critic_pass``        346/346 ``True``; ``critique_id`` None; ``critic_notes``
                                     ``[]`` — a field lint, not a control
``research_quality.critique()``      608 completions: VALID 503 / PARTIAL 93 / null 12 and
                                     **zero FAILED**; both passing verdicts are accepted, so
                                     the gate has never blocked anything
``StructuralGoldenJudge``            four of six rubric axes are hardcoded constants
===================================  =====================================================

A validator whose output does not vary is indistinguishable from no validator. This module
makes that statistically explicit and **fails closed**: a validator that is not calibrated
cannot certify anything — its verdict is downgraded to ``INSUFFICIENT_EVIDENCE``.

THE FOUR ANTI-BLINDNESS MECHANISMS
----------------------------------
i.   **Disagreement floor.** ``disagreement_rate == 0`` at ``n >= 30`` ⇒ ``UNCALIBRATED``.
     Day-one baselines (``day_one_calibration()``) stamp all three live validators
     UNCALIBRATED *by their own numbers* — no new measurement required to convict them.
ii.  **Seeded known-bads** at 1-in-20 (``seeded_probe_due``). A validator that PASSES a
     seeded known-bad is ``BLIND`` and **its whole window is voided** — the observations
     either side of the miss prove nothing, because the instrument was not measuring.
     This activates ``known_bad_regression``, a job type declared on the ``sentinel`` agent
     (``agent_runtime/agents/definitions.py``, ``config/agent_runtime_mvl.json``,
     ``config/agent_maturity_catalog.json``) that had no implementation anywhere.
iii. **Variance requirement.** An axis with zero variance across the window is not being
     measured, whatever its value says. This is what catches ``StructuralGoldenJudge``:
     ``grounding`` is always 4 and ``calibration`` always 3, so both axes contribute a
     constant to every total and separate nothing from anything.
iv.  The same rule is applied to the gate bridge itself — see
     ``scripts/cio_gate_measurement_bridge.py``, where six gates that were hardcoded
     constants now read ``NOT_YET_MEASURED``.

HONESTY RULE (inherited from report_goal_loop_baseline.py)
----------------------------------------------------------
``NOT_YET_MEASURED`` and ``CALIBRATED`` are different claims and are never collapsed. An
empty window is NOT a pass: with no observations the state is ``NOT_YET_MEASURED``, and
``permits_certification()`` is False for it exactly as it is for ``UNCALIBRATED``.

Authority: READ_ONLY_ADVISORY. No network, no model call, no writes. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "ValidatorCalibration@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

#: Below this many observations a window says NOT_YET_MEASURED rather than passing or
#: convicting. 30 is the number the plan fixed; it is the floor at which "never disagreed"
#: stops being plausible sampling noise.
MIN_SAMPLE = 30

#: One seeded known-bad in every twenty real validations. Frequent enough that a blind
#: validator is caught within a working window; rare enough to be free.
SEED_EVERY_N = 20

#: Verdict vocabularies differ per validator (accept/True/VALID/PASS). These are the
#: tokens that mean "this artifact may proceed" — i.e. the ones a known-bad must NOT get.
PASSING_TOKENS = frozenset(
    {
        "accept",
        "accepted",
        "pass",
        "passed",
        "true",
        "valid",
        "ok",
        "release",
        "publish",
        "reflective_pass",
        "partial",
    }
)

CALIBRATED = "CALIBRATED"
UNCALIBRATED = "UNCALIBRATED"
BLIND = "BLIND"
NOT_YET_MEASURED = "NOT_YET_MEASURED"

#: The single downgrade target. A validator that cannot be trusted to disagree is not
#: allowed to say REJECT either — it is allowed to say only that it does not know.
DOWNGRADE_STATE = "INSUFFICIENT_EVIDENCE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Observation:
    """One validation this validator performed.

    ``disagreed`` is the load-bearing field: it means the validator's verdict differed
    from the thing it was validating (a REJECT, a CAUTION with findings, a revise with
    named field changes). Recording ``accept`` on an ABSTAIN judgment is not a
    disagreement, which is precisely why ``independent_critic`` scores 31/31.
    """

    validator_id: str
    verdict: str
    disagreed: bool = False
    seeded_known_bad: bool = False
    known_bad_passed: bool = False
    scores: Mapping[str, float] | None = None
    observation_id: str = ""
    occurred_at: str = ""

    def __post_init__(self) -> None:
        if not str(self.validator_id).strip():
            raise ValueError("observation requires a validator_id")
        if self.known_bad_passed and not self.seeded_known_bad:
            raise ValueError("known_bad_passed is only meaningful on a seeded known-bad")


@dataclass(frozen=True)
class CalibrationVerdict:
    validator_id: str
    state: str
    n: int
    disagreements: int
    disagreement_rate: float | None
    seeded_known_bads: int
    seeded_known_bads_passed: int
    window_voided: bool
    constant_axes: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence: Mapping[str, Any] = field(default_factory=dict)
    assessed_at: str = field(default_factory=_now)
    schema: str = SCHEMA

    @property
    def permits_certification(self) -> bool:
        """Only a CALIBRATED validator may let a PASS/REJECT verdict stand."""
        return self.state == CALIBRATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "validator_id": self.validator_id,
            "state": self.state,
            "n": self.n,
            "disagreements": self.disagreements,
            "disagreement_rate": self.disagreement_rate,
            "seeded_known_bads": self.seeded_known_bads,
            "seeded_known_bads_passed": self.seeded_known_bads_passed,
            "window_voided": self.window_voided,
            "constant_axes": list(self.constant_axes),
            "reasons": list(self.reasons),
            "evidence": dict(self.evidence),
            "assessed_at": self.assessed_at,
            "permits_certification": self.permits_certification,
        }


# ------------------------------------------------------------------ mechanisms


def verdict_is_passing(verdict: Any) -> bool:
    """Did this verdict let the artifact through?

    Booleans are included because ``agent_view_v1.critic_pass`` is a bare bool — the
    field-lint shape this module exists to convict.
    """
    if isinstance(verdict, bool):
        return verdict
    token = str(verdict or "").strip().lower().replace("-", "_")
    return token in PASSING_TOKENS


def seeded_probe_due(sequence_number: int, *, every: int = SEED_EVERY_N) -> bool:
    """True on every ``every``-th validation (1-based), so 1-in-20 by default."""
    if every <= 0:
        raise ValueError("seed interval must be positive")
    if sequence_number <= 0:
        return False
    return sequence_number % every == 0


def zero_variance_axes(observations: Sequence[Observation]) -> tuple[str, ...]:
    """Axes that never moved across the window — i.e. axes that measure nothing.

    Requires at least two scored observations: one score vector cannot show variance and
    must not be convicted of lacking it.
    """
    vectors = [dict(o.scores) for o in observations if o.scores]
    if len(vectors) < 2:
        return ()
    axes = set(vectors[0])
    for vec in vectors[1:]:
        axes &= set(vec)
    constant: list[str] = []
    for axis in sorted(axes):
        values = {round(float(vec[axis]), 9) for vec in vectors}
        if len(values) == 1:
            constant.append(axis)
    return tuple(constant)


def assess(
    validator_id: str,
    observations: Sequence[Observation],
    *,
    min_sample: int = MIN_SAMPLE,
) -> CalibrationVerdict:
    """Calibrate one validator's window. Fails closed on every ambiguity.

    Rule order is deliberate: BLIND dominates everything, because a validator that missed
    a seeded known-bad has told us its other verdicts are worthless. Then sample size,
    then the disagreement floor, then the variance requirement.
    """
    rows = [o for o in observations if o.validator_id == validator_id]
    seeded = [o for o in rows if o.seeded_known_bad]
    missed = [o for o in seeded if o.known_bad_passed]
    real = [o for o in rows if not o.seeded_known_bad]
    n = len(real)
    disagreements = sum(1 for o in real if o.disagreed)
    rate = (disagreements / n) if n else None
    constant = zero_variance_axes(real)
    reasons: list[str] = []
    evidence: dict[str, Any] = {
        "seeded_known_bad_ids": [o.observation_id for o in seeded if o.observation_id],
        "missed_known_bad_ids": [o.observation_id for o in missed if o.observation_id],
        "verdicts": sorted({str(o.verdict) for o in real}),
    }

    if missed:
        reasons.append(
            f"PASSED_SEEDED_KNOWN_BAD:{len(missed)}/{len(seeded)} — window voided; "
            "observations either side of a miss prove nothing"
        )
        return CalibrationVerdict(
            validator_id=validator_id,
            state=BLIND,
            n=n,
            disagreements=disagreements,
            disagreement_rate=rate,
            seeded_known_bads=len(seeded),
            seeded_known_bads_passed=len(missed),
            window_voided=True,
            constant_axes=constant,
            reasons=tuple(reasons),
            evidence=evidence,
        )

    if n == 0:
        reasons.append("NO_OBSERVATIONS — an empty window is not a pass")
        state = NOT_YET_MEASURED
    elif n < min_sample:
        reasons.append(f"INSUFFICIENT_SAMPLE:{n}<{min_sample}")
        state = NOT_YET_MEASURED
    elif disagreements == 0:
        reasons.append(
            f"NO_DISAGREEMENT_IN_WINDOW:0/{n} — a validator that has never disagreed is "
            "indistinguishable from no validator"
        )
        state = UNCALIBRATED
    else:
        state = CALIBRATED

    if constant and state in (CALIBRATED, UNCALIBRATED):
        reasons.append("ZERO_SCORE_VARIANCE:" + ",".join(constant) + " — a constant axis is not a measurement")
        state = UNCALIBRATED

    return CalibrationVerdict(
        validator_id=validator_id,
        state=state,
        n=n,
        disagreements=disagreements,
        disagreement_rate=rate,
        seeded_known_bads=len(seeded),
        seeded_known_bads_passed=0,
        window_voided=False,
        constant_axes=constant,
        reasons=tuple(reasons),
        evidence=evidence,
    )


def downgrade_verdict(verdict: str, calibration: CalibrationVerdict) -> tuple[str, tuple[str, ...]]:
    """Apply mechanism (i): an uncalibrated validator may only say "I do not know".

    Returns ``(verdict, reasons)`` unchanged when the validator is calibrated.
    """
    if calibration.permits_certification:
        return verdict, ()
    reason = f"{calibration.validator_id} is {calibration.state}; verdict {verdict} downgraded to {DOWNGRADE_STATE}"
    return DOWNGRADE_STATE, (reason,) + tuple(calibration.reasons)


# ------------------------------------------------------- seeded known-bad probes


@dataclass(frozen=True)
class SeededKnownBad:
    """A fixture whose correct verdict is known in advance: it must NOT pass."""

    probe_id: str
    payload: Mapping[str, Any]
    defect: str = "known_bad_fixture"
    source: str = "tests/fixtures/shadow_acceptance/known_bad.json"

    def judge(self, verdict: Any) -> bool:
        """True when the validator PASSED a known-bad — i.e. it is blind."""
        return verdict_is_passing(verdict)


_FIXTURE_REL = Path("tests/fixtures/shadow_acceptance/known_bad.json")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_known_bad_probes(fixture_dir: Path | str | None = None) -> tuple[SeededKnownBad, ...]:
    """Load the repo's existing known-bad corpus (20 fixtures, already in git).

    Reuses ``tests/fixtures/shadow_acceptance/known_bad.json`` — the corpus
    ``packet_d_shadow_acceptance.py`` requires 20 of — rather than minting a second
    known-bad scheme. Missing corpus returns empty; the caller decides whether that is
    fatal (it is, for a window that claims to have been probed).
    """
    path = Path(fixture_dir) / "known_bad.json" if fixture_dir else _repo_root() / _FIXTURE_REL
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    rows = raw if isinstance(raw, list) else raw.get("artifacts") or []
    probes: list[SeededKnownBad] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        probes.append(
            SeededKnownBad(
                probe_id=str(row.get("artifact_id") or f"known-bad-{len(probes) + 1:03d}"),
                payload={**payload, "symbol": row.get("symbol"), "is_known_bad": True},
                defect=str(payload.get("defect") or row.get("known_bad_reason") or "known_bad"),
                source=str(row.get("source") or str(_FIXTURE_REL)),
            )
        )
    return tuple(probes)


def observe_known_bad(
    validator_id: str,
    probe: SeededKnownBad,
    verdict: Any,
    *,
    occurred_at: str | None = None,
) -> Observation:
    """Turn a probe result into an observation. PASS on a known-bad ⇒ BLIND."""
    return Observation(
        validator_id=validator_id,
        verdict=str(verdict),
        disagreed=not probe.judge(verdict),
        seeded_known_bad=True,
        known_bad_passed=probe.judge(verdict),
        observation_id=probe.probe_id,
        occurred_at=occurred_at or _now(),
    )


# --------------------------------------------------------- day-one baselines


def observations_from_counts(
    validator_id: str,
    *,
    total: int,
    disagreements: int,
    scores: Mapping[str, float] | None = None,
    verdict: str = "accept",
) -> tuple[Observation, ...]:
    """Reconstruct a window from measured counts.

    Used for the day-one baselines, where the corpora are live JSONL files and the counts
    are what was measured — not a simulation. ``disagreements`` observations carry
    ``disagreed=True``; the rest do not.
    """
    if disagreements > total:
        raise ValueError("disagreements cannot exceed total observations")
    rows: list[Observation] = []
    for index in range(total):
        rows.append(
            Observation(
                validator_id=validator_id,
                verdict=verdict,
                disagreed=index < disagreements,
                scores=dict(scores) if scores else None,
                observation_id=f"{validator_id}-baseline-{index + 1:04d}",
            )
        )
    return tuple(rows)


#: Measured 2026-09-16. Each row is a count taken off a live corpus, with the corpus named
#: so the number is checkable. These are the three validators the operator was told were
#: working; by their own numbers none of them is calibrated.
DAY_ONE_BASELINES: dict[str, dict[str, Any]] = {
    "independent_critic": {
        "total": 31,
        "disagreements": 0,
        "corpus": "/home/johnclaw/trade-ai-state/persistent_wake/state/views.jsonl",
        "measured": "31/31 accept, zero disagreements, every one on an ABSTAIN/INSUFFICIENT judgment",
    },
    "agent_view_critic_pass": {
        "total": 346,
        "disagreements": 0,
        "corpus": "/home/johnclaw/trade-ai-state/persistent_wake/state/agent_views.jsonl",
        "measured": "346/346 True, critique_id None, critic_notes [] — a field lint, not a control",
    },
    "research_quality_critique": {
        "total": 608,
        "disagreements": 0,
        "corpus": "hermes completions (VALID 503 / PARTIAL 93 / null 12, zero FAILED)",
        "measured": "both passing verdicts are accepted, so the gate has never blocked anything",
    },
}


def day_one_calibration(*, min_sample: int = MIN_SAMPLE) -> dict[str, CalibrationVerdict]:
    """Stamp the three live validators against the new floor, using their own numbers.

    Every one comes back UNCALIBRATED. That is the point: the bar is not retroactive
    speculation, it is arithmetic over what they have already done.
    """
    out: dict[str, CalibrationVerdict] = {}
    for validator_id, row in DAY_ONE_BASELINES.items():
        window = observations_from_counts(
            validator_id,
            total=int(row["total"]),
            disagreements=int(row["disagreements"]),
        )
        verdict = assess(validator_id, window, min_sample=min_sample)
        out[validator_id] = CalibrationVerdict(
            validator_id=verdict.validator_id,
            state=verdict.state,
            n=verdict.n,
            disagreements=verdict.disagreements,
            disagreement_rate=verdict.disagreement_rate,
            seeded_known_bads=verdict.seeded_known_bads,
            seeded_known_bads_passed=verdict.seeded_known_bads_passed,
            window_voided=verdict.window_voided,
            constant_axes=verdict.constant_axes,
            reasons=verdict.reasons,
            evidence={"corpus": row["corpus"], "measured": row["measured"]},
            assessed_at=verdict.assessed_at,
        )
    return out


def summarise(verdicts: Iterable[CalibrationVerdict]) -> dict[str, Any]:
    rows = list(verdicts)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "validators": len(rows),
        "calibrated": sum(1 for v in rows if v.state == CALIBRATED),
        "uncalibrated": sum(1 for v in rows if v.state == UNCALIBRATED),
        "blind": sum(1 for v in rows if v.state == BLIND),
        "not_yet_measured": sum(1 for v in rows if v.state == NOT_YET_MEASURED),
        "detail": [v.to_dict() for v in rows],
    }
