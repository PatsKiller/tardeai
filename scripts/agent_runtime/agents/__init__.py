"""Lane D — governed autonomous SHADOW agent definitions.

This package layers *agent definitions* (who each agent is, what triggers it,
what it may produce, who independently reviews and scores it, and the exact
maturity gates it must clear) on top of the existing governed runtime in
``scripts.agent_runtime``.  Nothing in this package can merge, deploy, activate,
ratify, promote, schedule itself, change production configuration, or touch any
broker / order / account / approval / 2FA / secret authority.  Everything is
DEFAULT-DISABLED and prepare-only.

Modules
-------
- ``base``            — ``ShadowAgentSpec`` + hard authority guards.
- ``definitions``     — the initial SHADOW agents (enabled in SHADOW) plus
                        the second maturity wave (defined but DISABLED) and
                        third wave (CIO + wealth advisory).
- ``governed_output`` — the *only* sanctioned channel an agent may use to emit
                        an advisory artifact / candidate / proposal.
- ``maturity_gates``  — measurable per-agent promotion gates; reports
                        ``NOT_YET_MEASURED`` until evidence is supplied.
- ``dispatcher``      — a deterministic, NON-agentic bounded-queue runner design
                        (agents cannot schedule themselves).
"""

from .base import (
    OutputKind,
    ShadowAgentSpec,
    Trigger,
    TriggerKind,
    assert_fleet_separation,
    assert_no_self_governance,
)
from .definitions import (
    FLEET,
    INITIAL_SHADOW_AGENT_IDS,
    SECOND_WAVE_AGENT_IDS,
    THIRD_WAVE_AGENT_IDS,
    fleet,
    initial_agents,
    reviewer_scorer_matrix,
    second_wave_agents,
    third_wave_agents,
    spec,
)
from .governed_output import (
    FORBIDDEN_OUTPUT_TOKENS,
    GovernedOutput,
    GovernedOutputError,
    emit_governed_output,
)
from .maturity_gates import (
    GATE_IDS,
    GateStatus,
    MaturityReport,
    assert_not_operational,
    evaluate_gates,
)

__all__ = [
    "FLEET",
    "FORBIDDEN_OUTPUT_TOKENS",
    "GATE_IDS",
    "GovernedOutput",
    "GovernedOutputError",
    "GateStatus",
    "INITIAL_SHADOW_AGENT_IDS",
    "MaturityReport",
    "OutputKind",
    "SECOND_WAVE_AGENT_IDS",
    "ShadowAgentSpec",
    "Trigger",
    "TriggerKind",
    "assert_fleet_separation",
    "assert_no_self_governance",
    "assert_not_operational",
    "emit_governed_output",
    "evaluate_gates",
    "fleet",
    "initial_agents",
    "reviewer_scorer_matrix",
    "second_wave_agents",
    "spec",
]
