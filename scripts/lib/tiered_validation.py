"""TieredValidation@v1 — deterministic, then free, then (operator-gated) paid.

WHY THIS EXISTS
---------------
``scripts/agent_runtime/critics.py`` has held a correct, tested ``CriticPanel`` — no
voting, no fallback, preserved disagreement, provider provenance verified per lane — with
**zero callers outside tests**. This module is its first production caller, and it is the
tiering the plan specifies:

* **Tier 0 — deterministic.** ``BLOCK_DETERMINISTIC`` short-circuits **before any critic
  is constructed**, let alone called. A deterministic failure is sovereign: no reflective
  lane may release it, and spending a call to be told so is spending a call. Free.
* **Tier 1 — free OAuth critics** (``max_cost_usd = 0.0``). Provider separation is
  enforced **twice**: here, across lanes and against the producer's own family, and again
  inside ``CriticPanel._run_lane``, which rejects a lane whose returned provenance does
  not match what was declared. Free.
* **Tier 2 — paid judge.** Reached **only** on ``INSUFFICIENT_EVIDENCE``,
  ``PARTIAL_PROVIDER_FAILURE`` or ``DISAGREEMENT``, and **disabled by default**: funding a
  paid judge is an operator decision (AGENTS.md §17), so the default outcome is
  ``WITHHELD_OPERATOR_GATED`` with ``cost_usd: 0.0`` and ``paid_calls: 0``.

NOT SELF-CERTIFYING
-------------------
Every lane's verdict is filtered through ``validator_calibration``. A lane that has never
disagreed, that passed a seeded known-bad, or whose score vector never moves cannot
certify anything: its verdict is downgraded to ``INSUFFICIENT_EVIDENCE`` and the panel
state follows. A BLIND lane's results are excluded from the reconciliation entirely — a
voided window is voided, not merely annotated.

Authority: READ_ONLY_ADVISORY. Advisory only, MBI_BEHAVIOR = 0. This module never sizes,
orders, stops, promotes, or writes broker state, and never itself spends money: a paid
call requires both an operator flag and a provider the caller injects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from scripts.agent_runtime.critics import (
    CriticLane,
    CriticPanel,
    CriticProvider,
    CriticReconciliation,
    CriticResult,
)
from scripts.agent_runtime.sentinel import SentinelReport
from scripts.lib.validator_calibration import (
    BLIND,
    DOWNGRADE_STATE,
    CalibrationVerdict,
    Observation,
    SeededKnownBad,
    assess,
    observe_known_bad,
)

SCHEMA = "TieredValidation@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

#: Tier 2 is money. It is off unless the operator turns it on (AGENTS.md §17), and the
#: flag alone is not enough — a paid provider must also be injected by the caller.
TIER2_FLAG = "TRADEAI_TIER2_PAID_JUDGE"

#: The only states that may escalate to a paid judge. A clean REFLECTIVE_PASS or a
#: REFLECTIVE_REJECT is an answer; paying to re-ask it buys nothing.
TIER2_TRIGGER_STATES = frozenset(
    {
        "INSUFFICIENT_EVIDENCE",
        "PARTIAL_PROVIDER_FAILURE",
        "DISAGREEMENT",
    }
)

#: Free OAuth lanes. grok-3-mini on the OAuth lane is the one the registry already
#: declares for independent critique, and it bills $0.
FREE_TIER1_LANES: tuple[CriticLane, ...] = (CriticLane("grok_free", "grok-oauth", "grok-3-mini", max_cost_usd=0.0),)


class ProviderSeparationError(ValueError):
    """Raised before any call when a critic is not independent of what it judges."""


@dataclass(frozen=True)
class TierPolicy:
    tier1_lanes: tuple[CriticLane, ...] = FREE_TIER1_LANES
    tier2_enabled: bool = False
    tier2_reason: str = "operator-gated (AGENTS.md §17): funding a paid judge is not the agent's decision"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kwargs: Any) -> "TierPolicy":
        source = env if env is not None else os.environ
        enabled = str(source.get(TIER2_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}
        return cls(tier2_enabled=enabled, **kwargs)


@dataclass(frozen=True)
class TieredValidationResult:
    state: str
    tier_reached: int
    operator_action: str
    deterministic_verdict: str
    deterministic_release_allowed: bool
    critic_calls: int
    paid_calls: int
    cost_usd: float
    disagreements: tuple[str, ...]
    failed_lanes: tuple[str, ...]
    blind_lanes: tuple[str, ...]
    downgrade_reasons: tuple[str, ...]
    tier2_state: str
    calibration: Mapping[str, CalibrationVerdict] = field(default_factory=dict)
    reconciliation: CriticReconciliation | None = None
    schema: str = SCHEMA

    @property
    def release_allowed(self) -> bool:
        """Advisory: only a clean reflective pass from calibrated lanes releases."""
        return self.deterministic_release_allowed and self.state == "REFLECTIVE_PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authority": AUTHORITY,
            "state": self.state,
            "tier_reached": self.tier_reached,
            "operator_action": self.operator_action,
            "deterministic_verdict": self.deterministic_verdict,
            "deterministic_release_allowed": self.deterministic_release_allowed,
            "critic_calls": self.critic_calls,
            "paid_calls": self.paid_calls,
            "cost_usd": self.cost_usd,
            "disagreements": list(self.disagreements),
            "failed_lanes": list(self.failed_lanes),
            "blind_lanes": list(self.blind_lanes),
            "downgrade_reasons": list(self.downgrade_reasons),
            "tier2_state": self.tier2_state,
            "calibration": {k: v.to_dict() for k, v in self.calibration.items()},
            "release_allowed": self.release_allowed,
            "mbi_behavior": MBI_BEHAVIOR,
        }


def assert_provider_separation(producer_family: str, lanes: Sequence[CriticLane]) -> None:
    """Independence, checked before a single byte is sent.

    Two rules, both fail-closed: no lane may share the producer's provider family, and no
    two lanes may share each other's. Two grok lanes are one opinion wearing two badges.
    """
    producer = str(producer_family or "").strip().lower()
    if not producer:
        raise ProviderSeparationError("producer provider family is required to prove independence")
    seen: set[str] = set()
    for lane in lanes:
        family = str(lane.provider_family or "").strip().lower()
        if not family:
            raise ProviderSeparationError(f"lane {lane.lane_id} declares no provider family")
        if family == producer:
            raise ProviderSeparationError(
                f"lane {lane.lane_id} shares the producer's provider family ({family}); a critic may not be the author"
            )
        if family in seen:
            raise ProviderSeparationError(
                f"lane {lane.lane_id} duplicates provider family {family}; "
                "two lanes on one provider are not two opinions"
            )
        seen.add(family)
        if lane.max_cost_usd > 0.0:
            raise ProviderSeparationError(
                f"lane {lane.lane_id} declares a non-zero budget ({lane.max_cost_usd}); tier 1 is free by construction"
            )


def run_known_bad_probe(
    probe: SeededKnownBad,
    lanes: Sequence[CriticLane],
    providers: Mapping[str, CriticProvider],
    deterministic: SentinelReport,
) -> tuple[Observation, ...]:
    """Mechanism (ii): ask the lanes to judge something already known to be bad.

    The probe is deliberately run through the *same* panel, on a deterministic report that
    allows release, so the lanes are genuinely asked. Any lane that passes it is BLIND.
    """
    panel = CriticPanel(lanes, providers)
    reconciliation = panel.review(
        {
            "task": "known_bad_regression probe — this artifact carries a planted defect",
            "probe_id": probe.probe_id,
            "defect": probe.defect,
            "artifact": dict(probe.payload),
            "seeded_known_bad": True,
        },
        deterministic,
    )
    return tuple(
        observe_known_bad(result.lane_id, probe, result.verdict)
        for result in reconciliation.results
        if not result.error
    )


def _calibrate_lanes(
    results: Sequence[CriticResult],
    ledger: Mapping[str, Sequence[Observation]],
    *,
    min_sample: int,
) -> dict[str, CalibrationVerdict]:
    out: dict[str, CalibrationVerdict] = {}
    for result in results:
        window = list(ledger.get(result.lane_id, ()))
        out[result.lane_id] = assess(result.lane_id, window, min_sample=min_sample)
    return out


def validate(
    request: Mapping[str, Any],
    deterministic: SentinelReport,
    *,
    providers: Mapping[str, CriticProvider] | None = None,
    producer_family: str,
    policy: TierPolicy | None = None,
    calibration_ledger: Mapping[str, Sequence[Observation]] | None = None,
    min_sample: int = 30,
    paid_judge: CriticProvider | None = None,
) -> TieredValidationResult:
    """Run the three tiers in order and stop at the first that answers.

    ``providers`` maps ``lane_id -> callable``. A lane with no provider is preserved as a
    failed lane; it is never silently substituted, which is the property ``CriticPanel``
    was written to guarantee and the reason nothing here votes.
    """
    policy = policy or TierPolicy()
    ledger = dict(calibration_ledger or {})

    # ---- Tier 0 -----------------------------------------------------------
    # Before the panel exists. A deterministic block must cost nothing at all, and the
    # only way to prove that is to not build the thing that could spend.
    if not deterministic.release_allowed:
        return TieredValidationResult(
            state="BLOCK_DETERMINISTIC",
            tier_reached=0,
            operator_action="Do not call reflective critics; inspect deterministic findings.",
            deterministic_verdict=deterministic.verdict,
            deterministic_release_allowed=False,
            critic_calls=0,
            paid_calls=0,
            cost_usd=0.0,
            disagreements=(),
            failed_lanes=(),
            blind_lanes=(),
            downgrade_reasons=(),
            tier2_state="NOT_REACHED_TIER0_BLOCK",
        )

    # ---- Tier 1 -----------------------------------------------------------
    lanes = tuple(policy.tier1_lanes)
    assert_provider_separation(producer_family, lanes)  # first enforcement
    panel = CriticPanel(lanes, dict(providers or {}))  # second: provenance per lane
    reconciliation = panel.review(request, deterministic)

    cost = round(sum(r.cost_usd for r in reconciliation.results), 6)
    if cost > 0.0:
        raise ProviderSeparationError(f"tier 1 reported {cost} USD; tier 1 is free by construction")

    calibration = _calibrate_lanes(reconciliation.results, ledger, min_sample=min_sample)
    blind = tuple(sorted(lid for lid, cal in calibration.items() if cal.state == BLIND))
    uncalibrated = tuple(sorted(lid for lid, cal in calibration.items() if not cal.permits_certification))

    state = reconciliation.state
    action = reconciliation.operator_action
    reasons: list[str] = []
    if uncalibrated:
        for lane_id in uncalibrated:
            cal = calibration[lane_id]
            reasons.append(f"{lane_id} is {cal.state}: " + "; ".join(cal.reasons))
        # A disagreement is still a disagreement — it is evidence the lanes are alive and
        # must reach the operator. Everything else collapses to "we do not know".
        if state != "DISAGREEMENT":
            state = DOWNGRADE_STATE
            action = (
                "No calibrated validator backed this verdict; collect evidence or accept "
                "an explicit abstention. " + ("BLIND lane(s): " + ", ".join(blind) if blind else "")
            ).strip()

    # ---- Tier 2 -----------------------------------------------------------
    paid_calls = 0
    if state not in TIER2_TRIGGER_STATES:
        tier2_state = "NOT_TRIGGERED"
        tier_reached = 1
    elif not policy.tier2_enabled:
        tier2_state = f"WITHHELD_OPERATOR_GATED — {policy.tier2_reason}"
        tier_reached = 1
    elif paid_judge is None:
        # Enabled but unfunded is a misconfiguration, and a cost misconfiguration denies.
        tier2_state = "DENIED_NO_PAID_JUDGE_CONFIGURED"
        tier_reached = 1
    else:
        verdict = dict(paid_judge(dict(request)))
        paid_calls = 1
        cost = round(cost + float(verdict.get("cost_usd") or 0.0), 6)
        tier2_state = f"ESCALATED:{str(verdict.get('verdict') or 'UNKNOWN').upper()}"
        tier_reached = 2
        action = "Operator-funded judge consulted; its verdict is advisory and does not vote."

    return TieredValidationResult(
        state=state,
        tier_reached=tier_reached,
        operator_action=action,
        deterministic_verdict=deterministic.verdict,
        deterministic_release_allowed=True,
        critic_calls=len(reconciliation.results),
        paid_calls=paid_calls,
        cost_usd=cost,
        disagreements=reconciliation.disagreements,
        failed_lanes=reconciliation.failed_lanes,
        blind_lanes=blind,
        downgrade_reasons=tuple(reasons),
        tier2_state=tier2_state,
        calibration=calibration,
        reconciliation=reconciliation,
    )
