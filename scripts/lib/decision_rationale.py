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


# ── Producer adapters ────────────────────────────────────────────────────────
# Each builds a rationale ONLY from fields the producer already stated on the
# decision. Reason codes are those fields verbatim as `name:value`; nothing is
# summarised, scored or inferred, and no model reasoning text is ever copied.

_PAYLOAD_REASON_FIELDS = (
    "decision_origin", "extra_emit_reason", "intel_state", "condition_type", "health", "row_class",
)
_MAX_CODES = 24


def _codes_from(fields: tuple[str, ...], row: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for name in fields:
        value = row.get(name)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip():
            codes.append(f"{name}:{str(value).strip()[:60]}")
    return codes


def _gate_codes(gates: Any) -> list[str]:
    codes: list[str] = []
    for gate in gates if isinstance(gates, list) else []:
        if isinstance(gate, dict) and gate.get("id") and isinstance(gate.get("pass"), bool):
            codes.append(f"gate:{str(gate['id'])[:40]}={'pass' if gate['pass'] else 'fail'}")
    return codes


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional fields so the record stays small on every decision row."""
    keep = {"schema", "decision_id", "conclusion", "structured_reason_codes", "created_at",
            "authority", "financial_action", "source_ref", "as_of"}
    return {k: v for k, v in row.items() if k in keep or v not in (None, "", [], {})}


def rationale_for_decision_payload(payload: dict[str, Any], *, source_ref: str | None = None) -> dict[str, Any] | None:
    """DecisionRationale@v1 for a DecisionPayload@v1 (AgentRunTrace decision). Fail-soft: None."""
    try:
        did = str(payload.get("decision_id") or "").strip()
        if not did:
            return None
        action = str(payload.get("current_action") or "DATA_UNAVAILABLE")
        surface = str(payload.get("surface") or "")
        codes = (_gate_codes(payload.get("gates_evaluated")) + _codes_from(_PAYLOAD_REASON_FIELDS, payload))[:_MAX_CODES]
        refs = [str(r) for r in (payload.get("evidence_refs") or []) if isinstance(r, (str, int)) and str(r).strip()]
        row = build_rationale(
            decision_id=did,
            conclusion=f"{surface}: {action}" if surface else action,
            structured_reason_codes=codes,
            evidence_refs=refs[:20],
            model_provider=str(payload.get("model")) if payload.get("model") else None,
            context_digest=str(payload.get("inputs_digest")) if payload.get("inputs_digest") else None,
        )
        row["source_ref"] = source_ref
        row["as_of"] = payload.get("as_of")
        return _compact(reject_private_reasoning(row))
    except Exception:
        return None


_PLAN_REASON_FIELDS = ("cio_stance", "stance_code", "action_label", "decision_policy_version")


def rationale_for_capital_plan_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """DecisionRationale@v1 for a capital-plan position decision. why_now is the plan's own stated reason."""
    try:
        did = str(row.get("decision_id") or "").strip()
        if not did:
            return None
        why_now = str(row.get("why_now") or "").strip()
        action = str(row.get("action") or row.get("stance_code") or row.get("cio_stance") or "")
        rec = build_rationale(
            decision_id=did,
            conclusion=why_now[:400] or action or "UNSTATED",
            structured_reason_codes=_codes_from(_PLAN_REASON_FIELDS, row)[:_MAX_CODES],
            evidence_refs=[str(r) for r in (row.get("framework_refs") or []) if str(r).strip()][:20],
            context_digest=str(row.get("decision_input_digest")) if row.get("decision_input_digest") else None,
        )
        rec["source_ref"] = row.get("source_ref")
        rec["as_of"] = row.get("decision_generated_at") or row.get("generated_at") or row.get("recorded_at")
        return _compact(reject_private_reasoning(rec))
    except Exception:
        return None
