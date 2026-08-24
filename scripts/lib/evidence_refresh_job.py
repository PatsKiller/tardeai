"""SYMBOL_EVIDENCE_REFRESH job states. Paid dispatch is a separate, explicit act."""
from __future__ import annotations

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "EvidenceRefreshJob@v1"

STATES = (
    "PLANNED",
    "FREE_FIRST_RUNNING",
    "FREE_EVIDENCE_COMPLETE",
    "LLM_ELIGIBLE",
    "LLM_ELIGIBLE_NOT_AUTHORIZED",
    "PAID_AUTHORIZED",
    "COMPLETED",
    "FAILED",
)

_ALLOWED = {
    "PLANNED": {"FREE_FIRST_RUNNING", "FAILED"},
    "FREE_FIRST_RUNNING": {"FREE_EVIDENCE_COMPLETE", "FAILED"},
    "FREE_EVIDENCE_COMPLETE": {"COMPLETED", "LLM_ELIGIBLE", "FAILED"},
    "LLM_ELIGIBLE": {"LLM_ELIGIBLE_NOT_AUTHORIZED", "PAID_AUTHORIZED", "FAILED"},
    "LLM_ELIGIBLE_NOT_AUTHORIZED": {"PAID_AUTHORIZED", "COMPLETED", "FAILED"},
    "PAID_AUTHORIZED": {"COMPLETED", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
}

PAID_FORBIDDEN = "PAID_DISPATCH_FORBIDDEN"


def can_transition(src: str, dst: str) -> bool:
    return dst in _ALLOWED.get(src, set())


def transition(src: str, dst: str) -> str:
    if not can_transition(src, dst):
        raise RuntimeError(f"ILLEGAL_JOB_TRANSITION: {src} -> {dst}")
    return dst


def assert_not_paid(state: str) -> None:
    if state in ("PLANNED", "FREE_FIRST_RUNNING"):
        raise RuntimeError(f"{PAID_FORBIDDEN}: cannot dispatch paid from {state}")
    if state == "LLM_ELIGIBLE":
        raise RuntimeError(f"{PAID_FORBIDDEN}: LLM_ELIGIBLE is not PAID_AUTHORIZED")
    if state == "LLM_ELIGIBLE_NOT_AUTHORIZED":
        raise RuntimeError(f"{PAID_FORBIDDEN}: not authorized")


_PAID_DISPATCH_ENTERED = 0


def reset_paid_dispatch_probe() -> None:
    global _PAID_DISPATCH_ENTERED
    _PAID_DISPATCH_ENTERED = 0


def paid_dispatch_entered() -> int:
    return _PAID_DISPATCH_ENTERED


def dispatch_paid_provider(*, state: str, mode: str = "FREE_FIRST_ONLY", **_kw) -> None:
    """The only paid entrypoint. FREE_FIRST_ONLY must never call this."""
    global _PAID_DISPATCH_ENTERED
    _PAID_DISPATCH_ENTERED += 1
    if mode != "PAID_AUTHORIZED":
        raise RuntimeError(f"{PAID_FORBIDDEN}: mode={mode}")
    assert_not_paid(state)
    raise RuntimeError(f"{PAID_FORBIDDEN}: dispatch_paid_provider entered")
