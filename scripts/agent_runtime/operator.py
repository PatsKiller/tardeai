from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .runtime import MvlRuntime


@dataclass(frozen=True)
class OperatorCommand:
    action: str
    run_id: str
    reason: str = ""


class OpenClawOperatorGateway:
    """Narrow operator gateway for reflective runs.

    Supported commands are status, explain, cancel, and resume. There is no
    arbitrary shell, production database, broker, order, approval, 2FA, secret,
    or config-promotion command in this contract.
    """

    ALLOWED = {"status", "explain", "cancel", "resume"}

    def __init__(self, runtime: MvlRuntime) -> None:
        self.runtime = runtime

    @classmethod
    def parse(cls, raw: str) -> OperatorCommand:
        parts = raw.strip().split(maxsplit=2)
        if len(parts) < 2:
            raise ValueError("command must be: <status|explain|cancel|resume> <run_id> [reason]")
        action = parts[0].lower()
        if action not in cls.ALLOWED:
            raise PermissionError(f"OpenClaw command is not governed: {action}")
        return OperatorCommand(action=action, run_id=parts[1], reason=parts[2] if len(parts) > 2 else "")

    def execute(self, command: OperatorCommand) -> Mapping[str, Any]:
        if command.action == "status":
            return self.runtime.status(command.run_id)
        if command.action == "explain":
            state = dict(self.runtime.status(command.run_id))
            return {
                "run_id": command.run_id,
                "status": state.get("status"),
                "checkpoint": state.get("checkpoint"),
                "retrieval_count": state.get("retrieval_count", 0),
                "tool_calls": state.get("tool_calls", 0),
                "model_calls": state.get("model_calls", 0),
                "cost_usd": state.get("cost_usd", 0.0),
                "last_event_hash": state.get("last_event_hash"),
                "authority": "reflective artifacts only; deterministic release remains sovereign",
            }
        if command.action == "cancel":
            self.runtime.cancel(command.run_id, command.reason or "operator cancelled through OpenClaw")
            return self.runtime.status(command.run_id)
        if command.action == "resume":
            return self.runtime.resume(command.run_id)
        raise PermissionError("unsupported command")
