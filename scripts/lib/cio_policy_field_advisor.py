"""cio_policy_field_advisor.py — DeepSeek Flash help for one CIO policy field.

The CIO Capital Policy tab lets the operator open a manager modal for each
policy field and ask DeepSeek for help. That help used to go through the
generic /api/v2/consumption/run-manual endpoint, which only runs DeepSeek for
the fixed-prompt smoke process, so every click came back
"Smoke prompt is invalid for this process".

This module is the dedicated path:

  * The client sends only ``field_name``. The prompt is built here, on the
    server, from the policy projection (field kind, current value, unconfirmed
    legacy claims). Client text never reaches the provider.
  * Calls run under the registered ``cio_policy_field_advisor`` process
    (FAST / deepseek-flash only, process + global USD caps, no fallback).
  * The answer is advisory. Nothing here ratifies, saves or infers a policy
    value; the operator still types and confirms the value in the modal.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

PROCESS_ID = "cio_policy_field_advisor"
LANE = "deepseek-flash"
POLICY = "FAST"
_MAX_CLAIMS_CHARS = 3000


def _label(field_name: str) -> str:
    return field_name.replace("_pct", " (%)").replace("_usd", " (USD)").replace("_", " ").strip().capitalize()


def field_claims(policy: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    """Unconfirmed legacy claims that bear on ``field_name`` (direct or resolved-by)."""
    out: list[dict[str, Any]] = []
    for conflict in policy.get("legacy_conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        if field_name not in (conflict.get("field"), conflict.get("resolved_by")):
            continue
        for claim in conflict.get("claims") or []:
            if isinstance(claim, dict):
                out.append({k: claim.get(k) for k in ("field", "value", "source", "status")})
    return out


def build_prompt(policy: dict[str, Any], field_name: str) -> str:
    field = (policy.get("fields") or {}).get(field_name) or {}
    kind = str(field.get("kind") or "text")
    claims = json.dumps(field_claims(policy, field_name), default=str)
    if len(claims) > _MAX_CLAIMS_CHARS:
        claims = claims[:_MAX_CLAIMS_CHARS] + " …(truncated)"
    shape = {
        "range_pct": "a percentage band {min, max} (cash bands also carry a target, with min <= target <= max)",
        "money": "a US dollar amount",
        "list": "a list of values",
        "object": "a JSON object",
    }.get(kind, "a short text answer")
    return "\n".join([
        "You are an advisory-only assistant helping a private investor set one field of their investment policy.",
        "Do not ratify, approve, or invent facts. Do not output an order or trade instruction.",
        f"Policy field: {_label(field_name)} ({field_name})",
        f"Value shape: {shape}",
        f"Current confirmed value: {json.dumps(field.get('value'), default=str)} (status {field.get('status') or 'UNKNOWN'})",
        f"Unconfirmed legacy claims from config files (they may conflict): {claims}",
        "Reply in under 200 words with: (1) two or three candidate values or criteria with the trade-off of each,",
        "(2) which legacy claim, if any, looks closest to a sound policy and why, and",
        "(3) the questions the investor must answer before choosing the final value.",
    ])


def advise(
    field_name: str,
    policy: dict[str, Any],
    *,
    generate: Optional[Callable[..., Any]] = None,
    readiness: Optional[Callable[[], list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """Return ``{"ok": True, "text": ...}`` or a sanitized ``{"ok": False, ...}``."""
    from lib.consumption_run_manual import deepseek_readiness_rows, sanitize_provider_error

    name = str(field_name or "").strip()
    if not name:
        return {"ok": False, "reason_code": "FIELD_REQUIRED", "error": "field_name required"}
    if name not in (policy.get("fields") or {}):
        return {"ok": False, "reason_code": "UNKNOWN_POLICY_FIELD", "error": "field_name is not a policy field"}

    rows = (readiness or deepseek_readiness_rows)()
    flash = next((r for r in rows if r.get("lane") == LANE), None)
    if not flash or not flash.get("ready"):
        return {
            "ok": False,
            "field_name": name,
            "reason_code": (flash or {}).get("reason_code") or "MODEL_NOT_AVAILABLE",
            "error": (flash or {}).get("hint") or "DeepSeek Flash not ready",
        }

    if generate is None:
        from lib import llm_consumption as lc

        generate = lc.gate_and_generate
    try:
        result = generate(
            build_prompt(policy, name),
            lane=LANE,
            process_id=PROCESS_ID,
            task_summary=f"Advisory suggestion for CIO policy field {name}",
            manual_trigger=True,
            timeout=60,
            model=LANE,
            policy=POLICY,
            return_provenance=True,
        )
    except Exception as exc:  # noqa: BLE001 — sanitized for the browser
        safe = sanitize_provider_error(exc)
        return {"ok": False, "field_name": name, **safe}

    text, prov = (result[0], result[1] or {}) if isinstance(result, tuple) else (result, {})
    usage = prov.get("usage") or {}
    return {
        "ok": True,
        "field_name": name,
        "text": str(text or "").strip(),
        "advisory_only": True,
        "process_id": PROCESS_ID,
        "lane": LANE,
        "returned_model": prov.get("returned_model"),
        "tokens_in": usage.get("prompt_tokens"),
        "tokens_out": usage.get("completion_tokens"),
        "estimated_cost_usd": prov.get("estimated_cost_usd"),
        "fallback_used": bool(prov.get("fallback_used")),
    }
