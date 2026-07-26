from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..contracts import assert_no_secret_material, canonical_hash, utc_now
from .base import OutputKind, ShadowAgentSpec

GOVERNED_OUTPUT_CONTRACT = "agent-runtime-governed-output-v1"


class GovernedOutputError(PermissionError):
    """Raised when an agent attempts an output outside its governed authority."""


# If any of these tokens appears as a *key* (or as a string value in an
# action-like field) the payload is claiming an authority an agent may never
# hold.  The governed channel is the single choke point, so this list is the
# hard boundary between "produce advisory evidence" and "act on the system".
FORBIDDEN_OUTPUT_TOKENS = (
    "merge",
    "deploy",
    "activate",
    "ratify",
    "promote",
    "execute",
    "place_order",
    "submit_order",
    "cancel_order",
    "modify_order",
    "broker",
    "approval",
    "approve",
    "two_factor",
    "2fa",
    "enable_agent",
    "set_budget",
    "change_config",
    "config_promote",
    "config_activate",
    "grant_permission",
    "modify_permission",
    "schedule_self",
    "restart_service",
    "systemctl",
)

# Action-bearing field names whose *values* are also scanned for forbidden verbs.
_ACTION_FIELDS = frozenset({"action", "actions", "effect", "apply", "command", "commit", "operation"})


@dataclass(frozen=True)
class GovernedOutput:
    """An immutable, advisory-only envelope produced through the governed channel.

    ``authority`` and ``target`` are stamped by the channel, never by the agent,
    and always denote a draft/advisory artifact with no execution semantics.
    """

    contract: str
    producer_agent_id: str
    kind: str
    payload: Mapping[str, Any]
    authority: str
    target: str
    created_at: str

    @property
    def payload_hash(self) -> str:
        return canonical_hash(self.payload)

    def as_dict(self) -> dict[str, Any]:
        body = {
            "contract": self.contract,
            "producer_agent_id": self.producer_agent_id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "authority": self.authority,
            "target": self.target,
            "created_at": self.created_at,
        }
        return {**body, "output_hash": canonical_hash(body)}


def _scan_forbidden(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            for token in FORBIDDEN_OUTPUT_TOKENS:
                if token in lowered:
                    raise GovernedOutputError(
                        f"governed output field asserts forbidden authority at {path}.{key}"
                    )
            if lowered in _ACTION_FIELDS:
                _scan_action_value(child, f"{path}.{key}")
            _scan_forbidden(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            _scan_forbidden(child, f"{path}[{index}]")


def _scan_action_value(value: Any, path: str) -> None:
    if isinstance(value, str):
        lowered = value.lower()
        for token in FORBIDDEN_OUTPUT_TOKENS:
            if token in lowered:
                raise GovernedOutputError(
                    f"governed output action at {path} names a forbidden verb: {token!r}"
                )
    elif isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            _scan_action_value(child, f"{path}[{index}]")
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _scan_action_value(child, f"{path}.{key}")


def emit_governed_output(
    spec: ShadowAgentSpec,
    kind: OutputKind | str,
    payload: Mapping[str, Any],
    *,
    now: str | None = None,
) -> GovernedOutput:
    """Produce ONE advisory governed output, or fail closed.

    This is the only sanctioned way for an agent to externalize a review,
    scorecard, candidate lesson/hypothesis, remediation proposal, research task,
    or draft-PR request.  It can never merge, deploy, activate, ratify, promote,
    schedule, order, approve, or change configuration; those are rejected here.
    """
    spec.validate()
    kind_value = kind.value if isinstance(kind, OutputKind) else str(kind)
    allowed = {item.value for item in spec.allowed_output_kinds}
    if kind_value not in allowed:
        raise GovernedOutputError(
            f"{spec.agent_id}: output kind {kind_value!r} is not permitted for this agent"
        )
    if not isinstance(payload, Mapping):
        raise GovernedOutputError("governed output payload must be a mapping")
    # No secret material, and no field/value that asserts a forbidden authority.
    try:
        assert_no_secret_material(payload)
    except ValueError as exc:
        raise GovernedOutputError(str(exc)) from exc
    _scan_forbidden(payload)
    return GovernedOutput(
        contract=GOVERNED_OUTPUT_CONTRACT,
        producer_agent_id=spec.agent_id,
        kind=kind_value,
        payload=dict(payload),
        authority="ADVISORY_ONLY",
        target="DRAFT_ONLY",
        created_at=now or utc_now(),
    )
