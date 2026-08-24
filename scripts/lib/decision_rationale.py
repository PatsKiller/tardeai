"""DecisionRationale@v1 — auditable reasons, never private chain-of-thought."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "DecisionRationale@v1"
FORBIDDEN_KEYS = (
    "chain_of_thought",
    "raw_chain_of_thought",
    "scratchpad",
    "hidden_reasoning",
    "private_reasoning",
    "reasoning_tokens",
    "internal_reasoning",
    "invisible_reasoning",
)
_FORBIDDEN_RE = re.compile("|".join(re.escape(k) for k in FORBIDDEN_KEYS), re.I)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def reject_private_reasoning(payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if CoT/scratchpad-shaped fields are present."""
    if not isinstance(payload, dict):
        raise RuntimeError("RATIONALE_NOT_OBJECT")
    for key in list(payload.keys()):
        if _FORBIDDEN_RE.search(str(key)):
            raise RuntimeError(f"PRIVATE_REASONING_FORBIDDEN:{key}")
        val = payload[key]
        if isinstance(val, str) and _FORBIDDEN_RE.search(val) and "reason_code" not in str(key).lower():
            # values that *are* the CoT blob
            if any(tok in val.lower() for tok in ("let me think step by step", "hidden chain", "scratchpad:")):
                raise RuntimeError("PRIVATE_REASONING_FORBIDDEN:value")
        if isinstance(val, dict):
            reject_private_reasoning(val)
    return payload


def build_rationale(
    *,
    decision_id: str,
    conclusion: str,
    structured_reason_codes: list[str],
    evidence_refs: list[str] | None = None,
    counterevidence_refs: list[str] | None = None,
    uncertainties: list[str] | None = None,
    assumptions: list[str] | None = None,
    model_provider: str | None = None,
    prompt_version: str | None = None,
    context_digest: str | None = None,
    tool_receipts: list[dict[str, Any]] | None = None,
    verification_results: list[dict[str, Any]] | None = None,
    source_sha: str = "",
) -> dict[str, Any]:
    row = {
        "schema": SCHEMA,
        "decision_id": decision_id,
        "conclusion": conclusion,
        "structured_reason_codes": list(structured_reason_codes),
        "evidence_refs": list(evidence_refs or []),
        "counterevidence_refs": list(counterevidence_refs or []),
        "uncertainties": list(uncertainties or []),
        "assumptions": list(assumptions or []),
        "model_provider": model_provider,
        "prompt_version": prompt_version,
        "context_digest": context_digest,
        "tool_receipts": list(tool_receipts or []),
        "verification_results": list(verification_results or []),
        "created_at": _now(),
        "source_sha": source_sha,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    return reject_private_reasoning(row)
