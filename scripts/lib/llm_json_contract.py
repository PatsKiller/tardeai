"""Strict JSON contract enforcement for DeepSeek structured outputs."""
from __future__ import annotations

import json
from typing import Any

from lib.deepseek_client import DeepSeekError, chat, parse_strict_json
from lib.llm_output_schemas import SCHEMA_MODELS, schema_example, validate_process_output

MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"


def generate_structured(
    *,
    policy: str,
    prompt: str,
    schema_id: str,
    timeout: float = 90.0,
    operator_confirmed: bool = False,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """One primary attempt + one bounded repair. No silent fallback."""
    if schema_id not in SCHEMA_MODELS:
        raise DeepSeekError(MODEL_OUTPUT_INVALID, f"unknown schema_id {schema_id}")

    example = schema_example(schema_id)
    full_prompt = (
        f"{prompt.strip()}\n\n"
        f"Return a single JSON object only (response_format=json_object). "
        f"schema_id must be {schema_id!r}. Example:\n"
        f"{json.dumps(example)}\n"
    )

    attempts: list[dict[str, Any]] = []
    last_err: str | None = None
    resp = chat(
        policy=policy,
        prompt=full_prompt,
        response_json=True,
        timeout=timeout,
        operator_confirmed=operator_confirmed,
        max_tokens=max_tokens,
    )
    attempts.append(resp.to_dict())
    if not resp.ok:
        raise DeepSeekError(resp.error_class or MODEL_OUTPUT_INVALID, resp.error_message or "provider failed")

    try:
        data = parse_strict_json(resp.content)
        validated = validate_process_output(schema_id, data)
        return {
            "ok": True,
            "data": validated,
            "schema_id": schema_id,
            "attempts": 1,
            "provenance": resp.to_dict(),
        }
    except Exception as e:
        last_err = str(e)[:400]

    # Bounded single repair
    repair_prompt = (
        f"Your previous response failed validation for schema {schema_id}.\n"
        f"Errors: {last_err}\n"
        f"Return corrected JSON only. Example:\n{json.dumps(example)}\n"
        f"Original task:\n{prompt.strip()}\n"
    )
    resp2 = chat(
        policy=policy,
        prompt=repair_prompt,
        response_json=True,
        timeout=timeout,
        operator_confirmed=operator_confirmed,
        max_tokens=max_tokens,
    )
    attempts.append(resp2.to_dict())
    if not resp2.ok:
        raise DeepSeekError(MODEL_OUTPUT_INVALID, f"repair failed: {resp2.error_class}")
    try:
        data2 = parse_strict_json(resp2.content)
        validated2 = validate_process_output(schema_id, data2)
        return {
            "ok": True,
            "data": validated2,
            "schema_id": schema_id,
            "attempts": 2,
            "provenance": resp2.to_dict(),
            "repair_used": True,
        }
    except Exception as e:
        raise DeepSeekError(MODEL_OUTPUT_INVALID, f"repair validation failed: {e}") from e
